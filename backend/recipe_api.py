"""Authenticated client for collecting recipes directly into a running MyRecipes service."""
from __future__ import annotations

import http.client
import json
import re
import ssl
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit

from app.importer import _NoRedirect

MAX_RESPONSE_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class OwnedStep:
    id: int
    text: str
    has_image: bool


@dataclass(frozen=True)
class OwnedRecipe:
    id: int
    title: str
    source_url: str | None
    has_image: bool
    steps: tuple[OwnedStep, ...] = ()


class APIError(Exception):
    """A sanitized API failure; fatal errors must stop collection."""

    def __init__(self, message: str, *, fatal: bool = True):
        super().__init__(message)
        self.fatal = fatal


class RecipeAPI:
    def __init__(self, server: str, ssl_context: ssl.SSLContext | None = None, *, require_step_images: bool = False):
        server = server.strip()
        try:
            parsed = urlsplit(server)
            valid = (parsed.scheme in ("http", "https") and parsed.hostname and
                     not parsed.username and not parsed.password and not parsed.query and not parsed.fragment and
                     not any(ord(char) < 32 or ord(char) == 127 for char in server))
            parsed.port
        except ValueError:
            valid = False
        if not valid:
            raise APIError("--server must be an HTTP(S) service URL without credentials, query or fragment")
        self.server = server.rstrip("/")
        handlers = [_NoRedirect()]
        if ssl_context is not None:
            handlers.append(urllib.request.HTTPSHandler(context=ssl_context))
        self.opener = urllib.request.build_opener(*handlers)
        self.access_token = ""
        self.refresh_token = ""
        self.categories: dict[str, int] = {}
        self.owned_recipes: list[OwnedRecipe] = []
        self.require_step_images = require_step_images
        self.step_images_checked = False

    def request(self, method: str, path: str, body: dict | bytes | None = None,
                content_type: str = "application/json", *, authenticated: bool = True,
                refresh: bool = True) -> dict | list:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if isinstance(body, dict) else body
        headers = {"Accept": "application/json", "Content-Type": content_type}
        if authenticated:
            headers["Authorization"] = f"Bearer {self.access_token}"
        request = urllib.request.Request(self.server + path, data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=30) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            status = exc.code
            exc.close()
            if status == 401 and authenticated and refresh and self.refresh_token:
                self.set_tokens(self.request("POST", "/api/auth/refresh", {"refresh_token": self.refresh_token},
                                             authenticated=False, refresh=False))
                return self.request(method, path, body, content_type, authenticated=True, refresh=False)
            uncertain = method != "GET" and status >= 500
            message = f"Service API {method} {path.split('?', 1)[0]} returned HTTP {status}"
            if uncertain:
                message += "; the write may have succeeded. Rerun to check existing recipes before retrying"
            raise APIError(message, fatal=status >= 500 or status in (401, 403, 429) or 300 <= status < 400) from None
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
            message = "Cannot reach the service; check its address, network and trusted TLS certificates"
            if method != "GET":
                message += ". The write may have succeeded; rerun to check existing recipes before retrying"
            raise APIError(message) from None
        except ValueError:
            raise APIError("Service request could not be encoded safely; collection stopped") from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise APIError("Service API response exceeded the size limit; collection stopped")
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise APIError("Service API returned invalid JSON; collection stopped") from None
        if not isinstance(result, (dict, list)):
            raise APIError("Service API returned an unexpected response; collection stopped")
        return result

    def set_tokens(self, data: dict | list) -> None:
        if (not isinstance(data, dict) or not isinstance(data.get("access_token"), str) or
                not isinstance(data.get("refresh_token"), str) or not data["access_token"] or not data["refresh_token"]):
            raise APIError("Service authentication returned an invalid response")
        if any(not re.fullmatch(r"[A-Za-z0-9._~-]+", data[key]) for key in ("access_token", "refresh_token")):
            raise APIError("Service authentication returned an invalid token format")
        self.access_token = data["access_token"]
        self.refresh_token = data["refresh_token"]

    def login(self, login: str, password: str) -> None:
        self.set_tokens(self.request("POST", "/api/auth/login", {"login": login, "password": password, "remember": False},
                                     authenticated=False, refresh=False))

    def prepare(self) -> tuple[set[str], set[str]]:
        """Read owned recipes before writing so repeated runs skip existing sources and titles."""
        if self.require_step_images:
            self.ensure_step_images_supported()
        categories = self.request("GET", "/api/categories")
        if not isinstance(categories, list):
            raise APIError("Service returned an invalid category list")
        for category in categories:
            if not isinstance(category, dict) or not isinstance(category.get("name"), str) or not isinstance(category.get("id"), int):
                raise APIError("Service returned an invalid category")
            self.categories[category["name"].casefold()] = category["id"]
        urls: set[str] = set()
        titles: set[str] = set()
        self.owned_recipes = []
        offset = 0
        while True:
            page = self.request("GET", "/api/recipes?" + urlencode({"mine": "true", "limit": 100, "offset": offset}))
            if not isinstance(page, dict) or not isinstance(page.get("items"), list) or not isinstance(page.get("total"), int):
                raise APIError("Service returned an invalid recipe list")
            for item in page["items"]:
                if not isinstance(item, dict) or not isinstance(item.get("id"), int) or not isinstance(item.get("title"), str):
                    raise APIError("Service returned an invalid recipe list entry")
                titles.add(item["title"].casefold())
                detail = self.request("GET", f"/api/recipes/{item['id']}")
                if not isinstance(detail, dict):
                    raise APIError("Service returned invalid recipe details")
                if isinstance(detail.get("source_url"), str) and detail["source_url"]:
                    urls.add(detail["source_url"])
                self.owned_recipes.append(OwnedRecipe(
                    id=item["id"], title=item["title"],
                    source_url=detail.get("source_url") if isinstance(detail.get("source_url"), str) else None,
                    has_image=bool(detail.get("image_url") or detail.get("thumb_url")),
                    steps=self._read_steps(detail),
                ))
            offset += len(page["items"])
            if offset >= page["total"]:
                break
            if not page["items"]:
                raise APIError("Service recipe pagination stopped early; no recipes were written")
        return urls, titles

    def ensure_step_images_supported(self) -> None:
        """Detect an old running backend before downloading or changing any recipe images."""
        specification = self.request("GET", "/openapi.json", authenticated=False, refresh=False)
        path = "/api/recipes/{recipe_id}/steps/{step_id}/image"
        paths = specification.get("paths") if isinstance(specification, dict) else None
        route = paths.get(path) if isinstance(paths, dict) else None
        if not isinstance(route, dict) or not isinstance(route.get("post"), dict):
            raise APIError(
                "The running service does not support step-photo uploads. Rebuild and restart it with the updated backend, "
                "then rerun --fill-missing-images. Use --no-step-images for cover-only imports."
            )
        self.step_images_checked = True

    def recipe_has_cover(self, recipe_id: int) -> bool:
        """Recheck before uploading so an already added cover is left in place."""
        detail = self.request("GET", f"/api/recipes/{recipe_id}")
        if not isinstance(detail, dict):
            raise APIError("Service returned invalid recipe details")
        return bool(detail.get("image_url") or detail.get("thumb_url"))

    @staticmethod
    def _read_steps(detail: dict) -> tuple[OwnedStep, ...]:
        steps = detail.get("steps", [])
        if not isinstance(steps, list):
            raise APIError("Service returned an invalid recipe step list")
        result = []
        for step in steps:
            if (not isinstance(step, dict) or not isinstance(step.get("id"), int) or step["id"] < 1 or
                    not isinstance(step.get("text"), str)):
                raise APIError("Service returned an invalid recipe step")
            result.append(OwnedStep(step["id"], step["text"], bool(step.get("image") or step.get("image_url") or step.get("thumb_url"))))
        return tuple(result)

    def recipe_steps(self, recipe_id: int) -> tuple[OwnedStep, ...]:
        detail = self.request("GET", f"/api/recipes/{recipe_id}")
        if not isinstance(detail, dict):
            raise APIError("Service returned invalid recipe details")
        return self._read_steps(detail)

    def create_recipe(self, item: dict) -> int:
        category_name = item.get("category")
        category_id = None
        if category_name:
            key = category_name.casefold()
            if key not in self.categories:
                category = self.request("POST", "/api/categories", {"name": category_name, "sort_order": 0})
                if not isinstance(category, dict) or not isinstance(category.get("id"), int):
                    raise APIError("Service returned an invalid category after creation")
                self.categories[key] = category["id"]
            category_id = self.categories[key]
        payload = {key: value for key, value in item.items() if key not in ("category", "image", "photos")}
        payload["category_id"] = category_id
        created = self.request("POST", "/api/recipes", payload)
        if not isinstance(created, dict) or not isinstance(created.get("id"), int) or created["id"] < 1:
            raise APIError("Service returned an invalid result after recipe creation; rerun to check existing recipes")
        return created["id"]

    @staticmethod
    def _multipart_image(image: bytes, content_type: str, filename: str) -> tuple[bytes, str]:
        boundary = "myrecipes-" + uuid.uuid4().hex
        # The source MIME type is untrusted; the service validates the actual image bytes.
        safe_type = content_type.split(";", 1)[0].strip()
        if not re.fullmatch(r"image/[A-Za-z0-9.+-]+", safe_type):
            raise APIError("Invalid image content type", fatal=False)
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
                f"Content-Type: {safe_type}\r\n\r\n").encode("ascii") + image + f"\r\n--{boundary}--\r\n".encode("ascii")
        return body, f"multipart/form-data; boundary={boundary}"

    def upload_cover(self, recipe_id: int, image: bytes, content_type: str) -> None:
        body, multipart_type = self._multipart_image(image, content_type, "cover.img")
        self.request("POST", f"/api/recipes/{recipe_id}/image", body, multipart_type)

    def upload_step_image(self, recipe_id: int, step_id: int, image: bytes, content_type: str) -> None:
        body, multipart_type = self._multipart_image(image, content_type, "step.img")
        try:
            self.request("POST", f"/api/recipes/{recipe_id}/steps/{step_id}/image?only_if_missing=true", body, multipart_type)
        except APIError as exc:
            if "HTTP 404" in str(exc) and self.step_images_checked:
                raise APIError("The recipe step no longer exists; reload the recipe before retrying step photos") from None
            if "HTTP 404" in str(exc) or "HTTP 405" in str(exc):
                raise APIError("Step image upload is unavailable; update the running service to include the step-photo endpoint") from None
            raise
