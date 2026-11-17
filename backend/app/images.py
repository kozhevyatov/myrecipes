"""Сохранение загруженных фото: поворот по EXIF, уменьшение, WebP."""
from __future__ import annotations

import io
import re
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar

from fastapi import HTTPException, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError

from .config import UPLOAD_DIR

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_SIDE = 1600
IMPORTED_MAX_SIDE = 1000  # фото, скачанные с чужих сайтов (импорт по ссылке и из «Базы рецептов»)
_max_side: ContextVar[int] = ContextVar("max_image_side", default=MAX_SIDE)
THUMB_SIDE = 640  # карточки в списке — ~40–70 КБ вместо 150–400 КБ
Image.MAX_IMAGE_PIXELS = 60_000_000  # защита от «бомб» распаковки


def image_url(name: str | None) -> str | None:
    return f"/api/uploads/{name}" if name else None


def _thumb_name(name: str) -> str:
    return name[:-5] + "-sm.webp" if name.endswith(".webp") else name + "-sm.webp"


def thumb_url(name: str | None) -> str | None:
    if not name:
        return None
    thumb = _thumb_name(name)
    return f"/api/uploads/{thumb}" if (UPLOAD_DIR / thumb).exists() else image_url(name)


def _save_thumb(img: Image.Image, name: str) -> None:
    small = img.copy()
    small.thumbnail((THUMB_SIDE, THUMB_SIDE), Image.Resampling.LANCZOS)
    small.save(UPLOAD_DIR / _thumb_name(name), "WEBP", quality=78, method=4)


def ensure_thumbs() -> None:
    """Миниатюры для фото, загруженных до их появления (и для восстановленных из архива)."""
    if not UPLOAD_DIR.exists():
        return
    for path in UPLOAD_DIR.glob("*.webp"):
        n = path.name
        if n.endswith("-sm.webp") or n.startswith(("avatar-", "imp-")):
            continue
        if not (UPLOAD_DIR / _thumb_name(n)).exists():
            try:
                with Image.open(path) as img:
                    _save_thumb(img, n)
            except (OSError, ValueError):
                pass


@contextmanager
def imported_images():
    """Внутри блока сохраняемые фото уменьшаются до IMPORTED_MAX_SIDE по большей стороне."""
    token = _max_side.set(IMPORTED_MAX_SIDE)
    try:
        yield
    finally:
        _max_side.reset(token)


async def save_image(file: UploadFile) -> str:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Файл больше 15 МБ")
    return save_image_bytes(data)


def save_image_bytes(data: bytes, prefix: str = "", max_side: int | None = None) -> str:
    side = max_side or _max_side.get()
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
        img.thumbnail((side, side), Image.Resampling.LANCZOS)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise HTTPException(400, "Это не похоже на изображение")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{prefix}{uuid.uuid4().hex}.webp"
    img.save(UPLOAD_DIR / name, "WEBP", quality=82, method=4)
    _save_thumb(img, name)
    return name


def save_avatar_bytes(data: bytes, size: int = 256) -> str:
    """Аватар: обрезка по центру в квадрат (клиент уже кадрирует, это страховка) и 256×256."""
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
        img = ImageOps.fit(img, (size, size), Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise HTTPException(400, "Это не похоже на изображение")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = f"avatar-{uuid.uuid4().hex}.webp"
    img.save(UPLOAD_DIR / name, "WEBP", quality=85, method=4)
    return name


def delete_image(name: str | None) -> None:
    if not name:
        return
    path = UPLOAD_DIR / name
    # Только файлы из нашей папки, без «../»
    for p in (path, UPLOAD_DIR / _thumb_name(name)):
        if p.parent == UPLOAD_DIR and p.exists():
            try:
                p.unlink()
            except OSError:
                pass


# ---------- временные фото из импорта ----------
IMPORT_PREFIX = "imp-"
_IMPORT_RE = re.compile(r"^imp-[0-9a-f]{32}\.webp$")  # без «-sm»


def claim_import_image(token: str | None) -> str | None:
    """Превращает временное фото импорта в постоянное. Возвращает новое имя или None."""
    if not token or not _IMPORT_RE.fullmatch(token):
        return None
    src = UPLOAD_DIR / token
    if not src.exists():
        return None
    name = f"{uuid.uuid4().hex}.webp"
    src.rename(UPLOAD_DIR / name)
    thumb = UPLOAD_DIR / _thumb_name(token)
    if thumb.exists():
        thumb.rename(UPLOAD_DIR / _thumb_name(name))
    return name


_PHOTO_RE = re.compile(r"^[0-9a-f]{32}\.webp$")


def resolve_photo(name: str | None, allowed: set[str]) -> str | None:
    """Фото из формы редактора: временный токен загрузки → постоянный файл;
    уже сохранённый файл принимаем, только если он и так принадлежал этому рецепту."""
    if not name:
        return None
    if _IMPORT_RE.fullmatch(name):
        return claim_import_image(name)
    if _PHOTO_RE.fullmatch(name) and name in allowed and (UPLOAD_DIR / name).exists():
        return name
    return None


def cleanup_import_images(max_age_hours: int = 24) -> None:
    """Удаляет временные фото импорта, которые так и не сохранили в рецепт."""
    if not UPLOAD_DIR.exists():
        return
    limit = time.time() - max_age_hours * 3600
    for path in UPLOAD_DIR.glob(f"{IMPORT_PREFIX}*.webp"):  # и сами фото, и их миниатюры
        try:
            if path.stat().st_mtime < limit:
                path.unlink()
        except OSError:
            pass
