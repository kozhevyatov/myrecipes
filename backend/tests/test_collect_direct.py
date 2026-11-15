"""Direct collection preserves saved recipes and records partial API failures."""
from __future__ import annotations

import contextlib
import getpass
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import collect_recipes as collector
from recipe_api import APIError
from recipe_sources import sources_from_data

FOOD = "https://food.ru/recipes/1-test"
SECOND = "https://food.ru/recipes/2-second"
THIRD = "https://food.ru/recipes/3-third"
COVER = "https://cdn.food.ru/cover.jpg"


def page(title: str) -> bytes:
    node = {
        "@type": "Recipe", "name": title, "recipeIngredient": ["Молоко 200 мл"],
        "recipeInstructions": ["Mix the ingredients."], "recipeYield": "4 порции", "image": COVER,
    }
    return ('<script type="application/ld+json">' + json.dumps(node) + "</script>").encode()


class SourceClient:
    def __init__(self, responses: dict):
        self.responses = responses
        self.calls: list[str] = []

    def fetch(self, url: str, limit: int, accept: str = "text/html"):
        self.calls.append(url)
        if url not in self.responses:
            raise collector.CollectionError("Fixture page not found")
        response = self.responses[url]
        if isinstance(response, BaseException):
            raise response
        return response, "image/jpeg" if url == COVER else "text/html", url

    def fetch_cover(self, url: str):
        return self.fetch(url, collector.importer.MAX_IMAGE_BYTES, "image/*")


class Service:
    def __init__(self, *, urls=(), titles=(), create_errors=None, cover_error=None, prepare_error=None):
        self.urls, self.titles = set(urls), set(titles)
        self.create_errors = create_errors or {}
        self.cover_error = cover_error
        self.prepare_error = prepare_error
        self.saved: list[dict] = []
        self.covers: list[int] = []
        self.prepared = False

    def login(self, login: str, password: str):
        pass

    def prepare(self):
        self.prepared = True
        if self.prepare_error:
            raise self.prepare_error
        return self.urls, self.titles

    def create_recipe(self, recipe: dict) -> int:
        error = self.create_errors.get(recipe["title"])
        if error:
            raise error
        self.saved.append(recipe)
        return len(self.saved)

    def upload_cover(self, recipe_id: int, image: bytes, content_type: str):
        if not self.saved:
            raise AssertionError("Cover uploaded before recipe creation")
        self.covers.append(recipe_id)
        if self.cover_error:
            raise self.cover_error


class DirectCollectionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.report_path = Path(self.directory.name) / "report.json"

    def options(self, *extra: str):
        return collector.parser().parse_args([
            "--server", "http://localhost:1331", "--login", "test-user",
            "--report", str(self.report_path), *extra,
        ])

    def run_collection(self, args, sources, api):
        with contextlib.redirect_stderr(io.StringIO()):
            report = collector.collect(args, sources, api)
        self.assertEqual(report, json.loads(self.report_path.read_text(encoding="utf-8")))
        return report

    def test_recipe_is_saved_directly_before_cover_without_a_zip(self):
        api = Service()
        report = self.run_collection(self.options("--url", FOOD), SourceClient({FOOD: page("First"), COVER: b"image"}), api)
        self.assertEqual(report["created"], 1)
        self.assertEqual(report["recipes"][0]["id"], 1)
        self.assertEqual(api.covers, [1])
        self.assertFalse(api.saved[0]["is_public"])
        self.assertFalse(report["fatal"])
        self.assertEqual(list(Path(self.directory.name).iterdir()), [self.report_path])

    def test_service_sources_and_titles_are_skipped_on_repeated_runs(self):
        api = Service(urls=[FOOD + "?tracking=1"], titles=["EXISTING"])
        sources = SourceClient({SECOND: page("Existing")})
        report = self.run_collection(self.options("--url", FOOD, "--url", SECOND, "--no-images"), sources, api)
        self.assertEqual((report["created"], report["duplicates"]), (0, 2))
        self.assertEqual(sources.calls, [SECOND])
        self.assertEqual(api.saved, [])

    def test_unlimited_import_passes_the_previous_default_attempt_budget_and_bounds_report_details(self):
        args = self.options("--limit", "0", "--no-images")
        args.url = [f"https://food.ru/recipes/{index}-fixture" for index in range(501)]
        client = SourceClient({url: page(f"Recipe {index}") for index, url in enumerate(args.url)})
        with patch.object(collector, "MAX_REPORT_ENTRIES", 8):
            report = self.run_collection(args, client, Service())
        self.assertEqual(report["created"], 501)
        self.assertEqual(report["processed"], 501)
        self.assertEqual(report["attempted"], 501)
        self.assertEqual(report["stop_reason"], "exhausted")
        self.assertEqual(len(report["recipes"]), 8)
        self.assertEqual(report["recipes_omitted"], 493)
        self.assertTrue(report["details_truncated"])

    def test_repeated_homepage_import_skips_first_eight_and_reaches_new_paginated_recipes(self):
        urls = [f"https://food.ru/recipes/{index}-fixture" for index in range(10)]
        args = self.options("--limit", "0", "--site", "food", "--no-images")
        args.source_config = sources_from_data({"food": {
            "canonical_host": "food.ru", "hosts": ["food.ru"], "catalog_url": "https://food.ru/",
            "recipe_pattern": r"/recipes/\d+-[^/]+", "catalog_pattern": "/",
        }})
        pages = {"https://food.ru/": ("<html><a href='/recipes'>All recipes</a>" +
                   "".join(f"<a href='{url}'>Recipe</a>" for url in urls[:8]) + "</html>").encode(),
                 "https://food.ru/recipes": (f"<html><a href='{urls[8]}'>New</a><a href='?page=2'>Next</a></html>").encode(),
                 "https://food.ru/recipes?page=2": (f"<html><a href='{urls[9]}'>Newer</a></html>").encode(),
                 urls[8]: page("Ninth"), urls[9]: page("Tenth")}
        snapshots = []
        args.progress_callback = lambda report: snapshots.append((report["processed"], report["duplicates"]))
        client = SourceClient(pages)
        report = self.run_collection(args, client, Service(urls=urls[:8]))
        self.assertEqual((report["created"], report["duplicates"], report["processed"]), (2, 8, 10))
        self.assertEqual(report["stop_reason"], "exhausted")
        self.assertTrue(report["discovery_complete"])
        self.assertIn((8, 8), snapshots)
        self.assertFalse(any(url in client.calls for url in urls[:8]))

    def test_cover_rejection_keeps_the_saved_recipe_and_records_a_warning(self):
        api = Service(cover_error=APIError("Invalid image", fatal=False))
        report = self.run_collection(self.options("--url", FOOD), SourceClient({FOOD: page("First"), COVER: b"image"}), api)
        self.assertEqual(report["created"], 1)
        self.assertFalse(report["fatal"])
        self.assertEqual(report["errors"], [])
        self.assertIn("saved recipe 1", report["warnings"][0]["warning"])

    def test_fatal_cover_error_stops_after_recording_the_saved_id(self):
        api = Service(cover_error=APIError("Service unavailable"))
        sources = SourceClient({FOOD: page("First"), SECOND: page("Second"), COVER: b"image"})
        report = self.run_collection(self.options("--url", FOOD, "--url", SECOND), sources, api)
        self.assertTrue(report["fatal"])
        self.assertEqual(report["created"], 1)
        self.assertEqual(report["errors"][0]["saved_id"], 1)
        self.assertNotIn(SECOND, sources.calls)

    def test_failed_preparation_records_error_before_source_fetches(self):
        api = Service(prepare_error=APIError("Login expired"))
        sources = SourceClient({})
        report = self.run_collection(self.options("--url", FOOD), sources, api)
        self.assertTrue(report["fatal"])
        self.assertEqual((report["created"], sources.calls), (0, []))
        self.assertEqual(report["errors"][0]["stage"], "service")

    def test_fatal_create_error_preserves_earlier_records_and_stops(self):
        api = Service(create_errors={"Second": APIError("Write may have succeeded")})
        sources = SourceClient({FOOD: page("First"), SECOND: page("Second"), THIRD: page("Third")})
        args = self.options("--url", FOOD, "--url", SECOND, "--url", THIRD, "--no-images")
        report = self.run_collection(args, sources, api)
        self.assertTrue(report["fatal"])
        self.assertEqual(report["created"], 1)
        self.assertEqual(report["recipes"][0]["id"], 1)
        self.assertNotIn(THIRD, sources.calls)

    def test_keyboard_interrupt_flushes_partial_progress(self):
        api = Service(create_errors={"Second": KeyboardInterrupt()})
        sources = SourceClient({FOOD: page("First"), SECOND: page("Second")})
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(KeyboardInterrupt):
            collector.collect(self.options("--url", FOOD, "--url", SECOND, "--no-images"), sources, api)
        report = json.loads(self.report_path.read_text(encoding="utf-8"))
        self.assertTrue(report["interrupted"])
        self.assertEqual(report["created"], 1)
        self.assertEqual(report["recipes"][0]["id"], 1)

    def test_existing_report_is_preserved_before_api_preparation(self):
        self.report_path.write_text("Existing report", encoding="utf-8")
        api = Service()
        with self.assertRaises(FileExistsError):
            collector.collect(self.options("--url", FOOD), SourceClient({}), api)
        self.assertFalse(api.prepared)
        self.assertEqual(self.report_path.read_text(encoding="utf-8"), "Existing report")

    def test_nonfatal_create_rejection_does_not_block_later_recipe(self):
        api = Service(create_errors={"First": APIError("Validation failed", fatal=False)})
        sources = SourceClient({FOOD: page("First"), SECOND: page("Second")})
        args = self.options("--url", FOOD, "--url", SECOND, "--no-images", "--public")
        report = self.run_collection(args, sources, api)
        self.assertFalse(report["fatal"])
        self.assertEqual((report["created"], len(report["errors"])), (1, 1))
        self.assertTrue(api.saved[0]["is_public"])

    def test_main_duplicate_only_run_succeeds_and_no_echo_fallback_is_allowed(self):
        args = ["--server", "http://localhost:1331", "--login", "test-user", "--url", FOOD,
                "--report", str(self.report_path)]
        api = Service(urls=[FOOD])
        with patch.object(collector, "RecipeAPI", return_value=api), \
             patch.object(collector.getpass, "getpass", return_value="synthetic-test-password"), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(collector.main(args), 0)
        self.report_path.unlink()
        with patch.object(collector, "RecipeAPI", return_value=Service()), \
             patch.object(collector.getpass, "getpass", side_effect=getpass.GetPassWarning("No secure terminal")), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(collector.main(args), 1)
        self.assertFalse(self.report_path.exists())


if __name__ == "__main__":
    unittest.main()
