"""Collect recipe pages into a MyRecipes ZIP or directly into a running service."""
from __future__ import annotations

import argparse
import getpass
import gzip
import hashlib
import io
import json
import math
import re
import ssl
import sys
import time
import warnings as warning_control
import urllib.error
import xml.etree.ElementTree as ET
import zipfile
import zlib
from collections import deque
from collections import Counter
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from html.parser import HTMLParser
from typing import Callable, Iterator
from urllib.parse import parse_qs, parse_qsl, quote, unquote, urlencode, urljoin, urlsplit, urlunsplit

from app import importer
from recipe_api import APIError, RecipeAPI
from tls_config import TLSConfigurationError, configure_tls
from recipe_sources import SourceConfigError, Sources, load_sources, normalize_recipe_url, public_source_url
from request_pacing import AdaptivePacer, retry_after_seconds

USER_AGENT = "MyRecipes-Collector/1.0"
MAX_SITEMAP_BYTES = 16 * 1024 * 1024
MAX_XML_BYTES = 32 * 1024 * 1024
MAX_ARCHIVE_BYTES = 1900 * 1024 * 1024
MAX_MANIFEST_BYTES = 100 * 1024 * 1024
MAX_REPORT_ENTRIES = 500


class CollectionError(Exception):
    """An actionable collection error that is safe to include in the report."""


def recipe_url(url: str, sources: Sources | None = None) -> str | None:
    return normalize_recipe_url(url, sources if sources is not None else load_sources())


def http_status(error: BaseException) -> int | None:
    """The existing downloader wraps HTTPError in a user-facing import error."""
    cause = error.__context__
    return cause.code if isinstance(cause, urllib.error.HTTPError) else None


def canonical_slash_redirect(error: BaseException, current: str) -> str | None:
    """Accept only an HTTPS trailing-slash change that preserves page identity."""
    source = public_source_url(current)
    if source is None or source.scheme != "https":
        return None
    cause: BaseException | None = error
    seen = set()
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        if isinstance(cause, urllib.error.HTTPError) and cause.code in (301, 302, 303, 307, 308):
            location = cause.headers.get("Location") if cause.headers else None
            if not location or cause.url != current:
                return None
            target = urljoin(current, location)
            parsed = public_source_url(target)
            if (parsed is None or parsed.scheme != "https" or parsed.fragment or
                    parsed.hostname != source.hostname or parsed.query != source.query or parsed.path == source.path or
                    parsed.path.rstrip("/") != source.path.rstrip("/")):
                return None
            return target
        cause = cause.__cause__ or cause.__context__
    return None


class RobotsRules:
    """Match sitemap hosts' robots rules, including wildcards and longest-match priority."""

    def __init__(self, lines: list[str]):
        self.sitemaps = [value.strip() for line in lines
                         for field, separator, value in [line.split("#", 1)[0].partition(":")]
                         if separator and field.strip().lower() == "sitemap" and value.strip()]
        groups: list[dict] = []
        group: dict = {"agents": [], "rules": [], "delay": 0.0}
        has_directives = False
        for line in lines:
            field, separator, value = line.split("#", 1)[0].partition(":")
            if not separator:
                continue
            field, value = field.strip().lower(), value.strip()
            if field == "user-agent":
                if has_directives:
                    groups.append(group)
                    group = {"agents": [], "rules": [], "delay": 0.0}
                    has_directives = False
                group["agents"].append(value.lower())
            elif group["agents"]:
                has_directives = True
                if field in ("allow", "disallow") and value:
                    group["rules"].append((value, field == "allow"))
                elif field in ("crawl-delay", "request-rate"):
                    try:
                        if field == "request-rate":
                            count, seconds = value.split("/", 1)
                            delay = float(seconds) / float(count)
                        else:
                            delay = float(value)
                        if math.isfinite(delay) and delay >= 0:
                            group["delay"] = max(group["delay"], delay)
                    except (ValueError, ZeroDivisionError):
                        raise CollectionError("Invalid robots.txt request timing rule")
        groups.append(group)
        agent = USER_AGENT.lower().split("/", 1)[0]
        priorities = [max((len(name) for name in item["agents"] if name != "*" and name in agent), default=0)
                      for item in groups]
        best = max(priorities, default=0)
        selected = [item for item, priority in zip(groups, priorities)
                    if priority == best and (best > 0 or "*" in item["agents"])]
        self.rules = [rule for item in selected for rule in item["rules"]]
        self.delay = max((item["delay"] for item in selected), default=0.0)

    def can_fetch(self, url: str) -> bool:
        parsed = urlsplit(url)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        path = quote(path, safe="/%?=&:@!$'()*+,;~-._")
        matches = []
        for pattern, allowed in self.rules:
            pattern = quote(pattern, safe="/%?=&:@!$'()*+,;~-._")
            terminal = pattern.endswith("$")
            pattern = pattern[:-1] if terminal else pattern
            expression = "^" + re.escape(pattern).replace(r"\*", ".*") + ("$" if terminal else "")
            if re.search(expression, path):
                matches.append((len(pattern.replace("*", "")), allowed))
        return max(matches, default=(0, True))[1]


class Client:
    def __init__(self, delay: float, retries: int, ssl_context: ssl.SSLContext | None = None, *,
                 adaptive_delay: bool = False, min_delay: float = 0.25, max_delay: float = 10):
        self.delay = delay
        self.retries = retries
        self.last_request = 0.0
        self.robots: dict[str, RobotsRules] = {}
        self.blocked: set[str] = set()
        self.host_delays: dict[str, float] = {}
        self.ssl_context = ssl_context
        self.pacer = AdaptivePacer(delay, min_delay, max_delay) if adaptive_delay else None

    def pacing_summary(self) -> dict:
        return self.pacer.summary() if self.pacer is not None else {}

    @staticmethod
    def _log_pause(host: str, before: float, after: float) -> None:
        if abs(after - before) >= 0.1:
            print(f"Pacing {host}: {before:.2f}s -> {after:.2f}s", file=sys.stderr)

    def request(self, url: str, limit: int, accept: str, *, user_agent: str = USER_AGENT,
                allow_redirects: bool = False) -> tuple[bytes, str, str]:
        host = urlsplit(url).netloc
        if host in self.blocked:
            raise CollectionError(f"Requests to {host} stopped after HTTP 401, 403 or 429")
        for attempt in range(self.retries + 1):
            if self.pacer is None:
                pause = max(self.delay, self.host_delays.get(host, 0))
                time.sleep(max(0, self.last_request + pause - time.monotonic()))
                started = time.monotonic()
            else:
                started = self.pacer.start(host, self.host_delays.get(host, 0))
            try:
                self.last_request = started
                result = importer.fetch(url, limit, accept, user_agent=user_agent, allow_redirects=allow_redirects,
                                        ssl_context=self.ssl_context)
                if self.pacer is not None:
                    self._log_pause(host, *self.pacer.success(host, started))
                return result
            except importer.ImportError_ as exc:
                cause = exc.__context__
                if isinstance(cause, urllib.error.URLError) and isinstance(cause.reason, ssl.SSLCertVerificationError):
                    raise CollectionError(
                        f"{url}: TLS certificate verification failed. Configure trusted CA certificates "
                        "for this Python runtime (SSL_CERT_FILE); do not disable certificate verification."
                    ) from exc
                status = http_status(exc)
                if status is not None and 300 <= status < 400:
                    raise CollectionError(f"{url}: HTTP redirect refused; use the final URL directly") from exc
                retry_after = None
                if status == 429 and isinstance(cause, urllib.error.HTTPError):
                    retry_after = retry_after_seconds(cause.headers.get("Retry-After") if cause.headers else None)
                recoverable = status is None or status >= 500 or status == 429
                if self.pacer is not None and recoverable:
                    self._log_pause(host, *self.pacer.failure(host, retry_after=retry_after if retry_after is not None and retry_after <= 60 else None))
                adaptive_retry = (self.pacer is not None and status == 429 and attempt < self.retries and
                                  (retry_after is None or retry_after <= 60))
                if status in (401, 403) or (status == 429 and not adaptive_retry):
                    self.blocked.add(host)
                if status == 429 and retry_after is not None and retry_after > 60:
                    raise CollectionError(f"{url}: HTTP 429 requires a wait longer than 60 seconds; requests to this host stopped") from exc
                if attempt == self.retries or (status is not None and status < 500 and not adaptive_retry):
                    raise CollectionError(f"{url}: {exc}") from exc
                if self.pacer is None:
                    time.sleep(min(2 ** attempt, 8))
        raise AssertionError("Retry loop exhausted")

    def fetch(self, url: str, limit: int, accept: str = "text/html,*/*;q=0.8") -> tuple[bytes, str, str]:
        parsed = urlsplit(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self.robots:
            robots_url = origin + "/robots.txt"
            try:
                data, ctype, _ = self.request(robots_url, 512 * 1024, "text/plain")
                rules = RobotsRules(importer._decode(data, ctype).splitlines())
            except CollectionError as exc:
                if exc.__cause__ is None or http_status(exc.__cause__) != 404:
                    raise CollectionError(f"Cannot check robots.txt for {origin}: {exc}") from exc
                rules = RobotsRules([])
            self.robots[origin] = rules
            self.host_delays[parsed.netloc] = rules.delay
        current = url
        for redirect in range(4):
            if not self.robots[origin].can_fetch(current):
                raise CollectionError(f"robots.txt disallows {current}")
            try:
                return self.request(current, limit, accept)
            except CollectionError as exc:
                target = canonical_slash_redirect(exc, current) if redirect < 3 else None
                if target is None:
                    raise
                current = target
        raise AssertionError("Redirect loop exhausted")

    def fetch_cover(self, url: str) -> tuple[bytes, str, str]:
        """Download an explicit cover URL using the interface importer's behavior."""
        return self.request(url, importer.MAX_IMAGE_BYTES, "image/*", user_agent=importer.USER_AGENT,
                            allow_redirects=True)


def unpack_catalog(data: bytes) -> bytes:
    if data.startswith(b"\x1f\x8b"):
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
                data = stream.read(MAX_XML_BYTES + 1)
        except (OSError, EOFError, zlib.error) as exc:
            raise CollectionError("Invalid compressed sitemap") from exc
    if len(data) > MAX_XML_BYTES:
        raise CollectionError("Sitemap exceeds the XML size limit")
    return data


def sitemap_locations(data: bytes) -> tuple[str, list[str]]:
    data = unpack_catalog(data)
    # Sitemaps do not need DTDs or entity declarations.
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise CollectionError("Sitemap contains unsupported XML declarations")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise CollectionError("Invalid sitemap XML") from exc
    kind = root.tag.rsplit("}", 1)[-1]
    if kind not in ("sitemapindex", "urlset"):
        raise CollectionError("Expected a sitemapindex or urlset")
    locations = [node.text.strip() for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "loc" and node.text]
    return kind, locations


class CatalogLinks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.entries: list[tuple[str, str]] = []
        self._href: str | None = None
        self._label: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)
                self._href = href
                self._label = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._label.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href:
            self.entries.append((self._href, " ".join(" ".join(self._label).split())[:200]))
            self._href = None
            self._label = []


def discover(site: str, client: Client, sources: Sources | None = None, *,
             max_catalog_pages: int | None = None, category_scope: bool = False,
             on_category: Callable[[dict], None] | None = None,
             on_recipe: Callable[[dict], None] | None = None,
             progress_callback: Callable[[dict], None] | None = None) -> Iterator[str]:
    """Walk a source until exhausted, keeping an explicit distinction from a partial scan."""
    sources = sources if sources is not None else load_sources()
    source = sources[site]
    pending = deque([(source.catalog_url, None, "", False, False)])
    queued = {source.catalog_url}
    visited: set[str] = set()
    emitted: set[str] = set()
    catalog_pages = 0
    failed_pages = 0
    roots: set[str] = set()
    start_path = urlsplit(source.catalog_url).path.rstrip("/") or "/"
    fallback_added = False
    category_emitted: set[str] = set()

    def progress(complete: bool = False, stop_reason: str | None = None) -> None:
        if progress_callback is not None:
            progress_callback({"catalog_pages": catalog_pages, "discovered": len(emitted),
                               "failed_catalog_pages": failed_pages, "complete": complete,
                               "stop_reason": stop_reason})

    def same_site(value: str) -> str | None:
        parsed = public_source_url(value)
        if parsed is None or parsed.hostname not in source.hosts or parsed.fragment:
            return None
        return urlunsplit(("https", source.canonical_host, parsed.path or "/", parsed.query, ""))

    def is_xml_path(path: str) -> bool:
        return bool(re.search(r"\.xml(?:\.gz)?$", path, re.I))

    def in_scope(value: str) -> bool:
        path = urlsplit(value).path.rstrip("/") or "/"
        return not category_scope or path == start_path or path.startswith(start_path.rstrip("/") + "/")

    def enqueue(value: str, parent: str | None, label: str = "", *, optional: bool = False,
                dynamic_map: bool = False) -> None:
        canonical = same_site(value)
        if canonical is None or canonical in queued:
            return
        parsed = urlsplit(canonical)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        rules = getattr(client, "robots", {}).get(origin)
        if rules is not None and not rules.can_fetch(canonical):
            return
        if category_scope and (dynamic_map or is_xml_path(parsed.path) or not in_scope(canonical)):
            return
        queued.add(canonical)
        pending.append((canonical, parent, label, optional, dynamic_map))

    def is_pagination(value: str, label: str) -> bool:
        parsed = urlsplit(value)
        return (bool(set(parse_qs(parsed.query)) & {"page", "p", "offset", "start"}) or
                bool(re.search(r"/(?:page|pages)/\d+/?$", parsed.path, re.I)) or
                bool(re.fullmatch(r"(?:\d+|next|previous|далее|назад|ещ[её]|показать больше|[›»‹«→←])", label, re.I)))

    def category_url(value: str) -> str:
        parsed = urlsplit(value)
        path = re.sub(r"/(?:page|pages)/\d+/?$", "", parsed.path, flags=re.I)
        query = urlencode([(key, item) for key, item in parse_qsl(parsed.query, keep_blank_values=True)
                           if key not in {"page", "p", "offset", "start"}])
        return urlunsplit((parsed.scheme, parsed.netloc, path, query, ""))

    progress()
    while pending:
        if max_catalog_pages is not None and max_catalog_pages > 0 and catalog_pages >= max_catalog_pages:
            progress(False, "catalog_page_limit")
            return
        url, parent, label, optional, dynamic_map = pending.popleft()
        if url in visited:
            continue
        visited.add(url)
        try:
            data, ctype, final_url = client.fetch(url, MAX_SITEMAP_BYTES, "application/xml,text/xml,text/html,*/*;q=0.8")
        except CollectionError as exc:
            if not optional:
                failed_pages += 1
                progress(False, "catalog_error")
                raise
            if source.canonical_host in getattr(client, "blocked", set()):
                raise
            continue
        canonical_final = same_site(final_url)
        if canonical_final is None:
            raise CollectionError(f"Catalog redirected outside the configured source: {source.canonical_host}")
        final_url = canonical_final
        visited.add(final_url)
        path = urlsplit(final_url).path
        if category_scope and not in_scope(final_url):
            raise CollectionError("Catalog redirected outside the selected category")
        if path == "/robots.txt":
            for line in importer._decode(data, ctype).splitlines():
                field, separator, value = line.partition(":")
                if separator and field.strip().lower() == "sitemap":
                    enqueue(urljoin(final_url, value.strip()), None, optional=True, dynamic_map=True)
            continue
        catalog_pages += 1
        data = unpack_catalog(data)
        head = data.lstrip(b"\xef\xbb\xbf \t\r\n")[:512].lower()
        xml_start = head.startswith(b"<?xml") or re.match(rb"<(?:[\w-]+:)?(?:urlset|sitemapindex)\b", head)
        html_start = re.match(rb"(?:<!doctype\s+html|<html\b)", head)
        kind = None
        add_fallback = False
        if html_start or ("text/html" in ctype.lower() and not xml_start):
            if optional and dynamic_map:
                continue
            if not (source.accepts_catalog(final_url) or in_scope(final_url) and
                    (category_scope or any(path.rstrip("/") == root or path.startswith(root + "/") for root in roots))):
                raise CollectionError(f"Catalog redirected outside the configured source: {source.canonical_host}")
            parser = CatalogLinks()
            parser.feed(importer._decode(data, ctype))
            locations = parser.links
            labels = dict(parser.entries)
            # A homepage can expose only a small 'new recipes' widget. Learn its
            # recipe section before deciding which category links to follow.
            for location in locations:
                normalized = recipe_url(urljoin(final_url, location), sources)
                if normalized:
                    parts = urlsplit(normalized).path.strip("/").split("/")
                    if len(parts) >= 2:
                        roots.add("/" + parts[0])
            if on_category is not None and path != "/" and not is_xml_path(path) and not is_pagination(final_url, label):
                if final_url not in category_emitted:
                    category_emitted.add(final_url)
                    title = label or unquote(path.rstrip("/").rsplit("/", 1)[-1]).replace("-", " ")
                    on_category({"url": final_url, "title": title[:200], "parent_url": parent})
            if not category_scope and not fallback_added and start_path == "/":
                fallback_added = True
                add_fallback = True
        else:
            if not (source.accepts_catalog(final_url) or dynamic_map):
                raise CollectionError(f"Catalog redirected outside the configured source: {source.canonical_host}")
            try:
                kind, locations = sitemap_locations(data)
            except CollectionError:
                if optional:
                    continue
                raise
            labels = {}
        for location in locations:
            absolute = urljoin(final_url, location)
            normalized = recipe_url(absolute, sources)
            if normalized and urlsplit(normalized).hostname == source.canonical_host:
                if on_recipe is not None:
                    on_recipe({"url": normalized, "category_url": category_url(final_url) if kind is None else None})
                if normalized not in emitted:
                    emitted.add(normalized)
                    progress()
                    yield normalized
            else:
                candidate = same_site(absolute)
                if candidate is None:
                    continue
                candidate_path = urlsplit(candidate).path
                learned_catalog = (in_scope(candidate) and any(candidate_path.rstrip("/") == root or
                                   candidate_path.startswith(root + "/") for root in roots))
                if (source.accepts_catalog(candidate) or learned_catalog or category_scope and in_scope(candidate) or
                        dynamic_map and kind == "sitemapindex" and is_xml_path(candidate_path)):
                    enqueue(candidate, category_url(final_url) if kind is None else None, labels.get(location, ""),
                            dynamic_map=dynamic_map and is_xml_path(candidate_path))
        if add_fallback:
            origin = f"https://{source.canonical_host}"
            rules = getattr(client, "robots", {}).get(origin)
            if rules is not None:
                for sitemap in getattr(rules, "sitemaps", ()):
                    enqueue(sitemap, None, optional=True, dynamic_map=True)
            else:
                enqueue(origin + "/robots.txt", None, optional=True)
            # Prefer links actually present on a site to probing conventional
            # filenames; a forbidden optional probe must not block a valid catalog.
            if all(item[0].endswith("/robots.txt") for item in pending):
                enqueue(origin + "/sitemap.xml", None, optional=True, dynamic_map=True)
                enqueue(origin + "/sitemap_index.xml", None, optional=True, dynamic_map=True)
        progress()
    if not emitted:
        progress(False, "no_recipes")
        raise CollectionError(f"No recipe links found for {source.canonical_host}; check source patterns and catalog URL")
    progress(failed_pages == 0, "exhausted" if failed_pages == 0 else "catalog_error")


def interleave(sources: list[Iterator[str]], errors: list[dict]) -> Iterator[str]:
    """Alternate sources so a small limit still includes both sites."""
    pending = deque(enumerate(sources))
    while pending:
        index, source = pending.popleft()
        try:
            yield next(source)
        except StopIteration:
            continue
        except CollectionError as exc:
            errors.append({"stage": "discovery", "source": index, "error": str(exc)})
            print(f"Discovery failed: {exc}", file=sys.stderr)
            continue
        pending.append((index, source))


def archive_recipe(recipe: importer.ImportedRecipe, public: bool) -> tuple[dict, list[str]]:
    """Match RecipeIn limits without importing application configuration or a database."""
    warnings = []
    if not recipe.title.strip() or not recipe.ingredients or not recipe.steps:
        raise CollectionError("Recipe must have a title, ingredients and instructions")
    if len(recipe.title) > 200 or len(recipe.source_url) > 500 or len(recipe.ingredients) > 200 or len(recipe.steps) > 200:
        raise CollectionError("Recipe exceeds the service field limits")
    for value in (recipe.prep_minutes, recipe.cook_minutes):
        if value is not None and not 0 <= value <= 10_000:
            raise CollectionError("Recipe duration is outside the service limits")
    if recipe.servings is None:
        warnings.append("Missing servings; using the service default of 2")
    if recipe.servings is not None and not 1 <= recipe.servings <= 100:
        raise CollectionError("Recipe servings are outside the service limits")
    ingredients = []
    for item in recipe.ingredients:
        if not item.product.strip():
            raise CollectionError("Ingredient has no product name")
        if item.amount is not None and (not math.isfinite(item.amount) or not 0 <= item.amount <= 1_000_000):
            raise CollectionError("Ingredient amount is outside the service limits")
        if len(item.group) > 100:
            raise CollectionError("Ingredient group exceeds the service limits")
        if item.amount is None and item.unit != "по вкусу":
            warnings.append(f"Check ingredient quantity: {item.product}")
        ingredients.append(vars(item).copy())
    if any(not step.strip() or len(step) > 10_000 for step in recipe.steps):
        raise CollectionError("Instruction is empty or exceeds the service limits")
    return {
        "title": recipe.title,
        "description": recipe.description,
        "category": recipe.category[:100] or None,
        "servings": recipe.servings or 2,
        "prep_minutes": recipe.prep_minutes,
        "cook_minutes": recipe.cook_minutes,
        "difficulty": None,
        "is_public": public,
        "source_url": recipe.source_url,
        "tags": recipe.tags,
        "ingredients": ingredients,
        "steps": [{"text": step, "timer_minutes": None} for step in recipe.steps],
        "image": None,
        "photos": [],
    }, warnings


def selected_urls(args: argparse.Namespace) -> list[str]:
    """Validate explicit source filters in both collection and cover repair modes."""
    sources = getattr(args, "source_config", None) or load_sources()
    explicit = list(args.url)
    if args.urls_file:
        try:
            lines = args.urls_file.read_text(encoding="utf-8").splitlines()
        except UnicodeError:
            raise CollectionError("The recipe URL file must use UTF-8 encoding") from None
        explicit.extend(line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#"))
    urls = []
    for url in explicit:
        normalized = recipe_url(url, sources)
        if normalized is None:
            raise CollectionError("Expected a recipe URL matching the configured source hosts and recipe patterns")
        urls.append(normalized)
    if args.urls_file and not urls and not args.site:
        raise CollectionError("URL file contains no recipe URLs; use --site to request automatic discovery")
    return urls


def download_image(client: Client, url: str) -> tuple[bytes, str]:
    image, content_type, _ = client.fetch_cover(url)
    if not content_type.lower().startswith("image/") or not image:
        raise CollectionError("Image response is not an image")
    return image, content_type


def attach_step_images(imported: importer.ImportedRecipe, recipe_id: int, client: Client, api: RecipeAPI,
                       warnings: list[str], on_uploaded: Callable[[int], None]) -> None:
    """Match the complete current step sequence before attaching photos to existing IDs."""
    if not any(imported.step_images):
        return
    current = api.recipe_steps(recipe_id)
    normalize = lambda text: " ".join(importer.clean_text(text).split())
    if (len(current) != len(imported.steps) or
            any(normalize(step.text) != normalize(text) for step, text in zip(current, imported.steps))):
        warnings.append("Step photos skipped: current step text or order differs from the source")
        return
    for index, step in enumerate(current):
        image_url = imported.step_images[index] if index < len(imported.step_images) else None
        if step.has_image or not image_url:
            continue
        try:
            image, content_type = download_image(client, image_url)
            api.upload_step_image(recipe_id, step.id, image, content_type)
            on_uploaded(index)
        except CollectionError as exc:
            warnings.append(f"Step {index + 1} photo omitted: {exc}")
        except APIError as exc:
            warnings.append(f"Step {index + 1} photo upload failed: {exc}")
            if exc.fatal:
                raise


def trim_report(report: dict) -> None:
    """Keep unlimited jobs' checkpoint size bounded while retaining aggregate counts."""
    for key in ("recipes", "errors", "warnings"):
        excess = len(report[key]) - MAX_REPORT_ENTRIES
        if excess > 0:
            del report[key][:excess]
            omitted = key + "_omitted"
            report[omitted] = report.get(omitted, 0) + excess
            report["details_truncated"] = True
        if key != "recipes":
            report[key + "_total"] = len(report[key]) + report.get(key + "_omitted", 0)
            report[key[:-1] + "_count"] = report[key + "_total"]


def backfill_images(args: argparse.Namespace, client: Client, api: RecipeAPI) -> dict:
    """Attach covers to existing owned recipes without creating recipes or changing their fields."""
    urls = set(selected_urls(args))
    sources = getattr(args, "source_config", None) or load_sources()
    hosts = {sources[site].canonical_host for site in args.site} if args.site else {source.canonical_host for source in sources.sites.values()}
    if args.report is None:
        args.report = Path("collection-report-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".json")
    report = {"created": 0, "updated_images": 0, "updated_step_images": 0, "skipped": 0, "attempted": 0, "processed": 0,
              "errors": [], "warnings": [], "recipes": [], "fatal": False, "interrupted": False, "stop_reason": None}
    page_limit = args.max_pages if args.max_pages is not None else (0 if args.limit == 0 else 500)
    with args.report.open("x", encoding="utf-8") as report_file:
        def checkpoint() -> None:
            trim_report(report)
            report_file.seek(0)
            json.dump(report, report_file, ensure_ascii=False, indent=2)
            report_file.truncate()
            report_file.flush()
            callback = getattr(args, "progress_callback", None)
            if callback is not None:
                callback(report)

        try:
            api.prepare()
            source_counts = Counter(recipe_url(recipe.source_url, sources) for recipe in api.owned_recipes if recipe.source_url)
            for recipe in api.owned_recipes:
                source = recipe_url(recipe.source_url, sources) if recipe.source_url else None
                record = {"id": recipe.id, "title": recipe.title, "source_url": source}
                if source is None or urlsplit(source).hostname not in hosts or (urls and source not in urls):
                    report["skipped"] += 1
                    continue
                if (args.limit and report["attempted"] >= args.limit) or (page_limit and report["attempted"] >= page_limit):
                    report["stop_reason"] = "limit" if args.limit and report["attempted"] >= args.limit else "attempt_limit"
                    break
                report["processed"] += 1
                wants_cover = not recipe.has_image
                wants_steps = (not args.no_step_images and
                               any(not step.has_image for step in getattr(recipe, "steps", ())))
                if not wants_cover and not wants_steps:
                    report["skipped"] += 1
                    report["recipes"].append({**record, "status": "already_has_image"})
                    continue
                if source_counts[source] > 1:
                    report["skipped"] += 1
                    report["warnings"].append({"url": source, "warning": "Multiple owned recipes share this source URL; cover repair skipped"})
                    report["recipes"].append({**record, "status": "ambiguous_source"})
                    continue
                report["attempted"] += 1
                print(f"[images {report['attempted']}/{args.limit or 'unlimited'}] Recipe {recipe.id}: {source}", file=sys.stderr)
                warnings: list[str] = []
                entry = None
                try:
                    raw, ctype, final_url = client.fetch(source, importer.MAX_PAGE_BYTES)
                    if recipe_url(final_url, sources) != source:
                        raise CollectionError("Source URL changed; cover repair skipped to preserve recipe identity")
                    imported = importer.import_from_html(importer._decode(raw, ctype), source)
                    entry = {**record, "status": "no_source_image", "step_images": 0}
                    report["recipes"].append(entry)
                    if wants_cover:
                        if not imported.image_url:
                            warnings.append("Recipe has no cover URL")
                        else:
                            try:
                                image, image_type = download_image(client, imported.image_url)
                                if api.recipe_has_cover(recipe.id):
                                    report["skipped"] += 1
                                    entry["status"] = "already_has_image"
                                else:
                                    api.upload_cover(recipe.id, image, image_type)
                                    report["updated_images"] += 1
                                    entry["status"] = "updated"
                                    checkpoint()
                            except CollectionError as exc:
                                report["errors"].append({"stage": "cover", "id": recipe.id, "url": source, "error": str(exc)})
                            except APIError as exc:
                                warnings.append(f"Cover upload failed for saved recipe {recipe.id}: {exc}")
                                if exc.fatal:
                                    raise
                    if wants_steps:
                        def step_uploaded(index: int) -> None:
                            report["updated_step_images"] += 1
                            entry["step_images"] += 1
                            entry["status"] = "updated"
                            checkpoint()

                        attach_step_images(imported, recipe.id, client, api, warnings, step_uploaded)
                    if wants_steps and not any(imported.step_images):
                        warnings.append("No step photos are available in the source recipe")
                except (CollectionError, importer.ImportError_) as exc:
                    report["errors"].append({"stage": "cover", "id": recipe.id, "url": source, "error": str(exc)})
                    if entry is None:
                        report["recipes"].append({**record, "status": "failed"})
                    else:
                        entry["status"] = "failed"
                    print(f"Cover skipped: {exc}", file=sys.stderr)
                except APIError as exc:
                    report["errors"].append({"stage": "service", "id": recipe.id, "url": source, "error": str(exc)})
                    if entry is None:
                        report["recipes"].append({**record, "status": "failed"})
                    else:
                        entry["status"] = "partial" if entry["status"] == "updated" else "failed"
                    if exc.fatal:
                        report["fatal"] = True
                        break
                finally:
                    report["warnings"].extend({"url": source, "warning": warning} for warning in warnings)
                    checkpoint()
        except APIError as exc:
            report["fatal"] = True
            report["errors"].append({"stage": "service", "error": str(exc)})
        except KeyboardInterrupt:
            report["interrupted"] = True
            report["stop_reason"] = "stopped"
            raise
        finally:
            if report["stop_reason"] is None:
                report["stop_reason"] = "fatal" if report["fatal"] else "exhausted"
            checkpoint()
    return report


def collect(args: argparse.Namespace, client: Client, api: RecipeAPI | None = None) -> dict:
    urls = selected_urls(args)
    source_config = getattr(args, "source_config", None) or load_sources()
    sites = list(dict.fromkeys(source_config.canonical_name(site) for site in (args.site or ([] if urls else source_config))))
    report = {"created": 0, "duplicates": 0, "attempted": 0, "processed": 0, "step_images": 0,
              "errors": [], "warnings": [], "recipes": [], "stop_reason": None,
              "discovered": len(urls), "catalog_pages": 0, "discovery_complete": not sites,
              "cache_hits": 0, "downloaded_pages": 0}
    page_limit = args.max_pages if args.max_pages is not None else (0 if args.limit == 0 else 500)
    discovery_stats: dict[str, dict] = {}

    def discovery_progress(site: str, event: dict) -> None:
        discovery_stats[site] = event
        report["discovered"] = len(urls) + sum(value["discovered"] for value in discovery_stats.values())
        report["catalog_pages"] = sum(value["catalog_pages"] for value in discovery_stats.values())
        report["discovery_complete"] = len(discovery_stats) == len(sites) and all(value["complete"] for value in discovery_stats.values())
        callback = getattr(args, "discovery_progress_callback", None)
        if callback is not None:
            callback(event)
        checkpoint()

    def explicit_candidates() -> Iterator[str]:
        callback = getattr(args, "on_recipe", None)
        for url in urls:
            if callback is not None:
                callback({"url": url})
            yield url

    sources = ([explicit_candidates()] if urls else []) + [discover(
        site, client, source_config, max_catalog_pages=getattr(args, "max_catalog_pages", None),
        category_scope=getattr(args, "category_scope", False), on_category=getattr(args, "on_category", None),
        on_recipe=getattr(args, "on_recipe", None), progress_callback=lambda event, site=site: discovery_progress(site, event),
    ) for site in sites]
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    recipes = []
    image_bytes = 0
    image_names: set[str] = set()
    manifest_bytes = 1024
    with ExitStack() as resources:
        archive = None
        report_file = None
        if api is None:
            # Exclusive creation prevents accidentally replacing a previous collection.
            archive = resources.enter_context(zipfile.ZipFile(args.output, "x", zipfile.ZIP_DEFLATED))
        else:
            if args.report is None:
                args.report = Path("collection-report-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".json")
            report_file = resources.enter_context(args.report.open("x", encoding="utf-8"))
            report["fatal"] = False
            report["interrupted"] = False

        def checkpoint() -> None:
            trim_report(report)
            if report_file is not None:
                report_file.seek(0)
                json.dump(report, report_file, ensure_ascii=False, indent=2)
                report_file.truncate()
                report_file.flush()
            callback = getattr(args, "progress_callback", None)
            if callback is not None:
                callback(report)

        def archive_image(image: bytes) -> str:
            nonlocal image_bytes
            name = f"images/{hashlib.sha256(image).hexdigest()}.img"
            if name not in image_names:
                if image_bytes + len(image) > MAX_ARCHIVE_BYTES:
                    raise CollectionError("Image budget exceeded; use a smaller --limit or --no-images")
                archive.writestr(name, image, compress_type=zipfile.ZIP_STORED)
                image_names.add(name)
                image_bytes += len(image)
            return name

        try:
            if api is not None:
                try:
                    existing_urls, existing_titles = api.prepare()
                except APIError as exc:
                    report["fatal"] = True
                    report["stop_reason"] = "fatal"
                    report["errors"].append({"stage": "service", "error": str(exc)})
                    return report
                seen_urls.update(normalized for url in existing_urls if (normalized := recipe_url(url, source_config)))
                seen_titles.update(title.casefold() for title in existing_titles)
            candidates = iter(interleave(sources, report["errors"]))
            while (args.limit == 0 or report["created"] < args.limit) and (page_limit == 0 or report["attempted"] < page_limit):
                try:
                    url = next(candidates)
                except StopIteration:
                    report["stop_reason"] = "exhausted" if report["discovery_complete"] else "discovery_partial"
                    break
                except APIError as exc:
                    report["fatal"], report["stop_reason"] = True, "fatal"
                    report["errors"].append({"stage": "catalog", "error": str(exc)})
                    break
                report["processed"] += 1
                if url in seen_urls:
                    report["duplicates"] += 1
                    checkpoint()
                    continue
                seen_urls.add(url)
                report["attempted"] += 1
                print(f"[{report['attempted']}/{page_limit or 'unlimited'}] {url}", file=sys.stderr)
                recipe_id = None
                try:
                    loader = getattr(args, "recipe_loader", None)
                    recipe = loader(url) if loader is not None else None
                    page = None
                    if recipe is None:
                        raw, ctype, final_url = client.fetch(url, importer.MAX_PAGE_BYTES)
                        report["downloaded_pages"] += 1
                        page = importer._decode(raw, ctype)
                    else:
                        report["cache_hits"] += 1
                        final_url = recipe.source_url
                    canonical = recipe_url(final_url, source_config)
                    if canonical is None:
                        raise CollectionError("Recipe redirected outside supported recipe pages")
                    if canonical != url and canonical in seen_urls:
                        report["duplicates"] += 1
                        continue
                    seen_urls.add(canonical)
                    if recipe is None:
                        recipe = importer.import_from_html(page, canonical)
                    item, warnings = archive_recipe(recipe, args.public)
                    node = (importer.find_recipe(page) or {}) if page is not None else {}
                    author = importer.clean_text(node.get("author"))
                    if author:
                        description = item["description"] + f"\n\nSource author: {author}"
                        item["description"] = description[:5000]
                        recipe.description = item["description"]
                        if len(description) > 5000:
                            warnings.append("Source author text truncated to fit the service description limit")
                    callback = getattr(args, "recipe_callback", None)
                    if callback is not None:
                        callback(recipe)
                    title_key = item["title"].casefold()
                    if title_key in seen_titles:
                        report["duplicates"] += 1
                        checkpoint()
                        continue
                    item_bytes = 0
                    if archive is not None:
                        # Include nesting whitespace, category entries and image references.
                        item_bytes = (len(json.dumps({"recipes": [item]}, ensure_ascii=False, indent=2).encode("utf-8"))
                                      + 1024 + len(item["steps"]) * 100)
                        if manifest_bytes + item_bytes > MAX_MANIFEST_BYTES:
                            raise CollectionError("Recipe would exceed the service's 100 MiB manifest limit; use a smaller collection")
                    else:
                        recipe_id = api.create_recipe(item)
                        # Record a successful write before attempting any optional cover operation.
                        report["created"] += 1
                        report["recipes"].append({"id": recipe_id, "title": item["title"], "source_url": canonical})
                        seen_titles.add(title_key)
                        checkpoint()
                    if not args.no_images and recipe.image_url:
                        try:
                            image, image_type = download_image(client, recipe.image_url)
                            if archive is None:
                                api.upload_cover(recipe_id, image, image_type)
                            else:
                                item["image"] = archive_image(image)
                        except CollectionError as exc:
                            warnings.append(f"Cover omitted: {exc}")
                        except APIError as exc:
                            warnings.append(f"Cover upload failed for saved recipe {recipe_id}: {exc}")
                            if exc.fatal:
                                report["warnings"].extend({"url": canonical, "warning": warning} for warning in warnings)
                                raise
                    elif not args.no_images:
                        warnings.append("Recipe has no cover URL")
                    if not args.no_images and not args.no_step_images:
                        if archive is not None:
                            for index, step_image in enumerate(recipe.step_images):
                                if not step_image:
                                    continue
                                try:
                                    image, _ = download_image(client, step_image)
                                    item["steps"][index]["image"] = archive_image(image)
                                    report["step_images"] += 1
                                except CollectionError as exc:
                                    warnings.append(f"Step {index + 1} photo omitted: {exc}")
                        else:
                            def step_uploaded(index: int) -> None:
                                report["step_images"] += 1
                                saved = report["recipes"][-1]
                                saved["step_images"] = saved.get("step_images", 0) + 1
                                checkpoint()

                            try:
                                attach_step_images(recipe, recipe_id, client, api, warnings, step_uploaded)
                            except APIError:
                                report["warnings"].extend({"url": canonical, "warning": warning} for warning in warnings)
                                raise
                    if archive is not None:
                        seen_titles.add(title_key)
                        recipes.append(item)
                        manifest_bytes += item_bytes
                        report["created"] += 1
                        report["recipes"].append({"title": item["title"], "source_url": canonical})
                    report["warnings"].extend({"url": canonical, "warning": warning} for warning in warnings)
                    checkpoint()
                except APIError as exc:
                    error = {"stage": "service", "url": url, "error": str(exc)}
                    if recipe_id is not None:
                        error["saved_id"] = recipe_id
                    report["errors"].append(error)
                    print(f"Service error: {exc}", file=sys.stderr)
                    if exc.fatal:
                        report["fatal"] = True
                        break
                except (CollectionError, importer.ImportError_, ValueError, TypeError, KeyError) as exc:
                    report["errors"].append({"stage": "recipe", "url": url, "error": str(exc)})
                    print(f"Skipped: {exc}", file=sys.stderr)
            if report["stop_reason"] is None:
                report["stop_reason"] = ("fatal" if report.get("fatal") else "limit" if args.limit and report["created"] >= args.limit
                                         else "attempt_limit" if page_limit and report["attempted"] >= page_limit else "exhausted")
            if archive is not None:
                trim_report(report)
                manifest = {
                    "format": "myrecipes-backup", "version": 1,
                    "exported_at": datetime.now(timezone.utc).isoformat(),
                    "categories": [{"name": name, "sort_order": index} for index, name in
                                   enumerate(dict.fromkeys(item["category"] for item in recipes if item["category"]))],
                    "recipes": recipes,
                }
                serialized = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
                if len(serialized) > MAX_MANIFEST_BYTES:
                    raise CollectionError("Manifest exceeds the service's 100 MiB limit; use a smaller collection")
                archive.writestr("recipes.json", serialized)
                archive.writestr("collection-report.json", json.dumps(report, ensure_ascii=False, indent=2))
        except KeyboardInterrupt:
            if api is not None:
                report["interrupted"] = True
            report["stop_reason"] = "stopped"
            raise
        finally:
            if report["stop_reason"] is None:
                report["stop_reason"] = ("fatal" if report.get("fatal") else "limit" if args.limit and report["created"] >= args.limit
                                         else "attempt_limit" if page_limit and report["attempted"] >= page_limit else "exhausted")
            checkpoint()
    if args.output is not None and args.output.stat().st_size > 2 * 1024 * 1024 * 1024:
        raise CollectionError("ZIP exceeds the service's 2 GiB limit; use a smaller collection")
    return report


def parser(sources: Sources | None = None) -> argparse.ArgumentParser:
    sources = sources if sources is not None else load_sources()
    result = argparse.ArgumentParser(description=__doc__)
    result.set_defaults(source_config=sources)
    result.add_argument("--sources-file", type=Path, help="Source settings JSON (default: recipe_sources.json next to the script)")
    result.add_argument("--site", action="append", choices=sources.names, help="Repeat to select sources; defaults to all configured sources unless explicit URLs are supplied")
    result.add_argument("--url", action="append", default=[], help="A specific recipe URL; repeat for multiple pages")
    result.add_argument("--urls-file", type=Path, help="UTF-8 file with one recipe URL per line; # comments allowed")
    destination = result.add_mutually_exclusive_group(required=True)
    destination.add_argument("--output", type=Path, help="New ZIP file (existing files are never overwritten)")
    destination.add_argument("--server", help="Save directly through the API of this running service")
    result.add_argument("--login", help="Service username or email for --server; the password is prompted securely")
    result.add_argument("--report", type=Path, help="New JSON report for --server (default: timestamped collection-report file)")
    result.add_argument("--ca-bundle", type=Path, help="Trusted PEM CA bundle (default: configured Python trust or a detected system CA bundle)")
    result.add_argument("--fill-missing-images", action="store_true", help="Only add missing covers and step photos to existing owned recipes on --server; never create recipes")
    result.add_argument("--limit", type=int, default=100, help="Maximum recipes across all sources; 0 imports until exhausted (default: 100)")
    result.add_argument("--max-pages", type=int, default=None, help="Maximum recipe page attempts; 0 is unlimited (default: 500, or unlimited with --limit 0)")
    result.add_argument("--delay", type=float, default=2, help="Initial pause in seconds, or fixed pause with --fixed-delay (default: 2)")
    result.add_argument("--fixed-delay", action="store_true", help="Use a fixed pause instead of adapting it to each host")
    result.add_argument("--min-delay", type=float, default=0.25, help="Minimum adaptive pause in seconds (default: 0.25)")
    result.add_argument("--max-delay", type=float, default=10, help="Maximum adaptive pause in seconds; robots.txt may require more (default: 10)")
    result.add_argument("--retries", type=int, default=2, help="Retries for network errors and HTTP 5xx (default: 2)")
    result.add_argument("--no-images", action="store_true", help="Skip all recipe images, including covers and step photos")
    result.add_argument("--no-step-images", action="store_true", help="Skip cooking-step photos while still downloading covers")
    result.add_argument("--public", action="store_true", help="Make imported recipes visible to other service users (default: private)")
    return result


def main(argv: list[str] | None = None) -> int:
    preflight = argparse.ArgumentParser(add_help=False)
    preflight.add_argument("--sources-file", type=Path)
    selected, _ = preflight.parse_known_args(argv)
    try:
        sources = load_sources(selected.sources_file)
    except SourceConfigError as exc:
        print(f"Source configuration failed: {exc}", file=sys.stderr)
        return 1
    cli = parser(sources)
    args = cli.parse_args(argv)
    if args.max_pages is None:
        args.max_pages = 0 if args.limit == 0 else 500
    if not 0 <= args.limit <= 5000 or not 0 <= args.max_pages <= 50_000:
        cli.error("--limit must be 0..5000 and --max-pages must be 0..50000; 0 means unlimited")
    if not math.isfinite(args.delay) or args.delay < 0.25 or not 0 <= args.retries <= 5:
        cli.error("--delay must be at least 0.25 seconds and --retries must be 0..5")
    if (not all(math.isfinite(value) for value in (args.min_delay, args.max_delay)) or
            not 0.1 <= args.min_delay <= args.max_delay <= 60):
        cli.error("Adaptive bounds must satisfy 0.1 <= --min-delay <= --max-delay <= 60")
    if not args.fixed_delay and not args.min_delay <= args.delay <= args.max_delay:
        cli.error("Adaptive timing requires --min-delay <= --delay <= --max-delay")
    if args.output is not None and args.output.suffix.lower() != ".zip":
        cli.error("--output must end in .zip")
    if args.server and not args.login:
        cli.error("--login is required with --server")
    if not args.server and (args.login or args.report):
        cli.error("--login and --report require --server")
    if args.fill_missing_images and not args.server:
        cli.error("--fill-missing-images requires --server")
    if args.fill_missing_images and args.no_images:
        cli.error("--fill-missing-images cannot be combined with --no-images")
    try:
        ssl_context, tls_message = configure_tls(args.ca_bundle)
        print(tls_message, file=sys.stderr)
        api = RecipeAPI(args.server, ssl_context=ssl_context,
                        require_step_images=not args.no_images and not args.no_step_images) if args.server else None
        if api is not None:
            if args.report is not None and args.report.exists():
                raise CollectionError("Report file already exists; choose a new --report path")
            # Refuse getpass's fallback to echoed input when no secure terminal is available.
            with warning_control.catch_warnings():
                warning_control.simplefilter("error", getpass.GetPassWarning)
                try:
                    password = getpass.getpass("Service password: ")
                except (getpass.GetPassWarning, EOFError):
                    raise CollectionError("A secure terminal is required to enter the service password") from None
            try:
                api.login(args.login, password)
            finally:
                del password
        if not args.fixed_delay:
            print(f"Adaptive pacing: initial {args.delay:g}s, minimum {args.min_delay:g}s, maximum {args.max_delay:g}s per host.", file=sys.stderr)
        client = Client(args.delay, args.retries, ssl_context=ssl_context, adaptive_delay=not args.fixed_delay,
                        min_delay=args.min_delay, max_delay=args.max_delay)
        report = backfill_images(args, client, api) if args.fill_missing_images else collect(args, client, api)
    except (APIError, CollectionError, TLSConfigurationError, OSError, zipfile.BadZipFile) as exc:
        print(f"Collection failed: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        if args.server:
            print(f"Collection interrupted; saved recipes remain on the service. Progress report: {args.report}", file=sys.stderr)
        else:
            print("Collection interrupted; the output may be incomplete. Use a new output path to retry.", file=sys.stderr)
        return 130
    destination = "the service" if args.server else str(args.output)
    detail = f"Report: {args.report}" if args.server else "See collection-report.json inside the ZIP"
    if args.fill_missing_images:
        print(f"Updated {report['updated_images']} covers and {report['updated_step_images']} step photos on the service; {report['skipped']} skipped, "
              f"{report['error_count']} errors, {report['warning_count']} warnings. {detail}.")
        return 1 if report["fatal"] or (report["errors"] and not (report["updated_images"] or report["updated_step_images"])) else 0
    print(f"Saved {report['created']} recipes to {destination}; {report['step_images']} step photos, {report['duplicates']} duplicates, "
          f"{report['error_count']} errors, {report['warning_count']} warnings. {detail}.")
    if report.get("fatal"):
        return 1
    return 0 if report["created"] or (args.server and report["duplicates"] and not report["errors"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
