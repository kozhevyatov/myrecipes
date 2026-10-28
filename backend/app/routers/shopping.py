"""Список покупок: добавление из рецептов со сложением одинаковых продуктов."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import importer
from ..db import get_db
from ..models import Product, Recipe, ShoppingItem, User
from ..schemas import (
    ShoppingAdded,
    ShoppingAddText,
    ShoppingFromRecipe,
    ShoppingItemOut,
    ShoppingItemUpdate,
)
from ..security import get_current_user
from .recipes import _get_visible

router = APIRouter(prefix="/api/shopping", tags=["shopping"])

# Единицы, которые можно складывать: приводим к базовой
_BASE = {"г": ("г", 1.0), "гр": ("г", 1.0), "кг": ("г", 1000.0), "мл": ("мл", 1.0), "л": ("мл", 1000.0)}


def _base(amount: float | None, unit: str) -> tuple[float | None, str]:
    if unit in _BASE and amount is not None:
        u, k = _BASE[unit]
        return amount * k, u
    return amount, unit


def _pretty(amount: float | None, unit: str) -> tuple[float | None, str]:
    """1500 г → 1,5 кг; 1200 мл → 1,2 л."""
    if amount is None:
        return None, unit
    if unit == "г" and amount >= 1000:
        return round(amount / 1000, 3), "кг"
    if unit == "мл" and amount >= 1000:
        return round(amount / 1000, 3), "л"
    return round(amount, 2), unit


def _items(db: Session, user: User) -> list[ShoppingItem]:
    return list(
        db.scalars(
            select(ShoppingItem)
            .where(ShoppingItem.user_id == user.id)
            .order_by(ShoppingItem.checked, ShoppingItem.created_at, ShoppingItem.id)
        )
    )


def _add(
    db: Session, user: User, name: str, amount: float | None, unit: str, product: Product | None, note: str
) -> bool:
    """Добавляет пункт или складывает с существующим. True — если сложили."""
    amount, unit = _base(amount, unit)
    key = (product.id if product else None, name.lower())
    for item in db.scalars(select(ShoppingItem).where(ShoppingItem.user_id == user.id, ShoppingItem.checked.is_(False))):
        same = (product and item.product_id == product.id) or (item.name.lower() == key[1])
        if not same:
            continue
        item_amount, item_unit = _base(item.amount, item.unit)
        if item_unit != unit:
            continue
        if unit == "по вкусу" or (item_amount is None and amount is None):
            pass
        elif item_amount is not None and amount is not None:
            item_amount += amount
        else:
            continue
        item.amount, item.unit = _pretty(item_amount, item_unit)
        if note and note not in item.note:
            item.note = ", ".join(x for x in (item.note, note) if x)[:300]
        return True
    pa, pu = _pretty(amount, unit)
    db.add(ShoppingItem(user_id=user.id, product_id=product.id if product else None, name=name, amount=pa, unit=pu, note=note[:300]))
    return False


@router.get("", response_model=list[ShoppingItemOut])
def list_items(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[ShoppingItem]:
    return _items(db, user)


@router.post("/from-recipe", response_model=ShoppingAdded)
def add_from_recipe(
    data: ShoppingFromRecipe, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> ShoppingAdded:
    recipe: Recipe = _get_visible(db, data.recipe_id, user)
    factor = (data.servings or recipe.servings) / max(recipe.servings, 1)
    wanted = set(data.ingredient_ids) if data.ingredient_ids is not None else None
    added = merged = 0
    with db.no_autoflush:
        for ing in recipe.ingredients:
            if wanted is not None and ing.id not in wanted:
                continue
            amount = ing.amount * factor if ing.amount is not None else None
            if _add(db, user, ing.product.name, amount, ing.unit, ing.product, recipe.title):
                merged += 1
            else:
                added += 1
            db.flush()
    db.commit()
    return ShoppingAdded(added=added, merged=merged, items=_items(db, user))


@router.post("/items", response_model=list[ShoppingItemOut])
def add_text(data: ShoppingAddText, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[ShoppingItem]:
    """Свободный ввод: «2 кг картошки», «молоко», «хлеб 2 шт»."""
    p = importer.parse_ingredient(data.text)
    name = p.product.strip() or data.text.strip()
    product = db.scalar(select(Product).where(func.lower(Product.name) == name.lower()))
    with db.no_autoflush:
        _add(db, user, product.name if product else name, p.amount, p.unit if p.amount is not None else "", product, "")
    db.commit()
    return _items(db, user)


@router.patch("/items/{item_id}", response_model=ShoppingItemOut)
def update_item(
    item_id: int, data: ShoppingItemUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> ShoppingItem:
    item = db.get(ShoppingItem, item_id)
    if not item or item.user_id != user.id:
        raise HTTPException(404, "Пункт не найден")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    db.commit()
    return item


@router.delete("/items/{item_id}")
def delete_item(item_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    item = db.get(ShoppingItem, item_id)
    if not item or item.user_id != user.id:
        raise HTTPException(404, "Пункт не найден")
    db.delete(item)
    db.commit()
    return {"ok": True}


@router.post("/clear", response_model=list[ShoppingItemOut])
def clear(checked_only: bool = True, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[ShoppingItem]:
    q = delete(ShoppingItem).where(ShoppingItem.user_id == user.id)
    if checked_only:
        q = q.where(ShoppingItem.checked.is_(True))
    db.execute(q)
    db.commit()
    return _items(db, user)
