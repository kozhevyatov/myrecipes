from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import User

ALGORITHM = "HS256"
REFRESH_COOKIE = "mr_refresh"
_ph = PasswordHasher()


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def _encode(payload: dict, lifetime: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = {**payload, "iat": now, "exp": now + lifetime}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def create_access_token(user: User) -> str:
    return _encode(
        {"sub": str(user.id), "type": "access", "adm": user.is_admin},
        timedelta(minutes=settings.access_token_minutes),
    )


SHORT_SESSION = timedelta(days=1)


def refresh_lifetime(remember: bool) -> timedelta:
    return timedelta(days=settings.refresh_token_days) if remember else SHORT_SESSION


def create_refresh_token(user: User, remember: bool = True) -> str:
    return _encode(
        {"sub": str(user.id), "type": "refresh", "ver": user.token_version, "rem": remember},
        refresh_lifetime(remember),
    )


def decode_token(token: str, expected_type: str) -> dict:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Недействительный токен")
    if payload.get("type") != expected_type:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Недействительный токен")
    return payload


def _bearer(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = _bearer(request)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется авторизация")
    payload = decode_token(token, "access")
    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Пользователь не найден")
    return user


def get_optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    if not _bearer(request):
        return None
    try:
        return get_current_user(request, db)
    except HTTPException:
        return None


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нужны права администратора")
    return user
