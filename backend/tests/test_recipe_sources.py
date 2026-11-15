"""Source configuration and URL matching work without site-specific Python changes."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

import recipe_sources
from recipe_sources import load_sources, normalize_recipe_url


def configuration():
    return {
        "example": {
            "canonical_host": "www.recipes.example.org",
            "hosts": ["recipes.example.org", "www.recipes.example.org"],
            "catalog_url": "https://www.recipes.example.org/catalog",
            "recipe_pattern": r"/recipe/\d+",
            "catalog_pattern": r"/catalog(?:/\d+)?",
            "aliases": ["example-old"],
        }
    }


class RecipeSourceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "sources.json"

    def load(self, value):
        self.path.write_text(json.dumps(value), encoding="utf-8")
        return load_sources(self.path)

    def test_default_sources_normalize_all_three_sites(self):
        sources = load_sources()
        examples = {
            "http://www.food.ru/recipes/1-test/?utm_source=test#fragment": "https://food.ru/recipes/1-test",
            "https://eda.rambler.ru/recepty/pasta-picca/test-2": "https://eda.rambler.ru/recepty/pasta-picca/test-2",
            "http://iamcook.ru/showrecipe/44502/?tracking=1#photo": "https://www.iamcook.ru/showrecipe/44502",
            "https://www.iamcook.ru/showrecipe/44502": "https://www.iamcook.ru/showrecipe/44502",
        }
        for url, expected in examples.items():
            with self.subTest(url=url):
                self.assertEqual(normalize_recipe_url(url, sources), expected)

    def test_custom_source_is_usable_without_python_changes(self):
        sources = self.load(configuration())
        self.assertEqual(sources.canonical_name("example-old"), "example")
        self.assertIs(sources["example-old"], sources["example"])
        self.assertEqual(
            normalize_recipe_url("http://recipes.example.org/recipe/123?utm_source=test#photo", sources),
            "https://www.recipes.example.org/recipe/123",
        )
        self.assertIsNone(normalize_recipe_url("https://food.ru/recipes/1-test", sources))
        self.assertIsNone(normalize_recipe_url("https://www.recipes.example.org/catalog", sources))

    def test_legacy_iamcook_alias_selects_the_canonical_source(self):
        sources = load_sources()
        self.assertEqual(sources.canonical_name("amcook"), "iamcook")
        self.assertIs(sources["amcook"], sources["iamcook"])

    def test_catalog_query_strings_are_preserved_in_configuration(self):
        value = configuration()
        value["example"]["catalog_url"] += "?page=2"
        sources = self.load(value)
        self.assertEqual(sources["example"].catalog_url, "https://www.recipes.example.org/catalog?page=2")

    def test_sites_with_canonical_trailing_slashes_keep_fetchable_recipe_urls(self):
        value = configuration()
        value["example"]["recipe_trailing_slash"] = True
        sources = self.load(value)
        self.assertEqual(
            normalize_recipe_url("https://recipes.example.org/recipe/123?tracking=1", sources),
            "https://www.recipes.example.org/recipe/123/",
        )
        value["example"]["recipe_trailing_slash"] = "true"
        with self.assertRaisesRegex(ValueError, "must be a boolean"):
            self.load(value)

    def test_untrusted_or_non_recipe_urls_are_rejected(self):
        sources = self.load(configuration())
        for url in (
            "https://www.recipes.example.org.attacker.test/recipe/123",
            "https://user:synthetic@www.recipes.example.org/recipe/123",
            "https://www.recipes.example.org:8443/recipe/123",
            "file:///recipe/123",
            "https://127.0.0.1/recipe/123",
            "https://www.recipes.example.org/recipe/123/extra",
            "https://www.recipes.example.org/recipe/not-a-number",
        ):
            with self.subTest(url=url):
                self.assertIsNone(normalize_recipe_url(url, sources))

    def test_invalid_configuration_shapes_and_patterns_fail_explicitly(self):
        cases = [[], {}, {"example": []}]
        for field, value in (
            ("hosts", "recipes.example.org"),
            ("hosts", []),
            ("canonical_host", "outside.example.org"),
            ("recipe_pattern", "["),
            ("catalog_pattern", "["),
            ("catalog_url", "https://outside.example.org/catalog"),
            ("catalog_url", "file:///catalog"),
            ("catalog_url", "https://user:synthetic@www.recipes.example.org/catalog"),
            ("aliases", "example-old"),
        ):
            value_config = configuration()
            value_config["example"][field] = value
            cases.append(value_config)
        missing = configuration()
        del missing["example"]["recipe_pattern"]
        cases.append(missing)
        for index, value in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.load(value)

    def test_alias_and_host_collisions_are_rejected(self):
        for collision in ("alias", "host"):
            value = configuration()
            second = copy.deepcopy(value["example"])
            if collision == "alias":
                second.update(canonical_host="other.example.org", hosts=["other.example.org"],
                              catalog_url="https://other.example.org/catalog")
            else:
                second["aliases"] = []
            value["second"] = second
            with self.subTest(collision=collision), self.assertRaises(ValueError):
                self.load(value)

    def test_broken_json_and_missing_files_fail_actionably(self):
        self.path.write_text("{broken-json", encoding="utf-8")
        with self.assertRaises(ValueError):
            load_sources(self.path)
        with self.assertRaises((ValueError, OSError)):
            load_sources(self.path.with_name("missing.json"))


if __name__ == "__main__":
    unittest.main()
