"""Persistent admin import jobs using the same collector as the command-line tool."""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import logging
import re
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from itertools import islice
from urllib.parse import urlsplit

from fastapi import HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import SQLAlchemyError

from collect_recipes import Client, CollectionError, archive_recipe, backfill_images, collect, discover
from recipe_api import APIError, OwnedRecipe, OwnedStep
from recipe_sources import SourceConfigError, public_source_url, sources_from_data
from tls_config import TLSConfigurationError, configure_tls

from . import db, importer
from .config import DATA_DIR
from .models import Category, ImportJob, ImportSource, Recipe, SourceCategory, SourceRecipe, User, utcnow
from .schemas import RecipeIn

log = logging.getLogger("uvicorn.error")
LEASE_SECONDS = 90


class JobCancelled(KeyboardInterrupt):
    """Cooperative cancellation between requests and committed recipe writes."""


@contextmanager
def session_scope():
    yield from db.get_db()


def probe_source(definition: dict) -> dict:
    sources = sources_from_data({"source": definition})
    context, _ = configure_tls()
    client = Client(1, 1, ssl_context=context, adaptive_delay=True, min_delay=0.25, max_delay=10)
    errors = []
    for index, url in enumerate(discover("source", client, sources, max_catalog_pages=10)):
        try:
            raw, ctype, final = client.fetch(url, importer.MAX_PAGE_BYTES)
            recipe = importer.import_from_html(importer._decode(raw, ctype), final)
            archive_recipe(recipe, False)
            has_cover = False
            if recipe.image_url:
                image, content_type, _ = client.fetch_cover(recipe.image_url)
                if not image or not content_type.lower().startswith("image/"):
                    raise CollectionError("The sample recipe cover is not an image")
                try:
                    with Image.open(io.BytesIO(image)) as decoded:
                        if decoded.width * decoded.height > 60_000_000:
                            raise CollectionError("The sample cover exceeds the image size limit")
                        decoded.verify()
                except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
                    raise CollectionError("The sample recipe cover cannot be decoded as an image") from None
                has_cover = True
            return {"title": recipe.title, "source_url": recipe.source_url,
                    "ingredients": len(recipe.ingredients), "steps": len(recipe.steps),
                    "step_images": sum(bool(image) for image in recipe.step_images), "has_cover": has_cover}
        except (CollectionError, importer.ImportError_, ValueError, TypeError) as exc:
            errors.append(str(exc))
        if index >= 2:
            break
    raise CollectionError("Could not read a complete sample recipe. " + (errors[-1] if errors else "No recipe links found"))


def _active_admin(session, user_id: int) -> User:
    user = session.get(User, user_id)
    if user is None or not user.is_active or not user.is_admin:
        raise APIError("The administrator account is no longer active; import stopped")
    return user


class DatabaseImportAPI:
    """Use shared recipe operations in-process, without passwords or loopback HTTP."""

    def __init__(self, user_id: int, check_cancel=lambda: None):
        self.user_id = user_id
        self.check_cancel = check_cancel
        self.owned_recipes: list[OwnedRecipe] = []

    def _authorize(self, session) -> User:
        return _active_admin(session, self.user_id)

    @staticmethod
    def _steps(recipe: Recipe) -> tuple[OwnedStep, ...]:
        return tuple(OwnedStep(step.id, step.text, bool(step.image)) for step in recipe.steps)

    def prepare(self) -> tuple[set[str], set[str]]:
        self.check_cancel()
        with session_scope() as session:
            self._authorize(session)
            recipes = session.scalars(select(Recipe).where(Recipe.author_id == self.user_id).order_by(Recipe.id)).unique().all()
            self.owned_recipes = [OwnedRecipe(recipe.id, recipe.title, recipe.source_url, bool(recipe.image), self._steps(recipe))
                                  for recipe in recipes]
        return ({recipe.source_url for recipe in self.owned_recipes if recipe.source_url},
                {recipe.title.casefold() for recipe in self.owned_recipes})

    def create_recipe(self, item: dict) -> int:
        from .routers.recipes import _apply

        self.check_cancel()
        try:
            with session_scope() as session:
                user = self._authorize(session)
                duplicate = or_(func.lower(Recipe.title) == item["title"].lower(), Recipe.source_url == item["source_url"])
                if session.scalar(select(Recipe.id).where(Recipe.author_id == user.id, duplicate).limit(1)):
                    raise APIError("A recipe with this source or title was already added; skipped", fatal=False)
                category_id = None
                if item.get("category"):
                    name = item["category"]
                    category = session.scalar(select(Category).where(func.lower(Category.name) == name.lower()))
                    if category is None:
                        category = Category(name=name)
                        session.add(category)
                        session.flush()
                    category_id = category.id
                payload = {key: value for key, value in item.items() if key not in ("category", "image", "photos")}
                payload["category_id"] = category_id
                recipe = Recipe(author_id=user.id)
                session.add(recipe)
                _apply(session, recipe, RecipeIn(**payload))
                session.commit()
                return recipe.id
        except HTTPException as exc:
            raise APIError(str(exc.detail), fatal=False) from None
        except SQLAlchemyError:
            raise APIError("Could not save the recipe; import stopped before retrying the write") from None

    def _recipe(self, session, recipe_id: int) -> Recipe:
        self._authorize(session)
        recipe = session.get(Recipe, recipe_id)
        if recipe is None or recipe.author_id != self.user_id:
            raise APIError("The recipe no longer belongs to this import account")
        return recipe

    def recipe_has_cover(self, recipe_id: int) -> bool:
        self.check_cancel()
        with session_scope() as session:
            return bool(self._recipe(session, recipe_id).image)

    def recipe_steps(self, recipe_id: int) -> tuple[OwnedStep, ...]:
        self.check_cancel()
        with session_scope() as session:
            return self._steps(self._recipe(session, recipe_id))

    def upload_cover(self, recipe_id: int, image: bytes, content_type: str) -> None:
        from .routers.recipes import upload_image

        self.check_cancel()
        try:
            with session_scope() as session:
                user = self._authorize(session)
                if self._recipe(session, recipe_id).image:
                    return
                asyncio.run(upload_image(recipe_id, UploadFile(io.BytesIO(image), filename="cover.img"), session, user))
        except HTTPException as exc:
            raise APIError(str(exc.detail), fatal=exc.status_code >= 500) from None
        except SQLAlchemyError:
            raise APIError("Could not save the cover; import stopped") from None

    def upload_step_image(self, recipe_id: int, step_id: int, image: bytes, content_type: str) -> None:
        from .routers.recipes import upload_step_image

        self.check_cancel()
        try:
            with session_scope() as session:
                user = self._authorize(session)
                self._recipe(session, recipe_id)
                asyncio.run(upload_step_image(recipe_id, step_id, UploadFile(io.BytesIO(image), filename="step.img"), True, session, user))
        except HTTPException as exc:
            raise APIError(str(exc.detail), fatal=exc.status_code >= 500 or exc.status_code in (401, 403, 404)) from None
        except SQLAlchemyError:
            raise APIError("Could not save a step photo; import stopped") from None


def claim_job(session, owner_id: str, now: datetime | None = None) -> int | None:
    now = now or utcnow()
    cutoff = now - timedelta(seconds=LEASE_SECONDS)
    stale_condition = (
        ImportJob.status.in_(("running", "stopping")),
        func.coalesce(ImportJob.heartbeat_at, ImportJob.started_at, ImportJob.created_at) < cutoff,
    )
    stale = session.scalars(select(ImportJob).where(*stale_condition)).all()
    for job in stale:
        report = json.loads(job.report_json or "{}")
        report["interrupted"] = True
        session.execute(update(ImportJob).where(ImportJob.id == job.id, *stale_condition).values(
            status="stopped", active_slot=None, finished_at=now, report_json=json.dumps(report, ensure_ascii=False),
        ).execution_options(synchronize_session=False))
    session.commit()
    job_id = session.scalar(select(ImportJob.id).where(ImportJob.status == "queued").order_by(ImportJob.id).limit(1))
    if job_id is None:
        return None
    result = session.execute(update(ImportJob).where(ImportJob.id == job_id, ImportJob.status == "queued").values(
        status="running", owner_id=owner_id, heartbeat_at=now, started_at=now,
    ).execution_options(synchronize_session=False))
    session.commit()
    return job_id if result.rowcount == 1 else None


def refresh_lease(job_id: int, owner_id: str) -> bool:
    with session_scope() as session:
        result = session.execute(update(ImportJob).where(
            ImportJob.id == job_id, ImportJob.owner_id == owner_id, ImportJob.status.in_(("running", "stopping")),
        ).values(heartbeat_at=utcnow()).execution_options(synchronize_session=False))
        session.commit()
        return result.rowcount == 1


class JobClient(Client):
    def __init__(self, check_cancel, current_url, **kwargs):
        super().__init__(2, 2, **kwargs)
        self.check_cancel = check_cancel
        self.current_url = current_url

    def request(self, *args, **kwargs):
        self.check_cancel()
        if args:
            self.current_url(args[0])
        result = super().request(*args, **kwargs)
        self.check_cancel()
        return result


def run_job(job_id: int, owner_id: str, stop_event: threading.Event) -> None:
    finished = threading.Event()
    lease_lost = threading.Event()

    def check_cancel() -> None:
        if stop_event.is_set() or lease_lost.is_set():
            raise JobCancelled()
        with session_scope() as session:
            job = session.get(ImportJob, job_id)
            if (job is None or job.owner_id != owner_id or job.cancel_requested or
                    job.status not in ("running", "stopping")):
                raise JobCancelled()
            _active_admin(session, job.author_id)
            source = session.get(ImportSource, job.source_id)
            if source is None or source.deleted_at is not None:
                raise JobCancelled()

    def progress(report: dict) -> None:
        with session_scope() as session:
            current = session.get(ImportJob, job_id)
            snapshot = dict(report)
            if current:
                snapshot["current_url"] = json.loads(current.report_json or "{}").get("current_url")
            result = session.execute(update(ImportJob).where(
                ImportJob.id == job_id, ImportJob.owner_id == owner_id, ImportJob.status.in_(("running", "stopping")),
            ).values(
                report_json=json.dumps(snapshot, ensure_ascii=False), heartbeat_at=utcnow(),
            ).execution_options(synchronize_session=False))
            session.commit()
            if result.rowcount != 1:
                raise JobCancelled()
        if not report.get("interrupted"):
            check_cancel()

    def current_url(url: str) -> None:
        with session_scope() as session:
            job = session.get(ImportJob, job_id)
            if job is None or job.owner_id != owner_id or job.status not in ("running", "stopping"):
                raise JobCancelled()
            report = json.loads(job.report_json or "{}")
            report["current_url"] = url
            job.report_json = json.dumps(report, ensure_ascii=False)
            session.commit()

    def heartbeat() -> None:
        while not finished.wait(5):
            try:
                if not refresh_lease(job_id, owner_id):
                    lease_lost.set()
                    return
            except SQLAlchemyError:
                lease_lost.set()
                log.error("Could not renew recipe import lease for job %s", job_id)
                return

    heartbeat_thread = threading.Thread(target=heartbeat, name=f"recipe-import-heartbeat-{job_id}", daemon=True)
    heartbeat_thread.start()
    status = "failed"
    try:
        with session_scope() as session:
            job = session.get(ImportJob, job_id)
            parameters = json.loads(job.parameters_json)
            user_id, mode, source_id = job.author_id, job.mode, job.source_id
        check_cancel()
        definition = parameters["definition"].copy()
        if parameters.get("catalog_url"):
            catalog = public_source_url(parameters["catalog_url"])
            if not catalog or catalog.hostname not in definition["hosts"]:
                raise SourceConfigError("The selected section is outside the source hosts")
            definition["catalog_url"] = parameters["catalog_url"]
            definition["catalog_pattern"] = re.escape(catalog.path)
        sources = sources_from_data({"source": definition})
        report_dir = DATA_DIR / "import-reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        urls = parameters.get("urls", [])
        if parameters.get("category_id") and not parameters.get("catalog_url"):
            with session_scope() as session:
                urls = list(session.scalars(select(SourceRecipe.url).where(SourceRecipe.source_id == source_id,
                                             SourceRecipe.category_id == parameters["category_id"], SourceRecipe.active.is_(True))
                                             .order_by(SourceRecipe.id)))
            if not urls:
                raise CollectionError("В выбранной категории пока нет найденных рецептов; обновите каталог")
        args = argparse.Namespace(source_config=sources, site=[] if urls else ["source"], url=urls, urls_file=None,
                                  report=report_dir / f"job-{job_id}-{uuid.uuid4().hex}.json", output=None,
                                  limit=parameters["limit"], max_pages=0 if parameters["limit"] == 0 else max(500, parameters["limit"] * 5),
                                  public=parameters.get("is_public", True), no_images=False,
                                  no_step_images=parameters.get("no_step_images", False), progress_callback=progress,
                                  category_scope=bool(parameters.get("catalog_url")), max_catalog_pages=None)
        context, _ = configure_tls()
        client = JobClient(check_cancel, current_url, ssl_context=context, adaptive_delay=True, min_delay=0.25, max_delay=10)
        if mode == "index":
            from .source_catalog import index_source

            report = index_source(source_id, definition, client, check_cancel, progress, parameters["limit"])
            status = "failed" if report.get("errors") and not (report.get("indexed") or report.get("cached")) else "completed"
            return
        if mode == "images" and parameters.get("catalog_url"):
            candidates = discover("source", client, sources, category_scope=True)
            args.url = list(islice(candidates, args.max_pages)) if args.max_pages else list(candidates)
            if not args.url:
                raise CollectionError("No recipes found in the selected section")
        if mode == "import":
            from .source_catalog import ImportCatalogSync

            catalog_sync = ImportCatalogSync(source_id, check_cancel)
            args.on_category = catalog_sync.category_found
            args.on_recipe = catalog_sync.recipe_found
            args.recipe_callback = catalog_sync.recipe_parsed
            args.recipe_loader = catalog_sync.cached_recipe
        adapter = DatabaseImportAPI(user_id, check_cancel)
        report = backfill_images(args, client, adapter) if mode == "images" else collect(args, client, adapter)
        progress(report)
        changed = report.get("created", 0) + report.get("updated_images", 0) + report.get("updated_step_images", 0)
        status = "failed" if report.get("fatal") or (report.get("errors") and not changed) else "completed"
    except (JobCancelled, KeyboardInterrupt):
        status = "stopped"
    except (CollectionError, importer.ImportError_, APIError, SourceConfigError, TLSConfigurationError, OSError, ValueError, SQLAlchemyError) as exc:
        log.error("Recipe import job %s failed (%s)", job_id, type(exc).__name__)
        with session_scope() as session:
            job = session.get(ImportJob, job_id)
            if job and job.owner_id == owner_id:
                report = json.loads(job.report_json or "{}")
                message = str(exc) if isinstance(exc, (CollectionError, APIError, SourceConfigError, TLSConfigurationError)) else "Import failed; check the service logs"
                report.setdefault("errors", []).append({"stage": "worker", "error": message})
                job.report_json = json.dumps(report, ensure_ascii=False)
                session.commit()
    finally:
        finished.set()
        heartbeat_thread.join(timeout=2)
        with session_scope() as session:
            session.execute(update(ImportJob).where(ImportJob.id == job_id, ImportJob.owner_id == owner_id,
                                                   ImportJob.status.in_(("running", "stopping"))).values(
                status=status, active_slot=None, heartbeat_at=utcnow(), finished_at=utcnow(),
            ).execution_options(synchronize_session=False))
            session.commit()


class ImportWorker:
    def __init__(self):
        self.stop_event = threading.Event()
        self.owner_id = uuid.uuid4().hex
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        self.thread = threading.Thread(target=self._loop, name="recipe-import-worker", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=15)

    def _loop(self) -> None:
        while not self.stop_event.is_set():
            if db.is_configured():
                try:
                    with session_scope() as session:
                        from .source_catalog import enqueue_scheduled_index

                        enqueue_scheduled_index(session)
                        job_id = claim_job(session, self.owner_id)
                    if job_id is not None:
                        run_job(job_id, self.owner_id, self.stop_event)
                        continue
                except SQLAlchemyError:
                    log.error("Recipe import worker could not access the database")
            self.stop_event.wait(2)
