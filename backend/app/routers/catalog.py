"""Справочники: категории, теги, продукты."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Category, Product, Recipe, RecipeIngredient, Tag, User, recipe_tags
from ..schemas import CategoryIn, CategoryOut, ProductMerge, ProductOut, ProductUpdate, TagOut
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


# ---------- справочник продуктов с КБЖУ ----------
def _product_out(p: Product, count: int) -> ProductOut:
    return ProductOut(
        id=p.id,
        name=p.name,
        kcal=p.kcal,
        protein=p.protein,
        fat=p.fat,
        carbs=p.carbs,
        piece_grams=p.piece_grams,
        density=p.density,
        nutrition_source=p.nutrition_source,
        recipe_count=count,
    )


def _usage(db: Session) -> dict[int, int]:
    return dict(
        db.execute(
            select(RecipeIngredient.product_id, func.count(func.distinct(RecipeIngredient.recipe_id))).group_by(
                RecipeIngredient.product_id
            )
        ).all()
    )


@router.get("/products/catalog", response_model=list[ProductOut])
def products_catalog(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[ProductOut]:
    usage = _usage(db)
    return [_product_out(p, usage.get(p.id, 0)) for p in db.scalars(select(Product).order_by(Product.name))]


@router.patch("/products/{product_id}", response_model=ProductOut)
def update_product(
    product_id: int, data: ProductUpdate, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> ProductOut:
    p = db.get(Product, product_id)
    if not p:
        raise HTTPException(404, "Продукт не найден")
    fields = data.model_dump(exclude_unset=True)
    if "name" in fields:
        name = " ".join(fields.pop("name").split())
        clash = db.scalar(select(Product).where(func.lower(Product.name) == name.lower(), Product.id != p.id))
        if clash:
            raise HTTPException(409, f"«{clash.name}» уже есть — объедините продукты")
        p.name = name
    nutrition_keys = {"kcal", "protein", "fat", "carbs"}
    for key, value in fields.items():
        setattr(p, key, value)
    if nutrition_keys & fields.keys():
        p.nutrition_source = "user"
    db.commit()
    return _product_out(p, _usage(db).get(p.id, 0))


@router.post("/products/{product_id}/merge", response_model=ProductOut)
def merge_product(
    product_id: int, data: ProductMerge, db: Session = Depends(get_db), _: User = Depends(require_admin)
) -> ProductOut:
    """Объединяет дубли: все ингредиенты переходят к выбранному продукту, дубль удаляется."""
    src = db.get(Product, product_id)
    dst = db.get(Product, data.into_id)
    if not src or not dst or src.id == dst.id:
        raise HTTPException(400, "Выберите два разных продукта")
    db.query(RecipeIngredient).filter(RecipeIngredient.product_id == src.id).update(
        {RecipeIngredient.product_id: dst.id}
    )
    # КБЖУ переносим, только если у целевого их нет
    for key in ("kcal", "protein", "fat", "carbs", "piece_grams", "density"):
        if getattr(dst, key) is None and getattr(src, key) is not None:
            setattr(dst, key, getattr(src, key))
    if dst.nutrition_source is None:
        dst.nutrition_source = src.nutrition_source
    db.delete(src)
    db.commit()
    return _product_out(dst, _usage(db).get(dst.id, 0))


@router.delete("/products/{product_id}")
def delete_product(product_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)) -> dict:
    p = db.get(Product, product_id)
    if not p:
        raise HTTPException(404, "Продукт не найден")
    if _usage(db).get(p.id):
        raise HTTPException(409, "Продукт используется в рецептах — его можно только объединить с другим")
    db.delete(p)
    db.commit()
    return {"ok": True}
