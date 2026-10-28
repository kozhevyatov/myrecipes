"""Меню на неделю: блюда по дням и приёмам пищи, общий доступ, сборка списка покупок."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..images import image_url, thumb_url
from ..models import MealPlanEntry, MealPlanMember, Recipe, User
from ..nutrition import recipe_nutrition
from ..schemas import (
    AuthorOut,
    PlanEntryIn,
    PlanEntryOut,
    PlanEntryUpdate,
    PlanMembersIn,
    PlanOut,
    PlanOwnersOut,
    PlanRecipe,
    PlanToShopping,
    ShoppingAdded,
)
from ..security import get_current_user
from .recipes import Pantry, _get_visible, _is_staple, _total
from .shopping import _add, _get_list, _items, _touch

router = APIRouter(prefix="/api/plan", tags=["plan"])

MAX_DAYS = 42


def _author(u: User) -> AuthorOut:
    return AuthorOut(id=u.id, name=u.display_name or u.username, avatar_url=image_url(u.avatar))


def _owner(db: Session, owner_id: int | None, user: User) -> User:
    """Чьё меню открываем: своё или то, которым поделились."""
    if owner_id is None or owner_id == user.id:
        return user
    allowed = db.get(MealPlanMember, (owner_id, user.id))
    owner = db.get(User, owner_id)
    if not allowed or not owner:
        raise HTTPException(404, "Меню не найдено")
    return owner


def _recipe_out(r: Recipe) -> PlanRecipe:
    n = recipe_nutrition(r.ingredients) if r.ingredients else None
    s = max(r.servings, 1)
    has = n is not None and n.counted > 0
    return PlanRecipe(
        id=r.id,
        title=r.title,
        thumb_url=thumb_url(r.image),
        servings=r.servings,
        total_minutes=_total(r),
        kcal_per_serving=round(n.kcal / s) if has else None,
        protein_per_serving=round(n.protein / s, 1) if has else None,
        fat_per_serving=round(n.fat / s, 1) if has else None,
        carbs_per_serving=round(n.carbs / s, 1) if has else None,
    )


def _entry_out(e: MealPlanEntry, cache: dict[int, PlanRecipe]) -> PlanEntryOut:
    recipe = None
    if e.recipe:
        if e.recipe.id not in cache:
            cache[e.recipe.id] = _recipe_out(e.recipe)
        recipe = cache[e.recipe.id]
    return PlanEntryOut(
        id=e.id, day=e.day, slot=e.slot, position=e.position, servings=e.servings, note=e.note, recipe=recipe
    )


def _members(db: Session, owner: User) -> list[AuthorOut]:
    users = db.scalars(
        select(User).join(MealPlanMember, MealPlanMember.user_id == User.id).where(MealPlanMember.owner_id == owner.id)
    )
    return [_author(u) for u in users]


@router.get("", response_model=PlanOut)
def get_plan(
    start: date,
    days: int = Query(default=7, ge=1, le=MAX_DAYS),
    owner_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PlanOut:
    owner = _owner(db, owner_id, user)
    entries = db.scalars(
        select(MealPlanEntry)
        .where(
            MealPlanEntry.owner_id == owner.id,
            MealPlanEntry.day >= start,
            MealPlanEntry.day < start + timedelta(days=days),
        )
        .order_by(MealPlanEntry.day, MealPlanEntry.position, MealPlanEntry.id)
    ).unique()
    cache: dict[int, PlanRecipe] = {}
    return PlanOut(
        owner=_author(owner),
        is_owner=owner.id == user.id,
        members=_members(db, owner) if owner.id == user.id else [],
        entries=[_entry_out(e, cache) for e in entries],
    )


@router.get("/owners", response_model=PlanOwnersOut)
def plan_owners(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> PlanOwnersOut:
    shared = db.scalars(
        select(User)
        .join(MealPlanMember, MealPlanMember.owner_id == User.id)
        .where(MealPlanMember.user_id == user.id, User.is_active.is_(True))
        .order_by(User.display_name, User.username)
    )
    return PlanOwnersOut(owners=[_author(user), *[_author(u) for u in shared]])


@router.put("/members", response_model=list[AuthorOut])
def set_members(data: PlanMembersIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[AuthorOut]:
    """Кому открыть своё меню (видят и могут менять)."""
    ids = {i for i in data.user_ids if i != user.id}
    valid = set(db.scalars(select(User.id).where(User.id.in_(ids), User.is_active.is_(True)))) if ids else set()
    for m in db.scalars(select(MealPlanMember).where(MealPlanMember.owner_id == user.id)):
        if m.user_id not in valid:
            db.delete(m)
        else:
            valid.discard(m.user_id)
    for uid in valid:
        db.add(MealPlanMember(owner_id=user.id, user_id=uid))
    db.commit()
    return _members(db, user)


def _next_position(db: Session, owner_id: int, day: date, slot: str) -> int:
    last = db.scalar(
        select(func.max(MealPlanEntry.position)).where(
            MealPlanEntry.owner_id == owner_id, MealPlanEntry.day == day, MealPlanEntry.slot == slot
        )
    )
    return (last or 0) + 1


@router.post("", response_model=PlanEntryOut)
def add_entry(data: PlanEntryIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> PlanEntryOut:
    owner = _owner(db, data.owner_id, user)
    recipe = _get_visible(db, data.recipe_id, user) if data.recipe_id else None
    note = " ".join(data.note.split())
    if not recipe and not note:
        raise HTTPException(422, "Выберите рецепт или напишите, что будет")
    entry = MealPlanEntry(
        owner_id=owner.id,
        day=data.day,
        slot=data.slot,
        position=_next_position(db, owner.id, data.day, data.slot),
        recipe_id=recipe.id if recipe else None,
        servings=data.servings or (recipe.servings if recipe else 1),
        note=note,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return _entry_out(entry, {})


def _entry(db: Session, entry_id: int, user: User) -> MealPlanEntry:
    entry = db.get(MealPlanEntry, entry_id)
    if not entry:
        raise HTTPException(404, "Блюдо не найдено")
    _owner(db, entry.owner_id, user)  # проверка доступа
    return entry


@router.patch("/{entry_id}", response_model=PlanEntryOut)
def update_entry(
    entry_id: int, data: PlanEntryUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> PlanEntryOut:
    entry = _entry(db, entry_id, user)
    changes = data.model_dump(exclude_unset=True)
    moved = ("day" in changes and changes["day"] != entry.day) or ("slot" in changes and changes["slot"] != entry.slot)
    for key, value in changes.items():
        if value is None:
            continue
        setattr(entry, key, " ".join(value.split()) if key == "note" else value)
    if moved and "position" not in changes:
        entry.position = _next_position(db, entry.owner_id, entry.day, entry.slot)
    db.commit()
    db.refresh(entry)
    return _entry_out(entry, {})


@router.delete("/{entry_id}")
def delete_entry(entry_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    db.delete(_entry(db, entry_id, user))
    db.commit()
    return {"ok": True}


@router.post("/to-shopping", response_model=ShoppingAdded)
def to_shopping(data: PlanToShopping, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> ShoppingAdded:
    """Все ингредиенты блюд за период — в список покупок; одинаковые продукты складываются."""
    if data.end < data.start or (data.end - data.start).days > MAX_DAYS:
        raise HTTPException(422, "Неверный период")
    owner = _owner(db, data.owner_id, user)
    lst = _get_list(db, data.list_id, user)
    q = select(MealPlanEntry).where(
        MealPlanEntry.owner_id == owner.id,
        MealPlanEntry.day >= data.start,
        MealPlanEntry.day <= data.end,
        MealPlanEntry.recipe_id.is_not(None),
    )
    if data.entry_ids is not None:
        q = q.where(MealPlanEntry.id.in_(data.entry_ids))
    entries = list(db.scalars(q).unique())
    pantry = Pantry(db, user) if data.skip_pantry else None
    added = merged = 0
    with db.no_autoflush:
        for e in entries:
            r = e.recipe
            if not r:
                continue
            factor = e.servings / max(r.servings, 1)
            for ing in r.ingredients:
                if _is_staple(ing.product.name) or (pantry and pantry.has(ing.product)):
                    continue
                amount = ing.amount * factor if ing.amount is not None else None
                if _add(db, lst, user, ing.product.name, amount, ing.unit, ing.product, r.title):
                    merged += 1
                else:
                    added += 1
                db.flush()
    _touch(lst)
    db.commit()
    return ShoppingAdded(added=added, merged=merged, items=_items(db, lst))
