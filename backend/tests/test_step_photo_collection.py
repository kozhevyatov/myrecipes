"""Cooking photos remain attached to the matching step in collection and repair."""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import collect_recipes as collector
from app import importer
from recipe_api import APIError, OwnedStep

SOURCE = "https://food.ru/recipes/9-source"
COVER = "https://cdn.food.ru/cover.jpg"
FIRST = "https://cdn.food.ru/step-1.jpg"
SECOND = "https://cdn.food.ru/step-2.jpg"


def imported_recipe():
    recipe = importer.ImportedRecipe(
        title="Source recipe", servings=2, source_url=SOURCE, image_url=COVER,
        ingredients=[importer.ParsedIngredient("Milk", 100, "мл")],
        steps=["Prepare the ingredients.", "Mix and serve."],
    )
    recipe.step_images = [FIRST, SECOND]
    return recipe


class Sources:
    def __init__(self, errors=None):
        self.errors = errors or {}
        self.calls = []
        self.image_calls = []

    def fetch(self, url, limit, accept="text/html"):
        self.calls.append(url)
        return b"<html>Recipe fixture</html>", "text/html", url

    def fetch_cover(self, url):
        self.image_calls.append(url)
        if url in self.errors:
            raise self.errors[url]
        # The cover and first step intentionally share bytes to exercise ZIP deduplication.
        return b"second-photo" if url == SECOND else b"shared-photo", "image/jpeg", url


class Service:
    def __init__(self, *, existing=False, covered=False, steps=None, upload_errors=None, cover_error=None):
        self.covered = covered
        self.steps = list(steps if steps is not None else (
            OwnedStep(101, "Prepare the ingredients.", False),
            OwnedStep(202, "Mix and serve.", False),
        ))
        self.saved = []
        self.cover_uploads = []
        self.step_uploads = []
        self.upload_errors = upload_errors or {}
        self.cover_error = cover_error
        self.owned_recipes = ([SimpleNamespace(id=71, title="User title", source_url=SOURCE,
                                               has_image=covered, steps=tuple(self.steps))] if existing else [])

    def prepare(self):
        for recipe in self.owned_recipes:
            recipe.has_image = self.covered
            recipe.steps = tuple(self.steps)
        return {recipe.source_url for recipe in self.owned_recipes}, {recipe.title.casefold() for recipe in self.owned_recipes}

    def create_recipe(self, item):
        self.saved.append(item)
        return 71

    def recipe_has_cover(self, recipe_id):
        return self.covered

    def recipe_steps(self, recipe_id):
        return tuple(self.steps)

    def upload_cover(self, recipe_id, image, content_type):
        if self.cover_error:
            raise self.cover_error
        self.cover_uploads.append(recipe_id)
        self.covered = True

    def upload_step_image(self, recipe_id, step_id, image, content_type):
        if step_id in self.upload_errors:
            raise self.upload_errors[step_id]
        self.step_uploads.append((recipe_id, step_id))
        self.steps = [replace(step, has_image=True) if step.id == step_id else step for step in self.steps]


class StepPhotoCollectionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.report_path = self.root / "report.json"
        self.recipe = imported_recipe()

    def options(self, *extra):
        return collector.parser().parse_args([
            "--server", "http://localhost:1331", "--login", "fixture-user", "--url", SOURCE,
            "--report", str(self.report_path), *extra,
        ])

    def collect(self, args, sources, api):
        with patch.object(importer, "import_from_html", return_value=self.recipe), contextlib.redirect_stderr(io.StringIO()):
            report = collector.collect(args, sources, api)
        return report

    def repair(self, args, sources, api):
        with patch.object(importer, "import_from_html", return_value=self.recipe), contextlib.redirect_stderr(io.StringIO()):
            report = collector.backfill_images(args, sources, api)
        self.assertEqual(report, json.loads(self.report_path.read_text(encoding="utf-8")))
        return report

    def test_direct_import_uses_saved_step_ids_and_records_each_photo(self):
        service = Service()
        sources = Sources()
        report = self.collect(self.options(), sources, service)
        self.assertEqual(report["created"], 1)
        self.assertEqual(report["step_images"], 2)
        self.assertEqual(service.step_uploads, [(71, 101), (71, 202)])
        self.assertEqual(service.cover_uploads, [71])
        self.assertEqual(sources.image_calls, [COVER, FIRST, SECOND])
        self.assertEqual([step["text"] for step in service.saved[0]["steps"]], self.recipe.steps)

    def test_zip_contains_step_references_and_reuses_identical_image_bytes(self):
        archive_path = self.root / "recipes.zip"
        args = collector.parser().parse_args(["--url", SOURCE, "--output", str(archive_path)])
        report = self.collect(args, Sources(), None)
        self.assertEqual(report["step_images"], 2)
        with zipfile.ZipFile(archive_path) as archive:
            manifest = json.loads(archive.read("recipes.json"))
            recipe = manifest["recipes"][0]
            first, second = recipe["steps"]
            self.assertEqual(first["image"], recipe["image"])
            self.assertEqual(archive.read(first["image"]), b"shared-photo")
            self.assertEqual(archive.read(second["image"]), b"second-photo")
            self.assertEqual(len([name for name in archive.namelist() if name.startswith("images/")]), 2)

    def test_image_flags_control_step_and_cover_requests(self):
        for flag, expected in (("--no-step-images", [COVER]), ("--no-images", [])):
            with self.subTest(flag=flag):
                self.report_path = self.root / (flag[2:] + ".json")
                service, sources = Service(), Sources()
                report = self.collect(self.options(flag), sources, service)
                self.assertEqual(report["step_images"], 0)
                self.assertEqual(sources.image_calls, expected)
                self.assertEqual(service.step_uploads, [])

    def test_failed_step_download_keeps_recipe_and_other_step_photos(self):
        service = Service()
        report = self.collect(self.options(), Sources({FIRST: collector.CollectionError("Photo unavailable")}), service)
        self.assertEqual((report["created"], report["step_images"]), (1, 1))
        self.assertEqual(service.step_uploads, [(71, 202)])
        self.assertTrue(any("Step 1" in item["warning"] for item in report["warnings"]))

    def test_unknown_step_write_stops_after_checkpointing_completed_photo(self):
        service = Service(upload_errors={202: APIError("Write may have succeeded")})
        report = self.collect(self.options(), Sources(), service)
        self.assertTrue(report["fatal"])
        self.assertEqual((report["created"], report["step_images"]), (1, 1))
        saved = json.loads(self.report_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["recipes"][0]["step_images"], 1)

    def test_existing_step_photos_are_not_downloaded_or_replaced(self):
        service = Service(steps=[OwnedStep(101, self.recipe.steps[0], True), OwnedStep(202, self.recipe.steps[1], False)])
        sources = Sources()
        report = self.collect(self.options(), sources, service)
        self.assertEqual(report["step_images"], 1)
        self.assertEqual(service.step_uploads, [(71, 202)])
        self.assertNotIn(FIRST, sources.image_calls)

    def test_repair_fills_step_photos_even_when_recipe_already_has_cover(self):
        service = Service(existing=True, covered=True)
        report = self.repair(self.options("--fill-missing-images"), Sources(), service)
        self.assertEqual((report["created"], report["updated_images"], report["updated_step_images"]), (0, 0, 2))
        self.assertEqual(service.saved, [])
        self.assertEqual(service.cover_uploads, [])
        self.assertEqual(service.step_uploads, [(71, 101), (71, 202)])
        self.assertEqual(service.owned_recipes[0].title, "User title")

    def test_repair_does_not_attach_photos_to_edited_or_reordered_steps(self):
        for steps in ([OwnedStep(101, "User edited text.", False), OwnedStep(202, self.recipe.steps[1], False)],
                      [OwnedStep(202, self.recipe.steps[1], False), OwnedStep(101, self.recipe.steps[0], False)]):
            with self.subTest(steps=steps):
                self.report_path = self.root / f"edited-{steps[0].id}.json"
                service = Service(existing=True, covered=True, steps=steps)
                report = self.repair(self.options("--fill-missing-images"), Sources(), service)
                self.assertEqual(report["updated_step_images"], 0)
                self.assertEqual(service.step_uploads, [])
                self.assertTrue(any("differs" in item["warning"] for item in report["warnings"]))

    def test_repair_preserves_existing_step_photo_and_fills_only_the_missing_one(self):
        service = Service(existing=True, covered=True, steps=[
            OwnedStep(101, self.recipe.steps[0], True), OwnedStep(202, self.recipe.steps[1], False),
        ])
        sources = Sources()
        report = self.repair(self.options("--fill-missing-images"), sources, service)
        self.assertEqual(report["updated_step_images"], 1)
        self.assertEqual(service.step_uploads, [(71, 202)])
        self.assertEqual(sources.image_calls, [SECOND])
        self.assertEqual(service.saved, [])

    def test_repair_cover_validation_failure_does_not_prevent_step_photo_updates(self):
        service = Service(existing=True, covered=False, cover_error=APIError("Invalid cover", fatal=False))
        report = self.repair(self.options("--fill-missing-images"), Sources(), service)
        self.assertEqual((report["updated_images"], report["updated_step_images"]), (0, 2))
        self.assertFalse(report["fatal"])
        self.assertEqual(service.cover_uploads, [])
        self.assertEqual(service.step_uploads, [(71, 101), (71, 202)])
        self.assertEqual(service.saved, [])
        self.assertEqual(service.owned_recipes[0].title, "User title")
        self.assertEqual([step.text for step in service.steps], self.recipe.steps)
        self.assertTrue(any("Invalid cover" in item["warning"] for item in report["warnings"]))

    def test_repair_sequential_rerun_keeps_existing_ids_without_duplicate_uploads(self):
        service = Service(existing=True, covered=True)
        self.repair(self.options("--fill-missing-images"), Sources(), service)
        self.report_path = self.root / "second-report.json"
        report = self.repair(self.options("--fill-missing-images"), Sources(), service)
        self.assertEqual((report["created"], report["updated_step_images"]), (0, 0))
        self.assertEqual(service.step_uploads, [(71, 101), (71, 202)])
        self.assertEqual(service.saved, [])


if __name__ == "__main__":
    unittest.main()
