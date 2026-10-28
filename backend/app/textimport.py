"""Импорт рецепта из обычного текста (Telegram, заметки) и со скриншота (OCR).

Текст из мессенджеров бывает каким угодно, поэтому разбор щадящий:
- если есть заголовки «Ингредиенты» / «Приготовление» — делим по ним;
- если нет — короткие строки с количеством считаем ингредиентами, длинные и нумерованные — шагами.
Результат всё равно открывается в редакторе, где его можно поправить.
"""
from __future__ import annotations

import io
import re
import shutil
import subprocess
import tempfile

from PIL import Image, ImageOps, UnidentifiedImageError

from .importer import _QTY_RE, ImportedRecipe, ParsedIngredient, _cap, parse_ingredient

# ---------------- заголовки разделов ----------------
_ING_HEAD = re.compile(
    r"^(?:ингредиенты|ингридиенты|продукты|состав|список продуктов|что нужно|"
    r"(?:нам |вам )?(?:понадобится|потребуется)|для рецепта|ingredients)\b[^.]{0,40}$",
    re.I,
)
_STEP_HEAD = re.compile(
    r"^(?:приготовление|способ приготовления|как (?:приготовить|готовить|готовим)|готовим|"
    r"пошагов\w* рецепт|рецепт приготовления|шаги|инструкция|method|directions|instructions)\b[^.]{0,40}$",
    re.I,
)
_NOTE_HEAD = re.compile(r"^(?:совет|советы|примечани\w*|подача|приятного аппетита|лайфхак)\b", re.I)
# «Для теста:», «Соус:», «Крем —»
_GROUP_HEAD = re.compile(r"^(?:для\s+[^:]{2,40}|[А-ЯЁA-Z][^:\d]{2,30}):?$")

_NUMBERED = re.compile(r"^(?:шаг\s*)?(\d{1,2})\s*[.)\-–—:]\s*(.*)$", re.I)
_BULLET = re.compile(r"^[\s•·▪▫◦●○■□✓✔☑✅➖➕\-–—*+>]+")
# Эмодзи и прочие символы-украшения
_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF‍️⃣⭐⭕←-⇿]"
)
_HASHTAG = re.compile(r"#([\wё]+)", re.I)

_SERVINGS = re.compile(r"(?:на\s+(\d{1,2})\s+порц|порци[йия]\s*[:\-–—]?\s*(\d{1,2})|(\d{1,2})\s+порци)", re.I)
_TIME = re.compile(
    r"(?:время|готовить|приготовлени[ея])[^:\d]{0,25}[:\-–—]?\s*(?:(\d{1,2})\s*(?:ч|час)\w*\.?)?\s*(?:(\d{1,3})\s*мин\w*)?",
    re.I,
)


def _clean_line(line: str) -> str:
    line = _EMOJI.sub(" ", line)
    line = line.replace("\xa0", " ").replace("\t", " ")
    line = " ".join(line.split()).strip()
    # Маркеры списков и эмодзи, которые распознавание превратило в «®», «°», «»», «@», «e»
    line = re.sub(r"^(?:[^\w\s(«\"]+\s*|[a-zA-Z©¢]\s+(?=[А-ЯЁа-яё]))+", "", line)
    line = re.sub(r"(?:\s+[^\w\s).!?»\"]+)+$", "", line)
    return line.strip()


_OCR_DIGIT = re.compile(r"(?<![А-Яа-яЁёA-Za-z])([ЗзOОо])(?=\s*(?:шт|г|гр|кг|мл|л|ст\.|ч\.|стакан|зуб|\d))")


def fix_ocr(text: str) -> str:
    """Типичные ошибки распознавания: «Зшт» → «3шт», «1О0 г» → «100 г»."""
    text = _OCR_DIGIT.sub(lambda m: "3" if m.group(1) in "Зз" else "0", text)
    return re.sub(r"(?<=\d)[OОо](?=\d|\s*(?:г|мл|кг)\b)", "0", text)


def _strip_bullet(line: str) -> str:
    return _BULLET.sub("", line).strip()


def _is_meta(line: str) -> bool:
    """Служебная строка: «Время приготовления: 40 мин», «На 4 порции»."""
    if len(line) > 60 or not re.match(r"^(?:время|общее время|порци|количество порций|на\s+\d|выход|готов)", line, re.I):
        return False
    return bool(_SERVINGS.search(line) or (_TIME.search(line) and _minutes(line)))


def _looks_like_ingredient(line: str) -> bool:
    """Короткая строка с количеством или «Соль по вкусу»."""
    plain = _strip_bullet(line)
    if not plain or len(plain) > 80 or _is_meta(plain):
        return False
    if plain.endswith((".", "!", "?")) and len(plain.split()) > 6:
        return False
    if "!" in plain or "?" in plain:
        return False
    if _QTY_RE.search(plain) and len(plain.split()) <= 10:
        return True
    if re.search(r"\bпо вкусу\b|\bдля подачи\b|\bпо желанию\b", plain, re.I):
        return True
    return False


def _looks_like_step(line: str) -> bool:
    plain = _strip_bullet(line)
    if _NUMBERED.match(plain) and len(plain) > 12:
        return True
    words = plain.split()
    return len(words) >= 7 or (len(words) >= 4 and plain.endswith("."))


def _minutes(text: str) -> int | None:
    m = _TIME.search(text)
    if not m or not (m.group(1) or m.group(2)):
        return None
    total = int(m.group(1) or 0) * 60 + int(m.group(2) or 0)
    return total if 0 < total <= 10_000 else None


def _servings(text: str) -> int | None:
    m = _SERVINGS.search(text)
    if not m:
        return None
    n = int(next(g for g in m.groups() if g))
    return n if 0 < n <= 100 else None


_VAGUE = re.compile(
    r"^(.{2,60}?)\s*[-–—:]\s*(щепотк\w*|по вкусу|немного|для подачи|для жарки|для смазывания|по желанию)\.?$", re.I
)


def _ingredients(lines: list[str]) -> list[ParsedIngredient]:
    out: list[ParsedIngredient] = []
    group = ""
    for raw in lines:
        line = _strip_bullet(raw)
        if not line:
            continue
        # Несколько ингредиентов в строку через «;» — «мука 200 г; сахар 100 г»
        parts = [p for p in re.split(r"\s*;\s*", line) if p] if ";" in line else [line]
        for part in parts:
            if not _QTY_RE.search(part) and _GROUP_HEAD.match(part) and (part.endswith(":") or part.lower().startswith("для ")):
                group = _cap(part.rstrip(":").strip())
                continue
            if _is_meta(part):
                continue
            m = _VAGUE.match(part)
            if m:
                # «Соль — щепотка», «Зелень: для подачи»
                word = m.group(2).lower()
                if word.startswith("щепот"):
                    ing = ParsedIngredient(product=_cap(m.group(1).strip()), amount=1, unit="щепотка")
                elif word == "по вкусу":
                    ing = ParsedIngredient(product=_cap(m.group(1).strip()), unit="по вкусу")
                else:
                    ing = ParsedIngredient(product=_cap(m.group(1).strip()), note=word)
            else:
                ing = parse_ingredient(part)
            if not ing.product:
                continue
            ing.group = group
            out.append(ing)
    return out


def _steps(lines: list[str]) -> list[str]:
    """Нумерованные шаги со строками-продолжениями; без номеров — каждая строка/абзац отдельно."""
    numbered = sum(1 for line in lines if _NUMBERED.match(_strip_bullet(line)))
    steps: list[str] = []
    if numbered >= 2:
        for raw in lines:
            line = _strip_bullet(raw)
            m = _NUMBERED.match(line)
            if m:
                steps.append(m.group(2).strip())
            elif steps:
                steps[-1] = f"{steps[-1]} {line}".strip()
            elif line:
                steps.append(line)
    else:
        for raw in lines:
            line = re.sub(r"^(?:шаг\s*)?\d{1,2}\s*[.):\-–—]\s*", "", _strip_bullet(raw), flags=re.I)
            if line:
                steps.append(line)
    return [s[:10_000] for s in steps if len(s) > 1]


def parse_text(text: str) -> ImportedRecipe:
    raw_lines = text.replace("\r", "").split("\n")
    tags: list[str] = []
    for m in _HASHTAG.finditer(text):
        t = m.group(1).lower().replace("_", " ")
        if t not in tags and len(t) <= 64:
            tags.append(t)
    lines = [_clean_line(_HASHTAG.sub("", line)) for line in raw_lines]
    joined = "\n".join(lines)

    servings = _servings(joined)
    minutes = _minutes(joined)

    # Название — первая содержательная строка, не заголовок и не ингредиент
    title = ""
    body: list[str] = []
    for i, line in enumerate(lines):
        if not line:
            continue
        if not title and not _ING_HEAD.match(line) and not _STEP_HEAD.match(line) and not _looks_like_ingredient(line):
            title = _strip_bullet(line).strip(" :.")[:200]
            body = lines[i + 1 :]
            break
    if not title:
        title, body = "Рецепт", lines

    # Делим по заголовкам разделов
    section = "intro"
    buckets: dict[str, list[str]] = {"intro": [], "ing": [], "steps": [], "notes": []}
    has_heads = any(_ING_HEAD.match(line) or _STEP_HEAD.match(line) for line in body if line)
    for line in body:
        if not line:
            continue
        head = line.rstrip(":").strip()
        if _ING_HEAD.match(head):
            section = "ing"
            continue
        if _STEP_HEAD.match(head):
            section = "steps"
            continue
        if _NOTE_HEAD.match(head) and section == "steps":
            section = "notes"
        if not has_heads:
            # Без заголовков: ингредиенты — пока идут «короткие строки с количеством», потом шаги
            if section == "intro" and _looks_like_ingredient(line):
                section = "ing"
            elif section == "ing" and not _looks_like_ingredient(line) and not _GROUP_HEAD.match(line):
                section = "steps"
        elif (
            section == "intro"
            and not buckets["ing"]
            and _looks_like_ingredient(line)
            and (_BULLET.match(line) or re.search(r"\d\s*(?:г|кг|мл|л|шт|ст\.|ч\.)\b", line))
        ):
            # Заголовок «Ингредиенты» забыли, а ниже есть «Приготовление»
            section = "ing"
        elif section == "ing" and _looks_like_step(line) and not _looks_like_ingredient(line):
            # Ингредиенты кончились, а заголовка «Приготовление» нет
            section = "steps"
        if section in ("ing", "steps") and _is_meta(line):
            continue
        buckets[section].append(line)

    # Описание: вступление без служебных строк про порции и время
    intro = [line for line in buckets["intro"] if not _is_meta(line)]
    description = "\n".join(intro + buckets["notes"]).strip()

    return ImportedRecipe(
        title=_cap(title),
        description=description[:2000],
        servings=servings,
        cook_minutes=minutes,
        tags=tags[:12],
        ingredients=_ingredients(buckets["ing"])[:200],
        steps=_steps(buckets["steps"])[:100],
    )


# ---------------- распознавание текста ----------------
class OcrError(Exception):
    pass


def ocr(data: bytes) -> str:
    """Скриншот → текст. Tesseract с русским и английским; тёмную тему инвертируем."""
    if not shutil.which("tesseract"):
        raise OcrError("Распознавание текста недоступно на сервере (нет tesseract)")
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img).convert("L")
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise OcrError("Это не похоже на изображение")
    # Светлый текст на тёмном фоне (тёмная тема Telegram) распознаётся плохо — инвертируем
    hist = img.histogram()
    dark = sum(hist[:100]) > sum(hist[156:])
    if dark:
        img = ImageOps.invert(img)
    img = ImageOps.autocontrast(img)
    # Мелкий текст увеличиваем — tesseract любит ~30 px на строку
    if img.width < 1400:
        k = min(3.0, 1400 / max(img.width, 1))
        img = img.resize((int(img.width * k), int(img.height * k)), Image.Resampling.LANCZOS)
    with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
        img.save(tmp.name)
        try:
            res = subprocess.run(
                ["tesseract", tmp.name, "-", "-l", "rus+eng", "--psm", "4"],
                capture_output=True,
                timeout=90,
            )
        except subprocess.TimeoutExpired:
            raise OcrError("Картинка распознавалась слишком долго")
    if res.returncode != 0:
        err = res.stderr.decode("utf-8", "replace").strip().splitlines()
        raise OcrError("Не удалось распознать текст" + (f": {err[-1][:200]}" if err else ""))
    text = fix_ocr(res.stdout.decode("utf-8", "replace"))
    # Убираем мусор распознавания: одиночные символы, пустые строки подряд
    lines = [line.rstrip() for line in text.split("\n")]
    lines = [line for line in lines if len(line.strip()) > 1 or not line.strip()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
