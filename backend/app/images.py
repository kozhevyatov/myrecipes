"""Сохранение загруженных фото: поворот по EXIF, уменьшение, WebP."""
from __future__ import annotations

import io
import re
import time
import uuid

from fastapi import HTTPException, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError

from .config import UPLOAD_DIR

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_SIDE = 1600
Image.MAX_IMAGE_PIXELS = 60_000_000  # защита от «бомб» распаковки


def image_url(name: str | None) -> str | None:
    return f"/api/uploads/{name}" if name else None


async def save_image(file: UploadFile) -> str:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Файл больше 15 МБ")
    return save_image_bytes(data)


def save_image_bytes(data: bytes, prefix: str = "") -> str:
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
        img.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise HTTPException(400, "Это не похоже на изображение")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{prefix}{uuid.uuid4().hex}.webp"
    img.save(UPLOAD_DIR / name, "WEBP", quality=82, method=4)
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
    if path.parent == UPLOAD_DIR and path.exists():
        try:
            path.unlink()
        except OSError:
            pass


# ---------- временные фото из импорта ----------
IMPORT_PREFIX = "imp-"
_IMPORT_RE = re.compile(r"^imp-[0-9a-f]{32}\.webp$")


def claim_import_image(token: str | None) -> str | None:
    """Превращает временное фото импорта в постоянное. Возвращает новое имя или None."""
    if not token or not _IMPORT_RE.fullmatch(token):
        return None
    src = UPLOAD_DIR / token
    if not src.exists():
        return None
    name = f"{uuid.uuid4().hex}.webp"
    src.rename(UPLOAD_DIR / name)
    return name


def cleanup_import_images(max_age_hours: int = 24) -> None:
    """Удаляет временные фото импорта, которые так и не сохранили в рецепт."""
    if not UPLOAD_DIR.exists():
        return
    limit = time.time() - max_age_hours * 3600
    for path in UPLOAD_DIR.glob(f"{IMPORT_PREFIX}*.webp"):
        try:
            if path.stat().st_mtime < limit:
                path.unlink()
        except OSError:
            pass
