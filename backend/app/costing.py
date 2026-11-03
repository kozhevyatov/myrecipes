"""Себестоимость рецепта и её история.

Всё сводится к граммам через nutrition.grams() — те же правила, что и для КБЖУ:
  цена упаковки / вес упаковки в граммах = цена за грамм;
  граммы ингредиента × цена за грамм     = стоимость.
Для штучного без веса штуки (имбирь 1 шт, цена за 1 шт) считаем по штукам.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ProductPrice, Recipe, RecipeCostSnapshot, RecipeIngredient
from .nutrition import NEGLIGIBLE, PIECE, grams

PRICE_UNITS = ("г", "кг", "мл", "л", "шт")
STALE_DAYS = 120          # цена старше — предупреждаем «обновите»
MONTHLY_DAYS = 28         # страховочный снимок, даже если ничего не менялось

log = logging.getLogger("uvicorn.error")


def naive_utc(dt: datetime) -> datetime:
    """MariaDB возвращает время без зоны, SQLite — как записали. Приводим к одному виду."""
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def unit_price(price: ProductPrice, product) -> tuple[float, str] | None:  # noqa: ANN001
    """Цена за кг / л / шт — для сравнения упаковок разного размера."""
    u = price.package_unit
    if u in ("мл", "л"):
        ml = price.package_amount * (1000 if u == "л" else 1)
        return (price.price / ml * 1000, "л") if ml else None
    if u == "шт" and not product.piece_grams:
        return (price.price / price.package_amount, "шт") if price.package_amount else None
    g = grams(price.package_amount, u, product)
    return (price.price / g * 1000, "кг") if g else None


def latest_prices(db: Session, product_ids, as_of: datetime | None = None) -> dict[int, ProductPrice]:  # noqa: ANN001
    """Последняя цена каждого продукта (на дату as_of, если задана)."""
    ids = list(set(product_ids))
    if not ids:
        return {}
    q = select(ProductPrice).where(ProductPrice.product_id.in_(ids))
    if as_of is not None:
        q = q.where(ProductPrice.created_at <= as_of)
    result: dict[int, ProductPrice] = {}
    for p in db.scalars(q.order_by(ProductPrice.created_at, ProductPrice.id)):
        result[p.product_id] = p
    return result


def ingredient_cost(amount: float | None, unit: str, product, price: ProductPrice) -> float | None:  # noqa: ANN001
    unit = (unit or "").strip()
    if unit in NEGLIGIBLE:
        return 0.0
    if amount is None or not price.package_amount:
        return None
    need = grams(amount, unit, product)
    pack = grams(price.package_amount, price.package_unit, product)
    if need is not None and pack:
        return need * price.price / pack
    if (unit in PIECE or unit == "") and price.package_unit == "шт":
        return amount * price.price / price.package_amount
    return None


@dataclass
class CostLine:
    product_id: int
    name: str
    cost: float


@dataclass
class Cost:
    total: float = 0.0
    counted: int = 0            # сколько ингредиентов посчитано
    total_count: int = 0        # сколько всего (без «по вкусу»)
    lines: list[CostLine] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)   # нет цены или не перевести единицы
    stale: list[str] = field(default_factory=list)     # цена давно не обновлялась


def recipe_cost(db: Session, recipe: Recipe, as_of: datetime | None = None) -> Cost:
    ings: list[RecipeIngredient] = recipe.ingredients
    prices = latest_prices(db, [i.product_id for i in ings], as_of)
    cost = Cost()
    by_product: dict[int, CostLine] = {}
    stale_before = (as_of or now_utc()) - timedelta(days=STALE_DAYS)
    for ing in ings:
        unit = (ing.unit or "").strip()
        if unit in NEGLIGIBLE:
            continue
        cost.total_count += 1
        p = ing.product
        price = prices.get(p.id)
        value = ingredient_cost(ing.amount, unit, p, price) if price else None
        if value is None:
            cost.missing.append(p.name)
            continue
        cost.counted += 1
        cost.total += value
        line = by_product.setdefault(p.id, CostLine(p.id, p.name, 0.0))
        line.cost += value
        if naive_utc(price.created_at) < stale_before:
            cost.stale.append(p.name)
    cost.lines = sorted(by_product.values(), key=lambda line: -line.cost)
    cost.missing = list(dict.fromkeys(cost.missing))
    cost.stale = list(dict.fromkeys(cost.stale))
    return cost


# ---------------- снимки ----------------
def take_snapshot(db: Session, recipe: Recipe, monthly: bool = False) -> bool:
    """Записывает снимок, если себестоимость изменилась.
    monthly=True — ещё и если последний снимок старше месяца (ровные точки на графике)."""
    cost = recipe_cost(db, recipe)
    if cost.counted == 0:
        return False
    total = round(cost.total, 2)
    last = db.scalar(
        select(RecipeCostSnapshot)
        .where(RecipeCostSnapshot.recipe_id == recipe.id)
        .order_by(RecipeCostSnapshot.taken_at.desc(), RecipeCostSnapshot.id.desc())
        .limit(1)
    )
    if last is not None:
        same = (
            abs(last.total - total) < 0.01
            and last.priced_count == cost.counted
            and last.total_count == cost.total_count
        )
        old = now_utc() - naive_utc(last.taken_at) >= timedelta(days=MONTHLY_DAYS)
        if same and not (monthly and old):
            return False
    db.add(
        RecipeCostSnapshot(
            recipe_id=recipe.id,
            taken_at=now_utc(),
            total=total,
            per_serving=round(total / max(recipe.servings, 1), 2),
            priced_count=cost.counted,
            total_count=cost.total_count,
            lines_json=json.dumps({str(line.product_id): round(line.cost, 2) for line in cost.lines}),
        )
    )
    return True


def snapshot_recipes_with_product(db: Session, product_id: int) -> None:
    """После новой цены — снимки всех рецептов, где есть этот продукт."""
    ids = set(db.scalars(select(RecipeIngredient.recipe_id).where(RecipeIngredient.product_id == product_id)))
    for rid in ids:
        recipe = db.get(Recipe, rid)
        if recipe:
            take_snapshot(db, recipe)


def snapshot_all(db: Session) -> int:
    """Плановый обход всех рецептов (раз в несколько часов, из фоновой задачи)."""
    n = 0
    for recipe in db.scalars(select(Recipe)):
        n += take_snapshot(db, recipe, monthly=True)
    db.commit()
    return n
