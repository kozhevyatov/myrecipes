from __future__ import annotations

import random
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import exists, func, or_, select, true
from sqlalchemy.orm import Session, noload

from ..db import get_db
from .. import importer, textimport
from ..nutrition import fill_from_seed, recipe_nutrition
from ..images import (
    IMPORT_PREFIX,
    MAX_UPLOAD_BYTES,
    claim_import_image,
    delete_image,
    image_url,
    resolve_photo,
    save_image,
    save_image_bytes,
    thumb_url,
)
from ..models import (
    Category,
    CookLog,
    Favorite,
    PantryItem,
    Product,
    Recipe,
    RecipeIngredient,
    RecipePhoto,
    RecipeStep,
    ShoppingList,
    Tag,
    User,
    recipe_tags,
    utcnow,
)
from ..schemas import (
    AuthorOut,
    CategoryRef,
    CookLogIn,
    CookLogOut,
    ImportIn,
    ImportTextIn,
    IngredientIn,
    IngredientOut,
    NutritionOut,
    NutritionValues,
    PhotoOut,
    RecipeDraft,
    RecipeMatch,
    RecipeMatchOut,
    ShareOut,
    UploadedPhoto,
    StepIn,
    RecipeIn,
    RecipeListItem,
    RecipeListOut,
    RecipeOut,
    StepOut,
)
from ..security import get_current_user

router = APIRouter(prefix="/api/recipes", tags=["recipes"])

MAX_SCREENSHOTS = 10


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


def _base(r: Recipe, is_favorite: bool = False, cooked_count: int = 0) -> dict:
    return dict(
        id=r.id,
        title=r.title,
        description=r.description,
        image_url=image_url(r.image),
        thumb_url=thumb_url(r.image),
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
        is_favorite=is_favorite,
        cooked_count=cooked_count,
    )


def _nutrition(r: Recipe) -> NutritionOut | None:
    if not r.ingredients:
        return None
    n = recipe_nutrition(r.ingredients)
    if n.counted == 0:
        return NutritionOut(
            per_serving=NutritionValues(kcal=0, protein=0, fat=0, carbs=0),
            total=NutritionValues(kcal=0, protein=0, fat=0, carbs=0),
            weight_g=0,
            counted=0,
            missing=n.missing,
        )
    s = max(r.servings, 1)

    def vals(div: float) -> NutritionValues:
        return NutritionValues(
            kcal=round(n.kcal / div), protein=round(n.protein / div, 1), fat=round(n.fat / div, 1), carbs=round(n.carbs / div, 1)
        )

    return NutritionOut(per_serving=vals(s), total=vals(1), weight_g=round(n.weight), counted=n.counted, missing=n.missing)


def _author(u: User) -> AuthorOut:
    return AuthorOut(id=u.id, name=u.display_name or u.username, avatar_url=image_url(u.avatar))


def _photo(name: str) -> PhotoOut:
    return PhotoOut(image=name, url=image_url(name) or "", thumb_url=thumb_url(name))


def _steps_out(r: Recipe) -> list[StepOut]:
    return [
        StepOut(
            id=s.id,
            position=s.position,
            text=s.text,
            timer_minutes=s.timer_minutes,
            image=s.image,
            image_url=image_url(s.image),
            thumb_url=thumb_url(s.image),
        )
        for s in r.steps
    ]


def pantry_ids(db: Session, user: User) -> set[int]:
    return set(db.scalars(select(PantryItem.product_id).where(PantryItem.user_id == user.id)))


def _stem(name: str) -> str:
    """Грубая основа для сравнения: «Яйца» ~ «Яйцо», «ё» = «е»."""
    words = []
    for w in name.lower().replace("ё", "е").split():
        w = w.strip(".,()")
        words.append(w.rstrip("аяыиоеуюйь") if len(w) > 3 else w)
    return " ".join(w for w in words if w)


class Pantry:
    """«Что есть дома»: «Мука» дома покрывает «Мука пшеничная» в рецепте и наоборот."""

    def __init__(self, db: Session, user: User) -> None:
        rows = db.execute(
            select(Product.id, Product.name).join(PantryItem, PantryItem.product_id == Product.id).where(PantryItem.user_id == user.id)
        ).all()
        self.ids = {r[0] for r in rows}
        self.stems = {_stem(r[1]) for r in rows}

    def __bool__(self) -> bool:
        return bool(self.ids)

    def has(self, product: Product) -> bool:
        if product.id in self.ids:
            return True
        n = _stem(product.name)
        return any(n == p or n.startswith(p + " ") or p.startswith(n + " ") for p in self.stems)


def _full(r: Recipe, user: User) -> RecipeOut:
    db = Session.object_session(r)
    fav = bool(db.get(Favorite, (user.id, r.id))) if db else False
    pantry = Pantry(db, user) if db else None
    logs = (
        list(db.scalars(select(CookLog).where(CookLog.recipe_id == r.id).order_by(CookLog.cooked_on.desc(), CookLog.id.desc())))
        if db
        else []
    )
    return RecipeOut(
        **_base(r, fav, len(logs)),
        cook_log=[
            CookLogOut(
                id=c.id,
                cooked_on=c.cooked_on,
                note=c.note,
                author=_author(c.user),
                can_delete=user.is_admin or c.user_id == user.id,
            )
            for c in logs[:50]
        ],
        source_url=r.source_url,
        nutrition=_nutrition(r),
        prep_minutes=r.prep_minutes,
        cook_minutes=r.cook_minutes,
        ingredients=[
            IngredientOut(
                id=i.id,
                product=i.product.name,
                amount=i.amount,
                unit=i.unit,
                note=i.note,
                group=i.group_name,
                in_pantry=bool(pantry and pantry.has(i.product)),
            )
            for i in r.ingredients
        ],
        steps=_steps_out(r),
        photos=[_photo(p.image) for p in r.photos],
        share_url=f"/r/{r.share_token}" if r.share_token and _can_edit(r, user) else None,
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
    favorites: bool = False,
    limit: int = Query(default=24, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RecipeListOut:
    conds = _filters(user, q, category_id, tag, mine, favorites)
    total = db.scalar(select(func.count()).select_from(Recipe).where(*conds)) or 0
    rows = db.scalars(
        select(Recipe)
        .where(*conds)
        # Для карточек нужны только название, фото, теги — ингредиенты и шаги не грузим
        .options(noload(Recipe.ingredients), noload(Recipe.steps), noload(Recipe.photos))
        .order_by(Recipe.updated_at.desc(), Recipe.id.desc())
        .limit(limit)
        .offset(offset)
    ).unique().all()
    return RecipeListOut(items=_list_items(db, list(rows), user), total=total)


def _list_items(db: Session, rows: list[Recipe], user: User) -> list[RecipeListItem]:
    ids = [r.id for r in rows]
    fav_ids = set(db.scalars(select(Favorite.recipe_id).where(Favorite.user_id == user.id, Favorite.recipe_id.in_(ids)))) if ids else set()
    cooked = (
        dict(db.execute(select(CookLog.recipe_id, func.count()).where(CookLog.recipe_id.in_(ids)).group_by(CookLog.recipe_id)).all())
        if ids
        else {}
    )
    return [RecipeListItem(**_base(r, r.id in fav_ids, cooked.get(r.id, 0))) for r in rows]


def _filters(
    user: User,
    q: str | None = None,
    category_id: int | None = None,
    tag: str | None = None,
    mine: bool = False,
    favorites: bool = False,
) -> list:
    conds = [_visible(user)]
    if mine:
        conds.append(Recipe.author_id == user.id)
    if favorites:
        conds.append(exists().where(Favorite.recipe_id == Recipe.id, Favorite.user_id == user.id))
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
    return conds


# ---------- «Что приготовить?» ----------
@router.get("/random", response_model=RecipeListItem)
def random_recipe(
    category_id: int | None = None,
    tag: str | None = Query(default=None, max_length=64),
    favorites: bool = False,
    max_minutes: int | None = Query(default=None, ge=1, le=10_000),
    not_cooked_days: int | None = Query(default=None, ge=1, le=3650),
    exclude: str | None = Query(default=None, max_length=2000, description="id через запятую — уже показанные"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RecipeListItem:
    """Случайный рецепт по фильтрам."""
    conds = _filters(user, None, category_id, tag, False, favorites)
    if max_minutes:
        total = func.coalesce(Recipe.prep_minutes, 0) + func.coalesce(Recipe.cook_minutes, 0)
        conds.append(or_(Recipe.prep_minutes.is_not(None), Recipe.cook_minutes.is_not(None)))
        conds.append(total <= max_minutes)
    if not_cooked_days:
        since = utcnow().date() - timedelta(days=not_cooked_days)
        conds.append(
            ~exists().where(CookLog.recipe_id == Recipe.id, CookLog.user_id == user.id, CookLog.cooked_on >= since)
        )
    ids = list(db.scalars(select(Recipe.id).where(*conds)))
    if not ids:
        raise HTTPException(404, "Под эти условия ничего не нашлось")
    shown = {int(x) for x in (exclude or "").split(",") if x.strip().isdigit()}
    pool = [i for i in ids if i not in shown] or ids  # все уже показаны — идём по второму кругу
    recipe = db.get(Recipe, random.choice(pool))
    return _list_items(db, [recipe], user)[0]


# ---------- подбор по продуктам «Что есть дома» ----------
def _is_staple(name: str) -> bool:
    """Вода есть всегда — не считаем её ни нужной, ни недостающей."""
    n = name.lower().strip()
    return n.startswith("вода") or "кипят" in n or n in ("лёд", "лед")


@router.get("/match", response_model=RecipeMatchOut)
def match_recipes(
    max_missing: int = Query(default=5, ge=0, le=50),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RecipeMatchOut:
    """Рецепты, для которых хватает продуктов из «Что есть дома» — или не хватает немногих."""
    have = Pantry(db, user)
    if not have:
        return RecipeMatchOut(items=[])
    recipes = db.scalars(
        select(Recipe).where(_visible(user)).options(noload(Recipe.steps), noload(Recipe.photos))
    ).unique().all()
    scored: list[tuple[int, int, Recipe, int, list[str]]] = []
    for r in recipes:
        need: dict[int, Product] = {}
        for ing in r.ingredients:
            if not _is_staple(ing.product.name):
                need.setdefault(ing.product_id, ing.product)
        if not need:
            continue
        got = sum(1 for p in need.values() if have.has(p))
        missing = [p.name for p in need.values() if not have.has(p)]
        if got == 0 or len(missing) > max_missing:
            continue
        scored.append((len(missing), -got, r, len(need), missing))
    scored.sort(key=lambda x: (x[0], x[1], x[2].title.lower()))
    scored = scored[:60]
    items = _list_items(db, [x[2] for x in scored], user)
    return RecipeMatchOut(
        items=[RecipeMatch(recipe=item, have=-x[1], need=x[3], missing=x[4]) for item, x in zip(items, scored)]
    )


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
                fill_from_seed(found)  # КБЖУ из встроенного справочника, если продукт известен
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
    # Фото: свои уже сохранённые файлы оставляем, новые загрузки забираем из временных
    own = recipe.image_names() if recipe.id else set()
    recipe.steps = [
        RecipeStep(
            position=pos,
            text=s.text.strip(),
            timer_minutes=s.timer_minutes,
            image=resolve_photo(s.image, own),
        )
        for pos, s in enumerate(data.steps)
        if s.text.strip()
    ]
    if data.photos is not None:
        names = [n for n in (resolve_photo(x, own) for x in dict.fromkeys(data.photos)) if n]
        recipe.photos = [RecipePhoto(position=pos, image=n) for pos, n in enumerate(names)]


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
    before = recipe.image_names()
    _apply(db, recipe, data)
    db.commit()
    db.refresh(recipe)
    # Фото, которые убрали из рецепта, — удаляем с диска
    for name in before - recipe.image_names():
        delete_image(name)
    return _full(recipe, user)


@router.delete("/{recipe_id}")
def delete_recipe(recipe_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    recipe = _get_editable(db, recipe_id, user)
    images = recipe.image_names()
    # Списки покупок рецепта остаются, просто больше не привязаны к нему
    for lst in db.scalars(select(ShoppingList).where(ShoppingList.recipe_id == recipe.id)):
        lst.recipe_id = None
    db.delete(recipe)
    db.commit()
    for name in images:
        delete_image(name)
    return {"ok": True}


# ---------- публичная ссылка ----------
@router.post("/{recipe_id}/share", response_model=ShareOut)
def enable_share(recipe_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> ShareOut:
    recipe = _get_editable(db, recipe_id, user)
    if not recipe.share_token:
        recipe.share_token = secrets.token_urlsafe(16)[:22]
        db.commit()
    return ShareOut(share_url=f"/r/{recipe.share_token}")


@router.delete("/{recipe_id}/share", response_model=ShareOut)
def disable_share(recipe_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> ShareOut:
    """Выключить ссылку. Если включить снова — будет новая, старая перестанет работать."""
    recipe = _get_editable(db, recipe_id, user)
    recipe.share_token = None
    db.commit()
    return ShareOut(share_url=None)


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
    if old and old not in recipe.image_names():
        delete_image(old)
    db.refresh(recipe)
    return _full(recipe, user)


@router.delete("/{recipe_id}/image", response_model=RecipeOut)
def remove_image(recipe_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> RecipeOut:
    recipe = _get_editable(db, recipe_id, user)
    old = recipe.image
    recipe.image = None
    db.commit()
    if old and old not in recipe.image_names():
        delete_image(old)
    db.refresh(recipe)
    return _full(recipe, user)


@router.post("/photos", response_model=UploadedPhoto)
async def upload_photo(file: UploadFile = File(...), _: User = Depends(get_current_user)) -> UploadedPhoto:
    """Фото для галереи или шага. Временное: станет постоянным, когда рецепт сохранят."""
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Файл больше 15 МБ")
    token = save_image_bytes(data, prefix=IMPORT_PREFIX)
    return UploadedPhoto(token=token, url=image_url(token) or "", thumb_url=thumb_url(token))


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

    return _draft(db, r, image_token)


def _draft(db: Session, r: importer.ImportedRecipe, image_token: str | None = None, text: str = "") -> RecipeDraft:
    category = None
    if r.category:
        category = db.scalar(select(Category).where(func.lower(Category.name) == r.category.lower()))

    return RecipeDraft(
        text=text,
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


@router.post("/import-text", response_model=RecipeDraft)
def import_text(data: ImportTextIn, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> RecipeDraft:
    """Рецепт, вставленный текстом (из Telegram, заметок, сообщения)."""
    r = textimport.parse_text(data.text)
    if not r.ingredients and not r.steps:
        raise HTTPException(422, "Не получилось найти в тексте ингредиенты и шаги")
    return _draft(db, r)


@router.post("/import-image", response_model=RecipeDraft)
async def import_image(
    files: list[UploadFile] = File(...), db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> RecipeDraft:
    """Скриншоты или фото рецепта (до 10, по порядку): распознаём текст каждого, склеиваем
    и разбираем как обычный текст. Повтор на стыке соседних скриншотов убирается."""
    if len(files) > MAX_SCREENSHOTS:
        raise HTTPException(413, f"Не больше {MAX_SCREENSHOTS} картинок за раз")
    texts: list[str] = []
    for i, file in enumerate(files, 1):
        raw = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(raw) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"Картинка {i} больше 15 МБ")
        try:
            texts.append(await run_in_threadpool(textimport.ocr, raw))
        except textimport.OcrError as e:
            raise HTTPException(422, f"Картинка {i}: {e}" if len(files) > 1 else str(e))
    text = textimport.join_pages(texts)
    if len(text.strip()) < 10:
        raise HTTPException(422, "На картинках не нашлось текста" if len(files) > 1 else "На картинке не нашлось текста")
    r = textimport.parse_text(text)
    return _draft(db, r, text=text)


# ---------- избранное и «готовил(а)» ----------
@router.put("/{recipe_id}/favorite")
def add_favorite(recipe_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    _get_visible(db, recipe_id, user)
    if not db.get(Favorite, (user.id, recipe_id)):
        db.add(Favorite(user_id=user.id, recipe_id=recipe_id))
        db.commit()
    return {"is_favorite": True}


@router.delete("/{recipe_id}/favorite")
def remove_favorite(recipe_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    fav = db.get(Favorite, (user.id, recipe_id))
    if fav:
        db.delete(fav)
        db.commit()
    return {"is_favorite": False}


@router.post("/{recipe_id}/cooked", response_model=RecipeOut)
def mark_cooked(
    recipe_id: int, data: CookLogIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> RecipeOut:
    recipe = _get_visible(db, recipe_id, user)
    db.add(
        CookLog(
            user_id=user.id,
            recipe_id=recipe.id,
            cooked_on=data.cooked_on or utcnow().date(),
            note=data.note.strip(),
        )
    )
    db.commit()
    return _full(recipe, user)


@router.delete("/{recipe_id}/cooked/{log_id}", response_model=RecipeOut)
def delete_cooked(
    recipe_id: int, log_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> RecipeOut:
    recipe = _get_visible(db, recipe_id, user)
    log = db.get(CookLog, log_id)
    if not log or log.recipe_id != recipe.id:
        raise HTTPException(404, "Запись не найдена")
    if not (user.is_admin or log.user_id == user.id):
        raise HTTPException(403, "Удалить можно только свою запись")
    db.delete(log)
    db.commit()
    return _full(recipe, user)
