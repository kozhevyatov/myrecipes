"""Missing-cover repair changes existing recipes without creating duplicate recipes."""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import collect_recipes as collector
from recipe_api import APIError

FOOD = "https://food.ru/recipes/9-ruletiki-s-syrom-i-maslinami"
SECOND = "https://food.ru/recipes/2-second"
RAMBLER = "https://eda.rambler.ru/recepty/pasta-picca/test-3"
COVER = "https://cdn.food.ru/cover.jpg"


def recipe_page(*, image=COVER) -> bytes:
    node = {
        "@type": "Recipe", "name": "Source recipe", "recipeIngredient": ["Milk 200 ml"],
        "recipeInstructions": ["Mix."], "recipeYield": "2", "image": image,
    }
    return ('<script type="application/ld+json">' + json.dumps(node) + "</script>").encode()


def owned(recipe_id, source_url, *, has_image=False, title="Existing recipe"):
    return SimpleNamespace(id=recipe_id, title=title, source_url=source_url, has_image=has_image)


class Sources:
    def __init__(self, pages=None, *, cover_error=None):
        self.pages = pages or {FOOD: recipe_page()}
        self.cover_error = cover_error
        self.calls = []
        self.cover_calls = []

    def fetch(self, url, limit, accept="text/html"):
        self.calls.append(url)
        value = self.pages[url]
        if isinstance(value, BaseException):
            raise value
        return value, "text/html", url

    def fetch_cover(self, url):
        self.cover_calls.append(url)
        if self.cover_error:
            raise self.cover_error
        return b"synthetic-image", "image/jpeg", url


class Service:
    def __init__(self, recipes, *, prepare_error=None, upload_errors=None, fresh_covers=()):
        self.owned_recipes = recipes
        self.prepare_error = prepare_error
        self.upload_errors = upload_errors or {}
        self.fresh_covers = set(fresh_covers)
        self.uploads = []
        self.checks = []
        self.prepared = False

    def prepare(self):
        self.prepared = True
        if self.prepare_error:
            raise self.prepare_error
        for recipe in self.owned_recipes:
            if recipe.id in self.fresh_covers:
                recipe.has_image = True
        return {r.source_url for r in self.owned_recipes if r.source_url}, {r.title.casefold() for r in self.owned_recipes}

    def recipe_has_cover(self, recipe_id):
        self.checks.append(recipe_id)
        return recipe_id in self.fresh_covers

    def create_recipe(self, item):
        raise AssertionError("Cover repair must never create a recipe")

    def upload_cover(self, recipe_id, image, content_type):
        if recipe_id in self.upload_errors:
            raise self.upload_errors[recipe_id]
        self.uploads.append((recipe_id, image, content_type))
        self.fresh_covers.add(recipe_id)


class BackfillImagesTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.report_path = Path(self.directory.name) / "repair-report.json"

    def options(self, *extra):
        return collector.parser().parse_args([
            "--server", "http://localhost:1331", "--login", "fixture-user", "--fill-missing-images",
            "--report", str(self.report_path), *extra,
        ])

    def run_repair(self, args, sources, api):
        with contextlib.redirect_stderr(io.StringIO()):
            report = collector.backfill_images(args, sources, api)
        self.assertEqual(report, json.loads(self.report_path.read_text(encoding="utf-8")))
        self.assertEqual(report["created"], 0)
        self.assertFalse(any(path.suffix == ".zip" for path in Path(self.directory.name).iterdir()))
        return report

    def test_fills_only_missing_cover_on_existing_recipe_id(self):
        existing = owned(16, FOOD, title="User-edited title")
        api = Service([existing, owned(20, SECOND, has_image=True)])
        sources = Sources()
        report = self.run_repair(self.options(), sources, api)
        self.assertEqual(report["updated_images"], 1)
        self.assertEqual([item[0] for item in api.uploads], [16])
        self.assertEqual(sources.calls, [FOOD])
        self.assertEqual(sources.cover_calls, [COVER])
        self.assertEqual(existing.title, "User-edited title")
        self.assertEqual(existing.source_url, FOOD)
        self.assertIn(16, api.checks)

    def test_zero_limit_repairs_all_selected_recipes_until_exhausted(self):
        api = Service([owned(16, FOOD), owned(20, SECOND)])
        sources = Sources({FOOD: recipe_page(), SECOND: recipe_page()})
        report = self.run_repair(self.options("--limit", "0", "--max-pages", "0"), sources, api)
        self.assertEqual(report["updated_images"], 2)
        self.assertEqual(report["attempted"], 2)
        self.assertEqual(report["stop_reason"], "exhausted")

    def test_site_filter_ignores_other_sources_and_unsupported_urls(self):
        api = Service([owned(1, FOOD), owned(2, RAMBLER), owned(3, "https://example.org/recipe"), owned(4, None)])
        sources = Sources()
        report = self.run_repair(self.options("--site", "food"), sources, api)
        self.assertEqual(report["updated_images"], 1)
        self.assertEqual([entry[0] for entry in api.uploads], [1])
        self.assertEqual(sources.calls, [FOOD])

    def test_explicit_urls_filter_uses_source_identity_instead_of_title(self):
        api = Service([owned(1, FOOD, title="Same title"), owned(2, SECOND, title="Same title")])
        sources = Sources()
        report = self.run_repair(self.options("--url", FOOD + "?tracking=1"), sources, api)
        self.assertEqual(report["updated_images"], 1)
        self.assertEqual([entry[0] for entry in api.uploads], [1])

    def test_ambiguous_duplicate_sources_are_not_guessed_or_uploaded(self):
        api = Service([owned(1, FOOD), owned(2, FOOD + "?tracking=1")])
        sources = Sources()
        report = self.run_repair(self.options(), sources, api)
        self.assertEqual(report["updated_images"], 0)
        self.assertGreaterEqual(report["skipped"], 2)
        self.assertEqual(api.uploads, [])
        self.assertEqual(sources.calls, [])

    def test_freshly_added_cover_is_not_replaced(self):
        api = Service([owned(1, FOOD)])
        sources = Sources()
        with patch.object(api, "recipe_has_cover", return_value=True) as fresh_check:
            report = self.run_repair(self.options(), sources, api)
        self.assertEqual(report["updated_images"], 0)
        fresh_check.assert_called_with(1)
        self.assertEqual(api.uploads, [])

    def test_sequential_rerun_does_not_upload_again(self):
        api = Service([owned(16, FOOD)])
        self.run_repair(self.options(), Sources(), api)
        self.report_path = Path(self.directory.name) / "second-report.json"
        sources = Sources()
        report = self.run_repair(self.options(), sources, api)
        self.assertEqual(report["updated_images"], 0)
        self.assertEqual(len(api.uploads), 1)
        self.assertEqual(sources.calls, [])

    def test_limits_bound_attempts_before_loading_more_recipes(self):
        for option in ("--limit", "--max-pages"):
            with self.subTest(option=option):
                self.report_path = Path(self.directory.name) / (option[2:] + ".json")
                api = Service([owned(1, FOOD), owned(2, SECOND)])
                sources = Sources({FOOD: recipe_page(), SECOND: recipe_page()})
                report = self.run_repair(self.options(option, "1"), sources, api)
                self.assertEqual(report["attempted"], 1)
                self.assertEqual(len(api.uploads), 1)
                self.assertEqual(len(sources.calls), 1)

    def test_missing_source_image_is_reported_without_a_write(self):
        api = Service([owned(1, FOOD)])
        report = self.run_repair(self.options(), Sources({FOOD: recipe_page(image=None)}), api)
        self.assertEqual(report["updated_images"], 0)
        self.assertTrue(report["warnings"] or report["errors"])
        self.assertEqual(api.uploads, [])

    def test_source_failure_does_not_prevent_later_repairs(self):
        api = Service([owned(1, FOOD), owned(2, SECOND)])
        sources = Sources({FOOD: collector.CollectionError("Source unavailable"), SECOND: recipe_page()})
        report = self.run_repair(self.options(), sources, api)
        self.assertEqual(report["updated_images"], 1)
        self.assertEqual([item[0] for item in api.uploads], [2])
        self.assertEqual(len(report["errors"]), 1)

    def test_fatal_upload_error_keeps_prior_updates_and_stops(self):
        api = Service([owned(1, FOOD), owned(2, SECOND), owned(3, RAMBLER)],
                      upload_errors={2: APIError("Uncertain write")})
        sources = Sources({FOOD: recipe_page(), SECOND: recipe_page(), RAMBLER: recipe_page()})
        report = self.run_repair(self.options(), sources, api)
        self.assertTrue(report["fatal"])
        self.assertEqual(report["updated_images"], 1)
        self.assertEqual([item[0] for item in api.uploads], [1])
        self.assertNotIn(RAMBLER, sources.calls)
        self.assertTrue(report["errors"])

    def test_interruption_checkpoints_completed_updates(self):
        api = Service([owned(1, FOOD), owned(2, SECOND)], upload_errors={2: KeyboardInterrupt()})
        sources = Sources({FOOD: recipe_page(), SECOND: recipe_page()})
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(KeyboardInterrupt):
            collector.backfill_images(self.options(), sources, api)
        report = json.loads(self.report_path.read_text(encoding="utf-8"))
        self.assertTrue(report["interrupted"])
        self.assertEqual(report["updated_images"], 1)

    def test_existing_report_is_never_overwritten(self):
        self.report_path.write_text("Original report", encoding="utf-8")
        api = Service([owned(1, FOOD)])
        with self.assertRaises(FileExistsError):
            collector.backfill_images(self.options(), Sources(), api)
        self.assertFalse(api.prepared)
        self.assertEqual(self.report_path.read_text(encoding="utf-8"), "Original report")

    def test_incompatible_modes_fail_before_requesting_a_password(self):
        invalid = [
            ["--output", str(Path(self.directory.name) / "recipes.zip"), "--fill-missing-images"],
            ["--server", "http://localhost:1331", "--login", "fixture-user", "--fill-missing-images", "--no-images"],
        ]
        for arguments in invalid:
            with self.subTest(arguments=arguments), patch.object(collector.getpass, "getpass") as password, \
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    collector.main(arguments)
                self.assertEqual(raised.exception.code, 2)
                password.assert_not_called()


if __name__ == "__main__":
    unittest.main()
