from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

USERNAME_PATTERN = r"^[a-zA-Z0-9_.-]{3,64}$"
# Простая проверка: домашние адреса вида admin@home.local тоже допустимы.
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+$"


# ---------- setup ----------
class SetupStatus(BaseModel):
    database_configured: bool
    database_from_env: bool
    setup_complete: bool
    setup_token_required: bool


class DatabaseConfig(BaseModel):
    type: Literal["sqlite", "mysql"]
    host: str | None = None
    port: int | None = 3306
    user: str | None = None
    password: str | None = None
    database: str | None = None


class AdminCreate(BaseModel):
    username: str = Field(pattern=USERNAME_PATTERN)
    email: str = Field(pattern=EMAIL_PATTERN, max_length=255)
    display_name: str = Field(default="", max_length=128)
    password: str = Field(min_length=8, max_length=128)
    site_name: str = Field(default="Мои рецепты", max_length=100)
    registration_mode: Literal["open", "closed"] = "closed"


# ---------- auth ----------
class LoginIn(BaseModel):
    login: str  # username или email
    password: str


class RegisterIn(BaseModel):
    username: str = Field(pattern=USERNAME_PATTERN)
    email: str = Field(pattern=EMAIL_PATTERN, max_length=255)
    display_name: str = Field(default="", max_length=128)
    password: str = Field(min_length=8, max_length=128)


class RefreshIn(BaseModel):
    refresh_token: str | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    display_name: str
    is_admin: bool
    is_active: bool
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    # Для мобильного приложения; в вебе refresh живёт в httpOnly-cookie.
    refresh_token: str
    token_type: str = "bearer"
    user: UserOut


# ---------- settings ----------
class PublicSettings(BaseModel):
    site_name: str
    registration_mode: Literal["open", "closed"]


class SettingsUpdate(BaseModel):
    site_name: str | None = Field(default=None, max_length=100)
    registration_mode: Literal["open", "closed"] | None = None


class UserAdminUpdate(BaseModel):
    is_admin: bool | None = None
    is_active: bool | None = None
