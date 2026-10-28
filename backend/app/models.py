from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    avatar: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Увеличивается при смене пароля/выходе со всех устройств — инвалидирует refresh-токены.
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


# ---------------- рецепты ----------------

recipe_tags = Table(
    "recipe_tags",
    Base.metadata,
    Column("recipe_id", ForeignKey("recipes.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Хранится в нижнем регистре
    name: Mapped[str] = mapped_column(String(64), unique=True)


class Product(Base):
    """Справочник продуктов: автодополнение, в будущем — КБЖУ."""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # КБЖУ на 100 г
    kcal: Mapped[float | None] = mapped_column(Float, nullable=True)
    protein: Mapped[float | None] = mapped_column(Float, nullable=True)
    fat: Mapped[float | None] = mapped_column(Float, nullable=True)
    carbs: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Для пересчёта в граммы: вес 1 шт и плотность (г/мл) — для ложек, стаканов, мл
    piece_grams: Mapped[float | None] = mapped_column(Float, nullable=True)
    density: Mapped[float | None] = mapped_column(Float, nullable=True)
    # auto — из встроенного справочника, user — поправлено вручную
    nutrition_source: Mapped[str | None] = mapped_column(String(16), nullable=True)


class Recipe(Base):
    __tablename__ = "recipes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True, index=True
    )
    servings: Mapped[int] = mapped_column(Integer, default=2)
    prep_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cook_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    difficulty: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1..3
    image: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Публичный — виден всем пользователям сервиса; иначе только автору (и админу)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    author: Mapped[User] = relationship(lazy="joined")
    category: Mapped[Category | None] = relationship(lazy="joined")
    tags: Mapped[list[Tag]] = relationship(secondary=recipe_tags, lazy="selectin", order_by=Tag.name)
    ingredients: Mapped[list[RecipeIngredient]] = relationship(
        back_populates="recipe",
        cascade="all, delete-orphan",
        order_by="RecipeIngredient.position",
        lazy="selectin",
    )
    steps: Mapped[list[RecipeStep]] = relationship(
        back_populates="recipe",
        cascade="all, delete-orphan",
        order_by="RecipeStep.position",
        lazy="selectin",
    )


class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str] = mapped_column(String(32), default="")
    note: Mapped[str] = mapped_column(String(200), default="")
    # Раздел: «Для теста», «Для соуса»; пустой — основной список
    group_name: Mapped[str] = mapped_column(String(100), default="")

    recipe: Mapped[Recipe] = relationship(back_populates="ingredients")
    product: Mapped[Product] = relationship(lazy="joined")


class RecipeStep(Base):
    __tablename__ = "recipe_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text)
    timer_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    recipe: Mapped[Recipe] = relationship(back_populates="steps")


class ShoppingItem(Base):
    """Пункт списка покупок. У каждого пользователя свой список."""

    __tablename__ = "shopping_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str] = mapped_column(String(32), default="")
    note: Mapped[str] = mapped_column(String(300), default="")  # из каких рецептов
    checked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Favorite(Base):
    __tablename__ = "favorites"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CookLog(Base):
    """Отметка «готовил(а)»: когда и с какой заметкой."""

    __tablename__ = "cook_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id", ondelete="CASCADE"), index=True)
    cooked_on: Mapped[date] = mapped_column(Date)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(lazy="joined")
