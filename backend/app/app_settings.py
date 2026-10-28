"""Настройки сервиса, хранящиеся в БД (меняются из админки)."""
from __future__ import annotations

from typing import Literal

from sqlalchemy.orm import Session

from .models import AppSetting

RegistrationMode = Literal["open", "closed"]

DEFAULTS: dict[str, str] = {
    "site_name": "Мои рецепты",
    "registration_mode": "closed",
    "setup_complete": "0",
}


def get_setting(db: Session, key: str) -> str:
    row = db.get(AppSetting, key)
    return row.value if row else DEFAULTS.get(key, "")


def set_setting(db: Session, key: str, value: str) -> None:
    row = db.get(AppSetting, key)
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))


def public_settings(db: Session) -> dict:
    return {
        "site_name": get_setting(db, "site_name"),
        "registration_mode": get_setting(db, "registration_mode"),
    }
