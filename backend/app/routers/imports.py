"""Administrative source verification and durable recipe import requests."""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from collect_recipes import CollectionError
from recipe_sources import SourceConfigError, load_sources, normalize_recipe_url, public_source_url, sources_from_data

from ..db import get_db
from ..importer import ImportError_
from ..models import ImportJob, ImportSource, SourceCategory, SourceRecipe, User, utcnow
from ..security import get_current_user, require_admin

router = APIRouter(prefix="/api", tags=["recipe imports"])
ACTIVE_STATUSES = {"queued", "running", "stopping"}


class SourceDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    canonical_host: str = Field(min_length=1, max_length=255)
    hosts: list[str] = Field(min_length=1, max_length=20)
    catalog_url: str = Field(min_length=8, max_length=2000)
    recipe_pattern: str = Field(min_length=1, max_length=1000)
    catalog_pattern: str = Field(min_length=1, max_length=1000)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    recipe_trailing_slash: bool = False


class SourceCreate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    catalog_url: str = Field(min_length=8, max_length=2000)
    definition: SourceDefinition | None = None


class SourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    enabled: bool | None = None
    visible_in_catalog: bool | None = None
    auto_refresh: bool | None = None
    refresh_interval_hours: int | None = Field(default=None, ge=1, le=720)


class JobCreate(BaseModel):
    source_id: int = Field(ge=1)
    mode: Literal["import", "images", "index"] = "import"
    limit: int = Field(default=100, ge=0, le=1000)
    is_public: bool = True
    urls: list[Annotated[str, Field(min_length=8, max_length=500)]] = Field(default_factory=list, max_length=100)
    catalog_url: str | None = Field(default=None, min_length=8, max_length=2000)
    category_id: int | None = Field(default=None, ge=1)
    no_step_images: bool = False


def _object(value: str) -> dict:
    try:
        result = json.loads(value)
    except (ValueError, TypeError):
        raise HTTPException(500, "Сохранённые данные импорта повреждены") from None
    if not isinstance(result, dict):
        raise HTTPException(500, "Сохранённые данные импорта имеют неверный формат")
    return result


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()


def _source_out(source: ImportSource, db: Session) -> dict:
    from ..source_catalog import source_counts

    definition = _object(source.definition_json)
    return {
        "id": source.id, "key": source.key, "name": source.name,
        "catalog_url": definition["catalog_url"], "hosts": definition["hosts"],
        "enabled": source.enabled, "verified": source.verified,
        "checked_at": _iso(source.checked_at), "last_error": source.last_error,
        "sample": _object(source.sample_json),
        "visible_in_catalog": source.visible_in_catalog, "auto_refresh": source.auto_refresh,
        "refresh_interval_hours": source.refresh_interval_hours,
        "last_indexed_at": _iso(source.last_indexed_at), "next_refresh_at": _iso(source.next_refresh_at),
        "index_complete": source.index_complete, "index_error": source.index_error,
        **source_counts(db, source),
    }


def _job_out(job: ImportJob) -> dict:
    parameters = _object(job.parameters_json)
    return {
        "id": job.id, "source_id": job.source_id, "source_name": job.source.name,
        "mode": job.mode, "status": job.status,
        "created_at": _iso(job.created_at), "started_at": _iso(job.started_at),
        "finished_at": _iso(job.finished_at), "cancel_requested": job.cancel_requested,
        "parameters": {key: parameters.get(key) for key in
                       ("limit", "is_public", "urls", "catalog_url", "category_id", "no_step_images")},
        "report": _object(job.report_json),
    }


def _seed_sources(db: Session) -> None:
    defaults = load_sources()
    existing = set(db.scalars(select(ImportSource.key)))
    labels = {"food": "Food.ru", "rambler": "Рамблер/еда", "iamcook": "Аймкук"}
    missing = [key for key in defaults if key not in existing]
    if not missing:
        return
    for key in missing:
        db.add(ImportSource(key=key, name=labels.get(key, defaults[key].canonical_host),
                            definition_json=json.dumps(asdict(defaults[key]), ensure_ascii=False),
                            enabled=True, verified=False, last_error="", sample_json="{}"))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        created = set(db.scalars(select(ImportSource.key)))
        if not set(missing).issubset(created):
            raise HTTPException(409, "Не удалось подключить стандартные источники — обновите страницу") from None


def _validate_definition(definition: dict):
    try:
        return sources_from_data({"source": definition})
    except SourceConfigError as exc:
        raise HTTPException(422, str(exc)) from None


def _definition_for_request(data: SourceCreate) -> tuple[str, dict]:
    parsed = public_source_url(data.catalog_url)
    if parsed is None or parsed.scheme != "https" or parsed.fragment:
        raise HTTPException(422, "Нужна публичная HTTPS-ссылка на каталог сайта")
    if data.definition is not None:
        definition = data.definition.model_dump()
        definition["catalog_url"] = data.catalog_url
        _validate_definition(definition)
        return "source-" + uuid.uuid5(uuid.NAMESPACE_DNS, definition["canonical_host"]).hex[:16], definition
    defaults = load_sources()
    for key in defaults:
        template = defaults[key]
        if parsed.hostname not in template.hosts:
            continue
        definition = asdict(template)
        definition["hosts"] = list(template.hosts)
        definition["catalog_url"] = urlunsplit(("https", template.canonical_host, parsed.path or "/", parsed.query, ""))
        if not re.fullmatch(template.catalog_pattern, parsed.path or "/"):
            definition["catalog_pattern"] = f"(?:{template.catalog_pattern}|{re.escape(parsed.path or '/')})"
        _validate_definition(definition)
        return key, definition
    from source_discovery import detect_source

    try:
        definition = detect_source(data.catalog_url)
        _validate_definition(definition)
    except (SourceConfigError, CollectionError, ImportError_, OSError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from None
    return "source-" + uuid.uuid5(uuid.NAMESPACE_DNS, definition["canonical_host"]).hex[:16], definition


def _probe(definition: dict) -> dict:
    from ..import_jobs import probe_source

    try:
        return probe_source(definition)
    except (SourceConfigError, CollectionError, ImportError_, OSError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from None


def _get_source(db: Session, source_id: int) -> ImportSource:
    source = db.get(ImportSource, source_id)
    if source is None or source.deleted_at is not None:
        raise HTTPException(404, "Источник не найден")
    return source


def _get_job(db: Session, job_id: int) -> ImportJob:
    job = db.get(ImportJob, job_id)
    if job is None:
        raise HTTPException(404, "Задание не найдено")
    return job


@router.get("/recipe-sources")
def connected_sources(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[dict]:
    sources = db.scalars(select(ImportSource).where(ImportSource.enabled.is_(True), ImportSource.verified.is_(True), ImportSource.deleted_at.is_(None))
                         .order_by(ImportSource.name)).all()
    return [{"id": source.id, "name": source.name, "hosts": _object(source.definition_json)["hosts"]} for source in sources]


@router.get("/admin/imports/sources")
def list_sources(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> list[dict]:
    _seed_sources(db)
    return [_source_out(source, db) for source in db.scalars(select(ImportSource).where(ImportSource.deleted_at.is_(None)).order_by(ImportSource.id))]


@router.post("/admin/imports/sources")
def create_source(data: SourceCreate, db: Session = Depends(get_db), _: User = Depends(require_admin)) -> dict:
    if data.name is not None and not data.name.strip():
        raise HTTPException(422, "Введите название источника")
    requested = public_source_url(data.catalog_url)
    if requested is not None:
        for existing in db.scalars(select(ImportSource).where(ImportSource.deleted_at.is_(None))):
            if requested.hostname in _object(existing.definition_json)["hosts"]:
                raise HTTPException(409, "Этот сайт уже подключён — проверьте существующий источник")
    key, definition = _definition_for_request(data)
    requested_hosts = set(definition["hosts"])
    for source in db.scalars(select(ImportSource).where(ImportSource.deleted_at.is_(None))):
        if requested_hosts.intersection(_object(source.definition_json)["hosts"]):
            raise HTTPException(409, "Этот сайт уже подключён — проверьте существующий источник")
    sample = _probe(definition)
    source = db.scalar(select(ImportSource).where(ImportSource.key == key, ImportSource.deleted_at.is_not(None)))
    if source is None:
        for previous in db.scalars(select(ImportSource).where(ImportSource.deleted_at.is_not(None))):
            if requested_hosts.intersection(_object(previous.definition_json)["hosts"]):
                source = previous
                break
    if source is None:
        source = ImportSource(key=key)
        db.add(source)
    source.name = (data.name or definition["canonical_host"]).strip()
    source.definition_json = json.dumps(definition, ensure_ascii=False)
    source.enabled, source.verified, source.deleted_at = True, True, None
    source.visible_in_catalog, source.auto_refresh, source.next_refresh_at = False, False, None
    source.checked_at, source.last_error = utcnow(), ""
    source.sample_json = json.dumps(sample, ensure_ascii=False)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Этот источник уже добавлен — обновите страницу") from None
    db.refresh(source)
    return _source_out(source, db)


@router.post("/admin/imports/sources/{source_id}/check")
def check_source(source_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)) -> dict:
    source = _get_source(db, source_id)
    definition = _object(source.definition_json)
    source.checked_at = utcnow()
    try:
        sample = _probe(definition)
    except HTTPException as exc:
        source.verified = False
        source.last_error = str(exc.detail)[:2000]
        db.commit()
        raise
    source.verified = True
    source.last_error = ""
    source.sample_json = json.dumps(sample, ensure_ascii=False)
    db.commit()
    return _source_out(source, db)


@router.patch("/admin/imports/sources/{source_id}")
def update_source(source_id: int, data: SourceUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    source = _get_source(db, source_id)
    if data.name is not None:
        if not data.name.strip():
            raise HTTPException(422, "Введите название источника")
        source.name = data.name.strip()
    if data.enabled is not None:
        source.enabled = data.enabled
    if data.visible_in_catalog is not None:
        if data.visible_in_catalog and not source.verified:
            raise HTTPException(409, "Сначала успешно проверьте источник")
        source.visible_in_catalog = data.visible_in_catalog
    if data.refresh_interval_hours is not None:
        source.refresh_interval_hours = data.refresh_interval_hours
        if source.auto_refresh:
            source.next_refresh_at = utcnow() + timedelta(hours=source.refresh_interval_hours)
    if data.auto_refresh is not None:
        if data.auto_refresh and (not source.enabled or not source.verified):
            raise HTTPException(409, "Автообновление доступно после проверки включённого источника")
        source.auto_refresh = data.auto_refresh
        source.refresh_author_id = admin.id if data.auto_refresh else source.refresh_author_id
        source.next_refresh_at = utcnow() if data.auto_refresh else None
    db.commit()
    return _source_out(source, db)


@router.get("/admin/imports/sources/{source_id}/categories")
def source_categories(source_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)) -> list[dict]:
    from ..source_catalog import category_out

    _get_source(db, source_id)
    return [category_out(db, category) for category in db.scalars(select(SourceCategory).where(SourceCategory.source_id == source_id)
                                                                .order_by(SourceCategory.title))]


@router.delete("/admin/imports/sources/{source_id}")
def delete_source(source_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)) -> dict:
    source = db.get(ImportSource, source_id)
    if source is None:
        raise HTTPException(404, "Источник не найден")
    source.deleted_at, source.enabled, source.visible_in_catalog = utcnow(), False, False
    source.auto_refresh, source.next_refresh_at = False, None
    db.execute(update(ImportJob).where(ImportJob.source_id == source_id, ImportJob.status == "queued").values(
        cancel_requested=True, status="stopped", active_slot=None, finished_at=utcnow()).execution_options(synchronize_session=False))
    db.execute(update(ImportJob).where(ImportJob.source_id == source_id, ImportJob.status.in_(("running", "stopping"))).values(
        cancel_requested=True, status="stopping").execution_options(synchronize_session=False))
    db.commit()
    return {"deleted": True}


@router.get("/admin/imports/jobs")
def list_jobs(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> list[dict]:
    return [_job_out(job) for job in db.scalars(select(ImportJob).order_by(ImportJob.id.desc()).limit(20))]


def _enqueue(db: Session, source: ImportSource, author: User, mode: str, parameters: dict) -> ImportJob:
    if not source.enabled or not source.verified:
        raise HTTPException(409, "Сначала включите и успешно проверьте источник")
    job = ImportJob(source_id=source.id, author_id=author.id, mode=mode,
                    parameters_json=json.dumps(parameters, ensure_ascii=False), report_json="{}",
                    status="queued", active_slot="collector", cancel_requested=False)
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Уже выполняется импорт. Дождитесь завершения или остановите его") from None
    db.refresh(job)
    return job


@router.post("/admin/imports/jobs")
def create_job(data: JobCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    if (data.urls and (data.catalog_url or data.category_id)) or (data.category_id and data.catalog_url):
        raise HTTPException(422, "Выберите ссылки на рецепты или ссылку на раздел, а не оба варианта сразу")
    source = _get_source(db, data.source_id)
    catalog_url = data.catalog_url
    if data.category_id is not None:
        category = db.get(SourceCategory, data.category_id)
        if category is None or category.source_id != source.id:
            raise HTTPException(422, "Категория не принадлежит выбранному источнику")
        catalog_url = category.url
    definition = _object(source.definition_json)
    settings = _validate_definition(definition)
    template = settings["source"]
    urls = []
    for value in data.urls:
        normalized = normalize_recipe_url(value, settings)
        if normalized is None:
            raise HTTPException(422, "Ссылка на рецепт не принадлежит выбранному источнику")
        if normalized not in urls:
            urls.append(normalized)
    if catalog_url:
        catalog = public_source_url(catalog_url)
        if catalog is None or catalog.scheme != "https" or catalog.hostname not in template.hosts or catalog.fragment:
            raise HTTPException(422, "Ссылка на раздел должна принадлежать выбранному источнику")
        if normalize_recipe_url(catalog_url, settings) is not None:
            raise HTTPException(422, "Ссылку на отдельный рецепт укажите в списке рецептов, а не в поле раздела")
    parameters = {"definition": definition, "limit": data.limit, "is_public": data.is_public,
                  "urls": urls, "catalog_url": catalog_url, "category_id": data.category_id, "no_step_images": data.no_step_images}
    job = _enqueue(db, source, admin, data.mode, parameters)
    return _job_out(job)


@router.post("/admin/imports/jobs/{job_id}/stop")
def stop_job(job_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)) -> dict:
    job = _get_job(db, job_id)
    # Do not release the active slot if a worker claimed a queued job concurrently.
    queued = db.execute(update(ImportJob).where(ImportJob.id == job_id, ImportJob.status == "queued")
                        .values(cancel_requested=True, status="stopped", active_slot=None, finished_at=utcnow())
                        .execution_options(synchronize_session=False))
    if queued.rowcount == 0:
        db.execute(update(ImportJob).where(ImportJob.id == job_id, ImportJob.status.in_(("running", "stopping")))
                   .values(cancel_requested=True, status="stopping").execution_options(synchronize_session=False))
    db.commit()
    db.refresh(job)
    return _job_out(job)


@router.post("/admin/imports/jobs/{job_id}/resume")
def resume_job(job_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    previous = _get_job(db, job_id)
    if previous.status in ACTIVE_STATUSES:
        raise HTTPException(409, "Задание ещё не остановлено")
    parameters = _object(previous.parameters_json)
    job = _enqueue(db, previous.source, admin, previous.mode, parameters)
    return _job_out(job)


class ExternalImportRequest(BaseModel):
    is_public: bool = False


@router.get("/site-recipes/sources")
def external_sources(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[dict]:
    sources = db.scalars(select(ImportSource).where(ImportSource.enabled.is_(True), ImportSource.verified.is_(True), ImportSource.deleted_at.is_(None),
                         ImportSource.visible_in_catalog.is_(True)).order_by(ImportSource.name))
    return [{"id": source.id, "name": source.name, "hosts": _object(source.definition_json)["hosts"]} for source in sources]


@router.get("/site-recipes/categories")
def external_categories(source_id: int | None = Query(default=None, ge=1), db: Session = Depends(get_db),
                        _: User = Depends(get_current_user)) -> list[dict]:
    from ..source_catalog import category_out

    query = select(SourceCategory).join(ImportSource).where(ImportSource.enabled.is_(True), ImportSource.verified.is_(True), ImportSource.deleted_at.is_(None),
                                                            ImportSource.visible_in_catalog.is_(True))
    if source_id is not None:
        query = query.where(SourceCategory.source_id == source_id)
    return [category_out(db, category) for category in db.scalars(query.order_by(SourceCategory.title))]


@router.get("/site-recipes")
def external_recipes(source_id: int | None = Query(default=None, ge=1), category_id: int | None = Query(default=None, ge=1),
                     q: str = Query(default="", max_length=200), limit: int = Query(default=24, ge=1, le=100),
                     offset: int = Query(default=0, ge=0), db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)) -> dict:
    from ..source_catalog import owned_external_ids, recipe_out

    conditions = [ImportSource.enabled.is_(True), ImportSource.verified.is_(True), ImportSource.deleted_at.is_(None), ImportSource.visible_in_catalog.is_(True),
                  SourceRecipe.active.is_(True), SourceRecipe.payload_json.is_not(None)]
    if source_id is not None:
        conditions.append(SourceRecipe.source_id == source_id)
    if category_id is not None:
        conditions.append(SourceRecipe.category_id == category_id)
    if q.strip():
        conditions.append(func.lower(SourceRecipe.title).contains(q.strip().lower(), autoescape=True))
    total = db.scalar(select(func.count()).select_from(SourceRecipe).join(ImportSource).where(*conditions)) or 0
    items = db.scalars(select(SourceRecipe).join(ImportSource).where(*conditions).order_by(SourceRecipe.first_seen_at.desc(), SourceRecipe.id.desc())
                       .offset(offset).limit(limit)).unique().all()
    owned_ids = owned_external_ids(db, items, user.id)
    return {"items": [recipe_out(db, item, user.id, owned_ids=owned_ids) for item in items], "total": total}


@router.get("/site-recipes/{recipe_id}")
def external_recipe(recipe_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    from ..source_catalog import ensure_metadata, recipe_out, visible_recipe

    external = visible_recipe(db, recipe_id)
    try:
        ensure_metadata(db, external)
    except (CollectionError, ImportError_, OSError, ValueError) as exc:
        raise HTTPException(422, "Не удалось прочитать рецепт: " + str(exc)) from None
    return recipe_out(db, external, user.id, detail=True)


@router.post("/site-recipes/{recipe_id}/import")
def import_external_recipe(recipe_id: int, data: ExternalImportRequest | None = None,
                           db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    from ..source_catalog import ensure_metadata, import_external, visible_recipe

    external = visible_recipe(db, recipe_id)
    try:
        ensure_metadata(db, external)
        return import_external(external, user.id, data.is_public if data else False)
    except (CollectionError, ImportError_, OSError, ValueError) as exc:
        raise HTTPException(422, "Не удалось импортировать рецепт: " + str(exc)) from None
