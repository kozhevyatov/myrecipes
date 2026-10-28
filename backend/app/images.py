"""Сохранение загруженных фото: поворот по EXIF, уменьшение, WebP."""
from __future__ import annotations

import io
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
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
        img.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise HTTPException(400, "Это не похоже на изображение")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.webp"
    img.save(UPLOAD_DIR / name, "WEBP", quality=82, method=4)
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
