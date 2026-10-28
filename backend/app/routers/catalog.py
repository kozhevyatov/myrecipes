"""Справочники: категории, теги, продукты."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Category, Product, Recipe, Tag, User, recipe_tags
from ..schemas import CategoryIn, CategoryOut, TagOut
from ..security import get_current_user, require_admin

router = APIRouter(prefix="/api", tags=["catalog"])


def _category_out(db: Session, cat: Category) -> CategoryOut:
    count = db.scalar(select(func.count()).select_from(Recipe).where(Recipe.category_id == cat.id)) or 0
    return CategoryOut(id=cat.id, name=cat.name, sort_order=cat.sort_order, recipe_count=count)


@router.get("/categories", response_model=list[CategoryOut])
def list_categories(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[CategoryOut]:
    counts = dict(
        db.execute(
            select(Recipe.category_id, func.count()).where(Recipe.category_id.is_not(None)).group_by(Recipe.category_id)
        ).all()
    )
    cats = db.scalars(select(Category).order_by(Category.sort_order, Category.name)).all()
    return [
        CategoryOut(id=c.id, name=c.name, sort_order=c.sort_order, recipe_count=counts.get(c.id, 0)) for c in cats
    ]


@router.post("/categories", response_model=CategoryOut)
def create_category(
    data: CategoryIn, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> CategoryOut:
    name = data.name.strip()
    existing = db.scalar(select(Category).where(func.lower(Category.name) == name.lower()))
    if existing:
        return _category_out(db, existing)
    cat = Category(name=name, sort_order=data.sort_order)
    db.add(cat)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Такая категория уже есть")
    db.refresh(cat)
    return _category_out(db, cat)


@router.patch("/categories/{cat_id}", response_model=CategoryOut)
def update_category(
    cat_id: int, data: CategoryIn, db: Session = Depends(get_db), _: User = Depends(require_admin)
) -> CategoryOut:
    cat = db.get(Category, cat_id)
    if not cat:
        raise HTTPException(404, "Категория не найдена")
    cat.name = data.name.strip()
    cat.sort_order = data.sort_order
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Такая категория уже есть")
    return _category_out(db, cat)


@router.delete("/categories/{cat_id}")
def delete_category(cat_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)) -> dict:
    cat = db.get(Category, cat_id)
    if not cat:
        raise HTTPException(404, "Категория не найдена")
    # Рецепты не удаляются — остаются без категории
    db.query(Recipe).filter(Recipe.category_id == cat_id).update({Recipe.category_id: None})
    db.delete(cat)
    db.commit()
    return {"ok": True}


@router.get("/tags", response_model=list[TagOut])
def list_tags(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[TagOut]:
    rows = db.execute(
        select(Tag.name, func.count(recipe_tags.c.recipe_id))
        .join(recipe_tags, recipe_tags.c.tag_id == Tag.id, isouter=True)
        .group_by(Tag.id, Tag.name)
        .order_by(func.count(recipe_tags.c.recipe_id).desc(), Tag.name)
    ).all()
    return [TagOut(name=n, recipe_count=c) for n, c in rows if c > 0]


@router.get("/products", response_model=list[str])
def list_products(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[str]:
    return list(db.scalars(select(Product.name).order_by(Product.name)))
