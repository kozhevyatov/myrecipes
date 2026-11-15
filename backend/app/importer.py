"""Импорт рецепта со страницы сайта по разметке schema.org/Recipe (JSON-LD).

Её используют почти все крупные кулинарные сайты: так их рецепты попадают в поиск.
Только стандартная библиотека — никаких лишних зависимостей.
"""
from __future__ import annotations

import html
import ipaddress
import json
import re
import socket
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

MAX_PAGE_BYTES = 4 * 1024 * 1024
MAX_IMAGE_BYTES = 15 * 1024 * 1024
TIMEOUT = 12
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36 MyRecipes-Import"
)


class ImportError_(Exception):
    """Понятная пользователю ошибка импорта."""


# ---------------- безопасная загрузка ----------------
def _check_host(url: str) -> None:
    """Не даём ходить во внутреннюю сеть (роутер, NAS, другие контейнеры)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ImportError_("Нужна ссылка вида https://…")
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror:
        raise ImportError_("Сайт не найден — проверьте ссылку")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise ImportError_("Ссылки на внутреннюю сеть не поддерживаются")


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        _check_host(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_SafeRedirect)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


_no_redirect_opener = urllib.request.build_opener(_NoRedirect)


def fetch(
    url: str,
    limit: int,
    accept: str = "text/html,application/xhtml+xml,*/*;q=0.8",
    *,
    user_agent: str = USER_AGENT,
    allow_redirects: bool = True,
    ssl_context: ssl.SSLContext | None = None,
) -> tuple[bytes, str, str]:
    """Возвращает (данные, content-type, итоговый URL)."""
    _check_host(url)
    req = urllib.request.Request(
        url, headers={"User-Agent": user_agent, "Accept": accept, "Accept-Language": "ru,en;q=0.8"}
    )
    try:
        opener = _opener if allow_redirects else _no_redirect_opener
        if ssl_context is not None:
            redirect_handler = _SafeRedirect if allow_redirects else _NoRedirect
            opener = urllib.request.build_opener(redirect_handler, urllib.request.HTTPSHandler(context=ssl_context))
        with opener.open(req, timeout=TIMEOUT) as resp:
            data = resp.read(limit + 1)
            if len(data) > limit:
                raise ImportError_("Страница слишком большая")
            return data, resp.headers.get("Content-Type", ""), resp.geturl()
    except urllib.error.HTTPError as e:
        raise ImportError_(f"Сайт ответил ошибкой {e.code}")
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ImportError_("Не удалось открыть страницу — сайт недоступен или долго отвечает")


def _decode(data: bytes, content_type: str) -> str:
    m = re.search(r"charset=([\w-]+)", content_type, re.I)
    if not m:
        m = re.search(rb'<meta[^>]+charset=["\']?([\w-]+)', data[:4096], re.I)
    enc = (m.group(1).decode() if isinstance(m.group(1), bytes) else m.group(1)) if m else "utf-8"
    try:
        return data.decode(enc, errors="replace")
    except LookupError:
        return data.decode("utf-8", errors="replace")


# ---------------- поиск разметки ----------------
_LD_RE = re.compile(r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", re.S | re.I)


def _is_recipe(node: dict) -> bool:
    t = node.get("@type")
    types = t if isinstance(t, list) else [t]
    return any(isinstance(x, str) and x.lower().endswith("recipe") for x in types)


def _walk(node):  # noqa: ANN001
    if isinstance(node, list):
        for item in node:
            yield from _walk(item)
    elif isinstance(node, dict):
        yield node
        for key in ("@graph", "mainEntity", "mainEntityOfPage", "itemListElement"):
            if key in node:
                yield from _walk(node[key])


def find_recipe(page: str) -> dict | None:
    for raw in _LD_RE.findall(page):
        raw = raw.strip().strip(";")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Некоторые сайты кладут «сырые» переводы строк внутрь строк JSON
            try:
                data = json.loads(re.sub(r"[\r\n\t]+", " ", raw))
            except json.JSONDecodeError:
                continue
        for node in _walk(data):
            if _is_recipe(node):
                return node
    from recipe_microdata import find_microdata_recipe

    try:
        return find_microdata_recipe(page)
    except ValueError as exc:
        raise ImportError_("Разметка страницы слишком сложная или повреждена; автоматический импорт недоступен") from exc


def _meta(page: str, prop: str) -> str | None:
    m = re.search(
        rf'<meta[^>]+(?:property|name)=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']+)', page, re.I
    ) or re.search(rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']{re.escape(prop)}["\']', page, re.I)
    return html.unescape(m.group(1)).strip() if m else None


# ---------------- нормализация полей ----------------
def clean_text(value) -> str:  # noqa: ANN001
    if value is None:
        return ""
    if isinstance(value, list):
        value = " ".join(clean_text(v) for v in value)
    if isinstance(value, dict):
        value = value.get("text") or value.get("name") or ""
    text = re.sub(r"<br\s*/?>|</p>|</li>", "\n", str(value), flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(html.unescape(text)).replace("\xa0", " ")
    lines = [" ".join(line.split()) for line in text.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def parse_duration(value) -> int | None:  # noqa: ANN001
    """ISO 8601: PT1H30M → 90."""
    if not value or not isinstance(value, str):
        return None
    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", value.strip().upper())
    if not m:
        return None
    d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    total = d * 1440 + h * 60 + mi + (1 if s >= 30 else 0)
    return total or None


def parse_yield(value) -> int | None:  # noqa: ANN001
    if isinstance(value, list):
        for v in value:
            n = parse_yield(v)
            if n:
                return n
        return None
    if isinstance(value, (int, float)):
        return int(value) or None
    m = re.search(r"\d+", str(value or ""))
    n = int(m.group()) if m else None
    return n if n and 0 < n <= 100 else None


def _image(value) -> str | None:  # noqa: ANN001
    if isinstance(value, list):
        for v in value:
            url = _image(v)
            if url:
                return url
        return None
    if isinstance(value, dict):
        return _image(value.get("url") or value.get("contentUrl"))
    return value if isinstance(value, str) and value.strip() else None


def _step_pairs(value) -> list[tuple[str, str | None]]:  # noqa: ANN001
    """Flatten instructions while retaining the image belonging to each text step."""
    out: list[tuple[str, str | None]] = []
    if isinstance(value, str):
        text = clean_text(value)
        # Одной строкой: «1. Сделать… 2. Потом…» или абзацы
        parts = re.split(r"\n+|(?<=[.!?])\s+(?=\d{1,2}[.)]\s)", text)
        out.extend((part, None) for part in parts if part.strip())
    elif isinstance(value, list):
        for item in value:
            out.extend(_step_pairs(item))
    elif isinstance(value, dict):
        t = value.get("@type")
        if t == "HowToSection" or "itemListElement" in value:
            out.extend(_step_pairs(value.get("itemListElement")))
        else:
            text = clean_text(value.get("text") or value.get("name") or value.get("description"))
            if text:
                out.append((text, _image(value.get("image"))))
    # Убираем «Шаг 1:» / «1.» в начале — номера рисуем сами
    result = []
    for text, image in out:
        text = re.sub(r"^(?:шаг\s*)?\d{1,2}\s*[.):\-–—]\s*", "", text, flags=re.I).strip()
        if text:
            result.append((text, image))
    return result


def _steps(value) -> list[str]:  # noqa: ANN001
    return [text for text, _ in _step_pairs(value)]


def _list_of_str(value) -> list[str]:  # noqa: ANN001
    if not value:
        return []
    if isinstance(value, str):
        return [x.strip() for x in re.split(r"[,;]", value) if x.strip()]
    if isinstance(value, list):
        return [clean_text(x) for x in value if clean_text(x)]
    return []


# ---------------- разбор строки ингредиента ----------------
_UNITS: list[tuple[str, str]] = [
    # (регулярка, как храним) — порядок важен: длинные раньше коротких
    (r"кг|килограмм\w*", "кг"),
    (r"г|гр|грамм\w*", "г"),
    (r"мл|миллилитр\w*", "мл"),
    (r"л|литр\w*", "л"),
    (r"ч\.?\s?л\.?|чайн\w*\s+лож\w*|ч\.\s?ложк\w*", "ч. л."),
    (r"ст\.?\s?л\.?|стол\w*\s+лож\w*|ст\.\s?ложк\w*", "ст. л."),
    (r"стакан\w*|ст\.?(?=\s|$)", "стакан"),
    (r"шт\.?|штук\w*", "шт"),
    (r"головк\w*", "шт"),
    (r"щепот\w*", "щепотка"),
    (r"зубч\w*|зуб\.", "зубчик"),
    (r"пуч\w*", "пучок"),
    (r"g|grams?", "г"),
    (r"kg", "кг"),
    (r"ml", "мл"),
    (r"tsp|teaspoons?", "ч. л."),
    (r"tbsp|tablespoons?", "ст. л."),
    (r"cups?", "стакан"),
]
_UNIT_RE = "|".join(f"(?:{u})" for u, _ in _UNITS)
_FRAC = {"½": 0.5, "¼": 0.25, "¾": 0.75, "⅓": 1 / 3, "⅔": 2 / 3, "⅛": 0.125}
_NUM = r"\d+(?:[.,]\d+)?(?:\s*/\s*\d+)?|[½¼¾⅓⅔⅛]|\d+\s*[½¼¾⅓⅔⅛]"
_QTY_RE = re.compile(
    rf"(?P<num>{_NUM})(?:\s*[-–—]\s*(?:{_NUM}))?\s*(?P<unit>(?:{_UNIT_RE})(?![а-яa-z]))?",
    re.I,
)
_TO_TASTE = re.compile(r"\b(по вкусу|для подачи|по желанию|to taste)\b", re.I)


def _to_number(s: str) -> float | None:
    s = s.replace(",", ".").replace(" ", "")
    for ch, v in _FRAC.items():
        if ch in s:
            whole = s.replace(ch, "")
            return (float(whole) if whole else 0) + v
    if "/" in s:
        a, b = s.split("/", 1)
        try:
            return float(a) / float(b) if float(b) else None
        except ValueError:
            return None
    try:
        return float(s)
    except ValueError:
        return None


def _norm_unit(raw: str | None) -> str:
    if not raw:
        return ""
    for pattern, unit in _UNITS:
        if re.fullmatch(pattern, raw.strip(), re.I):
            return unit
    return ""


# «200 г муки» → «Мука». Только частые продукты: лучше оставить как есть, чем исказить.
_GENITIVE = {
    "муки": "мука", "сахара": "сахар", "соли": "соль", "соды": "сода", "воды": "вода", "молока": "молоко",
    "сметаны": "сметана", "яиц": "яйца", "яблок": "яблоки", "сливочного масла": "сливочное масло",
    "растительного масла": "растительное масло", "слив. масла": "сливочное масло", "слив масла": "сливочное масло",
    "творога": "творог", "крахмала": "крахмал", "сливок": "сливки", "уксуса": "уксус", "ванилина": "ванилин",
    "корицы": "корица", "дрожжей": "дрожжи", "сухих дрожжей": "сухие дрожжи", "кефира": "кефир",
    "риса": "рис", "фарша": "фарш", "лука": "лук", "моркови": "морковь", "картофеля": "картофель",
    "сыра": "сыр", "меда": "мёд", "мёда": "мёд", "какао": "какао", "разрыхлителя": "разрыхлитель",
    "ванильного сахара": "ванильный сахар", "сахарной пудры": "сахарная пудра", "томатной пасты": "томатная паста",
    "чеснока": "чеснок", "рикотты": "рикотта", "желтков": "желтки", "белков": "белки", "орехов": "орехи",
    "картошки": "картошка", "морковки": "морковка", "помидоров": "помидоры", "огурцов": "огурцы",
    "бананов": "бананы", "лимона": "лимон", "лимонов": "лимоны", "апельсинов": "апельсины", "грибов": "грибы",
    "шампиньонов": "шампиньоны", "макарон": "макароны", "гречки": "гречка", "курицы": "курица",
    "говядины": "говядина", "свинины": "свинина", "сливочного": "сливочное", "майонеза": "майонез",
}


_GENITIVE.update({
    "масла": "масло", "шоколада": "шоколад", "порошка": "порошок", "экстракта": "экстракт",
    "пудры": "пудра", "желтка": "желток", "сыра": "сыр", "соуса": "соус", "бульона": "бульон",
    "пасты": "паста", "муки": "мука", "сахара": "сахар", "орехов": "орехи", "сливок": "сливки",
    "зелени": "зелень", "петрушки": "петрушка", "укропа": "укроп", "сгущенки": "сгущенка",
    "йогурта": "йогурт", "филе": "филе", "печенья": "печенье", "желатина": "желатин",
})


def _gender(noun: str) -> str:
    n = noun.lower()
    if n.endswith(("и", "ы")):
        return "pl"
    if n.endswith(("а", "я")) or n.endswith("ь") and n in ("соль", "морковь", "зелень"):
        return "f"
    if n.endswith(("о", "е", "ё")):
        return "n"
    return "m"


def _adj(word: str, gender: str) -> str:
    """Прилагательное из родительного падежа: «темного» → «темный», «сливочного» (масла) → «сливочное»."""
    w = word.lower()
    soft = len(w) > 4 and w[-4] in "кгхжшчщ"
    if w.endswith(("ого", "его")):
        stem = w[:-3]
        return {"m": stem + ("ий" if soft or w.endswith("его") else "ый"), "n": stem + ("ее" if w.endswith("его") else "ое")}.get(gender, word)
    if w.endswith(("ой", "ей")) and gender == "f":
        return w[:-2] + ("яя" if w.endswith("ей") else "ая")
    if w.endswith(("ых", "их")) and gender == "pl":
        return w[:-2] + ("ие" if w.endswith("их") else "ые")
    return word


def _nominative(name: str) -> str:
    low = name.lower().strip()
    if low in _GENITIVE:
        return _GENITIVE[low]
    for gen, nom in _GENITIVE.items():
        if " " in gen and low.startswith(gen + " "):
            return nom + name.strip()[len(gen):]
    # По словам: ищем существительное («размягченного сливочного масла» → «масла»),
    # прилагательные перед ним согласуем по роду, хвост («22%») оставляем как есть
    words = name.split()
    for j, word in enumerate(words):
        head, _, last = word.rpartition("-")  # «какао-порошка»
        nom = _GENITIVE.get(last.lower())
        if not nom or " " in nom or last.lower().endswith(("ого", "его")):
            continue
        g = _gender(nom)
        before = [_adj(w, g) for w in words[:j]]
        noun = f"{head}-{nom}" if head else nom
        return " ".join([*before, noun, *words[j + 1 :]])
    return name


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


@dataclass
class ParsedIngredient:
    product: str
    amount: float | None = None
    unit: str = ""
    note: str = ""
    group: str = ""


def parse_ingredient(line: str) -> ParsedIngredient:
    text = clean_text(line).replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip(" •-–—*")
    # Prefer the explicit weight to an approximate piece-to-grams conversion.
    equivalent = re.fullmatch(r"(.+?)\s*=\s*(\d+(?:[.,]\d+)?)\s*(г|мл)\.?", text, re.I)
    if equivalent:
        original = parse_ingredient(equivalent.group(1))
        if original.amount is not None:
            measure = f"{original.amount:g} {original.unit}"
            return ParsedIngredient(
                product=original.product,
                amount=float(equivalent.group(2).replace(",", ".")),
                unit=equivalent.group(3).lower(),
                note=", ".join(x for x in (measure, original.note) if x)[:200],
            )
    note = ""

    # Примечание в скобках: «Лук (средний)»
    m = re.search(r"\(([^)]{1,80})\)", text)
    if m and not _QTY_RE.fullmatch(m.group(1).strip()):
        note = m.group(1).strip()
        text = (text[: m.start()] + text[m.end() :]).strip()
    text = re.sub(r"[()]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    to_taste = bool(_TO_TASTE.search(text))
    if to_taste:
        text = _TO_TASTE.sub("", text).strip(" ,-–—:")

    name, qty_part = text, ""
    # «Мука — 200 г», «Мука: 200 г»
    sep = re.split(r"\s+[-–—]\s+|\s*:\s+", text, maxsplit=1)
    # «550 - 600 г муки» — это диапазон, а не «название — количество»
    if len(sep) == 2 and _QTY_RE.search(sep[1]) and not re.fullmatch(_NUM, sep[0].strip()):
        name, qty_part = sep[0], sep[1]
    else:
        # «200 г муки» — количество в начале
        m = _QTY_RE.match(text)
        if m and m.group("num"):
            qty_part, name = text[: m.end()], _nominative(text[m.end() :].strip())
        else:
            # «Мука 200 г» — количество в конце
            m = re.search(rf"\s(?P<q>(?:{_NUM})(?:\s*[-–—]\s*(?:{_NUM}))?\s*(?:{_UNIT_RE})?\.?)\s*$", text, re.I)
            if m:
                name, qty_part = text[: m.start()], m.group("q")

    amount, unit = None, ""
    if qty_part:
        m = _QTY_RE.search(qty_part)
        if m:
            amount = _to_number(m.group("num"))
            unit = _norm_unit(m.group("unit"))
            rest = (qty_part[: m.start()] + qty_part[m.end() :]).strip(" ,.;")
            if rest and not note:
                note = rest
            # Диапазон «2–3 зубчика», «550–600 г»: берём меньшее, диапазон — в примечание
            rng = re.match(r"\s*(\S+?)\s*[-–—]\s*(\S+)", m.group(0))
            if rng and _to_number(rng.group(2).rstrip(".")) is not None:
                span = re.sub(r"\s*[-–—]\s*", "–", m.group(0).strip(" ,.;"), count=1)
                note = ", ".join(x for x in (span, note) if x)
    if to_taste and amount is None:
        unit = "по вкусу"
    if amount is not None and not unit:
        unit = "шт"

    name = name.strip(" ,.;:-–—")
    # «Соль, крупная» → продукт + примечание
    if "," in name:
        head, tail = name.split(",", 1)
        if head.strip():
            name = head.strip()
            note = ", ".join(x for x in (tail.strip(), note) if x)
    return ParsedIngredient(product=_cap(name)[:128] or _cap(text)[:128], amount=amount, unit=unit, note=note[:200])


def _ingredients(recipe: dict) -> list[ParsedIngredient]:
    raw = recipe.get("recipeIngredient") or recipe.get("ingredients") or []
    if isinstance(raw, str):
        raw = [x for x in raw.split("\n") if x.strip()]
    out: list[ParsedIngredient] = []
    for item in raw:
        line = clean_text(item)
        if not line:
            continue
        # Заголовки разделов вида «Для соуса:» превращаем в группы
        if re.fullmatch(r"(?:для\s.+|.+:)", line, re.I) and not _QTY_RE.search(line):
            group = line.rstrip(":").strip()
            out.append(ParsedIngredient(product="", group=_cap(group)))
            continue
        out.append(parse_ingredient(line))
    # Раскладываем по группам
    result: list[ParsedIngredient] = []
    group = ""
    for ing in out:
        if not ing.product:
            group = ing.group
            continue
        ing.group = group
        result.append(ing)
    return result


# ---------------- итог ----------------
@dataclass
class ImportedRecipe:
    title: str
    description: str = ""
    servings: int | None = None
    prep_minutes: int | None = None
    cook_minutes: int | None = None
    category: str = ""
    tags: list[str] = field(default_factory=list)
    ingredients: list[ParsedIngredient] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    image_url: str | None = None
    source_url: str = ""
    step_images: list[str | None] = field(default_factory=list)


class _IamCookFields(HTMLParser):
    """Read IamCook's explicit recipe blocks when its JSON-LD omits their content."""

    _VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.ingredient_root: int | None = None
        self.ingredient_body: int | None = None
        self.ingredient_selected = False
        self.instructions_root: int | None = None
        self.instructions_selected = False
        self.capture: tuple[str, int, list[str]] | None = None
        self.ingredients: list[str] = []
        self.instructions: list[str] = []
        self.instruction_images: list[str | None] = []
        self.photo_root: int | None = None
        self.capture_image: str | None = None

    def _attach_image(self, image: str | None) -> None:
        if image and self.instruction_images and self.instruction_images[-1] is None:
            self.instruction_images[-1] = image

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if tag in self._VOID_TAGS:
            if tag == "br" and self.capture:
                self.capture[2].append(" ")
            if (tag == "img" and self.instructions_root is not None and self.photo_root is not None and
                    "result-photo" not in classes and not any(item in ("script", "style") for item in self.stack)):
                image = attributes.get("data-src") or attributes.get("data-original") or attributes.get("src")
                if self.capture and self.capture[0] == "instruction":
                    if self.capture_image is None:
                        self.capture_image = image
                else:
                    self._attach_image(image)
            return
        self.stack.append(tag)
        depth = len(self.stack)
        if tag == "div" and "ilist" in classes and self.ingredient_root is None and not self.ingredient_selected:
            self.ingredient_root = depth
        elif (tag == "div" and self.ingredient_root is not None and
              depth == self.ingredient_root + 1 and not self.ingredient_selected):
            self.ingredient_body = depth
            self.ingredient_selected = True
        if tag == "div" and "instructions" in classes and not self.instructions_selected:
            self.instructions_root = depth
            self.instructions_selected = True
        if tag == "div" and "primg" in classes and self.instructions_root is not None:
            self.photo_root = depth
        if self.capture is not None or any(item in ("script", "style") for item in self.stack):
            return
        if self.ingredient_body is not None and depth > self.ingredient_body and tag in ("p", "strong"):
            self.capture = ("group" if tag == "strong" else "ingredient", depth, [])
        elif self.instructions_root is not None and depth > self.instructions_root and tag == "p":
            self.capture = ("instruction", depth, [])

    def handle_endtag(self, tag: str) -> None:
        if tag not in self.stack:
            return
        index = len(self.stack) - 1 - self.stack[::-1].index(tag)
        depth = index + 1
        if self.capture and self.capture[1] >= depth:
            kind, _, parts = self.capture
            text = clean_text("".join(parts))
            if text:
                if kind == "instruction":
                    self.instructions.append(text)
                    self.instruction_images.append(self.capture_image)
                else:
                    self.ingredients.append(text.rstrip(":") + ":" if kind == "group" else text)
            elif kind == "instruction":
                self._attach_image(self.capture_image)
            self.capture = None
            self.capture_image = None
        if self.ingredient_body is not None and self.ingredient_body >= depth:
            self.ingredient_body = None
        if self.ingredient_root is not None and self.ingredient_root >= depth:
            self.ingredient_root = None
        if self.instructions_root is not None and self.instructions_root >= depth:
            self.instructions_root = None
        if self.photo_root is not None and self.photo_root >= depth:
            self.photo_root = None
        del self.stack[index:]

    def handle_data(self, data: str) -> None:
        if self.capture and not any(tag in ("script", "style") for tag in self.stack):
            self.capture[2].append(data)


def _iamcook_fields(page: str, node: dict, source_url: str) -> dict:
    parsed = urlparse(source_url)
    if (parsed.hostname not in ("iamcook.ru", "www.iamcook.ru") or
            not re.fullmatch(r"/showrecipe/\d+/?", parsed.path)):
        return node
    parser = _IamCookFields()
    parser.feed(page)
    parser.close()
    result = node.copy()
    if not (result.get("recipeIngredient") or result.get("ingredients")):
        result["recipeIngredient"] = parser.ingredients
    if not result.get("recipeInstructions"):
        result["recipeInstructions"] = [
            {"@type": "HowToStep", "text": text, "image": image}
            for text, image in zip(parser.instructions, parser.instruction_images)
        ]
    else:
        pairs = _step_pairs(result["recipeInstructions"])
        html_pairs = _step_pairs(parser.instructions)
        if [text for text, _ in pairs] == [text for text, _ in html_pairs] and len(pairs) == len(parser.instruction_images):
            result["recipeInstructions"] = [
                {"@type": "HowToStep", "text": text, "image": image or html_image}
                for (text, image), html_image in zip(pairs, parser.instruction_images)
            ]
    return result


def import_from_url(url: str) -> ImportedRecipe:
    data, ctype, final_url = fetch(url.strip(), MAX_PAGE_BYTES)
    page = _decode(data, ctype)
    return import_from_html(page, final_url)


def import_from_html(page: str, source_url: str) -> ImportedRecipe:
    """Parse an already downloaded page without making another network request."""
    node = find_recipe(page)
    if not node:
        raise ImportError_(
            "На странице не нашлось разметки рецепта. Такой сайт пока не поддерживается — рецепт можно внести вручную."
        )
    node = _iamcook_fields(page, node, source_url)

    prep = parse_duration(node.get("prepTime"))
    cook = parse_duration(node.get("cookTime"))
    total = parse_duration(node.get("totalTime"))
    if total and not prep and not cook:
        cook = total
    elif total and prep and not cook and total > prep:
        cook = total - prep

    image = _image(node.get("image")) or _meta(page, "og:image")
    tags = [t.lower() for t in _list_of_str(node.get("keywords"))][:10]
    category = _list_of_str(node.get("recipeCategory"))
    cuisine = _list_of_str(node.get("recipeCuisine"))
    for c in cuisine[:2]:
        if c.lower() not in tags:
            tags.append(c.lower())

    step_pairs = _step_pairs(node.get("recipeInstructions"))[:100]

    return ImportedRecipe(
        title=clean_text(node.get("name")) or _meta(page, "og:title") or "Рецепт",
        description=clean_text(node.get("description"))[:2000],
        servings=parse_yield(node.get("recipeYield")),
        prep_minutes=prep,
        cook_minutes=cook,
        category=category[0] if category else "",
        tags=[t[:64] for t in tags if len(t) <= 64][:12],
        ingredients=_ingredients(node),
        steps=[text for text, _ in step_pairs],
        image_url=urljoin(source_url, image) if image else None,
        source_url=source_url,
        step_images=[urljoin(source_url, image.strip()) if image else None for _, image in step_pairs],
    )
