"""Direct-import API behavior using a local HTTP fixture and synthetic authentication."""
from __future__ import annotations

import collections
import json
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import recipe_api
from recipe_api import APIError, RecipeAPI

try:
    from app.schemas import RecipeIn
except ImportError:
    RecipeIn = None


class FixtureHandler(BaseHTTPRequestHandler):
    def handle_request(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.server.requests.append((self.command, self.path, dict(self.headers), body))
        if not self.server.responses:
            self.server.errors.append("Unexpected request")
            status, payload, extra_headers = 500, {}, {}
        else:
            method, path, status, payload, extra_headers = self.server.responses.popleft()
            if (self.command, self.path) != (method, path):
                self.server.errors.append(f"Unexpected request route: {self.command} {self.path}")
                status, payload, extra_headers = 500, {}, {}
        encoded = json.dumps(payload).encode() if not isinstance(payload, bytes) else payload
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        for name, value in extra_headers.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(encoded)

    do_GET = handle_request
    do_POST = handle_request

    def log_message(self, format, *args):
        pass


class APITests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
        self.server.responses = collections.deque()
        self.server.requests = []
        self.server.errors = []
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.api = RecipeAPI(f"http://127.0.0.1:{self.server.server_port}")
        self.api.access_token = "fixture-access"
        self.api.refresh_token = "fixture-refresh"

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.assertFalse(self.server.errors)

    def respond(self, method, path, payload, status=200, headers=None):
        self.server.responses.append((method, path, status, payload, headers or {}))

    @staticmethod
    def item(title="Sample recipe", category="Dinner"):
        return {
            "title": title, "description": "Source author: Example", "category": category,
            "servings": 2, "prep_minutes": 5, "cook_minutes": 10, "difficulty": None,
            "is_public": False, "source_url": "https://food.ru/recipes/1-example", "tags": ["sample"],
            "ingredients": [{"product": "Milk", "amount": 200, "unit": "мл", "note": "", "group": ""}],
            "steps": [{"text": "Mix.", "timer_minutes": None}], "image": None, "photos": [],
        }

    def test_login_uses_expected_json_without_existing_authorization(self):
        self.respond("POST", "/api/auth/login", {"access_token": "fixture-new-access", "refresh_token": "fixture-new-refresh"})
        self.api.login("fixture-user", "fixture-password")
        _, _, headers, body = self.server.requests[0]
        self.assertNotIn("Authorization", headers)
        self.assertEqual(json.loads(body), {"login": "fixture-user", "password": "fixture-password", "remember": False})
        self.assertEqual(self.api.access_token, "fixture-new-access")
        self.assertEqual(self.api.refresh_token, "fixture-new-refresh")

    def test_expired_access_refreshes_once_then_replays_original_request(self):
        self.respond("POST", "/api/recipes", {}, status=401)
        self.respond("POST", "/api/auth/refresh", {"access_token": "fixture-renewed", "refresh_token": "fixture-renewed-refresh"})
        self.respond("POST", "/api/recipes", {"id": 42})
        self.assertEqual(self.api.request("POST", "/api/recipes", {"title": "Example"}), {"id": 42})
        first, refresh, replay = self.server.requests
        self.assertEqual(first[3], replay[3])
        self.assertNotEqual(first[2]["Authorization"], replay[2]["Authorization"])
        self.assertNotIn("Authorization", refresh[2])
        self.assertEqual(json.loads(refresh[3]), {"refresh_token": "fixture-refresh"})

    def test_authentication_failure_after_refresh_stops_without_another_refresh(self):
        self.respond("GET", "/api/categories", {}, status=401)
        self.respond("POST", "/api/auth/refresh", {"access_token": "fixture-renewed", "refresh_token": "fixture-renewed-refresh"})
        self.respond("GET", "/api/categories", {}, status=401)
        with self.assertRaises(APIError) as raised:
            self.api.request("GET", "/api/categories")
        self.assertTrue(raised.exception.fatal)
        self.assertEqual(len(self.server.requests), 3)

    def test_authenticated_redirect_is_not_followed(self):
        self.respond("GET", "/api/categories", {}, status=302, headers={"Location": self.api.server + "/other"})
        with self.assertRaises(APIError) as raised:
            self.api.request("GET", "/api/categories")
        self.assertTrue(raised.exception.fatal)
        self.assertEqual(len(self.server.requests), 1)

    def test_service_error_does_not_echo_response_secrets_or_retry_mutation(self):
        marker = "synthetic-sensitive-server-response"
        self.respond("POST", "/api/recipes", {"password": marker, "access_token": marker}, status=503)
        with self.assertRaises(APIError) as raised:
            self.api.request("POST", "/api/recipes", {"title": "Example"})
        self.assertTrue(raised.exception.fatal)
        self.assertIn("may have succeeded", str(raised.exception))
        self.assertNotIn(marker, str(raised.exception))
        self.assertEqual(len(self.server.requests), 1)

    def test_network_timeout_does_not_retry_mutation(self):
        with patch.object(self.api.opener, "open", side_effect=TimeoutError) as opened:
            with self.assertRaises(APIError) as raised:
                self.api.request("POST", "/api/recipes", {"title": "Example"})
        self.assertTrue(raised.exception.fatal)
        self.assertIn("may have succeeded", str(raised.exception))
        self.assertEqual(opened.call_count, 1)

    def test_transport_value_error_is_sanitized(self):
        marker = "synthetic-private-header-marker"
        with patch.object(self.api.opener, "open", side_effect=ValueError(marker)) as opened:
            with self.assertRaises(APIError) as raised:
                self.api.request("POST", "/api/recipes", {"title": "Example"})
        self.assertTrue(raised.exception.fatal)
        self.assertNotIn(marker, str(raised.exception))
        self.assertEqual(opened.call_count, 1)

    def test_validation_failure_is_nonfatal_and_sanitized(self):
        self.respond("POST", "/api/recipes", {"detail": "synthetic-private-input"}, status=422)
        with self.assertRaises(APIError) as raised:
            self.api.request("POST", "/api/recipes", {"title": "Example"})
        self.assertFalse(raised.exception.fatal)
        self.assertNotIn("synthetic-private-input", str(raised.exception))

    def test_preflight_paginates_owned_recipes_and_reads_source_urls(self):
        self.respond("GET", "/api/categories", [{"name": "Dinner", "id": 7}])
        self.respond("GET", "/api/recipes?mine=true&limit=100&offset=0",
                     {"items": [{"id": 10, "title": "First"}], "total": 2})
        self.respond("GET", "/api/recipes/10", {"source_url": "https://food.ru/recipes/1-example"})
        self.respond("GET", "/api/recipes?mine=true&limit=100&offset=1",
                     {"items": [{"id": 11, "title": "SECOND"}], "total": 2})
        self.respond("GET", "/api/recipes/11", {"source_url": None, "image_url": "/api/uploads/existing.webp"})
        urls, titles = self.api.prepare()
        self.assertEqual(urls, {"https://food.ru/recipes/1-example"})
        self.assertEqual(titles, {"first", "second"})
        self.assertEqual(self.api.categories, {"dinner": 7})
        self.assertEqual([(recipe.id, recipe.has_image) for recipe in self.api.owned_recipes], [(10, False), (11, True)])
        self.assertEqual(self.api.owned_recipes[0].source_url, "https://food.ru/recipes/1-example")
        self.assertFalse(self.server.responses)

    def test_fresh_cover_check_reads_existing_recipe_without_writes(self):
        self.respond("GET", "/api/recipes/42", {"image_url": None, "thumb_url": None})
        self.respond("GET", "/api/recipes/42", {"image_url": "/api/uploads/added.webp"})
        self.assertFalse(self.api.recipe_has_cover(42))
        self.assertTrue(self.api.recipe_has_cover(42))
        self.assertTrue(all(method == "GET" for method, _, _, _ in self.server.requests))

    def test_incomplete_pagination_stops_preflight(self):
        self.respond("GET", "/api/categories", [])
        self.respond("GET", "/api/recipes?mine=true&limit=100&offset=0", {"items": [], "total": 1})
        with self.assertRaisesRegex(APIError, "pagination"):
            self.api.prepare()
        self.assertFalse(any(method == "POST" for method, _, _, _ in self.server.requests))

    def test_create_recipe_uses_category_cache_and_valid_service_payload(self):
        self.respond("POST", "/api/categories", {"id": 7})
        self.respond("POST", "/api/recipes", {"id": 42})
        self.respond("POST", "/api/recipes", {"id": 43})
        self.assertEqual(self.api.create_recipe(self.item()), 42)
        self.assertEqual(self.api.create_recipe(self.item(title="Another", category="DINNER")), 43)
        self.assertEqual(len(self.server.requests), 3)
        for _, _, _, body in self.server.requests[1:]:
            payload = json.loads(body)
            self.assertEqual(payload["category_id"], 7)
            self.assertNotIn("category", payload)
            self.assertNotIn("image", payload)
            self.assertNotIn("photos", payload)
            if RecipeIn is not None:
                RecipeIn.model_validate(payload)

    def test_cover_is_uploaded_as_multipart_after_recipe_creation(self):
        self.respond("POST", "/api/recipes", {"id": 42})
        self.respond("POST", "/api/recipes/42/image", {"id": 42})
        recipe_id = self.api.create_recipe(self.item(category=None))
        image = b"synthetic-image-bytes"
        self.api.upload_cover(recipe_id, image, "image/png; charset=binary")
        method, path, headers, body = self.server.requests[-1]
        self.assertEqual((method, path), ("POST", "/api/recipes/42/image"))
        boundary = headers["Content-Type"].partition("boundary=")[2]
        self.assertTrue(body.startswith(f"--{boundary}\r\n".encode()))
        self.assertTrue(body.endswith(f"\r\n--{boundary}--\r\n".encode()))
        self.assertIn(b'name="file"; filename="cover.img"', body)
        self.assertIn(b"Content-Type: image/png\r\n", body)
        self.assertIn(image, body)

    def test_malformed_responses_stop_without_echoing_payload(self):
        for payload in (b"not-json-sensitive-marker", b"null", b"true", b"42"):
            with self.subTest(payload=payload):
                self.respond("GET", "/api/categories", payload)
                with self.assertRaises(APIError) as raised:
                    self.api.request("GET", "/api/categories")
                self.assertTrue(raised.exception.fatal)
                self.assertNotIn("sensitive-marker", str(raised.exception))

    def test_untrusted_cover_mime_is_rejected_before_upload(self):
        for content_type in ("text/plain", "image/png\r\nInjected: value", "image/пнг"):
            with self.subTest(content_type=content_type), self.assertRaises(APIError):
                self.api.upload_cover(42, b"synthetic-image", content_type)
        self.assertEqual(self.server.requests, [])

    def test_response_size_limit_is_enforced(self):
        self.respond("GET", "/api/categories", {"name": "x" * 100})
        with patch.object(recipe_api, "MAX_RESPONSE_BYTES", 32):
            with self.assertRaisesRegex(APIError, "size limit"):
                self.api.request("GET", "/api/categories")

    def test_invalid_authentication_payload_is_rejected(self):
        for payload in ({}, [], {"access_token": "fixture-token"}, {"access_token": "", "refresh_token": "fixture-token"}):
            with self.subTest(payload=payload), self.assertRaises(APIError):
                self.api.set_tokens(payload)

    def test_malformed_tokens_are_rejected_without_echoing_values(self):
        for marker in ("synthetic-token\r\nInjected: value", "synthetic token", "synthetic-токен"):
            for field in ("access_token", "refresh_token"):
                with self.subTest(field=field, marker=marker):
                    payload = {"access_token": "fixture-access", "refresh_token": "fixture-refresh"}
                    payload[field] = marker
                    with self.assertRaises(APIError) as raised:
                        self.api.set_tokens(payload)
                    self.assertNotIn(marker, str(raised.exception))
                    self.assertEqual(self.api.access_token, "fixture-access")
                    self.assertEqual(self.api.refresh_token, "fixture-refresh")

    def test_invalid_service_urls_are_rejected(self):
        for server in ("file:///tmp/service", "https://user:password@example.org", "https://example.org?token=x",
                       "https://example.org#fragment", "https://example.org:invalid"):
            with self.subTest(server=server), self.assertRaises(APIError):
                RecipeAPI(server)


if __name__ == "__main__":
    unittest.main()
