"""Custom source settings propagate through direct collection, deduplication and cover repair."""
from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import collect_recipes as collector
from recipe_sources import load_sources

HOST = "https://www.recipes.example.org"
URL = HOST + "/recipe/123"
COVER = HOST + "/cover.jpg"


def recipe_page():
    node = {
        "@type": "Recipe", "name": "Custom recipe", "recipeYield": "2",
        "recipeIngredient": ["Milk 100 ml"], "recipeInstructions": ["Mix."], "image": COVER,
    }
    return ('<script type="application/ld+json">' + json.dumps(node) + "</script>").encode()


class SourceClient:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []
        self.covers = []

    def fetch(self, url, limit, accept="text/html"):
        self.calls.append(url)
        return self.pages[url], "text/html", url

    def fetch_cover(self, url):
        self.covers.append(url)
        return b"synthetic-cover", "image/jpeg", url


class Service:
    def __init__(self, existing_urls=(), owned_recipes=()):
        self.existing_urls = set(existing_urls)
        self.owned_recipes = list(owned_recipes)
        self.saved = []
        self.uploads = []

    def login(self, login, password):
        pass

    def prepare(self):
        return self.existing_urls, set()

    def create_recipe(self, recipe):
        self.saved.append(recipe)
        return 1234

    def recipe_has_cover(self, recipe_id):
        return any(recipe.id == recipe_id and recipe.has_image for recipe in self.owned_recipes)

    def upload_cover(self, recipe_id, image, content_type):
        self.uploads.append((recipe_id, image, content_type))


class SourceConfigurationIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.config_path = self.root / "custom-sources.json"
        self.config_path.write_text(json.dumps({"example": {
            "canonical_host": "www.recipes.example.org",
            "hosts": ["www.recipes.example.org", "recipes.example.org"],
            "catalog_url": HOST + "/catalog",
            "recipe_pattern": r"/recipe/\d+", "catalog_pattern": r"/catalog",
            "aliases": ["example-old"],
        }}), encoding="utf-8")
        self.sources = load_sources(self.config_path)
        self.report_path = self.root / "report.json"

    def options(self, *extra):
        return collector.parser(self.sources).parse_args([
            "--server", "http://localhost:1331", "--login", "fixture-user",
            "--report", str(self.report_path), *extra,
        ])

    def test_main_loads_custom_configuration_and_saves_discovered_recipe_with_cover(self):
        client = SourceClient({HOST + "/catalog": b'<html><a href="/recipe/123">Recipe</a></html>', URL: recipe_page()})
        api = Service()
        arguments = ["--sources-file", str(self.config_path), "--site", "example-old", "--limit", "1",
                     "--server", "http://localhost:1331", "--login", "fixture-user", "--report", str(self.report_path)]
        with patch.object(collector, "RecipeAPI", return_value=api), \
                patch.object(collector, "Client", return_value=client), \
                patch.object(collector, "configure_tls", return_value=(None, "TLS: synthetic test trust")), \
                patch.object(collector.getpass, "getpass", return_value="synthetic-test-password"), \
                contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(collector.main(arguments), 0)
        report = json.loads(self.report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["created"], 1)
        self.assertEqual(api.saved[0]["source_url"], URL)
        self.assertEqual(api.uploads[0][0], 1234)
        self.assertEqual(client.calls, [HOST + "/catalog", URL])
        self.assertEqual(client.covers, [COVER])

    def test_custom_source_normalization_is_used_for_existing_recipe_deduplication(self):
        api = Service(existing_urls=["http://recipes.example.org/recipe/123?old_tracking=1"])
        client = SourceClient({})
        args = self.options("--url", URL + "?new_tracking=1", "--no-images")
        with contextlib.redirect_stderr(io.StringIO()):
            report = collector.collect(args, client, api)
        self.assertEqual((report["created"], report["duplicates"]), (0, 1))
        self.assertEqual(client.calls, [])
        self.assertEqual(api.saved, [])

    def test_explicit_config_recovers_when_bundled_settings_are_missing(self):
        script = (
            "import sys; from pathlib import Path; import recipe_sources; "
            "recipe_sources.DEFAULT_SOURCES_FILE = Path(sys.argv[1]); "
            "import collect_recipes; "
            "raise SystemExit(collect_recipes.main(['--sources-file', sys.argv[2], '--help']))"
        )
        result = subprocess.run([sys.executable, "-B", "-c", script, str(self.root / "missing.json"),
                                 str(self.config_path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("example-old", result.stdout)

    def test_missing_default_configuration_reports_an_actionable_error(self):
        script = (
            "import sys; from pathlib import Path; import recipe_sources; "
            "recipe_sources.DEFAULT_SOURCES_FILE = Path(sys.argv[1]); "
            "import collect_recipes; raise SystemExit(collect_recipes.main([]))"
        )
        result = subprocess.run([sys.executable, "-B", "-c", script, str(self.root / "missing.json")],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Source configuration failed", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_custom_source_alias_and_url_filters_work_for_existing_cover_repair(self):
        recipe = SimpleNamespace(id=71, title="Existing custom recipe", has_image=False,
                                 source_url="http://recipes.example.org/recipe/123?old_tracking=1")
        api = Service(owned_recipes=[recipe])
        client = SourceClient({URL: recipe_page()})
        args = self.options("--fill-missing-images", "--site", "example-old", "--url", URL)
        with contextlib.redirect_stderr(io.StringIO()):
            report = collector.backfill_images(args, client, api)
        self.assertEqual((report["created"], report["updated_images"]), (0, 1))
        self.assertEqual(api.saved, [])
        self.assertEqual([entry[0] for entry in api.uploads], [71])
        self.assertEqual(client.calls, [URL])
        self.assertEqual(client.covers, [COVER])
        self.assertEqual(report["recipes"][0]["source_url"], URL)


if __name__ == "__main__":
    unittest.main()
