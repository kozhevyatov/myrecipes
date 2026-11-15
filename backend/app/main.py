from __future__ import annotations

import asyncio
import logging
import re
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, HTTPException, Request
from html import escape

from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .config import UPLOAD_DIR, settings
from .images import cleanup_import_images, ensure_thumbs
from .routers import admin, auth, backup, catalog, imports, pantry, plan, profile, public, recipes, setup, shopping

VERSION = "0.8.0"


SNAPSHOT_EVERY_SECONDS = 6 * 60 * 60


def _snapshot_once() -> None:
    from .costing import snapshot_all

    if not db.is_configured():
        return
    session = next(db.get_db())
    try:
        n = snapshot_all(session)
        if n:
            logging.getLogger("uvicorn.error").info("Себестоимость: записано снимков — %s", n)
    except Exception:  # noqa: BLE001
        session.rollback()
        logging.getLogger("uvicorn.error").exception("Не удалось записать снимки себестоимости")
    finally:
        session.close()


async def _snapshot_loop() -> None:
    """Плановые снимки себестоимости: раз в 6 часов, а новый снимок рецепта — не чаще раза в месяц,
    если ничего не менялось. Изменения цен и рецептов снимаются сразу, без этой задачи."""
    await asyncio.sleep(60)
    while True:
        await asyncio.to_thread(_snapshot_once)
        await asyncio.sleep(SNAPSHOT_EVERY_SECONDS)


@asynccontextmanager
async def lifespan(_: FastAPI):
    from .import_jobs import ImportWorker

    db.startup()
    cleanup_import_images()
    ensure_thumbs()
    task = asyncio.create_task(_snapshot_loop())
    worker = ImportWorker()
    worker.start()
    try:
        yield
    finally:
        worker.stop_event.set()
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        await asyncio.to_thread(worker.stop)


class ImmutableStatic(StaticFiles):
    """Файлы сборки Vite с хешем в имени — кэшируем «навсегда»."""

    async def get_response(self, path, scope):  # noqa: ANN001
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


app = FastAPI(title="Мои рецепты API", version=VERSION, lifespan=lifespan)

app.include_router(setup.router)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(imports.router)
app.include_router(catalog.router)
app.include_router(recipes.router)
app.include_router(backup.router)
app.include_router(profile.router)
app.include_router(shopping.router)
app.include_router(plan.router)
app.include_router(pantry.router)
app.include_router(public.router)

# Загруженные фото. Имена файлов — случайные UUID.
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/api/uploads", ImmutableStatic(directory=UPLOAD_DIR), name="uploads")


@app.get("/api/health", tags=["system"])
def health() -> dict:
    return {"status": "ok", "version": VERSION, "database": db.is_configured()}


# ---------- фронтенд (SPA) ----------
static_dir = settings.static_dir
if (static_dir / "assets").exists():
    app.mount("/assets", ImmutableStatic(directory=static_dir / "assets"), name="assets")


def _shared_preview(page: str, token: str, base: str) -> str:
    if not db.is_configured():
        return page
    from .routers.public import shared_recipe

    session = next(db.get_db())
    try:
        r = shared_recipe(session, token)
        if not r:
            return page.replace("<head>", '<head>\n    <meta name="robots" content="noindex" />', 1)
        desc = " ".join((r.description or "").split())[:200] or f"Рецепт: {r.title}"
        tags = [
            '<meta name="robots" content="noindex" />',
            f'<meta property="og:url" content="{escape(base)}/r/{escape(token)}" />',
            '<meta property="og:type" content="article" />',
            f'<meta property="og:title" content="{escape(r.title)}" />',
            f'<meta property="og:description" content="{escape(desc)}" />',
        ]
        cover = r.image or (r.photos[0].image if r.photos else None)
        if cover:
            tags.append(f'<meta property="og:image" content="{escape(base)}/api/uploads/{escape(cover)}" />')
            tags.append('<meta name="twitter:card" content="summary_large_image" />')
        page = re.sub(r"<title>.*?</title>", f"<title>{escape(r.title)}</title>", page, count=1, flags=re.S)
        return page.replace("<head>", "<head>\n    " + "\n    ".join(tags), 1)
    finally:
        session.close()


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str, request: Request):
    if path.startswith("api/"):
        raise HTTPException(404, "Not found")
    candidate = (static_dir / path).resolve()
    if path and candidate.is_file() and static_dir.resolve() in candidate.parents:
        headers = {}
        if candidate.name in ("sw.js", "manifest.json"):
            # Браузер должен быстро замечать новую версию service worker
            headers["Cache-Control"] = "no-cache"
            if candidate.name == "sw.js":
                headers["Service-Worker-Allowed"] = "/"
        return FileResponse(candidate, headers=headers)
    index = static_dir / "index.html"
    if index.exists() and path.startswith("r/"):
        # Публичная ссылка: подставляем название и фото, чтобы Telegram показал красивое превью
        page = _shared_preview(index.read_text("utf-8"), path[2:].strip("/"), str(request.base_url).rstrip("/"))
        return HTMLResponse(page, headers={"Cache-Control": "no-cache"})
    if index.exists():
        # index.html не кэшируем — иначе после деплоя открывалась бы старая версия
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
    raise HTTPException(404, "Фронтенд не собран")
