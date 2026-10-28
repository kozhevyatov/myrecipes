"""Резервная копия рецептов: zip с recipes.json и фотографиями.

Формат простой и открытый — архив можно разобрать руками или перенести на другой сервер.
Это бэкап рецептов, а не всей базы: пользователи и настройки в архив не входят.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from ..config import UPLOAD_DIR
from ..db import get_db
from ..images import MAX_UPLOAD_BYTES, save_image_bytes
from ..models import Category, Recipe, RecipePhoto, User
from ..schemas import RecipeIn
from ..security import get_current_user
from .recipes import _apply

router = APIRouter(prefix="/api/backup", tags=["backup"])

FORMAT = "myrecipes-backup"
VERSION = 1
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024  # 2 ГБ


def _recipe_dict(r: Recipe, image_path: str | None, put=lambda name: None) -> dict:  # noqa: ANN001
    return {
        "title": r.title,
        "description": r.description,
        "category": r.category.name if r.category else None,
        "servings": r.servings,
        "prep_minutes": r.prep_minutes,
        "cook_minutes": r.cook_minutes,
        "difficulty": r.difficulty,
        "is_public": r.is_public,
        "source_url": r.source_url,
        "tags": [t.name for t in r.tags],
        "ingredients": [
            {"product": i.product.name, "amount": i.amount, "unit": i.unit, "note": i.note, "group": i.group_name}
            for i in r.ingredients
        ],
        "steps": [{"text": s.text, "timer_minutes": s.timer_minutes, "image": put(s.image)} for s in r.steps],
        "photos": [p for p in (put(ph.image) for ph in r.photos) if p],
        "image": image_path,
        "author": r.author.username,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.get("/export")
def export_recipes(
    scope: str = Query(default="auto", pattern="^(auto|mine|all)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FileResponse:
    """Админ по умолчанию выгружает все рецепты, остальные — только свои."""
    everything = user.is_admin and scope in ("auto", "all")
    query = select(Recipe).order_by(Recipe.id)
    if not everything:
        query = query.where(Recipe.author_id == user.id)
    recipes = db.scalars(query).unique().all()

    fd, path = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    try:
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            items = []
            written: set[str] = set()

            def put(name: str | None) -> str | None:
                if not name or not (UPLOAD_DIR / name).is_file():
                    return None
                arc = f"images/{name}"
                if arc not in written:
                    # WebP уже сжат — кладём без повторного сжатия
                    zf.write(UPLOAD_DIR / name, arc, compress_type=zipfile.ZIP_STORED)
                    written.add(arc)
                return arc

            for r in recipes:
                items.append(_recipe_dict(r, put(r.image), put))
            categories = db.scalars(select(Category).order_by(Category.sort_order, Category.name)).all()
            manifest = {
                "format": FORMAT,
                "version": VERSION,
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "categories": [{"name": c.name, "sort_order": c.sort_order} for c in categories],
                "recipes": items,
            }
            zf.writestr("recipes.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    except Exception:
        os.unlink(path)
        raise

    stamp = datetime.now().strftime("%Y-%m-%d")
    return FileResponse(
        path,
        media_type="application/zip",
        filename=f"recipes-{stamp}.zip",
        background=BackgroundTask(os.unlink, path),
    )


@router.post("/import")
def import_recipes(
    file: UploadFile = File(...),
    skip_duplicates: bool = True,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Загружает рецепты из архива. Повторы (то же название у того же автора) по умолчанию пропускаются."""
    with tempfile.TemporaryFile() as tmp:
        shutil.copyfileobj(file.file, tmp, length=1024 * 1024)
        if tmp.tell() > MAX_ARCHIVE_BYTES:
            raise HTTPException(413, "Архив больше 2 ГБ")
        tmp.seek(0)
        try:
            zf = zipfile.ZipFile(tmp)
        except zipfile.BadZipFile:
            raise HTTPException(400, "Это не zip-архив")
        with zf:
            try:
                if zf.getinfo("recipes.json").file_size > 100 * 1024 * 1024:
                    raise HTTPException(413, "recipes.json больше 100 МБ")
                manifest = json.loads(zf.read("recipes.json").decode("utf-8"))
            except (KeyError, UnicodeDecodeError, json.JSONDecodeError):
                raise HTTPException(400, "В архиве нет recipes.json — это не резервная копия «Моих рецептов»")
            if manifest.get("format") != FORMAT:
                raise HTTPException(400, "Неизвестный формат архива")
            return _restore(db, user, zf, manifest, skip_duplicates)


def _restore(db: Session, user: User, zf: zipfile.ZipFile, manifest: dict, skip_duplicates: bool) -> dict:
    names = set(zf.namelist())
    categories: dict[str, int] = {c.name.lower(): c.id for c in db.scalars(select(Category))}

    # Категории — в том порядке, что был на старом сервере
    for c in manifest.get("categories", []):
        name = str(c.get("name", "")).strip()[:100]
        if name and name.lower() not in categories:
            cat = Category(name=name, sort_order=int(c.get("sort_order") or 0))
            db.add(cat)
            db.flush()
            categories[name.lower()] = cat.id
    try:
        db.commit()
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(500, f"Не удалось создать категории: {getattr(e, 'orig', e)}")

    users_by_name = {u.username: u for u in db.scalars(select(User))} if user.is_admin else {}
    created = skipped = failed = 0
    errors: list[str] = []

    for item in manifest.get("recipes", []):
        title = str(item.get("title", "")).strip()
        # Админ сохраняет авторство, если такой пользователь есть; иначе автор — тот, кто загружает
        author = users_by_name.get(item.get("author")) or user
        try:
            if skip_duplicates and db.scalar(
                select(func.count())
                .select_from(Recipe)
                .where(Recipe.author_id == author.id, func.lower(Recipe.title) == title.lower())
            ):
                skipped += 1
                continue

            cat_name = (item.get("category") or "").strip()
            if cat_name and cat_name.lower() not in categories:
                cat = Category(name=cat_name[:100])
                db.add(cat)
                db.commit()  # сразу, чтобы откат следующего рецепта её не потерял
                categories[cat_name.lower()] = cat.id

            data = RecipeIn(
                title=title,
                description=item.get("description") or "",
                category_id=categories.get(cat_name.lower()) if cat_name else None,
                servings=item.get("servings") or 2,
                prep_minutes=item.get("prep_minutes"),
                cook_minutes=item.get("cook_minutes"),
                difficulty=item.get("difficulty"),
                is_public=item.get("is_public", True),
                source_url=item.get("source_url"),
                tags=item.get("tags") or [],
                ingredients=item.get("ingredients") or [],
                # Фото шагов разберём ниже — из архива
                steps=[{k: v for k, v in st.items() if k != "image"} for st in (item.get("steps") or []) if isinstance(st, dict)],
            )
            recipe = Recipe(author_id=author.id)
            db.add(recipe)
            _apply(db, recipe, data)

            def load(arc) -> str | None:  # noqa: ANN001
                if not isinstance(arc, str) or arc not in names or zf.getinfo(arc).file_size > MAX_UPLOAD_BYTES:
                    return None
                try:
                    return save_image_bytes(zf.read(arc))
                except HTTPException:
                    return None  # битое фото — рецепт всё равно восстанавливаем

            recipe.image = load(item.get("image"))
            raw_steps = [st for st in (item.get("steps") or []) if isinstance(st, dict) and str(st.get("text", "")).strip()]
            for step, raw in zip(recipe.steps, raw_steps):
                step.image = load(raw.get("image"))
            recipe.photos = [
                RecipePhoto(position=i, image=n)
                for i, n in enumerate(n for n in (load(a) for a in (item.get("photos") or [])[:30]) if n)
            ]
            db.commit()
            created += 1
        except (ValidationError, HTTPException, ValueError, TypeError, SQLAlchemyError) as e:
            db.rollback()
            failed += 1
            msg = getattr(e, "detail", None) or str(getattr(e, "orig", None) or e)
            if len(errors) < 10:
                errors.append(f"«{title or '?'}»: {str(msg)[:200]}")

    return {"created": created, "skipped": skipped, "failed": failed, "errors": errors}
