"""Личный кабинет: имя, email, пароль, аватар."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..images import MAX_UPLOAD_BYTES, delete_image, save_avatar_bytes
from ..models import User
from ..schemas import PasswordChange, ProfileUpdate, TokenOut, UserOut
from ..security import REFRESH_COOKIE, decode_token, get_current_user, hash_password, verify_password
from .auth import _tokens

router = APIRouter(prefix="/api/me", tags=["profile"])


@router.get("", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.patch("", response_model=UserOut)
def update_profile(data: ProfileUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> User:
    if data.display_name is not None:
        user.display_name = " ".join(data.display_name.split()) or user.username
    if data.email is not None:
        email = data.email.strip().lower()
        if email != user.email:
            taken = db.scalar(select(func.count()).select_from(User).where(User.email == email, User.id != user.id))
            if taken:
                raise HTTPException(409, "Этот email уже занят")
            user.email = email
    db.commit()
    db.refresh(user)
    return user


@router.post("/password", response_model=TokenOut)
def change_password(
    data: PasswordChange,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TokenOut:
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(400, "Текущий пароль указан неверно")
    user.password_hash = hash_password(data.new_password)
    user.token_version += 1  # остальные устройства выходят
    db.commit()
    db.refresh(user)
    # Текущее устройство остаётся в системе: выдаём новые токены, сохраняя «Запомнить меня»
    remember = True
    cookie = request.cookies.get(REFRESH_COOKIE)
    if cookie:
        try:
            remember = bool(decode_token(cookie, "refresh").get("rem", True))
        except HTTPException:
            pass
    return _tokens(user, request, response, remember)


@router.post("/avatar", response_model=UserOut)
async def upload_avatar(
    file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> User:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Файл больше 15 МБ")
    name = save_avatar_bytes(data)
    old = user.avatar
    user.avatar = name
    db.commit()
    delete_image(old)
    db.refresh(user)
    return user


@router.delete("/avatar", response_model=UserOut)
def remove_avatar(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> User:
    old = user.avatar
    user.avatar = None
    db.commit()
    delete_image(old)
    db.refresh(user)
    return user
