"""Automatic configuration learns only from bounded same-site recipe samples."""
from __future__ import annotations

import json
import urllib.error
import unittest
from unittest.mock import patch

from collect_recipes import Client, CollectionError, discover
from recipe_sources import normalize_recipe_url, sources_from_data
from source_discovery import MAX_FETCHES, detect_source

ORIGIN = "https://recipes.example.org"


def recipe(name="Carrot soup"):
    node = {"@context": "https://schema.org", "@type": "Recipe", "name": name,
            "recipeIngredient": ["1 carrot"], "recipeInstructions": ["Cook the carrot."]}
    return '<html><script type="application/ld+json">' + json.dumps(node) + "</script></html>"


def links(*values):
    return "<html>" + "".join(f'<a href="{value}">{value}</a>' for value in values) + "</html>"


class FakeClient:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []
        self.blocked = set()

    def fetch(self, url, limit, accept=""):
        self.calls.append(url)
        if url not in self.pages:
            raise CollectionError("Missing fixture page")
        value = self.pages[url]
        if isinstance(value, Exception):
            raise value
        if isinstance(value, tuple):
            return value
        content_type = "application/xml" if url.endswith(".xml") else "text/html; charset=utf-8"
        return value.encode(), content_type, url


class SourceDiscoveryTests(unittest.TestCase):
    def test_homepage_category_and_recipe_are_detected_without_json_settings(self):
        pages = {ORIGIN + "/": links("/shop", "/recipes/"),
                 ORIGIN + "/recipes/": links("/recipes/categories/soup/"),
                 ORIGIN + "/recipes/categories/soup/": links("/recipes/recept-carrot/", "/recipes/recept-bean/"),
                 ORIGIN + "/recipes/recept-carrot/": recipe(),
                 ORIGIN + "/recipes/recept-bean/": recipe("Beans")}
        client = FakeClient(pages)
        definition = detect_source(ORIGIN, client=client)
        self.assertEqual(definition["hosts"], ["recipes.example.org"])
        self.assertEqual(definition["catalog_url"], ORIGIN + "/recipes/categories/soup/")
        self.assertTrue(definition["recipe_trailing_slash"])
        settings = sources_from_data({"source": definition})
        self.assertEqual(normalize_recipe_url(ORIGIN + "/recipes/recept-new/?utm_source=fixture", settings),
                         ORIGIN + "/recipes/recept-new/")
        self.assertIsNone(normalize_recipe_url(ORIGIN + "/recipes/categories/soup/", settings))
        self.assertEqual(list(discover("source", FakeClient(pages), settings)),
                         [ORIGIN + "/recipes/recept-carrot/", ORIGIN + "/recipes/recept-bean/"])
        candidate = next(discover("source", FakeClient(pages), settings))
        raw, ctype, final = FakeClient(pages).fetch(candidate, 10000)
        from app import importer
        self.assertEqual(importer.import_from_html(importer._decode(raw, ctype), final).steps, ["Cook the carrot."])
        self.assertLessEqual(len(client.calls), MAX_FETCHES)

    def test_known_nonrecipe_catalog_at_same_depth_is_excluded_from_recipe_pattern(self):
        client = FakeClient({ORIGIN + "/recipes/": links("/recipes/soups/", "/recipes/carrot-soup/", "/recipes/bean-stew/"),
                             ORIGIN + "/recipes/soups/": "<html>Soups</html>",
                             ORIGIN + "/recipes/carrot-soup/": recipe(),
                             ORIGIN + "/recipes/bean-stew/": recipe("Beans")})
        definition = detect_source(ORIGIN + "/recipes/", client=client)
        settings = sources_from_data({"source": definition})
        self.assertIsNone(normalize_recipe_url(ORIGIN + "/recipes/soups/", settings))
        self.assertEqual(normalize_recipe_url(ORIGIN + "/recipes/another-soup/", settings), ORIGIN + "/recipes/another-soup/")

    def test_robots_advertised_custom_sitemap_index_is_used_and_remains_collectable(self):
        pages = {ORIGIN + "/": "<html>Home</html>",
                 ORIGIN + "/robots.txt": "User-agent: *\nSitemap: https://recipes.example.org/maps/index.xml",
                 ORIGIN + "/maps/index.xml": "<sitemapindex><sitemap><loc>https://recipes.example.org/maps/dishes.xml</loc></sitemap></sitemapindex>",
                 ORIGIN + "/maps/dishes.xml": "<urlset><url><loc>https://recipes.example.org/recipe/123</loc></url><url><loc>https://recipes.example.org/recipe/456</loc></url></urlset>",
                 ORIGIN + "/recipe/123": recipe(), ORIGIN + "/recipe/456": recipe("Beans")}
        definition = detect_source(ORIGIN, client=FakeClient(pages))
        self.assertEqual(definition["catalog_url"], ORIGIN + "/maps/dishes.xml")
        settings = sources_from_data({"source": definition})
        self.assertEqual(normalize_recipe_url(ORIGIN + "/recipe/789", settings), ORIGIN + "/recipe/789")
        self.assertEqual(list(discover("source", FakeClient(pages), settings)), [ORIGIN + "/recipe/123", ORIGIN + "/recipe/456"])

    def test_wordpress_date_paths_and_root_level_recipe_slugs_have_conservative_shapes(self):
        for paths, future in ((["/2024/01/carrot-soup/", "/2025/02/bean-stew/"], "/2026/03/new-soup/"),
                              (["/carrot-soup", "/bean-stew"], "/another-soup")):
            with self.subTest(paths=paths):
                pages = {ORIGIN + "/": links(*paths), **{ORIGIN + path: recipe() for path in paths}}
                definition = detect_source(ORIGIN, client=FakeClient(pages))
                settings = sources_from_data({"source": definition})
                self.assertEqual(normalize_recipe_url(ORIGIN + future, settings), ORIGIN + future)
                self.assertIsNone(normalize_recipe_url(ORIGIN + "/category", settings))
                self.assertIsNone(normalize_recipe_url(ORIGIN + "/category/soups", settings))

    def test_external_credential_port_and_non_https_links_are_never_requested(self):
        unsafe = ["https://attacker.example.org/recipe/1", "https://127.0.0.1/recipe/1",
                  "http://recipes.example.org/recipe/1", "https://user:fixture@recipes.example.org/recipe/1",
                  "https://recipes.example.org:8443/recipe/1", "javascript:alert(1)"]
        pages = {ORIGIN + "/recipes": links(*unsafe, "/recipe/1", "/recipe/2"),
                 ORIGIN + "/recipe/1": recipe(), ORIGIN + "/recipe/2": recipe("Beans")}
        client = FakeClient(pages)
        detect_source(ORIGIN + "/recipes", client=client)
        self.assertTrue(all(url.startswith(ORIGIN + "/") and ":8443" not in url and "@" not in url for url in client.calls))
        self.assertTrue(set(unsafe).isdisjoint(client.calls))

    def test_private_or_credential_input_fails_before_network_access(self):
        for url in ("https://127.0.0.1", "https://localhost", "https://box.local", "http://recipes.example.org",
                    "https://user:fixture@recipes.example.org", "https://recipes.example.org:8443", "https://recipes.example.org/#x"):
            with self.subTest(url=url):
                client = FakeClient({})
                with self.assertRaises(CollectionError):
                    detect_source(url, client=client)
                self.assertEqual(client.calls, [])

    def test_external_redirect_and_malformed_sitemap_do_not_create_settings(self):
        client = FakeClient({ORIGIN + "/": (b"<html>Moved</html>", "text/html", "https://attacker.example.org/")})
        with self.assertRaisesRegex(CollectionError, "конечную HTTPS"):
            detect_source(ORIGIN, client=client)
        client = FakeClient({ORIGIN + "/": "<html>Home</html>",
                             ORIGIN + "/sitemap.xml": "<?xml version='1.0'?><urlset><url>broken"})
        with self.assertRaisesRegex(CollectionError, "полноценный рецепт"):
            detect_source(ORIGIN, client=client)

    def test_initial_canonical_www_and_slash_redirects_are_followed_with_fetch(self):
        def redirect(source, target):
            error = CollectionError("Redirect refused")
            error.__cause__ = urllib.error.HTTPError(source, 301, "Moved", {"Location": target}, None)
            error.__cause__.close()
            return error

        canonical = "https://www.recipes.example.org"
        client = FakeClient({ORIGIN + "/recipes": redirect(ORIGIN + "/recipes", canonical + "/recipes"),
                             canonical + "/recipes": redirect(canonical + "/recipes", "/recipes/"),
                             canonical + "/recipes/": links(ORIGIN + "/recipe/123/", "/recipe/456/"),
                             canonical + "/recipe/123/": recipe(), canonical + "/recipe/456/": recipe("Beans")})
        definition = detect_source(ORIGIN + "/recipes", client=client)
        self.assertEqual(definition["canonical_host"], "www.recipes.example.org")
        self.assertEqual(definition["hosts"], ["recipes.example.org", "www.recipes.example.org"])
        self.assertEqual(definition["catalog_url"], canonical + "/recipes/")
        self.assertEqual(client.calls[:3], [ORIGIN + "/recipes", canonical + "/recipes", canonical + "/recipes/"])

    def test_initial_redirect_cannot_escape_host_or_downgrade_or_loop_unbounded(self):
        for target in ("https://attacker.example.org/", "https://127.0.0.1/", "http://recipes.example.org/",
                       "https://www.recipes.example.org:8443/", "https://user:fixture@www.recipes.example.org/"):
            with self.subTest(target=target):
                error = CollectionError("Redirect refused")
                error.__cause__ = urllib.error.HTTPError(ORIGIN + "/", 301, "Moved", {"Location": target}, None)
                error.__cause__.close()
                client = FakeClient({ORIGIN + "/": error})
                with self.assertRaises(CollectionError):
                    detect_source(ORIGIN, client=client)
                self.assertEqual(client.calls, [ORIGIN + "/"])
        error = CollectionError("Redirect refused")
        error.__cause__ = urllib.error.HTTPError(ORIGIN + "/", 301, "Moved", {"Location": ORIGIN + "/"}, None)
        error.__cause__.close()
        client = FakeClient({ORIGIN + "/": error})
        with self.assertRaises(CollectionError):
            detect_source(ORIGIN, client=client)
        self.assertEqual(len(client.calls), 4)

    def test_later_catalog_slash_redirect_is_saved_as_collectable_canonical_catalog(self):
        error = CollectionError("Redirect refused")
        error.__cause__ = urllib.error.HTTPError(ORIGIN + "/recipes", 301, "Moved", {"Location": "/recipes/"}, None)
        error.__cause__.close()
        pages = {ORIGIN + "/": links("/recipes"), ORIGIN + "/recipes": error,
                 ORIGIN + "/recipes/": links("/recipe/123/", "/recipe/456/"),
                 ORIGIN + "/recipe/123/": recipe(), ORIGIN + "/recipe/456/": recipe("Beans")}
        client = FakeClient(pages)
        definition = detect_source(ORIGIN, client=client)
        self.assertEqual(definition["catalog_url"], ORIGIN + "/recipes/")
        self.assertEqual(definition["hosts"], ["recipes.example.org"])
        settings = sources_from_data({"source": definition})
        from app import importer
        candidates = list(discover("source", FakeClient(pages), settings))
        self.assertEqual(candidates, [ORIGIN + "/recipe/123/", ORIGIN + "/recipe/456/"])
        raw, ctype, final = FakeClient(pages).fetch(candidates[0], 10000)
        self.assertEqual(importer.import_from_html(importer._decode(raw, ctype), final).steps, ["Cook the carrot."])

    def test_later_redirect_refuses_host_path_and_query_changes(self):
        for target in ("https://www.recipes.example.org/recipes/", "https://attacker.example.org/recipes/",
                       "/other-recipes/", "/recipes/?page=2", "http://recipes.example.org/recipes/"):
            with self.subTest(target=target):
                error = CollectionError("Redirect refused")
                error.__cause__ = urllib.error.HTTPError(ORIGIN + "/recipes", 301, "Moved", {"Location": target}, None)
                error.__cause__.close()
                client = FakeClient({ORIGIN + "/": links("/recipes"), ORIGIN + "/recipes": error})
                with self.assertRaisesRegex(CollectionError, "полноценный рецепт"):
                    detect_source(ORIGIN, client=client)
                self.assertNotIn(ORIGIN + "/recipes/", client.calls)
                self.assertTrue(all(url.startswith(ORIGIN + "/") for url in client.calls))

    def test_detected_source_runtime_handles_child_catalog_and_mixed_recipe_slashes(self):
        from app import importer

        pages = {ORIGIN + "/recipes/": links("/recipes/recept-carrot/", "/recipes/recept-bean", "/recipes/more"),
                 ORIGIN + "/recipes/recept-carrot/": recipe(), ORIGIN + "/recipes/recept-bean": recipe("Beans"),
                 ORIGIN + "/recipes/more/": links("/recipes/recept-third"), ORIGIN + "/recipes/recept-third": recipe("Third")}
        definition = detect_source(ORIGIN + "/recipes/", client=FakeClient(pages))
        settings = sources_from_data({"source": definition})
        requested = []

        def response(url, *args, **kwargs):
            requested.append(url)
            self.assertFalse(kwargs["allow_redirects"])
            if url.endswith("/robots.txt"):
                return b"User-agent: *\nAllow: /", "text/plain", url
            target = None
            if url == ORIGIN + "/recipes/more":
                target = url + "/"
            elif url in (ORIGIN + "/recipes/recept-bean/", ORIGIN + "/recipes/recept-third/"):
                target = url.rstrip("/")
            if target:
                try:
                    raise urllib.error.HTTPError(url, 301, "Moved", {"Location": target}, None)
                except urllib.error.HTTPError as http_error:
                    http_error.close()
                    raise importer.ImportError_("Site returned HTTP 301")
            return pages[url].encode(), "text/html", url

        with patch.object(importer, "fetch", side_effect=response):
            client = Client(0, 0)
            candidates = list(discover("source", client, settings))
            self.assertEqual(len(candidates), 3)
            for candidate in candidates:
                raw, ctype, final = client.fetch(candidate, 10000)
                self.assertEqual(normalize_recipe_url(final, settings), candidate)
                self.assertTrue(importer.import_from_html(importer._decode(raw, ctype), final).ingredients)
        self.assertIn(ORIGIN + "/recipes/more", requested)
        self.assertIn(ORIGIN + "/recipes/more/", requested)
        self.assertIn(ORIGIN + "/recipes/recept-bean/", requested)
        self.assertIn(ORIGIN + "/recipes/recept-bean", requested)

    def test_real_client_canonicalizes_nonhinted_catalog_and_preserves_mixed_recipe_identity(self):
        from app import importer

        pages = {ORIGIN + "/": links("/menu"), ORIGIN + "/menu/": links("/dish/123/", "/blog/pie"),
                 ORIGIN + "/dish/123/": recipe(), ORIGIN + "/blog/pie": recipe("Pie")}

        def response(url, *args, **kwargs):
            if url.endswith("/robots.txt"):
                return b"User-agent: *\nAllow: /", "text/plain", url
            target = ORIGIN + "/menu/" if url == ORIGIN + "/menu" else None
            if url == ORIGIN + "/blog/pie/":
                target = ORIGIN + "/blog/pie"
            if target or url not in pages:
                try:
                    raise urllib.error.HTTPError(url, 301 if target else 404, "Fixture status",
                                                 {"Location": target} if target else {}, None)
                except urllib.error.HTTPError as http_error:
                    http_error.close()
                    raise importer.ImportError_("Fixture HTTP error")
            return pages[url].encode(), "text/html", url

        with patch.object(importer, "fetch", side_effect=response):
            definition = detect_source(ORIGIN, client=Client(0, 0))
            self.assertEqual(definition["catalog_url"], ORIGIN + "/menu/")
            settings = sources_from_data({"source": definition})
            client = Client(0, 0)
            candidates = list(discover("source", client, settings))
            self.assertEqual(len(candidates), 2)
            for candidate in candidates:
                raw, ctype, final = client.fetch(candidate, 10000)
                self.assertEqual(normalize_recipe_url(final, settings), candidate)
                self.assertTrue(importer.import_from_html(importer._decode(raw, ctype), final).steps)

    def test_absent_or_incomplete_recipe_is_not_a_success_and_attempts_are_bounded(self):
        paths = [f"/recipe/{index}" for index in range(100)]
        incomplete = recipe().replace('"recipeInstructions": ["Cook the carrot."]', '"recipeInstructions": []')
        client = FakeClient({ORIGIN + "/": links(*paths), **{ORIGIN + path: incomplete for path in paths}})
        with self.assertRaisesRegex(CollectionError, "полноценный рецепт"):
            detect_source(ORIGIN, client=client)
        self.assertLessEqual(len(client.calls), MAX_FETCHES)

    def test_deadline_stops_probing_more_candidates(self):
        client = FakeClient({ORIGIN + "/": links("/recipe/1")})
        with patch("source_discovery.time.monotonic", side_effect=[0, 0, 100]):
            with self.assertRaisesRegex(CollectionError, "полноценный рецепт"):
                detect_source(ORIGIN, client=client)
        self.assertEqual(client.calls, [ORIGIN + "/"])

    def test_query_only_recipe_identity_is_rejected_instead_of_losing_the_id(self):
        client = FakeClient({ORIGIN + "/": links("/recipe?id=1"), ORIGIN + "/recipe?id=1": recipe()})
        with self.assertRaisesRegex(CollectionError, "параметрами запроса"):
            detect_source(ORIGIN, client=client)


if __name__ == "__main__":
    unittest.main()
