from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import ratelimit
from ..app_settings import get_setting
from ..config import settings
from ..db import get_db
from ..models import User
from ..schemas import LoginIn, RefreshIn, RegisterIn, TokenOut, UserOut
from ..security import (
    REFRESH_COOKIE,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

def set_refresh_cookie(response: Response, token: str, request: Request, remember: bool = True) -> None:
    if settings.cookie_secure == "auto":
        # За reverse proxy схема берётся из X-Forwarded-Proto (uvicorn --proxy-headers).
        is_secure = request.url.scheme == "https"
    else:
        is_secure = settings.cookie_secure.lower() in ("1", "true", "yes")
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        # Без «Запомнить меня» — сессионная cookie: исчезает при закрытии браузера
        max_age=settings.refresh_token_days * 86400 if remember else None,
        httponly=True,
        secure=is_secure,
        samesite="lax",
        path="/api/auth",
    )


def _tokens(user: User, request: Request, response: Response, remember: bool = True) -> TokenOut:
    refresh = create_refresh_token(user, remember)
    set_refresh_cookie(response, refresh, request, remember)
    return TokenOut(
        access_token=create_access_token(user),
        refresh_token=refresh,
        user=UserOut.model_validate(user),
    )


@router.post("/login", response_model=TokenOut)
def login(data: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)) -> TokenOut:
    login_value = data.login.strip()
    ip = request.client.host if request.client else "?"
    ratelimit.check(login_value, ip)
    user = db.scalar(
        select(User).where(or_(User.username == login_value, User.email == login_value.lower()))
    )
    if not user or not verify_password(data.password, user.password_hash):
        ratelimit.fail(login_value, ip)
        raise HTTPException(401, "Неверный логин или пароль")
    ratelimit.success(login_value)
    if not user.is_active:
        raise HTTPException(403, "Учётная запись отключена")
    return _tokens(user, request, response, data.remember)


@router.post("/register", response_model=TokenOut)
def register(
    data: RegisterIn, request: Request, response: Response, db: Session = Depends(get_db)
) -> TokenOut:
    if get_setting(db, "setup_complete") != "1":
        raise HTTPException(409, "Сервис ещё не настроен")
    if get_setting(db, "registration_mode") != "open":
        raise HTTPException(403, "Регистрация закрыта")
    email = data.email.lower()
    exists = db.scalar(
        select(func.count()).select_from(User).where(or_(User.username == data.username, User.email == email))
    )
    if exists:
        raise HTTPException(409, "Пользователь с таким логином или email уже есть")
    user = User(
        username=data.username,
        email=email,
        display_name=data.display_name or data.username,
        password_hash=hash_password(data.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _tokens(user, request, response)


@router.post("/refresh", response_model=TokenOut)
def refresh(
    request: Request,
    response: Response,
    data: RefreshIn | None = None,
    db: Session = Depends(get_db),
) -> TokenOut:
    token = (data.refresh_token if data else None) or request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise HTTPException(401, "Нет refresh-токена")
    payload = decode_token(token, "refresh")
    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active or payload.get("ver") != user.token_version:
        raise HTTPException(401, "Сессия истекла")
    return _tokens(user, request, response, bool(payload.get("rem", True)))


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth")
    return {"ok": True}


@router.post("/logout-all")
def logout_all(response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    db_user = db.get(User, user.id)
    db_user.token_version += 1
    db.commit()
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth")
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user
