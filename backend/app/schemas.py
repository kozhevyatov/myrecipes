from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

USERNAME_PATTERN = r"^[a-zA-Z0-9_.-]{3,64}$"
# Простая проверка: домашние адреса вида admin@home.local тоже допустимы.
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+$"


# ---------- setup ----------
class SetupStatus(BaseModel):
    database_configured: bool
    database_from_env: bool
    setup_complete: bool
    setup_token_required: bool


class DatabaseConfig(BaseModel):
    type: Literal["sqlite", "mysql"]
    host: str | None = None
    port: int | None = 3306
    user: str | None = None
    password: str | None = None
    database: str | None = None


class AdminCreate(BaseModel):
    username: str = Field(pattern=USERNAME_PATTERN)
    email: str = Field(pattern=EMAIL_PATTERN, max_length=255)
    display_name: str = Field(default="", max_length=128)
    password: str = Field(min_length=8, max_length=128)
    site_name: str = Field(default="Мои рецепты", max_length=100)
    registration_mode: Literal["open", "closed"] = "closed"


# ---------- auth ----------
class LoginIn(BaseModel):
    login: str  # username или email
    password: str
    remember: bool = True  # «Запомнить меня»


class RegisterIn(BaseModel):
    username: str = Field(pattern=USERNAME_PATTERN)
    email: str = Field(pattern=EMAIL_PATTERN, max_length=255)
    display_name: str = Field(default="", max_length=128)
    password: str = Field(min_length=8, max_length=128)


class RefreshIn(BaseModel):
    refresh_token: str | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    display_name: str
    is_admin: bool
    is_active: bool
    created_at: datetime
    avatar_url: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _avatar(cls, v):  # noqa: ANN001
        # ORM-объект: превращаем имя файла в URL
        if hasattr(v, "avatar") and not isinstance(v, dict):
            return {
                **{k: getattr(v, k) for k in ("id", "username", "email", "display_name", "is_admin", "is_active", "created_at")},
                "avatar_url": f"/api/uploads/{v.avatar}" if v.avatar else None,
            }
        return v


class ProfileUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=128)
    email: str | None = Field(default=None, pattern=EMAIL_PATTERN, max_length=255)


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    # Для мобильного приложения; в вебе refresh живёт в httpOnly-cookie.
    refresh_token: str
    token_type: str = "bearer"
    user: UserOut


# ---------- settings ----------
class PublicSettings(BaseModel):
    site_name: str
    registration_mode: Literal["open", "closed"]


class SettingsUpdate(BaseModel):
    site_name: str | None = Field(default=None, max_length=100)
    registration_mode: Literal["open", "closed"] | None = None


class UserAdminCreate(BaseModel):
    username: str = Field(pattern=USERNAME_PATTERN)
    email: str = Field(pattern=EMAIL_PATTERN, max_length=255)
    display_name: str = Field(default="", max_length=128)
    password: str = Field(min_length=8, max_length=128)
    is_admin: bool = False


class PasswordReset(BaseModel):
    password: str = Field(min_length=8, max_length=128)


class UserAdminUpdate(BaseModel):
    is_admin: bool | None = None
    is_active: bool | None = None
    username: str | None = Field(default=None, pattern=USERNAME_PATTERN)
    display_name: str | None = Field(default=None, max_length=128)
    email: str | None = Field(default=None, pattern=EMAIL_PATTERN, max_length=255)


# ---------- справочники ----------
class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    sort_order: int = 0
    recipe_count: int = 0


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    sort_order: int = 0


class PriceOut(BaseModel):
    id: int
    price: float
    package_amount: float
    package_unit: str
    created_at: datetime
    # Цена за кг / л / шт — для сравнения упаковок
    unit_price: float | None = None
    unit_label: str | None = None
    author: str | None = None
    can_delete: bool = False


class ProductOut(BaseModel):
    id: int
    name: str
    kcal: float | None
    protein: float | None
    fat: float | None
    carbs: float | None
    piece_grams: float | None
    density: float | None
    nutrition_source: str | None
    recipe_count: int = 0
    # Последняя цена
    price: PriceOut | None = None


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    kcal: float | None = Field(default=None, ge=0, le=1000)
    protein: float | None = Field(default=None, ge=0, le=100)
    fat: float | None = Field(default=None, ge=0, le=100)
    carbs: float | None = Field(default=None, ge=0, le=100)
    piece_grams: float | None = Field(default=None, gt=0, le=100_000)
    density: float | None = Field(default=None, gt=0, le=20)


class ProductMerge(BaseModel):
    into_id: int


class PriceIn(BaseModel):
    price: float = Field(gt=0, le=1_000_000)
    package_amount: float = Field(gt=0, le=1_000_000)
    package_unit: Literal["г", "кг", "мл", "л", "шт"]


class DuplicateProduct(BaseModel):
    id: int
    name: str
    recipe_count: int
    has_price: bool
    # Совпадает по строгому ключу с первым в группе — почти наверняка дубль
    exact: bool


class DuplicateGroup(BaseModel):
    products: list[DuplicateProduct]


class CostLineOut(BaseModel):
    product_id: int
    name: str
    cost: float


class CostOut(BaseModel):
    total: float
    per_serving: float
    counted: int
    total_count: int
    lines: list[CostLineOut]
    missing: list[str]
    stale: list[str]


class CostPoint(BaseModel):
    taken_at: datetime
    total: float
    per_serving: float
    priced_count: int
    total_count: int


class CostDriver(BaseModel):
    name: str
    before: float
    after: float


class CostHistoryOut(BaseModel):
    points: list[CostPoint]
    # Рост «яблоки к яблокам»: только по продуктам, у которых цена была в обеих точках
    change_pct: float | None = None
    since: datetime | None = None
    drivers: list[CostDriver] = []


class NutritionValues(BaseModel):
    kcal: float
    protein: float
    fat: float
    carbs: float


class NutritionOut(BaseModel):
    per_serving: NutritionValues
    total: NutritionValues
    weight_g: float
    counted: int
    missing: list[str]


class TagOut(BaseModel):
    name: str
    recipe_count: int = 0


# ---------- рецепты ----------
class IngredientIn(BaseModel):
    product: str = Field(min_length=1, max_length=128)
    amount: float | None = Field(default=None, ge=0, le=1_000_000)
    unit: str = Field(default="", max_length=32)
    note: str = Field(default="", max_length=200)
    group: str = Field(default="", max_length=100)


class StepIn(BaseModel):
    text: str = Field(min_length=1, max_length=10_000)
    timer_minutes: int | None = Field(default=None, ge=1, le=10_000)
    # Фото шага: имя уже сохранённого файла этого рецепта или временный токен загрузки (imp-….webp)
    image: str | None = Field(default=None, max_length=64)


class RecipeIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    category_id: int | None = None
    servings: int = Field(default=2, ge=1, le=100)
    prep_minutes: int | None = Field(default=None, ge=0, le=10_000)
    cook_minutes: int | None = Field(default=None, ge=0, le=10_000)
    difficulty: int | None = Field(default=None, ge=1, le=3)
    is_public: bool = True
    source_url: str | None = Field(default=None, max_length=500)
    # Временное фото из импорта по ссылке (imp-….webp)
    image_token: str | None = Field(default=None, max_length=64)
    tags: list[str] = Field(default_factory=list, max_length=30)
    ingredients: list[IngredientIn] = Field(default_factory=list, max_length=200)
    steps: list[StepIn] = Field(default_factory=list, max_length=200)
    # Галерея: имена файлов/токены по порядку. None — не менять
    photos: list[str] | None = Field(default=None, max_length=30)


class ImportIn(BaseModel):
    url: str = Field(min_length=8, max_length=2000)


class ImportTextIn(BaseModel):
    text: str = Field(min_length=3, max_length=50_000)


class UploadedPhoto(BaseModel):
    token: str
    url: str
    thumb_url: str | None


class RecipeDraft(BaseModel):
    """Черновик из импорта — заполняет форму редактора, ещё не сохранён."""

    title: str
    description: str
    servings: int | None
    prep_minutes: int | None
    cook_minutes: int | None
    category_id: int | None
    category_name: str
    tags: list[str]
    ingredients: list[IngredientIn]
    steps: list[StepIn]
    image_token: str | None
    image_url: str | None
    source_url: str
    # Распознанный текст (для импорта со скриншота) — можно сверить
    text: str = ""


class IngredientOut(BaseModel):
    id: int
    product: str
    amount: float | None
    unit: str
    note: str
    group: str
    in_pantry: bool = False  # продукт есть в кладовке у текущего пользователя


class StepOut(BaseModel):
    id: int
    position: int
    text: str
    timer_minutes: int | None
    image: str | None = None  # имя файла — отправляется обратно при сохранении
    image_url: str | None = None
    thumb_url: str | None = None


class PhotoOut(BaseModel):
    image: str
    url: str
    thumb_url: str | None


class AuthorOut(BaseModel):
    id: int
    name: str
    avatar_url: str | None = None


class CategoryRef(BaseModel):
    id: int
    name: str


class CookLogOut(BaseModel):
    id: int
    cooked_on: date
    note: str
    author: AuthorOut
    can_delete: bool


class CookLogIn(BaseModel):
    cooked_on: date | None = None
    note: str = Field(default="", max_length=2000)


class RecipeListItem(BaseModel):
    id: int
    title: str
    description: str
    image_url: str | None
    thumb_url: str | None = None  # уменьшенное фото для карточек
    category: CategoryRef | None
    tags: list[str]
    servings: int
    total_minutes: int | None
    difficulty: int | None
    is_public: bool
    author: AuthorOut
    updated_at: datetime
    is_favorite: bool = False
    cooked_count: int = 0


class RecipeOut(RecipeListItem):
    source_url: str | None
    nutrition: NutritionOut | None
    cost: CostOut | None = None
    prep_minutes: int | None
    cook_minutes: int | None
    ingredients: list[IngredientOut]
    steps: list[StepOut]
    can_edit: bool
    created_at: datetime
    cook_log: list[CookLogOut] = []
    photos: list[PhotoOut] = []
    # Публичная ссылка: только автору/админу
    share_url: str | None = None


class SharedRecipeOut(BaseModel):
    """Рецепт по публичной ссылке — без личных данных."""

    title: str
    description: str
    image_url: str | None
    category: str | None
    tags: list[str]
    servings: int
    prep_minutes: int | None
    cook_minutes: int | None
    total_minutes: int | None
    difficulty: int | None
    author: str
    source_url: str | None
    nutrition: NutritionOut | None
    ingredients: list[IngredientOut]
    steps: list[StepOut]
    photos: list[PhotoOut]
    site_name: str


class ShareOut(BaseModel):
    share_url: str | None


class RecipeMatch(BaseModel):
    recipe: RecipeListItem
    have: int
    need: int
    missing: list[str]


class RecipeMatchOut(BaseModel):
    items: list[RecipeMatch]


class RecipeListOut(BaseModel):
    items: list[RecipeListItem]
    total: int


# ---------- списки покупок ----------
class ShoppingItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    amount: float | None
    unit: str
    note: str
    checked: bool
    product_id: int | None = None
    # Последняя цена продукта и примерная стоимость пункта по ней
    price: PriceOut | None = None
    est_cost: float | None = None


class ShoppingListOut(BaseModel):
    id: int
    name: str
    owner: AuthorOut
    members: list[AuthorOut]
    is_owner: bool
    todo: int
    total: int
    recipe_id: int | None = None


class ShoppingListIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ShoppingMembersIn(BaseModel):
    user_ids: list[int] = Field(default_factory=list, max_length=200)


class ShoppingAddText(BaseModel):
    text: str = Field(min_length=1, max_length=200)


class ShoppingFromRecipe(BaseModel):
    recipe_id: int
    servings: int | None = Field(default=None, ge=1, le=100)
    # Если указано — добавить только эти ингредиенты
    ingredient_ids: list[int] | None = None


class ShoppingRecipeList(BaseModel):
    """Отдельный список для рецепта: создаётся при первом добавлении, потом обновляется."""

    recipe_id: int
    servings: int | None = Field(default=None, ge=1, le=100)
    ingredient_ids: list[int] | None = None


class ShoppingRecipeListOut(BaseModel):
    shopping_list: ShoppingListOut
    created: bool
    items: list[ShoppingItemOut]


class ShoppingFromProducts(BaseModel):
    """Недостающие продукты из подбора «что приготовить»."""

    names: list[str] = Field(min_length=1, max_length=100)
    note: str = Field(default="", max_length=200)


class ShoppingItemUpdate(BaseModel):
    checked: bool | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    amount: float | None = Field(default=None, ge=0, le=1_000_000)
    unit: str | None = Field(default=None, max_length=32)


class ShoppingAdded(BaseModel):
    added: int
    merged: int
    items: list[ShoppingItemOut]


# ---------- меню на неделю ----------
SLOTS = ("breakfast", "lunch", "dinner", "snack")


class PlanRecipe(BaseModel):
    id: int
    title: str
    thumb_url: str | None
    servings: int
    total_minutes: int | None
    kcal_per_serving: int | None
    protein_per_serving: float | None
    fat_per_serving: float | None
    carbs_per_serving: float | None


class PlanEntryOut(BaseModel):
    id: int
    day: date
    slot: str
    position: int
    servings: int
    note: str
    recipe: PlanRecipe | None


class PlanEntryIn(BaseModel):
    day: date
    slot: str = Field(default="dinner", pattern="^(breakfast|lunch|dinner|snack)$")
    recipe_id: int | None = None
    servings: int | None = Field(default=None, ge=1, le=100)
    note: str = Field(default="", max_length=200)
    owner_id: int | None = None  # чьё меню; по умолчанию своё


class PlanEntryUpdate(BaseModel):
    day: date | None = None
    slot: str | None = Field(default=None, pattern="^(breakfast|lunch|dinner|snack)$")
    servings: int | None = Field(default=None, ge=1, le=100)
    note: str | None = Field(default=None, max_length=200)
    position: int | None = Field(default=None, ge=0, le=1000)


class PlanOut(BaseModel):
    owner: AuthorOut
    is_owner: bool
    members: list[AuthorOut]
    entries: list[PlanEntryOut]


class PlanOwnersOut(BaseModel):
    """Чьи меню доступны: своё и те, которыми поделились."""

    owners: list[AuthorOut]


class PlanToShopping(BaseModel):
    list_id: int
    start: date
    end: date
    owner_id: int | None = None
    skip_pantry: bool = True
    entry_ids: list[int] | None = None


class PlanMembersIn(BaseModel):
    user_ids: list[int] = Field(default_factory=list, max_length=200)


# ---------- кладовка ----------
class PantryItemOut(BaseModel):
    product_id: int
    name: str


class PantryAdd(BaseModel):
    name: str = Field(min_length=1, max_length=128)
