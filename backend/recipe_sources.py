"""Validate collector source settings and normalize recipe identities."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

DEFAULT_SOURCES_FILE = Path(__file__).with_name("recipe_sources.json")


class SourceConfigError(ValueError):
    """Source settings are invalid or ambiguous."""


@dataclass(frozen=True)
class Source:
    canonical_host: str
    hosts: tuple[str, ...]
    catalog_url: str
    recipe_pattern: str
    catalog_pattern: str
    recipe_trailing_slash: bool = False

    def accepts_catalog(self, url: str) -> bool:
        parsed = public_source_url(url)
        return bool(parsed and parsed.hostname in self.hosts and re.fullmatch(self.catalog_pattern, parsed.path))


@dataclass(frozen=True)
class Sources:
    sites: dict[str, Source]
    aliases: dict[str, str]

    def __iter__(self):
        return iter(self.sites)

    def __getitem__(self, name: str) -> Source:
        return self.sites[self.canonical_name(name)]

    def canonical_name(self, name: str) -> str:
        key = self.aliases.get(name, name)
        if key not in self.sites:
            raise SourceConfigError(f"Unknown recipe source: {name}")
        return key

    @property
    def names(self) -> list[str]:
        return [*self.sites, *self.aliases]


def public_source_url(url: str):
    """Reject credentials and custom ports before following catalog links."""
    try:
        parsed = urlsplit(url.strip())
        if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or
                parsed.port is not None or any(ord(char) < 32 or ord(char) == 127 for char in url)):
            return None
        return parsed
    except ValueError:
        return None


def load_sources(path: Path | None = None) -> Sources:
    selected = path if path is not None else DEFAULT_SOURCES_FILE
    try:
        data = json.loads(selected.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise SourceConfigError("Cannot read recipe source settings; provide a valid UTF-8 JSON file") from exc
    return sources_from_data(data)


def sources_from_data(data: dict) -> Sources:
    """Validate source definitions from either a settings file or the admin database."""
    if not isinstance(data, dict) or not data:
        raise SourceConfigError("Source settings must be a nonempty object mapping source names to settings")
    sites = {}
    aliases = {}
    known_hosts = set()
    name_pattern = r"[a-z][a-z0-9_-]*"
    fields = {"canonical_host", "hosts", "catalog_url", "recipe_pattern", "catalog_pattern", "aliases", "recipe_trailing_slash"}
    for name, entry in data.items():
        if not re.fullmatch(name_pattern, name) or not isinstance(entry, dict) or set(entry) - fields:
            raise SourceConfigError(f"Invalid source entry: {name}")
        required = ("canonical_host", "catalog_url", "recipe_pattern", "catalog_pattern")
        if any(not isinstance(entry.get(field), str) or not entry[field] for field in required):
            raise SourceConfigError(f"Source {name} requires canonical_host, catalog_url, recipe_pattern and catalog_pattern")
        hosts = entry.get("hosts")
        if not isinstance(entry.get("recipe_trailing_slash", False), bool):
            raise SourceConfigError(f"Source {name}: recipe_trailing_slash must be a boolean")
        if (not isinstance(hosts, list) or not hosts or
                any(not isinstance(host, str) or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host) or
                    ".." in host for host in hosts) or len(set(hosts)) != len(hosts)):
            raise SourceConfigError(f"Source {name} requires unique lowercase domain names in hosts")
        if entry["canonical_host"] not in hosts or known_hosts.intersection(hosts):
            raise SourceConfigError(f"Source {name} has an unlisted canonical host or a host shared with another source")
        catalog = public_source_url(entry["catalog_url"])
        if not catalog or catalog.scheme != "https" or catalog.hostname not in hosts or catalog.fragment:
            raise SourceConfigError(f"Source {name} requires an HTTPS catalog_url on one of its hosts")
        for field in ("recipe_pattern", "catalog_pattern"):
            try:
                re.compile(entry[field])
            except re.error as exc:
                raise SourceConfigError(f"Source {name} has an invalid {field}") from exc
        source = Source(entry["canonical_host"], tuple(hosts), entry["catalog_url"],
                        entry["recipe_pattern"], entry["catalog_pattern"], entry.get("recipe_trailing_slash", False))
        if not source.accepts_catalog(source.catalog_url):
            raise SourceConfigError(f"Source {name}: catalog_pattern must match the catalog_url path")
        source_aliases = entry.get("aliases", [])
        if not isinstance(source_aliases, list):
            raise SourceConfigError(f"Source {name}: aliases must be a list")
        for alias in source_aliases:
            if not isinstance(alias, str) or not re.fullmatch(name_pattern, alias) or alias in data or alias in aliases:
                raise SourceConfigError(f"Source {name} has an invalid or duplicate alias")
            aliases[alias] = name
        known_hosts.update(hosts)
        sites[name] = source
    return Sources(sites, aliases)


def normalize_recipe_url(url: str, sources: Sources) -> str | None:
    parsed = public_source_url(url)
    if parsed is None:
        return None
    path = parsed.path.rstrip("/")
    for source in sources.sites.values():
        if parsed.hostname in source.hosts and re.fullmatch(source.recipe_pattern, path):
            recipe_path = path + "/" if source.recipe_trailing_slash else path
            return urlunsplit(("https", source.canonical_host, recipe_path, "", ""))
    return None
