"""Справочники: категории, теги, продукты."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..costing import latest_prices, snapshot_recipes_with_product, unit_price
from ..db import get_db
from ..models import (
    Category,
    PantryItem,
    Product,
    ProductAlias,
    ProductPrice,
    Recipe,
    RecipeIngredient,
    ShoppingItem,
    Tag,
    User,
    recipe_tags,
)
from ..productmatch import add_alias, loose_key, match_key
from ..schemas import (
    CategoryIn,
    CategoryOut,
    DuplicateGroup,
    DuplicateProduct,
    PriceIn,
    PriceOut,
    ProductMerge,
    ProductOut,
    ProductUpdate,
    TagOut,
)
from ..security import get_current_user, require_admin
from .recipes import SelectedTags, _filters, _like, _selected_tags, _source_filters

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


@router.get("/tags/suggestions", response_model=list[TagOut])
def suggest_tags(
    q: str = Query(default="", max_length=100),
    category_id: int | None = None,
    tag: str | None = Query(default=None, max_length=64),
    tags: SelectedTags = None,
    mine: bool = False,
    favorites: bool = False,
    source_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=8, ge=1, le=8),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TagOut]:
    selected = _selected_tags(tag, tags)
    conditions = _filters(user, None, category_id, None, mine, favorites, selected)
    conditions.extend(_source_filters(db, source_id))
    query = q.strip().lower()
    if len(query) < 2:
        return []
    name = func.lower(func.trim(Tag.name))
    count = func.count(func.distinct(Recipe.id))
    # Count recipes, not tag rows: historical spelling variants can share a recipe.
    conditions.extend([name.like(_like(query), escape="\\"), name.not_in(selected)])
    rows = db.execute(
        select(name.label("name"), count.label("recipe_count"))
        .select_from(Tag)
        .join(recipe_tags, recipe_tags.c.tag_id == Tag.id)
        .join(Recipe, Recipe.id == recipe_tags.c.recipe_id)
        .where(*conditions)
        .group_by(name)
        .order_by(
            case((name == query, 1), else_=0).desc(),
            case((name.like(_like(query)[1:], escape="\\"), 1), else_=0).desc(),
            count.desc(),
            name,
        )
        .limit(limit)
    ).all()
    return [TagOut(name=tag_name, recipe_count=recipe_count) for tag_name, recipe_count in rows]


@router.get("/products", response_model=list[str])
def list_products(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[str]:
    return list(db.scalars(select(Product.name).order_by(Product.name)))


# ---------- справочник продуктов с КБЖУ ----------
def _price_out(pr: ProductPrice, p: Product, user: User | None = None, author: str | None = None) -> PriceOut:
    up = unit_price(pr, p)
    return PriceOut(
        id=pr.id,
        price=pr.price,
        package_amount=pr.package_amount,
        package_unit=pr.package_unit,
        created_at=pr.created_at,
        unit_price=round(up[0], 2) if up else None,
        unit_label=up[1] if up else None,
        author=author,
        can_delete=bool(user and (user.is_admin or pr.user_id == user.id)),
    )


def _product_out(p: Product, count: int, price: ProductPrice | None = None) -> ProductOut:
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
        price=_price_out(price, p) if price else None,
    )


def _one(db: Session, p: Product) -> ProductOut:
    return _product_out(p, _usage(db).get(p.id, 0), latest_prices(db, [p.id]).get(p.id))


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
    products = list(db.scalars(select(Product).order_by(Product.name)))
    prices = latest_prices(db, [p.id for p in products])
    return [_product_out(p, usage.get(p.id, 0), prices.get(p.id)) for p in products]


@router.patch("/products/{product_id}", response_model=ProductOut)
def update_product(
    product_id: int, data: ProductUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> ProductOut:
    p = db.get(Product, product_id)
    if not p:
        raise HTTPException(404, "Продукт не найден")
    fields = data.model_dump(exclude_unset=True)
    if "name" in fields and not user.is_admin:
        raise HTTPException(403, "Переименовать продукт может администратор")
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
    if {"piece_grams", "density"} & fields.keys():
        # Вес штуки и плотность влияют и на себестоимость
        snapshot_recipes_with_product(db, p.id)
        db.commit()
    return _one(db, p)


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
    # Цены, синонимы, списки покупок и кладовка тоже переходят к целевому продукту
    db.query(ProductPrice).filter(ProductPrice.product_id == src.id).update({ProductPrice.product_id: dst.id})
    db.query(ProductAlias).filter(ProductAlias.product_id == src.id).update({ProductAlias.product_id: dst.id})
    db.query(ShoppingItem).filter(ShoppingItem.product_id == src.id).update({ShoppingItem.product_id: dst.id})
    have = set(db.scalars(select(PantryItem.user_id).where(PantryItem.product_id == dst.id)))
    for item in db.scalars(select(PantryItem).where(PantryItem.product_id == src.id)):
        if item.user_id not in have:
            db.add(PantryItem(user_id=item.user_id, product_id=dst.id))
    # Старое имя запоминаем — импорт рецептов больше не создаст этот дубль
    if src.name.lower() != dst.name.lower():
        add_alias(db, src.name, dst.id)
    # КБЖУ переносим, только если у целевого их нет
    for key in ("kcal", "protein", "fat", "carbs", "piece_grams", "density"):
        if getattr(dst, key) is None and getattr(src, key) is not None:
            setattr(dst, key, getattr(src, key))
    if dst.nutrition_source is None:
        dst.nutrition_source = src.nutrition_source
    db.delete(src)
    db.commit()
    snapshot_recipes_with_product(db, dst.id)
    db.commit()
    return _one(db, dst)


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


# ---------- цены ----------
@router.get("/products/{product_id}/prices", response_model=list[PriceOut])
def product_prices(
    product_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[PriceOut]:
    p = db.get(Product, product_id)
    if not p:
        raise HTTPException(404, "Продукт не найден")
    names = {u.id: (u.display_name or u.username) for u in db.scalars(select(User))}
    rows = db.scalars(
        select(ProductPrice)
        .where(ProductPrice.product_id == p.id)
        .order_by(ProductPrice.created_at.desc(), ProductPrice.id.desc())
        .limit(50)
    )
    return [_price_out(r, p, user, names.get(r.user_id)) for r in rows]


@router.post("/products/{product_id}/prices", response_model=ProductOut)
def add_price(
    product_id: int, data: PriceIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> ProductOut:
    p = db.get(Product, product_id)
    if not p:
        raise HTTPException(404, "Продукт не найден")
    db.add(
        ProductPrice(
            product_id=p.id,
            price=round(data.price, 2),
            package_amount=data.package_amount,
            package_unit=data.package_unit,
            user_id=user.id,
        )
    )
    db.flush()
    snapshot_recipes_with_product(db, p.id)
    db.commit()
    return _one(db, p)


@router.delete("/products/prices/{price_id}", response_model=ProductOut)
def delete_price(price_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> ProductOut:
    pr = db.get(ProductPrice, price_id)
    if not pr:
        raise HTTPException(404, "Цена не найдена")
    if not (user.is_admin or pr.user_id == user.id):
        raise HTTPException(403, "Удалить цену может тот, кто её добавил, или администратор")
    p = db.get(Product, pr.product_id)
    db.delete(pr)
    db.flush()
    snapshot_recipes_with_product(db, p.id)
    db.commit()
    return _one(db, p)


# ---------- дубли ----------
@router.get("/products/duplicates", response_model=list[DuplicateGroup])
def product_duplicates(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[DuplicateGroup]:
    """Группы похожих продуктов. Первый в группе — предлагаемый «главный» (чаще всего в рецептах)."""
    usage = _usage(db)
    priced = set(db.scalars(select(ProductPrice.product_id).distinct()))
    groups: dict[str, list[Product]] = {}
    for p in db.scalars(select(Product)):
        key = loose_key(p.name)
        if key:
            groups.setdefault(key, []).append(p)
    result: list[DuplicateGroup] = []
    for items in groups.values():
        if len(items) < 2:
            continue
        # Главный: больше рецептов, затем короче название, затем старше
        items.sort(key=lambda p: (-usage.get(p.id, 0), len(p.name), p.id))
        head_key = match_key(items[0].name)
        result.append(
            DuplicateGroup(
                products=[
                    DuplicateProduct(
                        id=p.id,
                        name=p.name,
                        recipe_count=usage.get(p.id, 0),
                        has_price=p.id in priced,
                        exact=match_key(p.name) == head_key,
                    )
                    for p in items
                ]
            )
        )
    # Сначала группы с явными дублями, затем по числу продуктов
    result.sort(key=lambda g: (-sum(x.exact for x in g.products[1:]), -len(g.products), g.products[0].name))
    return result
