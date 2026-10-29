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
from difflib import SequenceMatcher

from PIL import Image, ImageOps, UnidentifiedImageError

from .importer import _QTY_RE, ImportedRecipe, ParsedIngredient, _cap, _nominative, parse_ingredient

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


_OCR_DIGIT = re.compile(r"(?<![А-Яа-яЁёA-Za-z])([ЗзOОо])(?=\s*(?:(?:шт|гр|г|кг|мл|л)(?![а-яё])|ст\.|ч\.|стакан|зубч|\d))")


def fix_ocr(text: str) -> str:
    """Типичные ошибки распознавания: «Зшт» → «3шт», «1О0 г» → «100 г»."""
    text = _OCR_DIGIT.sub(lambda m: "3" if m.group(1) in "Зз" else "0", text)
    # «½» распознаётся как «У» / «У2»: «У ч. л. разрыхлителя»
    text = re.sub(r"(?m)^(\W*)[УYу]2?[,.]?(?=\s*(?:ч\.|ст\.|стакан|кг|шт))", r"\1½", text)
    # Латинские буквы-двойники в единицах после числа: «2 CT. л» → «2 ст. л»
    lat = str.maketrans("ACEHKMOPTXYBacekmopxy", "АСЕНКМОРТХУВасекморху")
    text = re.sub(
        r"(\d\s*)([ACEHKMOPTXYBacekmopxy]{1,3})(?=\.|\s|$)",
        lambda m: m.group(1) + m.group(2).translate(lat).lower(),
        text,
    )
    # «1 ч. л.» распознаётся как «14. л.»
    text = re.sub(r"(\d)4\.\s*[лJjl]\.", r"\1 ч. л.", text)
    text = re.sub(r"((?:ч|ст)\.\s*)[Jjl]\.", r"\1л.", text)
    # Короткие слова латиницей посреди русского текста: «Ha 12 часов» → «на 12 часов»
    text = re.sub(
        r"(?<=[а-яё,] )(Ha|He|Ho|Ta|To|Bo|Ka|Kak|Bce|Ec|Ee|Ero|Mope)(?= )",
        lambda m: m.group(1).translate(str.maketrans("HaeoTBKcEgMp", "наеотвксеgмр")).lower(),
        text,
    )
    # «120 гмуки» → «120 г муки» (только для двузначных и больше — «1 груша» не трогаем)
    text = re.sub(r"(\d{2,})\s*(г|кг|мл)(?=[а-яё]{3,})", r"\1 \2 ", text)
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


_ADJ_END = re.compile(r"(?:ого|его|ой|ей|ый|ий|ая|яя|ых|их|ое|ее|[-,])$", re.I)
_FORM = re.compile(r"^(?:на форму|форма|для формы|диаметр|выход|на \d+ порц)", re.I)


def _merge_wrapped(lines: list[str]) -> list[str]:
    """В книгах длинный ингредиент переносится: «45 г размягченного» / «сливочного масла»."""
    out: list[str] = []
    for raw in lines:
        line = _strip_bullet(raw)
        if not line:
            out.append("")
            continue
        prev = out[-1] if out else ""
        wrapped = (
            prev
            and not prev.endswith(":")
            and line[:1].islower()
            and not re.search(r"\d", line)
            and _ADJ_END.search(prev)
        )
        size = prev and re.fullmatch(r"\d+(?:[.,]\d+)?\s*(?:см|мм|cm)\.?", line)  # «22 см» к «На форму диаметром»
        if wrapped or size:
            out[-1] = f"{prev} {line}".replace("- ", "-") if prev.endswith("-") else f"{prev} {line}"
        else:
            out.append(line)
    return out


def _ingredients(lines: list[str], notes: list[str] | None = None) -> list[ParsedIngredient]:
    out: list[ParsedIngredient] = []
    group = ""
    for raw in _merge_wrapped(lines):
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
            if _FORM.match(part):
                # «На форму диаметром 22 см» — не ингредиент, а примечание к рецепту
                if notes is not None:
                    notes.append(part)
                continue
            pinch = re.match(r"^(щепотк\w*|немного|пара)\s+(.{2,})$", part, re.I)
            m = _VAGUE.match(part)
            if pinch:
                # «щепотка соли» → Соль, 1 щепотка
                word = pinch.group(1).lower()
                name = _cap(_nominative(pinch.group(2).strip()))
                ing = (
                    ParsedIngredient(product=name, amount=1, unit="щепотка")
                    if word.startswith("щепот")
                    else ParsedIngredient(product=name, note=word)
                )
            elif m:
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
        # Без номеров (в книгах их часто не распознать): абзац — один шаг, если абзацы есть;
        # иначе каждая строка — шаг
        paragraphs: list[list[str]] = [[]]
        for raw in lines:
            line = re.sub(r"^(?:шаг\s*)?\d{1,2}\s*[.):\-–—]\s*", "", _strip_bullet(raw), flags=re.I)
            if not line:
                if paragraphs[-1]:
                    paragraphs.append([])
            else:
                paragraphs[-1].append(line)
        paragraphs = [p for p in paragraphs if p]
        # Абзац оборвался на полуслове («…за 10 минут» / «до раскатки…») — это один шаг
        joined: list[list[str]] = []
        for p in paragraphs:
            if joined and not re.search(r"[.!?:…)]$", joined[-1][-1]) and p[0][:1].islower():
                joined[-1].extend(p)
            else:
                joined.append(p)
        paragraphs = joined
        if any(len(p) > 1 for p in paragraphs):
            for p in paragraphs:
                text = ""
                for line in p:
                    if text.endswith("-") and line[:1].islower():
                        text = _join_hyphen(text, line)
                    else:
                        text = f"{text} {line}".strip()
                steps.append(text)
        else:
            steps = [p[0] for p in paragraphs]
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
        if _ING_HEAD.match(line.rstrip(":").strip()) or _STEP_HEAD.match(line.rstrip(":").strip()):
            break  # дошли до разделов, а названия так и не было
        if _FORM.match(line):
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
            # Границы абзацев нужны шагам без номеров
            if section == "steps" and buckets["steps"] and buckets["steps"][-1]:
                buckets["steps"].append("")
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
    form_notes: list[str] = []
    ingredients = _ingredients(buckets["ing"], form_notes)[:200]
    description = "\n".join(intro + form_notes + buckets["notes"]).strip()

    return ImportedRecipe(
        title=_cap(title),
        description=description[:2000],
        servings=servings,
        cook_minutes=minutes,
        tags=tags[:12],
        ingredients=ingredients,
        steps=_steps(buckets["steps"])[:100],
    )


# ---------------- распознавание текста ----------------
def _norm(line: str) -> str:
    return re.sub(r"[^\wё]+", "", line.lower())


def _same(a: str, b: str) -> bool:
    """Строки совпадают с поправкой на ошибки распознавания и обрезанный край."""
    if not a or not b:
        return False
    # Разные числа — разные строки («мука 200 г» ≠ «мука 300 г»)
    if re.findall(r"\d+", a) != re.findall(r"\d+", b):
        return False
    if a == b or (min(len(a), len(b)) >= 8 and (a in b or b in a)):
        return True
    return SequenceMatcher(None, a, b).ratio() >= 0.75


def join_pages(texts: list[str]) -> str:
    """Склеить текст нескольких скриншотов по порядку. Соседние скриншоты обычно
    перекрываются на несколько строк — повтор в начале следующего убираем."""
    out: list[str] = []
    for text in texts:
        lines = text.split("\n")
        tail = [n for n in (_norm(x) for x in out) if n][-30:]
        if tail:
            # Идём сверху вниз по новому скриншоту, пока строки уже были в конце прошлого.
            # Пару несовпадений подряд прощаем: на краю бывает обрезанная наполовину строка.
            cut, misses, seen = 0, 0, 0
            for idx, line in enumerate(lines):
                n = _norm(line)
                if not n:
                    continue
                seen += 1
                if seen > 30:
                    break
                if any(_same(n, t) for t in tail):
                    cut, misses = idx + 1, 0
                else:
                    misses += 1
                    if misses > 2:
                        break
            lines = lines[cut:]
        if out and lines:
            out.append("")
        out.extend(lines)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


class OcrError(Exception):
    pass


def _join_hyphen(a: str, b: str) -> str:
    """Перенос в конце строки: «соеди-» + «нить» → «соединить»; составное прилагательное
    «шоколадно-» + «творожного» дефис сохраняет."""
    last = re.findall(r"[\wё]+$", a[:-1].lower())
    keep = bool(last) and len(last[0]) >= 6 and last[0].endswith(("о", "е"))
    return a + b if keep else a[:-1] + b


def _layout_text(tsv: str) -> str:
    """Текст из разметки tesseract (TSV): колонки не перемешиваются, абзацы разделены
    пустой строкой, заголовок над колонками идёт первым, переносы слов склеиваются."""
    blocks: dict[int, dict] = {}
    for row in tsv.splitlines()[1:]:
        cols = row.split("\t")
        if len(cols) < 12:
            continue
        level, block, par, line = int(cols[0]), int(cols[2]), int(cols[3]), int(cols[4])
        left, top, width, height = (int(cols[k]) for k in (6, 7, 8, 9))
        b = blocks.setdefault(block, {"top": top, "bottom": top + height, "lines": {}})
        if level == 2:
            b["top"], b["bottom"] = top, top + height
        if level != 5:
            continue
        word, conf = cols[11].strip(), float(cols[10])
        if conf < 30:
            # Неуверенно распознанное: иконки и обрывки картинок выкидываем, а слова
            # (часто это заголовок затейливым шрифтом) оставляем — их легко поправить
            word = re.sub(r"^[^\wё]+|[^\wё]+$", "", word)
            if len(re.sub(r"[^а-яёa-z]", "", word.lower())) < 4:
                continue
        if not word:
            continue
        b["lines"].setdefault((par, line), []).append(word)

    # Порядок блоков — как у tesseract (он идёт по колонкам), но блоки, которые целиком
    # выше всех остальных (заголовок над колонками), — вперёд
    order = [k for k in blocks if blocks[k]["lines"]]
    head: list[int] = []
    rest = sorted(order, key=lambda k: blocks[k]["top"])
    while len(rest) > 1 and blocks[rest[0]]["bottom"] <= min(blocks[k]["top"] for k in rest[1:]):
        head.append(rest.pop(0))
    order = head + [k for k in order if k not in head]

    out: list[str] = []
    for k in order:
        pars: dict[int, list[str]] = {}
        for (par, _line), words in sorted(blocks[k]["lines"].items()):
            pars.setdefault(par, []).append(" ".join(words))
        text_lines = [line for p in pars.values() for line in p]
        # Номер страницы и прочие одиночные числа
        if all(re.fullmatch(r"[\d\s.,]+", line) for line in text_lines):
            continue
        for par_lines in pars.values():
            merged: list[str] = []
            for line in par_lines:
                # «соеди-» + «нить» → «соединить»
                if merged and merged[-1].endswith("-") and line[:1].islower():
                    merged[-1] = _join_hyphen(merged[-1], line)
                else:
                    merged.append(line)
            out.extend(merged)
            out.append("")
    return "\n".join(out)


def ocr(data: bytes) -> str:
    """Скриншот или фото страницы → текст. Tesseract (русский + английский) с разбором
    макета страницы: две колонки (ингредиенты | шаги) не смешиваются. Тёмную тему инвертируем."""
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
    # Мелкий текст увеличиваем: скриншот телефона ~1000 px в ширину, а tesseract
    # лучше всего читает строки высотой 30–40 px
    if img.width < 2400:
        k = min(3.0, 2400 / max(img.width, 1))
        img = img.resize((int(img.width * k), int(img.height * k)), Image.Resampling.LANCZOS)
    with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
        img.save(tmp.name)
        try:
            res = subprocess.run(
                [
                    "tesseract", tmp.name, "-", "-l", "rus+eng", "--psm", "3",
                    "-c", "tessedit_create_tsv=1", "-c", "tessedit_create_txt=0",
                ],
                capture_output=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            raise OcrError("Картинка распознавалась слишком долго")
    if res.returncode != 0:
        err = res.stderr.decode("utf-8", "replace").strip().splitlines()
        raise OcrError("Не удалось распознать текст" + (f": {err[-1][:200]}" if err else ""))
    text = fix_ocr(_layout_text(res.stdout.decode("utf-8", "replace")))
    # Убираем мусор распознавания: одиночные символы, пустые строки подряд
    lines = [line.rstrip() for line in text.split("\n")]
    lines = [line for line in lines if len(line.strip()) > 1 or not line.strip()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
