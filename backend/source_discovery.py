"""Infer a bounded, verified recipe source configuration from a public URL."""
from __future__ import annotations

import heapq
import ipaddress
import re
import time
import urllib.error
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

from app import importer
from collect_recipes import Client, CollectionError, MAX_SITEMAP_BYTES, archive_recipe, canonical_slash_redirect, sitemap_locations
from recipe_sources import public_source_url, sources_from_data
from tls_config import configure_tls

MAX_FETCHES = 24
MAX_SECONDS = 60
MAX_LINKS = 1000
_RECIPE_HINT = re.compile(r"recip|recept|rezept|рецепт|кулинар|cook", re.I)
_SKIP_PATH = re.compile(r"\.(?:jpg|jpeg|png|gif|webp|svg|pdf|zip|mp4|css|js)$|/(?:login|logout|cart|checkout|account|privacy|contacts?)(?:/|$)", re.I)


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.href: str | None = None
        self.label = ""

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            self.href = dict(attrs).get("href")
            self.label = ""

    def handle_data(self, data):
        if self.href and len(self.label) < 200:
            self.label += data[:200]

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self.href:
            if len(self.links) < MAX_LINKS:
                self.links.append((self.href, self.label))
            self.href = None


def _public_host(host: str) -> bool:
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return True


def _same_site(url: str, host: str) -> str | None:
    parsed = public_source_url(url)
    if (parsed is None or parsed.hostname != host or parsed.scheme != "https" or
            parsed.fragment or len(url) > 2000 or _SKIP_PATH.search(parsed.path)):
        return None
    return urlunsplit(("https", host, parsed.path or "/", parsed.query, ""))


def _initial_redirect(error: CollectionError, current: str) -> str | None:
    """Follow only a proven canonical slash or bare/www redirect on the entered site."""
    cause: BaseException | None = error
    seen = set()
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        if isinstance(cause, urllib.error.HTTPError) and cause.code in (301, 302, 303, 307, 308):
            location = cause.headers.get("Location") if cause.headers else None
            if not location:
                return None
            target = urljoin(cause.url, location)
            parsed = public_source_url(target)
            source = urlsplit(current)
            if (parsed is None or parsed.scheme != "https" or parsed.fragment or
                    parsed.hostname.removeprefix("www.") != source.hostname.removeprefix("www.") or
                    not _public_host(parsed.hostname)):
                return None
            if cause.url != current:
                # A robots.txt redirect may establish the same site's canonical www alias.
                if urlsplit(cause.url).path != "/robots.txt" or parsed.hostname == source.hostname:
                    return None
                target = urlunsplit(("https", parsed.hostname, source.path or "/", source.query, ""))
            return _same_site(target, parsed.hostname)
        cause = cause.__cause__ or cause.__context__
    return None


def _recipe_pattern(paths: list[str], catalog_paths: set[str]) -> str:
    patterns = []
    root_slugs = sum(path.count("/") == 1 and "-" in path for path in paths)
    for path in paths:
        parts = path.strip("/").split("/")
        last = parts[-1]
        if last.isdecimal():
            leaf = r"\d+"
        elif re.match(r"(?:recipe|recept|rezept)[-_]", last, re.I):
            prefix = re.match(r"(?:recipe|recept|rezept)[-_]", last, re.I).group()
            leaf = re.escape(prefix) + r"[^/]+"
        elif len(parts) == 1:
            # Root-level slugs need evidence of a multiword shape, not /.*.
            leaf = r"[^/]+-[^/]+" if "-" in last and root_slugs >= 2 else re.escape(last)
        else:
            leaf = r"[^/]+"
        parents = [re.escape(part) for part in parts[:-1]]
        if len(parents) >= 2 and re.fullmatch(r"\d{4}", parts[0]) and re.fullmatch(r"\d{1,2}", parts[1]):
            parents[:2] = [r"\d{4}", r"\d{1,2}"]
        pattern = "/" + "/".join([*parents, leaf])
        if pattern not in patterns:
            patterns.append(pattern)
    combined = "(?:" + "|".join(patterns) + ")"
    excluded = sorted(path.rstrip("/") for path in catalog_paths if path.rstrip("/") and re.fullmatch(combined, path.rstrip("/")))
    return ("(?!(?:" + "|".join(re.escape(path) for path in excluded) + ")$)" if excluded else "") + combined


def _catalog_pattern(paths: set[str], recipe_paths: list[str]) -> str:
    broad = set()
    for path in paths:
        parts = path.strip("/").split("/")
        if parts and _RECIPE_HINT.search(parts[0]) and any(recipe.startswith("/" + parts[0] + "/") for recipe in recipe_paths):
            broad.add("/" + re.escape(parts[0]) + r"(?:/[^?#]*)?")
        if re.search(r"\.xml(?:\.gz)?$", path, re.I):
            directory = path.rsplit("/", 1)[0]
            # Sitemap indexes often split a site across numbered sibling files.
            if directory:
                broad.add(re.escape(directory) + r"/[^/]+\.xml(?:\.gz)?")
    patterns = broad | {re.escape(path) for path in paths if not any(re.fullmatch(pattern, path) for pattern in broad)}
    return "(?:" + "|".join(sorted(patterns)) + ")"


def detect_source(url: str, *, client=None) -> dict:
    """Find real recipes before generating settings; never persist partial guesses."""
    entered = public_source_url(url)
    if entered is None or entered.scheme != "https" or entered.fragment or not _public_host(entered.hostname):
        raise CollectionError("Укажите публичную HTTPS-ссылку на сайт или каталог рецептов")
    host = entered.hostname.encode("idna").decode("ascii")
    hosts = {host}
    first = urlunsplit(("https", host, entered.path or "/", entered.query, ""))
    if client is None:
        context, _ = configure_tls()
        client = Client(0.5, 0, ssl_context=context, adaptive_delay=True, min_delay=0.25, max_delay=5)
    deadline = time.monotonic() + MAX_SECONDS
    queue: list[tuple[int, int, str]] = []
    queued: set[str] = set()
    processed: set[str] = set()
    catalogs: set[str] = set()
    parents: dict[str, str] = {}
    recipes: list[str] = []
    recipe_urls: list[str] = []
    catalog_candidates: list[str] = []
    fetches = 0
    robots_checked = False
    last_error = ""

    def enqueue(value: str, parent: str | None = None, label: str = "", priority: int = 30):
        parsed_value = public_source_url(value)
        candidate = _same_site(value, parsed_value.hostname) if parsed_value and parsed_value.hostname in hosts else None
        if candidate is not None and parsed_value.hostname != host:
            candidate = urlunsplit(("https", host, parsed_value.path or "/", parsed_value.query, ""))
        if candidate is None or candidate in queued or len(queued) >= MAX_LINKS:
            return
        parsed = urlsplit(candidate)
        if priority == 30:
            # Prefer following a promising section to its recipes over visiting every category first.
            priority -= min(fetches, 20)
        if _RECIPE_HINT.search(parsed.path + " " + label):
            priority -= 20
        if re.search(r"sitemap.*\.xml(?:\.gz)?$", parsed.path, re.I):
            priority -= 10
        if recipes and parsed.path.rsplit("/", 1)[0] == recipes[0].rsplit("/", 1)[0]:
            priority -= 25
        queued.add(candidate)
        if parent:
            parents[candidate] = parent
        heapq.heappush(queue, (priority, len(queued), candidate))

    enqueue(first, priority=-100)
    while queue and fetches < MAX_FETCHES and time.monotonic() < deadline:
        _, _, current = heapq.heappop(queue)
        if current in processed:
            continue
        processed.add(current)
        fetches += 1
        try:
            requested = current
            for redirect in range(4):
                try:
                    raw, content_type, final = client.fetch(requested, MAX_SITEMAP_BYTES, "application/xml,text/xml,text/html,*/*;q=0.8")
                    break
                except CollectionError as exc:
                    target = None
                    if redirect < 3:
                        target = _initial_redirect(exc, requested) if current == first else canonical_slash_redirect(exc, requested)
                    if target is None or fetches >= MAX_FETCHES or time.monotonic() >= deadline:
                        raise
                    requested = target
                    hosts.add(urlsplit(target).hostname)
                    fetches += 1
            if requested != current:
                if current in parents:
                    parents[requested] = parents[current]
                if current == first:
                    host = urlsplit(requested).hostname
                    first = requested
                current = requested
                queued.add(requested)
                processed.add(requested)
        except CollectionError as exc:
            if current == first:
                raise CollectionError("Не удалось проверить сайт: " + str(exc)) from exc
            last_error = str(exc)
            if host in getattr(client, "blocked", set()):
                raise CollectionError("Сайт запретил автоматические запросы: " + last_error) from exc
            continue
        final = _same_site(final, host)
        if final is None:
            raise CollectionError("Сайт перенаправил проверку на другой адрес. Укажите конечную HTTPS-ссылку")
        if final != current:
            # Client.fetch can already have resolved a same-site slash redirect internally.
            if current in parents:
                parents[final] = parents[current]
            if current == first:
                first = final
            current = final
            queued.add(final)
            processed.add(final)
        path = urlsplit(final).path
        if not robots_checked:
            robots_checked = True
            enqueue(f"https://{host}/robots.txt", priority=-80)
            enqueue(f"https://{host}/sitemap.xml", priority=15)
            enqueue(f"https://{host}/sitemap_index.xml", priority=15)
            if path != "/":
                enqueue(f"https://{host}/", priority=20)
        if path == "/robots.txt":
            for line in importer._decode(raw, content_type).splitlines():
                field, separator, value = line.partition(":")
                if separator and field.strip().lower() == "sitemap":
                    enqueue(urljoin(final, value.strip()), priority=-60)
            continue
        head = raw.lstrip(b"\xef\xbb\xbf \t\r\n")[:512].lower()
        is_xml = head.startswith(b"<?xml") or re.match(rb"<(?:[\w-]+:)?(?:urlset|sitemapindex)\b", head) or raw.startswith(b"\x1f\x8b")
        if is_xml:
            try:
                kind, locations = sitemap_locations(raw)
            except CollectionError as exc:
                last_error = str(exc)
                continue
            catalogs.add(path)
            catalog_candidates.append(current)
            for location in locations[:MAX_LINKS]:
                enqueue(urljoin(final, location), current, priority=0 if kind == "sitemapindex" else 10)
            continue
        page = importer._decode(raw, content_type)
        try:
            recipe = importer.import_from_html(page, final)
            archive_recipe(recipe, False)
        except (importer.ImportError_, CollectionError, ValueError, TypeError):
            catalogs.add(path)
            catalog_candidates.append(current)
            links = _Links()
            links.feed(page)
            for location, label in links.links:
                enqueue(urljoin(final, location.split("#", 1)[0]), current, label)
        else:
            parsed = urlsplit(final)
            if parsed.query and any(not key.startswith("utm_") and key not in ("gclid", "fbclid") for key in (item.partition("=")[0] for item in parsed.query.split("&"))):
                last_error = "Ссылки на рецепты только с параметрами запроса пока не поддерживаются"
                continue
            recipes.append(path.rstrip("/"))
            recipe_urls.append(final)
            if len(recipes) >= 2:
                break

    if not recipes:
        detail = " " + last_error if last_error else ""
        raise CollectionError("Не удалось автоматически найти полноценный рецепт с ингредиентами и шагами. Укажите ссылку на раздел рецептов или задайте настройки вручную. Сайту может требоваться отдельный парсер." + detail)
    # Select a catalog that actually linked to a verified recipe, including sitemap ancestors.
    catalog = None
    for recipe_url in recipe_urls:
        chain = []
        current = recipe_url
        while current in parents:
            current = parents[current]
            if current in catalog_candidates:
                chain.append(current)
        if chain:
            catalog = chain[0]
            break
    if catalog is None:
        raise CollectionError("Рецепт читается, но каталог со ссылками на рецепты не найден. Укажите адрес раздела рецептов")
    definition = {"canonical_host": host, "hosts": sorted(hosts), "catalog_url": catalog,
                  "recipe_pattern": _recipe_pattern(recipes, catalogs),
                  "catalog_pattern": _catalog_pattern(catalogs, recipes),
                  "recipe_trailing_slash": urlsplit(recipe_urls[0]).path.endswith("/")}
    if len(definition["recipe_pattern"]) > 1000 or len(definition["catalog_pattern"]) > 1000:
        raise CollectionError("Структура сайта слишком неоднородна. Укажите ссылку на конкретный раздел рецептов")
    sources_from_data({"source": definition})
    return definition
