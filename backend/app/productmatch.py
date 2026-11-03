"""Сопоставление названий продуктов — защита справочника от дублей.

Все способы добавить рецепт (вручную, по ссылке, текстом, со скриншота) проходят через
find_product(). Порядок поиска:
  1. точное название (без учёта регистра);
  2. синоним — старое имя продукта, которое когда-то объединили с другим;
  3. «ключ» — название без мусора: количеств, состояний, порядка слов, окончаний.
     «Сливочное масло», «Масло сливочное», «Размягчённое сливочное масло» → один ключ.

Жирность и проценты в ключе остаются: «Сливки 33%» и «Сливки 22%» — разные продукты.
Для поиска возможных дублей есть loose_key() — он отбрасывает и числа; его результат
только подсказка, автоматически по нему ничего не склеивается.
"""
from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Product, ProductAlias

UNITS = r"(?:г|гр|грамм\w*|кг|мл|л|шт|штук\w*|ст\.?\s*л|ч\.?\s*л)\.?"

# Состояние продукта — на сам продукт не влияет
STATE_WORDS = {
    "размягченное", "размягченного", "мягкое", "мягкого", "холодное", "холодного", "охлажденное",
    "охлажденного", "растопленное", "растопленного", "теплое", "теплого", "теплая", "теплой",
    "свежий", "свежая", "свежее", "свежие", "любой", "любая", "любое", "любые", "любого", "любых",
    "крупные", "крупный", "мелкие", "мелкий", "очищенный", "очищенные", "комнатной", "температуры",
}

_VOWEL_END = re.compile(r"[аяоеиыуюйь]+$")


def clean_name(name: str) -> str:
    """Название для показа: без количеств в скобках и «- 100 г». Регистр и слова сохраняются."""
    s = " ".join((name or "").split())
    s = re.sub(r"\([^)]*\)", " ", s)                                   # «Яйца (5 шт C1)»
    s = re.sub(rf"\s*[-–—]\s*\d+[.,]?\d*\s*{UNITS}?\s*$", "", s, flags=re.I)  # «Яйцо - 100 г», «-160 гр»
    s = re.sub(rf"\s+\d+[.,]?\d*\s*{UNITS}\s*$", "", s, flags=re.I)    # «Шоколад 160 г»
    s = " ".join(s.split()).strip(" -–—,.:")
    return s[:1].upper() + s[1:] if s else (name or "").strip()


def _words(name: str) -> list[str]:
    s = clean_name(name).lower().replace("ё", "е")
    s = re.sub(r"\bдля\b.*$", "", s)                 # «Белок для смазывания», «Вода для замачивания»
    s = re.sub(r"(\d)\s*[,.]\s*(\d)", r"\1.\2", s)     # 3,2% → 3.2
    s = re.sub(r"[%«»\"“”'`’()\[\],;:!?/]", " ", s)
    s = s.replace("-", " ").replace("–", " ")
    return [w for w in s.split() if w and w not in STATE_WORDS]


def _stem(word: str) -> str:
    if word[0].isdigit() or len(word) < 4:
        return word
    return _VOWEL_END.sub("", word) or word


def match_key(name: str) -> str:
    """Строгий ключ: по нему продукт находится автоматически."""
    return " ".join(sorted(_stem(w) for w in _words(name)))[:128]


def loose_key(name: str) -> str:
    """Мягкий ключ без чисел — только для подсказки «похоже на дубль»."""
    return " ".join(sorted(_stem(w) for w in _words(name) if not w[0].isdigit()))[:128]


class ProductMatcher:
    """Поиск продукта по названию. Один экземпляр на запрос: справочник читается один раз."""

    def __init__(self, db: Session):
        self.db = db
        self._by_key: dict[str, Product] | None = None
        self._alias_keys: dict[str, int] | None = None

    def _load(self) -> None:
        if self._by_key is not None:
            return
        self._by_key = {}
        for p in self.db.scalars(select(Product).order_by(Product.id)):
            self._by_key.setdefault(match_key(p.name), p)
        self._alias_keys = {}
        for a in self.db.scalars(select(ProductAlias).order_by(ProductAlias.id)):
            self._alias_keys.setdefault(a.match_key, a.product_id)

    def find(self, name: str) -> Product | None:
        name = " ".join((name or "").split())
        if not name:
            return None
        low = name.lower()
        found = self.db.scalar(select(Product).where(func.lower(Product.name) == low))
        if found:
            return found
        alias = self.db.scalar(select(ProductAlias).where(ProductAlias.alias == low))
        if alias:
            return self.db.get(Product, alias.product_id)
        key = match_key(name)
        if not key:
            return None
        self._load()
        if key in self._by_key:
            return self._by_key[key]
        if key in self._alias_keys:
            return self.db.get(Product, self._alias_keys[key])
        return None

    def remember(self, product: Product) -> None:
        """Новый продукт добавлен в справочник — учитываем его в этом же запросе."""
        if self._by_key is not None:
            self._by_key.setdefault(match_key(product.name), product)


def add_alias(db: Session, name: str, product_id: int) -> None:
    """Запоминает старое имя продукта после объединения."""
    low = " ".join(name.split()).lower()[:128]
    existing = db.scalar(select(ProductAlias).where(ProductAlias.alias == low))
    if existing:
        existing.product_id = product_id
    else:
        db.add(ProductAlias(alias=low, match_key=match_key(name), product_id=product_id))
