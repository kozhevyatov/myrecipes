from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import exists, func, or_, select, true
from sqlalchemy.orm import Session

from ..db import get_db
from .. import importer
from ..images import IMPORT_PREFIX, claim_import_image, delete_image, image_url, save_image, save_image_bytes
from ..models import Category, Product, Recipe, RecipeIngredient, RecipeStep, Tag, User, recipe_tags, utcnow
from ..schemas import (
    AuthorOut,
    CategoryRef,
    ImportIn,
    IngredientIn,
    IngredientOut,
    RecipeDraft,
    StepIn,
    RecipeIn,
    RecipeListItem,
    RecipeListOut,
    RecipeOut,
    StepOut,
)
from ..security import get_current_user

router = APIRouter(prefix="/api/recipes", tags=["recipes"])


# ---------- доступ ----------
def _visible(user: User):
    """Условие видимости: публичные + свои; админ видит всё."""
    if user.is_admin:
        return true()
    return or_(Recipe.is_public == true(), Recipe.author_id == user.id)


def _can_edit(recipe: Recipe, user: User) -> bool:
    return user.is_admin or recipe.author_id == user.id


def _get_visible(db: Session, recipe_id: int, user: User) -> Recipe:
    recipe = db.get(Recipe, recipe_id)
    if not recipe or not (recipe.is_public or _can_edit(recipe, user)):
        raise HTTPException(404, "Рецепт не найден")
    return recipe


def _get_editable(db: Session, recipe_id: int, user: User) -> Recipe:
    recipe = _get_visible(db, recipe_id, user)
    if not _can_edit(recipe, user):
        raise HTTPException(403, "Редактировать может только автор")
    return recipe


# ---------- сериализация ----------
def _total(r: Recipe) -> int | None:
    if r.prep_minutes is None and r.cook_minutes is None:
        return None
    return (r.prep_minutes or 0) + (r.cook_minutes or 0)


def _base(r: Recipe) -> dict:
    return dict(
        id=r.id,
        title=r.title,
        description=r.description,
        image_url=image_url(r.image),
        category=CategoryRef(id=r.category.id, name=r.category.name) if r.category else None,
        tags=[t.name for t in r.tags],
        servings=r.servings,
        total_minutes=_total(r),
        difficulty=r.difficulty,
        is_public=r.is_public,
        author=AuthorOut(
            id=r.author.id,
            name=r.author.display_name or r.author.username,
            avatar_url=image_url(r.author.avatar),
        ),
        updated_at=r.updated_at,
    )


def _full(r: Recipe, user: User) -> RecipeOut:
    return RecipeOut(
        **_base(r),
        source_url=r.source_url,
        prep_minutes=r.prep_minutes,
        cook_minutes=r.cook_minutes,
        ingredients=[
            IngredientOut(
                id=i.id, product=i.product.name, amount=i.amount, unit=i.unit, note=i.note, group=i.group_name
            )
            for i in r.ingredients
        ],
        steps=[StepOut(id=s.id, position=s.position, text=s.text, timer_minutes=s.timer_minutes) for s in r.steps],
        can_edit=_can_edit(r, user),
        created_at=r.created_at,
    )


# ---------- поиск ----------
def _like(value: str) -> str:
    escaped = value.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@router.get("", response_model=RecipeListOut)
def list_recipes(
    q: str | None = Query(default=None, max_length=100),
    category_id: int | None = None,
    tag: str | None = Query(default=None, max_length=64),
    mine: bool = False,
    limit: int = Query(default=24, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RecipeListOut:
    conds = [_visible(user)]
    if mine:
        conds.append(Recipe.author_id == user.id)
    if category_id is not None:
        conds.append(Recipe.category_id == category_id)
    if tag:
        conds.append(Recipe.tags.any(Tag.name == tag.strip().lower()))
    if q and q.strip():
        # Каждое слово должно найтись в названии, описании, тегах или ингредиентах:
        # «курица рис» → рецепты, где есть и то, и другое.
        for word in q.split()[:6]:
            pattern = _like(word)
            by_product = exists().where(
                RecipeIngredient.recipe_id == Recipe.id,
                RecipeIngredient.product_id == Product.id,
                func.lower(Product.name).like(pattern, escape="\\"),
            )
            by_tag = exists().where(
                recipe_tags.c.recipe_id == Recipe.id,
                recipe_tags.c.tag_id == Tag.id,
                Tag.name.like(pattern, escape="\\"),
            )
            conds.append(
                or_(
                    func.lower(Recipe.title).like(pattern, escape="\\"),
                    func.lower(Recipe.description).like(pattern, escape="\\"),
                    by_product,
                    by_tag,
                )
            )

    total = db.scalar(select(func.count()).select_from(Recipe).where(*conds)) or 0
    rows = db.scalars(
        select(Recipe).where(*conds).order_by(Recipe.updated_at.desc(), Recipe.id.desc()).limit(limit).offset(offset)
    ).unique()
    return RecipeListOut(items=[RecipeListItem(**_base(r)) for r in rows], total=total)


@router.get("/{recipe_id}", response_model=RecipeOut)
def get_recipe(recipe_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> RecipeOut:
    return _full(_get_visible(db, recipe_id, user), user)


# ---------- сохранение ----------
def _clean(s: str) -> str:
    return " ".join(s.split())


def _apply(db: Session, recipe: Recipe, data: RecipeIn) -> None:
    # Без autoflush: иначе первый же запрос (проверка категории) попытается
    # записать в БД новый рецепт, у которого ещё нет названия.
    with db.no_autoflush:
        _fill(db, recipe, data)


def _fill(db: Session, recipe: Recipe, data: RecipeIn) -> None:
    if data.category_id is not None and not db.get(Category, data.category_id):
        raise HTTPException(422, "Категория не найдена")

    recipe.title = _clean(data.title)
    recipe.description = data.description.strip()
    recipe.category_id = data.category_id
    recipe.servings = data.servings
    recipe.prep_minutes = data.prep_minutes
    recipe.cook_minutes = data.cook_minutes
    recipe.difficulty = data.difficulty
    recipe.is_public = data.is_public
    if data.source_url is not None:
        src = data.source_url.strip()
        recipe.source_url = src if src.startswith(("http://", "https://")) else None
    recipe.updated_at = utcnow()

    imported = claim_import_image(data.image_token)
    if imported:
        delete_image(recipe.image)
        recipe.image = imported

    # Теги: в нижнем регистре, без дублей
    tag_names = list(dict.fromkeys(t for t in (_clean(x).lower().lstrip("#") for x in data.tags) if t))[:30]
    tags: list[Tag] = []
    for name in tag_names:
        name = name[:64]
        tag = db.scalar(select(Tag).where(Tag.name == name))
        if not tag:
            tag = Tag(name=name)
            db.add(tag)
            db.flush()
        tags.append(tag)
    recipe.tags = tags

    # Продукты: ищем без учёта регистра, новые добавляем в справочник
    products: dict[str, Product] = {}

    def product_for(name: str) -> Product:
        key = name.lower()
        if key not in products:
            found = db.scalar(select(Product).where(func.lower(Product.name) == key))
            if not found:
                found = Product(name=name)
                db.add(found)
                db.flush()
            products[key] = found
        return products[key]

    recipe.ingredients = [
        RecipeIngredient(
            product=product_for(_clean(i.product)),
            position=pos,
            amount=i.amount,
            unit=_clean(i.unit),
            note=i.note.strip(),
            group_name=_clean(i.group),
        )
        for pos, i in enumerate(data.ingredients)
        if _clean(i.product)
    ]
    recipe.steps = [
        RecipeStep(position=pos, text=s.text.strip(), timer_minutes=s.timer_minutes)
        for pos, s in enumerate(data.steps)
        if s.text.strip()
    ]


@router.post("", response_model=RecipeOut)
def create_recipe(data: RecipeIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> RecipeOut:
    recipe = Recipe(author_id=user.id)
    db.add(recipe)
    _apply(db, recipe, data)
    db.commit()
    db.refresh(recipe)
    return _full(recipe, user)


@router.put("/{recipe_id}", response_model=RecipeOut)
def update_recipe(
    recipe_id: int, data: RecipeIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> RecipeOut:
    recipe = _get_editable(db, recipe_id, user)
    _apply(db, recipe, data)
    db.commit()
    db.refresh(recipe)
    return _full(recipe, user)


@router.delete("/{recipe_id}")
def delete_recipe(recipe_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    recipe = _get_editable(db, recipe_id, user)
    image = recipe.image
    db.delete(recipe)
    db.commit()
    delete_image(image)
    return {"ok": True}


# ---------- фото ----------
@router.post("/{recipe_id}/image", response_model=RecipeOut)
async def upload_image(
    recipe_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RecipeOut:
    recipe = _get_editable(db, recipe_id, user)
    name = await save_image(file)
    old = recipe.image
    recipe.image = name
    recipe.updated_at = utcnow()
    db.commit()
    delete_image(old)
    db.refresh(recipe)
    return _full(recipe, user)


@router.delete("/{recipe_id}/image", response_model=RecipeOut)
def remove_image(recipe_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> RecipeOut:
    recipe = _get_editable(db, recipe_id, user)
    old = recipe.image
    recipe.image = None
    db.commit()
    delete_image(old)
    db.refresh(recipe)
    return _full(recipe, user)


# ---------- импорт по ссылке ----------
@router.post("/import", response_model=RecipeDraft)
def import_recipe(data: ImportIn, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> RecipeDraft:
    """Разбирает страницу и возвращает черновик для редактора. Ничего не сохраняет, кроме временного фото."""
    try:
        r = importer.import_from_url(data.url)
    except importer.ImportError_ as e:
        raise HTTPException(422, str(e))

    image_token = None
    if r.image_url:
        try:
            raw, _ctype, _ = importer.fetch(r.image_url, importer.MAX_IMAGE_BYTES, accept="image/*")
            image_token = save_image_bytes(raw, prefix=IMPORT_PREFIX)
        except (importer.ImportError_, HTTPException):
            image_token = None  # без фото — не страшно

    category = None
    if r.category:
        category = db.scalar(select(Category).where(func.lower(Category.name) == r.category.lower()))

    return RecipeDraft(
        title=r.title[:200],
        description=r.description[:5000],
        servings=r.servings,
        prep_minutes=r.prep_minutes,
        cook_minutes=r.cook_minutes,
        category_id=category.id if category else None,
        category_name="" if category else r.category[:100],
        tags=r.tags,
        ingredients=[
            IngredientIn(
                product=i.product[:128] or "?",
                amount=i.amount if i.amount is None or i.amount <= 1_000_000 else None,
                unit=i.unit[:32],
                note=i.note[:200],
                group=i.group[:100],
            )
            for i in r.ingredients
            if i.product
        ][:200],
        steps=[StepIn(text=s[:10_000]) for s in r.steps if s][:200],
        image_token=image_token,
        image_url=image_url(image_token),
        source_url=r.source_url[:500],
    )
