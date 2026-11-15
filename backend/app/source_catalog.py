"""Persist source structure and external recipe metadata without importing a collection."""
from __future__ import annotations

import hashlib
import ipaddress
import json
from dataclasses import asdict
from contextlib import contextmanager
from datetime import timedelta
from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlalchemy import func, or_, select, text, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from collect_recipes import Client, CollectionError, archive_recipe, attach_step_images, discover, download_image
from recipe_api import APIError
from recipe_sources import normalize_recipe_url, public_source_url, sources_from_data
from tls_config import configure_tls

from . import db, importer
from .models import Category, ImportJob, ImportSource, Recipe, SourceCategory, SourceRecipe, SourceRecipeImport, User, utcnow
from .schemas import RecipeIn


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def visible_source(source: ImportSource) -> bool:
    return bool(source.deleted_at is None and source.enabled and source.verified and source.visible_in_catalog)


def visible_recipe(session, recipe_id: int) -> SourceRecipe:
    recipe = session.get(SourceRecipe, recipe_id)
    if recipe is None or not recipe.active or not visible_source(recipe.source):
        raise HTTPException(404, "Рецепт подключённого сайта не найден")
    return recipe


def safe_image_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = public_source_url(value)
    if parsed is None or parsed.hostname == "localhost" or parsed.hostname.endswith((".local", ".internal", ".localhost")):
        return None
    try:
        if not ipaddress.ip_address(parsed.hostname).is_global:
            return None
    except ValueError:
        pass
    return value


def imported_recipe_id(session, external: SourceRecipe, user_id: int) -> int | None:
    linked = session.get(SourceRecipeImport, (user_id, external.id))
    if linked:
        return linked.recipe_id
    settings = sources_from_data({"source": json.loads(external.source.definition_json)})
    for recipe_id, source_url in session.execute(select(Recipe.id, Recipe.source_url).where(Recipe.author_id == user_id)):
        if source_url and normalize_recipe_url(source_url, settings) == external.url:
            return recipe_id
    return None


def source_counts(session, source: ImportSource) -> dict:
    total = session.scalar(select(func.count()).select_from(SourceRecipe).where(SourceRecipe.source_id == source.id, SourceRecipe.active.is_(True))) or 0
    indexed = session.scalar(select(func.count()).select_from(SourceRecipe).where(SourceRecipe.source_id == source.id,
                              SourceRecipe.active.is_(True), SourceRecipe.payload_json.is_not(None))) or 0
    categories = session.scalar(select(func.count()).select_from(SourceCategory).where(SourceCategory.source_id == source.id)) or 0
    sources = sources_from_data({"source": json.loads(source.definition_json)})
    imported = {normalized for value in session.scalars(select(Recipe.source_url).where(Recipe.source_url.is_not(None)))
                if (normalized := normalize_recipe_url(value, sources))}
    imported.update(session.scalars(select(SourceRecipe.url).join(SourceRecipeImport, SourceRecipeImport.source_recipe_id == SourceRecipe.id)
                                    .where(SourceRecipe.source_id == source.id)))
    return {"total_recipes": total if source.last_indexed_at or total else None,
            "indexed_recipes": indexed, "imported_recipes": len(imported), "categories_count": categories}


def category_out(session, category: SourceCategory) -> dict:
    count = session.scalar(select(func.count()).select_from(SourceRecipe).where(SourceRecipe.category_id == category.id,
                           SourceRecipe.active.is_(True))) or 0
    return {"id": category.id, "title": category.title, "url": category.url,
            "parent_url": category.parent_url, "recipes_count": count}


def owned_external_ids(session, items: list[SourceRecipe], user_id: int) -> dict[int, int]:
    """Resolve a page of external cards with a bounded number of database reads."""
    if not items:
        return {}
    ids = [item.id for item in items]
    result = {external_id: recipe_id for external_id, recipe_id in session.execute(
        select(SourceRecipeImport.source_recipe_id, SourceRecipeImport.recipe_id)
        .where(SourceRecipeImport.user_id == user_id, SourceRecipeImport.source_recipe_id.in_(ids)))}
    owned = list(session.execute(select(Recipe.id, Recipe.source_url).where(Recipe.author_id == user_id,
                                Recipe.source_url.is_not(None))))
    settings = {item.source_id: sources_from_data({"source": json.loads(item.source.definition_json)}) for item in items}
    normalized = {(source_id, value): recipe_id for source_id, configured in settings.items()
                  for recipe_id, url in owned if (value := normalize_recipe_url(url, configured))}
    for item in items:
        if item.id not in result and (recipe_id := normalized.get((item.source_id, item.url))) is not None:
            result[item.id] = recipe_id
    return result


def recipe_out(session, external: SourceRecipe, user_id: int, *, detail: bool = False, owned_ids: dict[int, int] | None = None) -> dict:
    result = {"id": external.id, "source_id": external.source_id, "source_name": external.source.name,
              "title": external.title, "description": external.description, "image_url": safe_image_url(external.image_url),
              "source_url": external.url, "category": {"id": external.category.id, "title": external.category.title} if external.category else None,
              "imported_recipe_id": owned_ids.get(external.id) if owned_ids is not None else imported_recipe_id(session, external, user_id)}
    if detail:
        payload = json.loads(external.payload_json or "{}")
        result.update({"servings": payload.get("servings"), "prep_minutes": payload.get("prep_minutes"),
                       "cook_minutes": payload.get("cook_minutes"), "tags": payload.get("tags", []),
                       "ingredients": payload.get("ingredients", []),
                       "steps": [{"text": value, "image_url": safe_image_url(payload.get("step_images", [])[index])
                                  if index < len(payload.get("step_images", [])) else None}
                                 for index, value in enumerate(payload.get("steps", []))]})
    return result


def cached_recipe(external: SourceRecipe) -> importer.ImportedRecipe:
    data = json.loads(external.payload_json or "{}")
    data["ingredients"] = [importer.ParsedIngredient(**item) for item in data.get("ingredients", [])]
    return importer.ImportedRecipe(**data)


def store_category(session, source_id: int, event: dict) -> SourceCategory:
    url = event["url"]
    source = session.get(ImportSource, source_id)
    definition = sources_from_data({"source": json.loads(source.definition_json)})["source"]
    parsed = public_source_url(url)
    if parsed is None or parsed.scheme != "https" or parsed.hostname not in definition.hosts:
        raise CollectionError("Категория не принадлежит подключённому сайту")
    category = session.scalar(select(SourceCategory).where(SourceCategory.source_id == source_id, SourceCategory.url_hash == url_hash(url)))
    title = (event.get("title") or parsed.path).strip()[:200]
    if category is None:
        category = session.scalar(select(SourceCategory).where(SourceCategory.source_id == source_id,
                                  SourceCategory.url.is_(None), func.lower(SourceCategory.title) == title.lower()).limit(1))
        if category is None:
            category = SourceCategory(source_id=source_id, url_hash=url_hash(url), url=url,
                                      title=title, parent_url=event.get("parent_url"))
            session.add(category)
            session.flush()
        else:
            category.url, category.url_hash, category.parent_url = url, url_hash(url), event.get("parent_url")
    else:
        category.title = title or category.title
        category.parent_url = event.get("parent_url") or category.parent_url
    return category


def store_reference(session, source_id: int, url: str, category_url: str | None = None) -> SourceRecipe:
    source = session.get(ImportSource, source_id)
    settings = sources_from_data({"source": json.loads(source.definition_json)})
    normalized = normalize_recipe_url(url, settings)
    if normalized is None or len(normalized) > 500:
        raise CollectionError("Ссылка не соответствует рецептам подключённого сайта")
    external = session.scalar(select(SourceRecipe).where(SourceRecipe.source_id == source_id, SourceRecipe.url_hash == url_hash(normalized)))
    if external is None:
        external = SourceRecipe(source_id=source_id, url_hash=url_hash(normalized), url=normalized)
        session.add(external)
        session.flush()
    external.last_seen_at, external.active = utcnow(), True
    if category_url:
        category = session.scalar(select(SourceCategory).where(SourceCategory.source_id == source_id,
                                  SourceCategory.url_hash == url_hash(category_url)))
        if category:
            external.category_id = category.id
    return external


def fetch_metadata(client: Client, url: str, settings) -> importer.ImportedRecipe:
    raw, ctype, final = client.fetch(url, importer.MAX_PAGE_BYTES)
    if normalize_recipe_url(final, settings) != normalize_recipe_url(url, settings):
        raise CollectionError("Страница рецепта перенаправлена за пределы выбранного источника")
    recipe = importer.import_from_html(importer._decode(raw, ctype), final)
    recipe.source_url = normalize_recipe_url(final, settings)
    archive_recipe(recipe, False)
    return recipe


def cache_metadata(session, external: SourceRecipe, recipe: importer.ImportedRecipe) -> None:
    external.title = recipe.title[:200]
    external.description = recipe.description
    external.image_url = safe_image_url(recipe.image_url)
    external.payload_json = json.dumps(asdict(recipe), ensure_ascii=False)
    external.fetched_at, external.last_error, external.active = utcnow(), "", True
    if external.category_id is None and recipe.category:
        category = session.scalar(select(SourceCategory).where(SourceCategory.source_id == external.source_id,
                                  func.lower(SourceCategory.title) == recipe.category.lower()))
        if category is None:
            category = SourceCategory(source_id=external.source_id, url_hash=url_hash("category:" + recipe.category.casefold()),
                                      url=None, title=recipe.category[:200])
            try:
                with session.begin_nested():
                    session.add(category)
                    session.flush()
            except IntegrityError:
                category = session.scalar(select(SourceCategory).where(SourceCategory.source_id == external.source_id,
                                          SourceCategory.url_hash == url_hash("category:" + recipe.category.casefold())))
                if category is None:
                    raise
        external.category_id = category.id


class ImportCatalogSync:
    """Reuse an import's discovery and parsed pages without additional source requests."""

    def __init__(self, source_id: int, check_cancel):
        self.source_id = source_id
        self.check_cancel = check_cancel
        self._categories: set[tuple[str, str | None, str | None]] = set()
        self._references: set[tuple[str, str | None]] = set()

    @contextmanager
    def _session(self):
        from .import_jobs import session_scope

        self.check_cancel()
        try:
            with session_scope() as session:
                source = session.get(ImportSource, self.source_id)
                if source is None or source.deleted_at is not None or not source.enabled or not source.verified:
                    raise APIError("Источник больше недоступен; импорт остановлен")
                yield session, source
        except SQLAlchemyError:
            raise APIError("Не удалось обновить каталог источника; импорт остановлен. Проверьте доступность базы данных") from None

    @staticmethod
    def _settings(source: ImportSource):
        try:
            return sources_from_data({"source": json.loads(source.definition_json)})
        except (ValueError, TypeError):
            raise APIError("Настройки каталога повреждены; проверьте источник перед повторным импортом") from None

    def category_found(self, event: dict) -> None:
        self.check_cancel()
        key = (event["url"], event.get("title"), event.get("parent_url"))
        if key in self._categories:
            return
        with self._session() as (session, _):
            store_category(session, self.source_id, event)
            session.commit()
        self._categories.add(key)

    def recipe_found(self, event: dict) -> None:
        self.check_cancel()
        key = (event["url"], event.get("category_url"))
        if key in self._references:
            return
        with self._session() as (session, _):
            store_reference(session, self.source_id, event["url"], event.get("category_url"))
            session.commit()
        self._references.add(key)

    def recipe_parsed(self, recipe: importer.ImportedRecipe) -> None:
        # Only public source data reaches this hook. Personal recipes and edits
        # are never used to manufacture an external catalog entry.
        archive_recipe(recipe, False)
        with self._session() as (session, source):
            settings = self._settings(source)
            normalized = normalize_recipe_url(recipe.source_url, settings)
            if normalized is None:
                raise APIError("Рецепт не принадлежит выбранному источнику; импорт остановлен")
            external = store_reference(session, self.source_id, normalized)
            payload = json.dumps(asdict(recipe), ensure_ascii=False)
            if external.payload_json != payload:
                cache_metadata(session, external, recipe)
            elif external.category_id is None and recipe.category:
                fetched_at = external.fetched_at
                cache_metadata(session, external, recipe)
                external.fetched_at = fetched_at
            session.commit()

    def cached_recipe(self, url: str) -> importer.ImportedRecipe | None:
        with self._session() as (session, source):
            settings = self._settings(source)
            normalized = normalize_recipe_url(url, settings)
            if normalized is None:
                raise APIError("Рецепт не принадлежит выбранному источнику; импорт остановлен")
            external = session.scalar(select(SourceRecipe).where(SourceRecipe.source_id == self.source_id,
                                      SourceRecipe.url_hash == url_hash(normalized), SourceRecipe.active.is_(True)))
            if external is None or not external.payload_json:
                return None
            try:
                payload = json.loads(external.payload_json)
                if not isinstance(payload, dict):
                    raise ValueError("Expected cached recipe fields")
                recipe = cached_recipe(external)
                if normalize_recipe_url(recipe.source_url, settings) != normalized:
                    raise ValueError("Cached source URL does not match its catalog entry")
                archive_recipe(recipe, False)
            except (CollectionError, ValueError, TypeError, KeyError, AttributeError):
                raise APIError("Сохранённый рецепт каталога повреждён; обновите каталог источника перед импортом") from None
            recipe.source_url = normalized
            return recipe


def ensure_metadata(session, external: SourceRecipe) -> None:
    if external.payload_json:
        return
    context, _ = configure_tls()
    settings = sources_from_data({"source": json.loads(external.source.definition_json)})
    recipe = fetch_metadata(Client(0.5, 1, ssl_context=context, adaptive_delay=True), external.url, settings)
    cache_metadata(session, external, recipe)
    session.commit()


def index_source(source_id: int, definition: dict, client: Client, check_cancel, progress, limit: int = 0) -> dict:
    """Scan metadata only; original recipes and media stay external until explicit import."""
    from .import_jobs import session_scope

    settings = sources_from_data({"source": definition})
    scan_started = utcnow()
    with session_scope() as session:
        source = session.get(ImportSource, source_id)
        source.index_complete, source.index_error = False, ""
        session.commit()
    report = {"created": 0, "indexed": 0, "discovered": 0, "cached": 0, "catalog_pages": 0,
              "attempted": 0, "errors": [], "error_count": 0, "complete": False, "stop_reason": "running"}

    def category_found(event):
        check_cancel()
        with session_scope() as session:
            store_category(session, source_id, event)
            session.commit()

    def recipe_found(event):
        check_cancel()
        with session_scope() as session:
            store_reference(session, source_id, event["url"], event.get("category_url"))
            session.commit()

    def discovery_progress(value):
        report["catalog_pages"] = value.get("catalog_pages", report["catalog_pages"])
        report["discovered"] = value.get("discovered", report["discovered"])
        if value.get("complete"):
            report["complete"] = True
            report["stop_reason"] = value.get("stop_reason", "exhausted")
        elif value.get("stop_reason"):
            report["stop_reason"] = value["stop_reason"]
        progress(report)

    try:
        for url in discover("source", client, settings, max_catalog_pages=None, on_category=category_found,
                            on_recipe=recipe_found, progress_callback=discovery_progress):
            check_cancel()
            report["attempted"] += 1
            with session_scope() as session:
                external = store_reference(session, source_id, url)
                external_id, cached = external.id, bool(external.payload_json)
                session.commit()
            if cached:
                report["cached"] += 1
            else:
                try:
                    recipe = fetch_metadata(client, url, settings)
                    check_cancel()
                    with session_scope() as session:
                        cache_metadata(session, session.get(SourceRecipe, external_id), recipe)
                        session.commit()
                    report["indexed"] += 1
                except (CollectionError, importer.ImportError_, ValueError) as exc:
                    report["error_count"] += 1
                    if len(report["errors"]) < 100:
                        report["errors"].append({"url": url, "error": str(exc)})
                    with session_scope() as session:
                        session.get(SourceRecipe, external_id).last_error = str(exc)[:2000]
                        session.commit()
            progress(report)
            if limit and report["attempted"] >= limit:
                report["complete"], report["stop_reason"] = False, "limit"
                break
    except KeyboardInterrupt:
        report["complete"], report["stop_reason"] = False, "stopped"
        with session_scope() as session:
            source = session.get(ImportSource, source_id)
            source.index_complete, source.index_error = False, "Обновление каталога остановлено"
            session.commit()
        progress({**report, "interrupted": True})
        raise
    except (CollectionError, importer.ImportError_, ValueError) as exc:
        report["complete"], report["stop_reason"] = False, "failed"
        report["error_count"] += 1
        if len(report["errors"]) < 100:
            report["errors"].append({"stage": "discovery", "error": str(exc)})
    if report["error_count"]:
        report["complete"] = False
    with session_scope() as session:
        source = session.get(ImportSource, source_id)
        if report["complete"]:
            session.execute(update(SourceRecipe).where(SourceRecipe.source_id == source_id,
                            SourceRecipe.last_seen_at < scan_started).values(active=False))
        source.last_indexed_at, source.index_complete = utcnow(), report["complete"]
        source.index_error = report["errors"][-1]["error"][:2000] if report["errors"] else ""
        if source.auto_refresh:
            source.next_refresh_at = utcnow() + timedelta(hours=source.refresh_interval_hours)
        session.commit()
    progress(report)
    return report


def enqueue_scheduled_index(session) -> None:
    """Queue at most one due metadata refresh; an active job keeps the global slot."""
    if session.scalar(select(ImportJob.id).where(ImportJob.active_slot == "collector").limit(1)):
        return
    now = utcnow()
    source = session.scalar(select(ImportSource).where(ImportSource.auto_refresh.is_(True), ImportSource.enabled.is_(True),
                            ImportSource.verified.is_(True), ImportSource.deleted_at.is_(None),
                            or_(ImportSource.next_refresh_at.is_(None), ImportSource.next_refresh_at <= now))
                            .order_by(ImportSource.next_refresh_at, ImportSource.id).limit(1))
    if source is None:
        return
    author = session.get(User, source.refresh_author_id) if source.refresh_author_id else None
    if author is None or not author.is_active or not author.is_admin:
        source.auto_refresh = False
        source.index_error = "Автообновление отключено: администратор больше недоступен"
        session.commit()
        return
    parameters = {"definition": json.loads(source.definition_json), "limit": 0, "is_public": False,
                  "urls": [], "catalog_url": None, "category_id": None, "no_step_images": True}
    source.next_refresh_at = now + timedelta(hours=source.refresh_interval_hours)
    session.add(ImportJob(source_id=source.id, author_id=author.id, mode="index", parameters_json=json.dumps(parameters, ensure_ascii=False),
                          report_json="{}", status="queued", active_slot="collector"))
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        if session.scalar(select(ImportJob.id).where(ImportJob.active_slot == "collector").limit(1)) is None:
            raise


def create_user_import(external_id: int, user_id: int, is_public: bool) -> tuple[int, bool]:
    """Serialize one user's explicit imports and commit the recipe and idempotency link together."""
    from .import_jobs import session_scope
    from .routers.recipes import _apply

    with session_scope() as session:
        if session.bind.dialect.name == "sqlite":
            session.execute(text("BEGIN IMMEDIATE"))
        user = session.scalar(select(User).where(User.id == user_id).with_for_update())
        if user is None or not user.is_active:
            raise HTTPException(403, "Учётная запись недоступна")
        external = visible_recipe(session, external_id)
        recipe_id = imported_recipe_id(session, external, user_id)
        if recipe_id is None:
            recipe_id = session.scalar(select(Recipe.id).where(Recipe.author_id == user_id,
                                      func.lower(Recipe.title) == external.title.lower()).limit(1))
        already_imported = recipe_id is not None
        if recipe_id is None:
            payload, _ = archive_recipe(cached_recipe(external), is_public)
            category_id = None
            if payload.get("category"):
                category = session.scalar(select(Category).where(func.lower(Category.name) == payload["category"].lower()))
                if category is None:
                    category = Category(name=payload["category"])
                    session.add(category)
                    session.flush()
                category_id = category.id
            payload = {key: value for key, value in payload.items() if key not in ("category", "image", "photos")}
            recipe = Recipe(author_id=user_id)
            session.add(recipe)
            _apply(session, recipe, RecipeIn(**payload, category_id=category_id))
            session.flush()
            recipe_id = recipe.id
        if session.get(SourceRecipeImport, (user_id, external_id)) is None:
            session.add(SourceRecipeImport(user_id=user_id, source_recipe_id=external_id, recipe_id=recipe_id))
        session.commit()
        return recipe_id, already_imported


def import_external(external: SourceRecipe, user_id: int, is_public: bool) -> dict:
    from .import_jobs import DatabaseImportAPI, session_scope

    class UserCatalogImportAPI(DatabaseImportAPI):
        def _authorize(self, session):
            visible_recipe(session, external.id)
            user = session.get(User, self.user_id)
            if user is None or not user.is_active:
                raise APIError("Учётная запись недоступна")
            return user

    recipe_id, already_imported = create_user_import(external.id, user_id, is_public)
    recipe = cached_recipe(external)
    adapter = UserCatalogImportAPI(user_id)
    context, _ = configure_tls()
    client = Client(0.5, 1, ssl_context=context, adaptive_delay=True)
    warnings = []
    if recipe.image_url and not adapter.recipe_has_cover(recipe_id):
        try:
            image, content_type = download_image(client, recipe.image_url)
            adapter.upload_cover(recipe_id, image, content_type)
        except (CollectionError, APIError) as exc:
            warnings.append(str(exc))
    try:
        attach_step_images(recipe, recipe_id, client, adapter, warnings, lambda index: None)
    except (CollectionError, APIError) as exc:
        warnings.append(str(exc))
    return {"recipe_id": recipe_id, "already_imported": already_imported, "warnings": warnings}
