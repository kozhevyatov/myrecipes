"""Behavior checks for offline collection and the service's import contract."""
from __future__ import annotations

import contextlib
import base64
import gzip
import io
import json
import ssl
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import patch

import collect_recipes as collector
from app import importer

try:
    from app.schemas import RecipeIn
except ImportError:
    RecipeIn = None


FOOD = "https://food.ru/recipes/1-test"
RAMBLER = "https://eda.rambler.ru/recepty/pasta-picca/test-2"


def recipe_page(title: str, ingredients: list[str] | None = None, **fields) -> bytes:
    node = {
        "@type": "Recipe", "name": title,
        "recipeIngredient": ingredients or ["Молоко 200 мл"],
        "recipeInstructions": [{"@type": "HowToStep", "text": "Mix the ingredients."}],
        "recipeYield": "4 порции", "totalTime": "PT20M",
        "recipeCategory": "Основное блюдо", "image": "https://cdn.food.ru/cover.png",
        "author": {"@type": "Person", "name": "Sample author"},
    }
    node.update(fields)
    return ('<script type="application/ld+json">' + json.dumps(node, ensure_ascii=False) + "</script>").encode()


def sitemap(kind: str, *urls: str) -> bytes:
    entry = "sitemap" if kind == "sitemapindex" else "url"
    return (f'<{kind} xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' +
            "".join(f"<{entry}><loc>{url}</loc></{entry}>" for url in urls) + f"</{kind}>").encode()


class FakeClient:
    def __init__(self, responses: dict):
        self.responses = responses
        self.calls: list[str] = []

    def fetch(self, url: str, limit: int, accept: str = "text/html,*/*;q=0.8"):
        self.calls.append(url)
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        if isinstance(response, tuple):
            return response
        return response, "text/html; charset=utf-8", url

    def fetch_cover(self, url: str):
        return self.fetch(url, importer.MAX_IMAGE_BYTES, "image/*")


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.output = Path(self.directory.name) / "recipes.zip"

    def options(self, *extra: str):
        return collector.parser().parse_args(["--output", str(self.output), *extra])

    def run_collection(self, args, client):
        with contextlib.redirect_stderr(io.StringIO()):
            report = collector.collect(args, client)
        with zipfile.ZipFile(self.output) as archive:
            manifest = json.loads(archive.read("recipes.json"))
            stored_report = json.loads(archive.read("collection-report.json"))
            images = {name: archive.read(name) for name in archive.namelist() if name.startswith("images/")}
        self.assertEqual(report, stored_report)
        return report, manifest, images

    def test_both_sitemaps_produce_a_service_compatible_archive(self):
        food_map = "https://food.ru/sitemaps/recipes-1.xml"
        rambler_map = "https://eda.rambler.ru/sitemap/map_RecipePagesGroup_https_0.xml.gz"
        ignored_map = "https://eda.rambler.ru/sitemap/map_RecipeGroupPagesGroup_https_0.xml.gz"
        # A tiny valid PNG also verifies that ZIP entries contain the original image bytes.
        image = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
        client = FakeClient({
            collector.load_sources()["food"].catalog_url: sitemap("sitemapindex", food_map),
            collector.load_sources()["rambler"].catalog_url: sitemap("sitemapindex", ignored_map, rambler_map),
            food_map: sitemap("urlset", FOOD),
            rambler_map: gzip.compress(sitemap("urlset", RAMBLER)),
            FOOD: recipe_page("Food sample", ["Чеснок 2 зубчик = 10 г"]),
            RAMBLER: recipe_page("Rambler sample", ["Красный лук, 1 головка"]),
            "https://cdn.food.ru/cover.png": (image, "image/png", "https://cdn.food.ru/cover.png"),
        })
        report, manifest, images = self.run_collection(self.options("--limit", "2"), client)
        self.assertEqual(report["created"], 2)
        self.assertFalse(report["errors"])
        self.assertEqual((manifest["format"], manifest["version"]), ("myrecipes-backup", 1))
        self.assertEqual(len(manifest["categories"]), 1)
        self.assertEqual([r["source_url"] for r in manifest["recipes"]], [FOOD, RAMBLER])
        self.assertNotIn(ignored_map, client.calls)
        self.assertEqual(len(images), 1)
        self.assertEqual(next(iter(images.values())), image)
        for item in manifest["recipes"]:
            self.assertFalse(item["is_public"])
            self.assertIn("Sample author", item["description"])
            self.assertIn(item["image"], images)
            if RecipeIn is not None:
                validated = RecipeIn.model_validate(item)
                self.assertEqual(validated.servings, 4)
                self.assertEqual(validated.cook_minutes, 20)
        first, second = (r["ingredients"][0] for r in manifest["recipes"])
        self.assertEqual((first["product"], first["amount"], first["unit"]), ("Чеснок", 10, "г"))
        self.assertIn("2", first["note"])
        self.assertEqual((second["product"], second["amount"], second["unit"]), ("Красный лук", 1, "шт"))

    def test_partial_failures_and_missing_cover_are_reported(self):
        bad = "https://food.ru/recipes/3-bad"
        client = FakeClient({
            bad: b"<html>No recipe here</html>",
            FOOD: recipe_page("Usable recipe"),
            "https://cdn.food.ru/cover.png": collector.CollectionError("Cover unavailable"),
        })
        report, manifest, images = self.run_collection(self.options("--url", bad, "--url", FOOD), client)
        self.assertEqual((report["created"], report["attempted"]), (1, 2))
        self.assertEqual(len(report["errors"]), 1)
        self.assertEqual(report["errors"][0]["url"], bad)
        self.assertTrue(any("Cover omitted" in warning["warning"] for warning in report["warnings"]))
        self.assertIsNone(manifest["recipes"][0]["image"])
        self.assertEqual(images, {})

    def test_duplicate_tracking_urls_and_titles_are_not_imported_twice(self):
        alternate = "https://food.ru/recipes/3-alternate"
        client = FakeClient({FOOD: recipe_page("Same recipe"), alternate: recipe_page("SAME RECIPE")})
        args = self.options("--url", FOOD, "--url", FOOD + "?utm_source=test#fragment",
                            "--url", alternate, "--no-images")
        report, manifest, _ = self.run_collection(args, client)
        self.assertEqual((report["created"], report["duplicates"]), (1, 2))
        self.assertEqual(client.calls.count(FOOD), 1)
        self.assertEqual(len(manifest["recipes"]), 1)

    def test_limit_and_page_budget_stop_before_extra_fetches(self):
        third = "https://food.ru/recipes/3-third"
        for option in ("--limit", "--max-pages"):
            with self.subTest(option=option):
                self.output = Path(self.directory.name) / f"{option[2:]}.zip"
                client = FakeClient({FOOD: recipe_page("First"), third: recipe_page("Third")})
                args = self.options("--url", FOOD, "--url", third, option, "1", "--no-images")
                report, _, _ = self.run_collection(args, client)
                self.assertEqual(report["created"], 1)
                self.assertEqual(client.calls, [FOOD])

    def test_discovery_failure_does_not_discard_other_site(self):
        food_map = "https://food.ru/sitemaps/recipes-1.xml"
        client = FakeClient({
            collector.load_sources()["food"].catalog_url: sitemap("sitemapindex", food_map),
            food_map: sitemap("urlset", FOOD),
            FOOD: recipe_page("Available"),
            collector.load_sources()["rambler"].catalog_url: collector.CollectionError("Site unavailable"),
        })
        report, _, _ = self.run_collection(self.options("--no-images", "--site", "food", "--site", "rambler"), client)
        self.assertEqual(report["created"], 1)
        self.assertEqual(report["errors"][0]["stage"], "discovery")

    def test_urls_file_ignores_comments_and_only_uses_explicit_sources(self):
        urls_file = Path(self.directory.name) / "urls.txt"
        urls_file.write_text(f"# Recipe selection\n\n{FOOD}\n", encoding="utf-8")
        client = FakeClient({FOOD: recipe_page("Selected")})
        report, manifest, images = self.run_collection(
            self.options("--urls-file", str(urls_file), "--no-images", "--public"), client)
        self.assertEqual(report["created"], 1)
        self.assertEqual(client.calls, [FOOD])
        self.assertTrue(manifest["recipes"][0]["is_public"])
        self.assertEqual(images, {})

    def test_existing_output_is_never_overwritten(self):
        self.output.write_bytes(b"Existing output")
        with self.assertRaises(FileExistsError):
            collector.collect(self.options("--url", FOOD), FakeClient({}))
        self.assertEqual(self.output.read_bytes(), b"Existing output")

    def test_empty_url_file_does_not_trigger_automatic_discovery(self):
        urls_file = Path(self.directory.name) / "empty.txt"
        urls_file.write_text("# No selected recipes\n", encoding="utf-8")
        client = FakeClient({})
        with self.assertRaisesRegex(collector.CollectionError, "no recipe URLs"):
            collector.collect(self.options("--urls-file", str(urls_file)), client)
        self.assertEqual(client.calls, [])
        self.assertFalse(self.output.exists())

    def test_recipe_redirect_to_another_site_is_rejected(self):
        client = FakeClient({FOOD: (recipe_page("Wrong source"), "text/html", "https://example.org/recipe")})
        report, manifest, _ = self.run_collection(self.options("--url", FOOD, "--no-images"), client)
        self.assertEqual(report["created"], 0)
        self.assertEqual(len(report["errors"]), 1)
        self.assertEqual(manifest["recipes"], [])

    def test_manifest_budget_skips_large_recipe_and_preserves_importable_archive(self):
        large = "https://food.ru/recipes/3-large"
        client = FakeClient({
            large: recipe_page("Large recipe", recipeInstructions=[{"@type": "HowToStep", "text": "Д" * 9999}]),
            FOOD: recipe_page("Small recipe"),
        })
        with patch.object(collector, "MAX_MANIFEST_BYTES", 20_000):
            report, manifest, _ = self.run_collection(
                self.options("--url", large, "--url", FOOD, "--no-images"), client)
        self.assertEqual(report["created"], 1)
        self.assertEqual(manifest["recipes"][0]["title"], "Small recipe")
        self.assertEqual(report["errors"][0]["url"], large)
        with zipfile.ZipFile(self.output) as archive:
            self.assertLessEqual(len(archive.read("recipes.json")), 20_000)

    def test_long_source_author_is_truncated_to_fit_service_description(self):
        client = FakeClient({FOOD: recipe_page("Attributed", author={"@type": "Person", "name": "Автор" * 2000})})
        report, manifest, _ = self.run_collection(self.options("--url", FOOD, "--no-images"), client)
        self.assertEqual(report["created"], 1)
        item = manifest["recipes"][0]
        self.assertLessEqual(len(item["description"]), 5000)
        self.assertIn("Source author:", item["description"])
        self.assertEqual(item["source_url"], FOOD)
        self.assertTrue(any("truncated" in warning["warning"] for warning in report["warnings"]))
        if RecipeIn is not None:
            RecipeIn.model_validate(item)


class ParsingTests(unittest.TestCase):
    def test_downloader_follows_redirects_by_default_and_can_explicitly_disable_them(self):
        for allow_redirects in (True, False):
            with self.subTest(allow_redirects=allow_redirects):
                response = io.BytesIO(b"Recipe HTML")
                response.headers = {"Content-Type": "text/html"}
                response.geturl = lambda: FOOD
                with patch.object(importer, "_check_host"), \
                     patch.object(importer._opener, "open", return_value=response) as standard, \
                     patch.object(importer._no_redirect_opener, "open", return_value=response) as restricted:
                    # Omitting the new option exercises the existing application call contract.
                    if allow_redirects:
                        result = importer.fetch(FOOD, 100)
                    else:
                        result = importer.fetch(FOOD, 100, allow_redirects=False)
                self.assertEqual(result, (b"Recipe HTML", "text/html", FOOD))
                selected, unused = (standard, restricted) if allow_redirects else (restricted, standard)
                selected.assert_called_once()
                unused.assert_not_called()
                self.assertEqual(selected.call_args.args[0].get_header("User-agent"), importer.USER_AGENT)

    def test_supported_recipe_urls_are_normalized_and_other_urls_rejected(self):
        self.assertEqual(collector.recipe_url("http://www.food.ru/recipes/1-test/?tracking=1#x"), FOOD)
        self.assertEqual(collector.recipe_url(RAMBLER), RAMBLER)
        for url in ("https://food.ru/recipes", "https://food.ru.attacker.test/recipes/1-test",
                    "https://127.0.0.1/recipes/1-test", "https://user:password@food.ru/recipes/1-test",
                    "https://food.ru:1234/recipes/1-test", "file:///recipes/1-test"):
            with self.subTest(url=url):
                self.assertIsNone(collector.recipe_url(url))

    def test_sitemap_rejects_bad_xml_and_oversized_gzip_output(self):
        for data in (b"Not XML", b"<html/>", b'<!DOCTYPE x [<!ENTITY x "a">]><urlset/>'):
            with self.subTest(data=data), self.assertRaises(collector.CollectionError):
                collector.sitemap_locations(data)
        with patch.object(collector, "MAX_XML_BYTES", 128):
            with self.assertRaisesRegex(collector.CollectionError, "size limit"):
                collector.sitemap_locations(gzip.compress(b" " * 129))

    def test_service_limits_reject_invalid_recipe_values(self):
        for field, value in (("servings", 101), ("cook_minutes", 10001), ("title", "x" * 201)):
            with self.subTest(field=field):
                recipe = importer.import_from_html(recipe_page("Valid").decode(), FOOD)
                setattr(recipe, field, value)
                with self.assertRaises(collector.CollectionError):
                    collector.archive_recipe(recipe, False)

    def test_source_ingredient_formats_preserve_amount_and_product(self):
        examples = [
            ("Чеснок 2 зубчик = 10 г", "Чеснок", 10, "г"),
            ("Укроп 1 пучок = 15 г", "Укроп", 15, "г"),
            ("Маринованные огурцы 3 шт. = 150 г", "Маринованные огурцы", 150, "г"),
            ("Красный лук, 1 головка", "Красный лук", 1, "шт"),
            ("Сливки 20%-ные, 200 мл", "Сливки 20%-ные", 200, "мл"),
            ("Соль по вкусу", "Соль", None, "по вкусу"),
        ]
        for line, product, amount, unit in examples:
            with self.subTest(line=line):
                parsed = importer.parse_ingredient(line)
                self.assertEqual((parsed.product, parsed.amount, parsed.unit), (product, amount, unit))


class ClientTests(unittest.TestCase):
    @staticmethod
    def redirect_failure(url: str, target: str):
        try:
            raise urllib.error.HTTPError(url, 301, "Moved", {"Location": target}, None)
        except urllib.error.HTTPError as http_error:
            http_error.close()
            try:
                raise importer.ImportError_("Site returned HTTP 301")
            except importer.ImportError_ as error:
                return error

    @staticmethod
    def http_failure(status: int):
        # Preserve the exception chain produced by the real importer.
        try:
            raise urllib.error.HTTPError(FOOD, status, "Test status", {}, None)
        except urllib.error.HTTPError as http_error:
            http_error.close()
            try:
                raise importer.ImportError_(f"Site returned HTTP {status}")
            except importer.ImportError_ as error:
                return error

    def test_missing_robots_allows_page_and_robots_is_cached(self):
        with patch.object(importer, "fetch", side_effect=[self.http_failure(404),
                          (b"Page", "text/html", FOOD), (b"Page", "text/html", FOOD)]) as fetch:
            with patch.object(collector.time, "sleep"):
                client = collector.Client(2, 2)
                self.assertEqual(client.fetch(FOOD, 100)[0], b"Page")
                client.fetch(FOOD, 100)
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(fetch.call_args_list[0].args[0], "https://food.ru/robots.txt")
        self.assertEqual(fetch.call_args_list[1].kwargs["user_agent"], collector.USER_AGENT)
        self.assertFalse(fetch.call_args_list[1].kwargs["allow_redirects"])

    def test_robots_disallow_prevents_page_request(self):
        robots = b"User-agent: *\nDisallow: /recipes/\n"
        with patch.object(importer, "fetch", return_value=(robots, "text/plain", "https://food.ru/robots.txt")) as fetch:
            with patch.object(collector.time, "sleep"):
                with self.assertRaisesRegex(collector.CollectionError, "disallows"):
                    collector.Client(2, 2).fetch(FOOD, 100)
        self.assertEqual(fetch.call_count, 1)

    def test_page_fetch_follows_a_canonical_slash_redirect_without_enabling_general_redirects(self):
        target = FOOD + "/"
        with patch.object(importer, "fetch", side_effect=[(b"User-agent: *\nAllow: /", "text/plain", "https://food.ru/robots.txt"),
                          self.redirect_failure(FOOD, target), (b"Page", "text/html", target)]) as fetch:
            with patch.object(collector.time, "sleep"):
                self.assertEqual(collector.Client(0, 0).fetch(FOOD, 100), (b"Page", "text/html", target))
        self.assertEqual([call.args[0] for call in fetch.call_args_list], ["https://food.ru/robots.txt", FOOD, target])
        self.assertTrue(all(not call.kwargs["allow_redirects"] for call in fetch.call_args_list))

    def test_canonical_slash_target_is_checked_against_robots_before_request(self):
        robots = b"User-agent: *\nDisallow: /recipes/1-test/$\n"
        with patch.object(importer, "fetch", side_effect=[(robots, "text/plain", "https://food.ru/robots.txt"),
                          self.redirect_failure(FOOD, FOOD + "/")]) as fetch:
            with patch.object(collector.time, "sleep"):
                with self.assertRaisesRegex(collector.CollectionError, "robots.txt disallows"):
                    collector.Client(0, 0).fetch(FOOD, 100)
        self.assertEqual([call.args[0] for call in fetch.call_args_list], ["https://food.ru/robots.txt", FOOD])

    def test_canonical_slash_redirect_loop_is_bounded(self):
        def response(url, *args, **kwargs):
            if url.endswith("/robots.txt"):
                return b"User-agent: *\nAllow: /", "text/plain", url
            raise self.redirect_failure(url, FOOD if url.endswith("/") else FOOD + "/")

        with patch.object(importer, "fetch", side_effect=response) as fetch, patch.object(collector.time, "sleep"):
            with self.assertRaisesRegex(collector.CollectionError, "redirect refused"):
                collector.Client(0, 3).fetch(FOOD, 100)
        self.assertEqual(fetch.call_count, 5)

    def test_page_fetch_refuses_redirects_that_change_host_path_query_or_scheme(self):
        targets = ["https://attacker.example.org/recipes/1-test/", "https://www.food.ru/recipes/1-test/",
                   "https://127.0.0.1/recipes/1-test/", "https://food.ru/recipes/other/", FOOD + "/?page=2",
                   "http://food.ru/recipes/1-test/", "https://user:fixture@food.ru/recipes/1-test/",
                   "https://food.ru:8443/recipes/1-test/", FOOD + "/#fragment"]
        for target in targets:
            with self.subTest(target=target):
                with patch.object(importer, "fetch", side_effect=[(b"User-agent: *\nAllow: /", "text/plain", "https://food.ru/robots.txt"),
                                  self.redirect_failure(FOOD, target)]) as fetch, patch.object(collector.time, "sleep"):
                    with self.assertRaisesRegex(collector.CollectionError, "redirect refused"):
                        collector.Client(0, 3).fetch(FOOD, 100)
                self.assertEqual(fetch.call_count, 2)

    def test_cover_uses_interface_downloader_without_robots_checks(self):
        cover = "https://cdn.food.ru/cover.jpg"
        context = ssl.create_default_context()
        client = collector.Client(2, 0, ssl_context=context)
        client.robots["https://cdn.food.ru"] = collector.RobotsRules(["User-agent: *", "Disallow: /"])
        with patch.object(importer, "fetch", return_value=(b"Image", "image/jpeg", cover)) as fetch, \
                patch.object(collector.time, "sleep"):
            self.assertEqual(client.fetch_cover(cover), (b"Image", "image/jpeg", cover))
        fetch.assert_called_once_with(cover, importer.MAX_IMAGE_BYTES, "image/*",
                                      user_agent=importer.USER_AGENT, allow_redirects=True, ssl_context=context)

    def test_cover_download_keeps_bounded_retries_and_host_blocking(self):
        cover = "https://cdn.food.ru/cover.jpg"
        with patch.object(importer, "fetch", side_effect=self.http_failure(503)) as fetch, \
                patch.object(collector.time, "sleep"):
            with self.assertRaises(collector.CollectionError):
                collector.Client(2, 2).fetch_cover(cover)
        self.assertEqual(fetch.call_count, 3)
        with patch.object(importer, "fetch", side_effect=self.http_failure(403)) as fetch, \
                patch.object(collector.time, "sleep"):
            client = collector.Client(2, 2)
            with self.assertRaises(collector.CollectionError):
                client.fetch_cover(cover)
            with self.assertRaisesRegex(collector.CollectionError, "stopped"):
                client.fetch_cover(cover)
        self.assertEqual(fetch.call_count, 1)

    def assert_robots_access(self, robots: bytes, cases: list[tuple[str, bool]]):
        def response(url, *args, **kwargs):
            if url.endswith("/robots.txt"):
                return robots, "text/plain", url
            return b"Page", "text/html", url

        with patch.object(importer, "fetch", side_effect=response), patch.object(collector.time, "sleep"):
            client = collector.Client(2, 0)
            for url, allowed in cases:
                with self.subTest(url=url):
                    if allowed:
                        self.assertEqual(client.fetch(url, 100)[0], b"Page")
                    else:
                        with self.assertRaisesRegex(collector.CollectionError, "disallows"):
                            client.fetch(url, 100)

    def test_robots_literal_query_prefix_does_not_block_plain_recipe_paths(self):
        robots = b"User-agent: *\nDisallow: /?\nDisallow: /*?tracking=*\n"
        self.assert_robots_access(robots, [
            (FOOD, True),
            ("https://food.ru/sitemaps/recipes-1.xml", True),
            ("https://food.ru/?tracking=test", False),
            (FOOD + "?tracking=test", False),
        ])

    def test_robots_wildcards_end_anchor_and_longest_rule_precedence(self):
        robots = (b"User-agent: *\nDisallow: /recipes/*\nAllow: /recipes/1-test$\n"
                  b"Allow: /recipes/open/\nDisallow: /recipes/open/private\n"
                  b"Disallow: /same\nAllow: /same\n")
        self.assert_robots_access(robots, [
            (FOOD, True),
            (FOOD + "/extra", False),
            ("https://food.ru/recipes/2-other", False),
            ("https://food.ru/recipes/open/sample", True),
            ("https://food.ru/recipes/open/private", False),
            ("https://food.ru/same", True),
        ])

    def test_robots_specific_user_agent_group_takes_precedence_over_wildcard(self):
        robots = (b"User-agent: *\nDisallow: /\n\n"
                  b"User-agent: MyRecipes-Collector\nAllow: /\nDisallow: /private\n\n"
                  b"User-agent: AnotherBot\nDisallow: /recipes/\n")
        self.assert_robots_access(robots, [(FOOD, True), ("https://food.ru/private", False)])

    def test_forbidden_or_rate_limited_host_is_not_retried(self):
        for status in (403, 429):
            with self.subTest(status=status):
                with patch.object(importer, "fetch", side_effect=self.http_failure(status)) as fetch:
                    with patch.object(collector.time, "sleep"):
                        client = collector.Client(2, 3)
                        with self.assertRaises(collector.CollectionError):
                            client.request(FOOD, 100, "text/html")
                        with self.assertRaisesRegex(collector.CollectionError, "stopped"):
                            client.request(FOOD, 100, "text/html")
                self.assertEqual(fetch.call_count, 1)

    def test_server_errors_have_bounded_retries(self):
        with patch.object(importer, "fetch", side_effect=self.http_failure(503)) as fetch:
            with patch.object(collector.time, "sleep"):
                with self.assertRaises(collector.CollectionError):
                    collector.Client(2, 2).request(FOOD, 100, "text/html")
        self.assertEqual(fetch.call_count, 3)

    def test_redirect_responses_are_rejected_without_retries(self):
        for status in (301, 302):
            with self.subTest(status=status):
                with patch.object(importer, "fetch", side_effect=self.http_failure(status)) as fetch:
                    with patch.object(collector.time, "sleep"):
                        with self.assertRaisesRegex(collector.CollectionError, "redirect refused"):
                            collector.Client(2, 3).request(FOOD, 100, "text/html")
                self.assertEqual(fetch.call_count, 1)
                self.assertFalse(fetch.call_args.kwargs["allow_redirects"])

    def test_certificate_verification_error_fails_immediately_with_actionable_message(self):
        try:
            raise urllib.error.URLError(ssl.SSLCertVerificationError(1, "Certificate is not trusted"))
        except urllib.error.URLError:
            try:
                raise importer.ImportError_("Could not open page")
            except importer.ImportError_ as exc:
                failure = exc
        with patch.object(importer, "fetch", side_effect=failure) as fetch:
            with patch.object(collector.time, "sleep"):
                with self.assertRaisesRegex(collector.CollectionError, "SSL_CERT_FILE"):
                    collector.Client(2, 3).request(FOOD, 100, "text/html")
        self.assertEqual(fetch.call_count, 1)

    def test_crawl_delay_is_used_for_following_requests(self):
        robots = b"User-agent: *\nAllow: /\nCrawl-delay: 7\n"
        with patch.object(importer, "fetch", side_effect=[(robots, "text/plain", "https://food.ru/robots.txt"),
                          (b"Page", "text/html", FOOD)]):
            with patch.object(collector.time, "sleep") as sleep, patch.object(collector.time, "monotonic", return_value=100):
                collector.Client(2, 0).fetch(FOOD, 100)
        self.assertEqual(sleep.call_args_list[-1].args[0], 7)


if __name__ == "__main__":
    unittest.main()
