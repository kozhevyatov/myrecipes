from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .config import UPLOAD_DIR, settings
from .routers import admin, auth, catalog, recipes, setup

VERSION = "0.2.0"


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.startup()
    yield


app = FastAPI(title="Мои рецепты API", version=VERSION, lifespan=lifespan)

app.include_router(setup.router)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(catalog.router)
app.include_router(recipes.router)

# Загруженные фото. Имена файлов — случайные UUID.
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/api/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


@app.get("/api/health", tags=["system"])
def health() -> dict:
    return {"status": "ok", "version": VERSION, "database": db.is_configured()}


# ---------- фронтенд (SPA) ----------
static_dir = settings.static_dir
if (static_dir / "assets").exists():
    app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(404, "Not found")
    candidate = (static_dir / path).resolve()
    if path and candidate.is_file() and static_dir.resolve() in candidate.parents:
        return FileResponse(candidate)
    index = static_dir / "index.html"
    if index.exists():
        return FileResponse(index)
    raise HTTPException(404, "Фронтенд не собран")
