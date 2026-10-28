"""Списки покупок: несколько списков, общий доступ, добавление из рецептов со сложением."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.orm import Session

from .. import importer
from ..db import get_db
from ..images import image_url
from ..models import Product, Recipe, ShoppingItem, ShoppingList, ShoppingListMember, User, utcnow
from ..schemas import (
    AuthorOut,
    ShoppingAdded,
    ShoppingAddText,
    ShoppingFromProducts,
    ShoppingFromRecipe,
    ShoppingItemOut,
    ShoppingItemUpdate,
    ShoppingListIn,
    ShoppingListOut,
    ShoppingMembersIn,
)
from ..security import get_current_user
from .recipes import _get_visible, _is_staple

router = APIRouter(prefix="/api/shopping", tags=["shopping"])

DEFAULT_NAME = "Покупки"


# ---------- доступ ----------
def _accessible(user: User):
    return or_(
        ShoppingList.owner_id == user.id,
        exists().where(ShoppingListMember.list_id == ShoppingList.id, ShoppingListMember.user_id == user.id),
    )


def _get_list(db: Session, list_id: int, user: User) -> ShoppingList:
    lst = db.scalar(select(ShoppingList).where(ShoppingList.id == list_id, _accessible(user)))
    if not lst:
        raise HTTPException(404, "Список не найден")
    return lst


def _own_list(db: Session, list_id: int, user: User) -> ShoppingList:
    lst = _get_list(db, list_id, user)
    if lst.owner_id != user.id:
        raise HTTPException(403, "Это может только владелец списка")
    return lst


def _author(u: User) -> AuthorOut:
    return AuthorOut(id=u.id, name=u.display_name or u.username, avatar_url=image_url(u.avatar))


def _list_out(db: Session, lst: ShoppingList, user: User) -> ShoppingListOut:
    total = db.scalar(select(func.count()).select_from(ShoppingItem).where(ShoppingItem.list_id == lst.id)) or 0
    todo = (
        db.scalar(
            select(func.count())
            .select_from(ShoppingItem)
            .where(ShoppingItem.list_id == lst.id, ShoppingItem.checked.is_(False))
        )
        or 0
    )
    return ShoppingListOut(
        id=lst.id,
        name=lst.name,
        owner=_author(lst.owner),
        members=[_author(m) for m in lst.members],
        is_owner=lst.owner_id == user.id,
        todo=todo,
        total=total,
    )


def _items(db: Session, lst: ShoppingList) -> list[ShoppingItem]:
    return list(
        db.scalars(
            select(ShoppingItem)
            .where(ShoppingItem.list_id == lst.id)
            .order_by(ShoppingItem.checked, ShoppingItem.created_at, ShoppingItem.id)
        )
    )


def _touch(lst: ShoppingList) -> None:
    lst.updated_at = utcnow()


# ---------- сложение одинаковых продуктов ----------
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


def _add(
    db: Session,
    lst: ShoppingList,
    user: User,
    name: str,
    amount: float | None,
    unit: str,
    product: Product | None,
    note: str,
) -> bool:
    """Добавляет пункт или складывает с существующим некупленным. True — если сложили."""
    amount, unit = _base(amount, unit)
    for item in db.scalars(
        select(ShoppingItem).where(ShoppingItem.list_id == lst.id, ShoppingItem.checked.is_(False))
    ):
        same = (product is not None and item.product_id == product.id) or item.name.lower() == name.lower()
        if not same:
            continue
        item_amount, item_unit = _base(item.amount, item.unit)
        if item_unit != unit:
            continue
        if item_amount is not None and amount is not None:
            item_amount += amount
        elif not (item_amount is None and amount is None):
            continue
        item.amount, item.unit = _pretty(item_amount, item_unit)
        if note and note not in item.note:
            item.note = ", ".join(x for x in (item.note, note) if x)[:300]
        return True
    pa, pu = _pretty(amount, unit)
    db.add(
        ShoppingItem(
            list_id=lst.id,
            user_id=user.id,
            product_id=product.id if product else None,
            name=name,
            amount=pa,
            unit=pu,
            note=note[:300],
        )
    )
    return False


# ---------- списки ----------
@router.get("/lists", response_model=list[ShoppingListOut])
def get_lists(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[ShoppingListOut]:
    lists = list(db.scalars(select(ShoppingList).where(_accessible(user)).order_by(ShoppingList.created_at, ShoppingList.id)))
    if not lists:
        # У каждого всегда есть хотя бы один список
        lst = ShoppingList(name=DEFAULT_NAME, owner_id=user.id)
        db.add(lst)
        db.commit()
        db.refresh(lst)
        lists = [lst]
    return [_list_out(db, lst, user) for lst in lists]


@router.post("/lists", response_model=ShoppingListOut)
def create_list(data: ShoppingListIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> ShoppingListOut:
    lst = ShoppingList(name=" ".join(data.name.split()), owner_id=user.id)
    db.add(lst)
    db.commit()
    db.refresh(lst)
    return _list_out(db, lst, user)


@router.patch("/lists/{list_id}", response_model=ShoppingListOut)
def rename_list(
    list_id: int, data: ShoppingListIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> ShoppingListOut:
    lst = _get_list(db, list_id, user)  # переименовать может любой участник
    lst.name = " ".join(data.name.split())
    db.commit()
    return _list_out(db, lst, user)


@router.delete("/lists/{list_id}")
def delete_list(list_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    lst = _get_list(db, list_id, user)
    if lst.owner_id == user.id:
        db.delete(lst)
    else:
        # Участник не удаляет чужой список, а выходит из него
        lst.members = [m for m in lst.members if m.id != user.id]
    db.commit()
    return {"ok": True}


@router.get("/users", response_model=list[AuthorOut])
def shareable_users(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[AuthorOut]:
    """С кем можно поделиться: все активные пользователи, кроме себя."""
    users = db.scalars(select(User).where(User.is_active.is_(True), User.id != user.id).order_by(User.display_name, User.username))
    return [_author(u) for u in users]


@router.put("/lists/{list_id}/members", response_model=ShoppingListOut)
def set_members(
    list_id: int, data: ShoppingMembersIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> ShoppingListOut:
    lst = _own_list(db, list_id, user)
    ids = {i for i in data.user_ids if i != user.id}
    lst.members = list(db.scalars(select(User).where(User.id.in_(ids), User.is_active.is_(True)))) if ids else []
    db.commit()
    db.refresh(lst)
    return _list_out(db, lst, user)


# ---------- пункты ----------
@router.get("/lists/{list_id}/items", response_model=list[ShoppingItemOut])
def list_items(list_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[ShoppingItem]:
    return _items(db, _get_list(db, list_id, user))


@router.post("/lists/{list_id}/from-recipe", response_model=ShoppingAdded)
def add_from_recipe(
    list_id: int, data: ShoppingFromRecipe, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> ShoppingAdded:
    lst = _get_list(db, list_id, user)
    recipe: Recipe = _get_visible(db, data.recipe_id, user)
    factor = (data.servings or recipe.servings) / max(recipe.servings, 1)
    wanted = set(data.ingredient_ids) if data.ingredient_ids is not None else None
    added = merged = 0
    with db.no_autoflush:
        for ing in recipe.ingredients:
            if wanted is not None and ing.id not in wanted:
                continue
            if _is_staple(ing.product.name):
                continue  # воду не покупают
            amount = ing.amount * factor if ing.amount is not None else None
            if _add(db, lst, user, ing.product.name, amount, ing.unit, ing.product, recipe.title):
                merged += 1
            else:
                added += 1
            db.flush()
    _touch(lst)
    db.commit()
    return ShoppingAdded(added=added, merged=merged, items=_items(db, lst))


@router.post("/lists/{list_id}/from-products", response_model=ShoppingAdded)
def add_products(
    list_id: int, data: ShoppingFromProducts, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> ShoppingAdded:
    """Список названий без количества — например, чего не хватает для рецепта."""
    lst = _get_list(db, list_id, user)
    added = merged = 0
    with db.no_autoflush:
        for raw in dict.fromkeys(" ".join(n.split()) for n in data.names):
            if not raw:
                continue
            name = raw[:200]
            product = db.scalar(select(Product).where(func.lower(Product.name) == name.lower()))
            # Уже есть в списке (с количеством или без) — второй строкой не добавляем
            existing = next(
                (
                    i
                    for i in db.scalars(select(ShoppingItem).where(ShoppingItem.list_id == lst.id, ShoppingItem.checked.is_(False)))
                    if i.name.lower() == name.lower() or (product is not None and i.product_id == product.id)
                ),
                None,
            )
            if existing:
                note = data.note.strip()
                if note and note not in existing.note:
                    existing.note = ", ".join(x for x in (existing.note, note) if x)[:300]
                merged += 1
                continue
            if _add(db, lst, user, product.name if product else name, None, "", product, data.note.strip()):
                merged += 1
            else:
                added += 1
            db.flush()
    _touch(lst)
    db.commit()
    return ShoppingAdded(added=added, merged=merged, items=_items(db, lst))


@router.post("/lists/{list_id}/items", response_model=list[ShoppingItemOut])
def add_text(
    list_id: int, data: ShoppingAddText, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[ShoppingItem]:
    """Свободный ввод: «2 кг картошки», «молоко», «хлеб 2 шт»."""
    lst = _get_list(db, list_id, user)
    p = importer.parse_ingredient(data.text)
    name = p.product.strip() or data.text.strip()
    product = db.scalar(select(Product).where(func.lower(Product.name) == name.lower()))
    with db.no_autoflush:
        _add(db, lst, user, product.name if product else name, p.amount, p.unit if p.amount is not None else "", product, "")
    _touch(lst)
    db.commit()
    return _items(db, lst)


def _item(db: Session, item_id: int, user: User) -> ShoppingItem:
    item = db.get(ShoppingItem, item_id)
    if not item:
        raise HTTPException(404, "Пункт не найден")
    _get_list(db, item.list_id, user)  # проверка доступа
    return item


@router.patch("/items/{item_id}", response_model=ShoppingItemOut)
def update_item(
    item_id: int, data: ShoppingItemUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> ShoppingItem:
    item = _item(db, item_id, user)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    db.commit()
    return item


@router.delete("/items/{item_id}")
def delete_item(item_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    db.delete(_item(db, item_id, user))
    db.commit()
    return {"ok": True}


@router.post("/lists/{list_id}/clear", response_model=list[ShoppingItemOut])
def clear(
    list_id: int, checked_only: bool = True, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[ShoppingItem]:
    lst = _get_list(db, list_id, user)
    q = delete(ShoppingItem).where(ShoppingItem.list_id == lst.id)
    if checked_only:
        q = q.where(ShoppingItem.checked.is_(True))
    db.execute(q)
    db.commit()
    return _items(db, lst)
