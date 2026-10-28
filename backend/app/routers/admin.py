from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..app_settings import public_settings, set_setting
from ..db import get_db
from ..models import User
from ..schemas import PasswordReset, PublicSettings, SettingsUpdate, UserAdminCreate, UserAdminUpdate, UserOut
from ..security import hash_password, require_admin

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/settings", response_model=PublicSettings)
def get_public_settings(db: Session = Depends(get_db)) -> dict:
    """Публичные настройки: название сайта, открыта ли регистрация."""
    return public_settings(db)


@router.patch("/admin/settings", response_model=PublicSettings)
def update_settings(
    data: SettingsUpdate, db: Session = Depends(get_db), _: User = Depends(require_admin)
) -> dict:
    if data.site_name is not None:
        set_setting(db, "site_name", data.site_name.strip() or "Мои рецепты")
    if data.registration_mode is not None:
        set_setting(db, "registration_mode", data.registration_mode)
    db.commit()
    return public_settings(db)


@router.get("/admin/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> list[User]:
    return list(db.scalars(select(User).order_by(User.id)))


@router.patch("/admin/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    data: UserAdminUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> User:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Пользователь не найден")
    if user.id == admin.id and (data.is_admin is False or data.is_active is False):
        raise HTTPException(400, "Нельзя снять права или отключить самого себя")
    if data.is_admin is not None:
        user.is_admin = data.is_admin
    if data.is_active is not None:
        user.is_active = data.is_active
        if not data.is_active:
            user.token_version += 1
    db.commit()
    db.refresh(user)
    return user


@router.post("/admin/users", response_model=UserOut)
def create_user(data: UserAdminCreate, db: Session = Depends(get_db), _: User = Depends(require_admin)) -> User:
    """Админ добавляет пользователя сам — работает и при закрытой регистрации."""
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
        is_admin=data.is_admin,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/admin/users/{user_id}/password")
def reset_password(
    user_id: int, data: PasswordReset, db: Session = Depends(get_db), _: User = Depends(require_admin)
) -> dict:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Пользователь не найден")
    user.password_hash = hash_password(data.password)
    user.token_version += 1  # выкидывает со всех устройств
    db.commit()
    return {"ok": True}
