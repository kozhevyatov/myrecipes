"""«Что есть дома»: продукты, которые есть у пользователя. По ним подбираются рецепты,
и их можно не добавлять в список покупок."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import PantryItem, Product, User
from ..nutrition import fill_from_seed
from ..schemas import PantryAdd, PantryItemOut
from ..security import get_current_user

router = APIRouter(prefix="/api/pantry", tags=["pantry"])


def _out(db: Session, user: User) -> list[PantryItemOut]:
    rows = db.scalars(
        select(PantryItem).join(Product).where(PantryItem.user_id == user.id).order_by(func.lower(Product.name))
    ).unique()
    return [PantryItemOut(product_id=p.product_id, name=p.product.name) for p in rows]


@router.get("", response_model=list[PantryItemOut])
def get_pantry(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[PantryItemOut]:
    return _out(db, user)


@router.post("", response_model=list[PantryItemOut])
def add_to_pantry(data: PantryAdd, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[PantryItemOut]:
    """Добавить по названию. Незнакомый продукт попадёт в справочник."""
    name = " ".join(data.name.split())
    name = name[:1].upper() + name[1:]
    product = db.scalar(select(Product).where(func.lower(Product.name) == name.lower()))
    if not product:
        product = Product(name=name)
        fill_from_seed(product)
        db.add(product)
        db.flush()
    if not db.get(PantryItem, (user.id, product.id)):
        db.add(PantryItem(user_id=user.id, product_id=product.id))
    db.commit()
    return _out(db, user)


@router.delete("/{product_id}", response_model=list[PantryItemOut])
def remove_from_pantry(product_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[PantryItemOut]:
    item = db.get(PantryItem, (user.id, product_id))
    if item:
        db.delete(item)
        db.commit()
    return _out(db, user)


@router.delete("", response_model=list[PantryItemOut])
def clear_pantry(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[PantryItemOut]:
    for item in db.scalars(select(PantryItem).where(PantryItem.user_id == user.id)):
        db.delete(item)
    db.commit()
    return []
