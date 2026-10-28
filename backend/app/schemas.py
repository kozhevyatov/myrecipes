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
    remember: bool = True  # «Запомнить меня»


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


# ---------- справочники ----------
class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    sort_order: int = 0
    recipe_count: int = 0


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    sort_order: int = 0


class TagOut(BaseModel):
    name: str
    recipe_count: int = 0


# ---------- рецепты ----------
class IngredientIn(BaseModel):
    product: str = Field(min_length=1, max_length=128)
    amount: float | None = Field(default=None, ge=0, le=1_000_000)
    unit: str = Field(default="", max_length=32)
    note: str = Field(default="", max_length=200)
    group: str = Field(default="", max_length=100)


class StepIn(BaseModel):
    text: str = Field(min_length=1, max_length=10_000)
    timer_minutes: int | None = Field(default=None, ge=1, le=10_000)


class RecipeIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    category_id: int | None = None
    servings: int = Field(default=2, ge=1, le=100)
    prep_minutes: int | None = Field(default=None, ge=0, le=10_000)
    cook_minutes: int | None = Field(default=None, ge=0, le=10_000)
    difficulty: int | None = Field(default=None, ge=1, le=3)
    is_public: bool = True
    source_url: str | None = Field(default=None, max_length=500)
    # Временное фото из импорта по ссылке (imp-….webp)
    image_token: str | None = Field(default=None, max_length=64)
    tags: list[str] = Field(default_factory=list, max_length=30)
    ingredients: list[IngredientIn] = Field(default_factory=list, max_length=200)
    steps: list[StepIn] = Field(default_factory=list, max_length=200)


class ImportIn(BaseModel):
    url: str = Field(min_length=8, max_length=2000)


class RecipeDraft(BaseModel):
    """Черновик из импорта — заполняет форму редактора, ещё не сохранён."""

    title: str
    description: str
    servings: int | None
    prep_minutes: int | None
    cook_minutes: int | None
    category_id: int | None
    category_name: str
    tags: list[str]
    ingredients: list[IngredientIn]
    steps: list[StepIn]
    image_token: str | None
    image_url: str | None
    source_url: str


class IngredientOut(BaseModel):
    id: int
    product: str
    amount: float | None
    unit: str
    note: str
    group: str


class StepOut(BaseModel):
    id: int
    position: int
    text: str
    timer_minutes: int | None


class AuthorOut(BaseModel):
    id: int
    name: str


class CategoryRef(BaseModel):
    id: int
    name: str


class RecipeListItem(BaseModel):
    id: int
    title: str
    description: str
    image_url: str | None
    category: CategoryRef | None
    tags: list[str]
    servings: int
    total_minutes: int | None
    difficulty: int | None
    is_public: bool
    author: AuthorOut
    updated_at: datetime


class RecipeOut(RecipeListItem):
    source_url: str | None
    prep_minutes: int | None
    cook_minutes: int | None
    ingredients: list[IngredientOut]
    steps: list[StepOut]
    can_edit: bool
    created_at: datetime


class RecipeListOut(BaseModel):
    items: list[RecipeListItem]
    total: int
