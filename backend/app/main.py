from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .config import UPLOAD_DIR, settings
from .images import cleanup_import_images
from .routers import admin, auth, backup, catalog, recipes, setup

VERSION = "0.4.0"


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.startup()
    cleanup_import_images()
    yield


app = FastAPI(title="Мои рецепты API", version=VERSION, lifespan=lifespan)

app.include_router(setup.router)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(catalog.router)
app.include_router(recipes.router)
app.include_router(backup.router)

# Загруженные фото. Имена файлов — случайные UUID.
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/api/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


@app.get("/api/health", tags=["system"])
def health() -> dict:
    return {"status": "ok", "version": VERSION, "database": db.is_configured()}


# ---------- фронтенд (SPA) ----------
class ImmutableStatic(StaticFiles):
    """Файлы сборки Vite с хешем в имени — кэшируем «навсегда»."""

    async def get_response(self, path, scope):  # noqa: ANN001
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


static_dir = settings.static_dir
if (static_dir / "assets").exists():
    app.mount("/assets", ImmutableStatic(directory=static_dir / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
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
    if index.exists():
        # index.html не кэшируем — иначе после деплоя открывалась бы старая версия
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
    raise HTTPException(404, "Фронтенд не собран")
