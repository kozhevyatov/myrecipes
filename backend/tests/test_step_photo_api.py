"""Targeted step-photo writes preserve recipe content and existing images."""
from __future__ import annotations

import ast
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException
from sqlalchemy import DateTime, ForeignKey, Integer, String, create_engine, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship

from app.schemas import StepOut
from recipe_api import APIError, OwnedStep, RecipeAPI


class Base(DeclarativeBase):
    pass


class Recipe(Base):
    __tablename__ = "test_recipes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String)
    author_id: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    steps: Mapped[list[RecipeStep]] = relationship(back_populates="recipe")

    def image_names(self):
        return {step.image for step in self.steps if step.image}


class RecipeStep(Base):
    __tablename__ = "test_recipe_steps"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("test_recipes.id"))
    position: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(String)
    timer_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image: Mapped[str | None] = mapped_column(String, nullable=True)
    recipe: Mapped[Recipe] = relationship(back_populates="steps")


def load_route(namespace):
    # Compile the real route without importing application configuration or runtime credentials.
    source = Path(__file__).parents[1] / "app" / "routers" / "recipes.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    functions = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in ("_step_out", "upload_step_image"):
            node.decorator_list = []
            node.args.defaults = []
            functions.append(node)
    isolated = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *functions], type_ignores=[])
    exec(compile(ast.fix_missing_locations(isolated), str(source), "exec"), namespace)
    return namespace["upload_step_image"]


class StepImageRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.recipe = Recipe(id=10, title="Keep this title", author_id=1, updated_at=datetime(2020, 1, 1))
        self.step = RecipeStep(id=20, position=0, text="Keep this step text", timer_minutes=7, image=None)
        self.recipe.steps = [self.step]
        self.db.add(self.recipe)
        self.db.commit()
        self.deleted = []
        self.saved = []

        def editable(db, recipe_id, user):
            recipe = db.get(Recipe, recipe_id)
            if recipe is None:
                raise HTTPException(404, "Missing recipe")
            if recipe.author_id != user.id:
                raise HTTPException(403, "Not editable")
            return recipe

        async def save_image(file):
            self.saved.append(file)
            return "new-step.webp"

        self.namespace = {"RecipeStep": RecipeStep, "StepOut": StepOut, "HTTPException": HTTPException,
                          "SQLAlchemyError": SQLAlchemyError, "select": select, "update": update,
                          "_get_editable": editable, "save_image": save_image, "delete_image": self.deleted.append,
                          "utcnow": lambda: datetime.now(timezone.utc),
                          "image_url": lambda image: f"/api/uploads/{image}" if image else None,
                          "thumb_url": lambda image: f"/api/uploads/{image}-sm" if image else None}
        self.route = load_route(self.namespace)
        self.user = SimpleNamespace(id=1)

    async def invoke(self, step_id=20, only_if_missing=True, user=None):
        return await self.route(10, step_id, object(), only_if_missing, self.db, user or self.user)

    async def test_step_image_update_preserves_text_timer_and_recipe_fields(self):
        result = await self.invoke()
        self.assertEqual(result.image, "new-step.webp")
        self.assertEqual((self.step.text, self.step.timer_minutes), ("Keep this step text", 7))
        self.assertEqual((self.recipe.title, self.recipe.author_id), ("Keep this title", 1))
        self.assertEqual(len(self.recipe.steps), 1)
        self.assertEqual(self.deleted, [])

    async def test_existing_step_photo_is_left_unchanged_without_reading_upload(self):
        self.step.image = "existing.webp"
        self.db.commit()
        result = await self.invoke()
        self.assertEqual(result.image, "existing.webp")
        self.assertEqual(self.saved, [])
        self.assertEqual(self.deleted, [])

    async def test_concurrent_photo_is_not_replaced_and_unused_upload_is_cleaned(self):
        async def save_during_manual_edit(file):
            self.db.execute(update(RecipeStep).where(RecipeStep.id == 20).values(image="manual.webp")
                            .execution_options(synchronize_session=False))
            self.db.commit()
            return "new-step.webp"
        self.namespace["save_image"] = save_during_manual_edit
        result = await self.invoke()
        self.assertEqual(result.image, "manual.webp")
        self.assertEqual(self.deleted, ["new-step.webp"])

    async def test_database_failure_cleans_new_photo_and_keeps_existing_photo(self):
        self.step.image = "existing.webp"
        self.db.commit()
        with patch.object(self.db, "commit", side_effect=SQLAlchemyError("Synthetic database failure")):
            with self.assertRaises(HTTPException) as raised:
                await self.invoke(only_if_missing=False)
        self.assertEqual(raised.exception.status_code, 500)
        self.assertEqual(self.deleted, ["new-step.webp"])
        self.assertEqual(self.step.image, "existing.webp")

    async def test_step_from_another_recipe_is_rejected_before_upload(self):
        with self.assertRaises(HTTPException) as raised:
            await self.invoke(step_id=99)
        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(self.saved, [])

    async def test_non_owner_is_rejected_before_upload(self):
        with self.assertRaises(HTTPException) as raised:
            await self.invoke(user=SimpleNamespace(id=2))
        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(self.saved, [])


class StepImageClientTests(unittest.TestCase):
    def setUp(self):
        self.api = RecipeAPI("http://localhost:1331")

    def test_fresh_steps_preserve_ids_text_and_image_presence(self):
        self.api.request = Mock(return_value={"steps": [
            {"id": 20, "text": "Mix.", "image_url": None},
            {"id": 21, "text": "Bake.", "image": "existing.webp"},
        ]})
        self.assertEqual(self.api.recipe_steps(10), (OwnedStep(20, "Mix.", False), OwnedStep(21, "Bake.", True)))
        self.api.request.assert_called_once_with("GET", "/api/recipes/10")

    def test_step_upload_targets_existing_id_and_missing_only_parameter(self):
        self.api.request = Mock(return_value={"id": 20})
        self.api.upload_step_image(10, 20, b"synthetic image", "image/jpeg")
        method, path, body, content_type = self.api.request.call_args.args
        self.assertEqual((method, path), ("POST", "/api/recipes/10/steps/20/image?only_if_missing=true"))
        self.assertIn(b'name="file"; filename="step.img"', body)
        self.assertIn(b"synthetic image", body)
        self.assertIn("multipart/form-data; boundary=", content_type)

    def test_old_service_reports_required_update_without_retrying(self):
        for status in (404, 405):
            with self.subTest(status=status):
                self.api.request = Mock(side_effect=APIError(
                    f"Service API POST /api/recipes/10/steps/20/image returned HTTP {status}", fatal=False))
                with self.assertRaisesRegex(APIError, "update the running service") as raised:
                    self.api.upload_step_image(10, 20, b"synthetic image", "image/jpeg")
                self.assertTrue(raised.exception.fatal)
                self.assertEqual(self.api.request.call_count, 1)

    def test_preflight_rejects_missing_wrong_method_or_malformed_step_route(self):
        path = "/api/recipes/{recipe_id}/steps/{step_id}/image"
        invalid = [[], {}, {"paths": []}, {"paths": {}}, {"paths": {path: None}},
                   {"paths": {path: {"get": {}}}}, {"paths": {path: {"post": None}}}]
        for specification in invalid:
            with self.subTest(specification=specification):
                self.api.request = Mock(return_value=specification)
                with self.assertRaisesRegex(APIError, "running service does not support step-photo uploads") as raised:
                    self.api.ensure_step_images_supported()
                self.assertTrue(raised.exception.fatal)
                self.assertFalse(self.api.step_images_checked)
                self.api.request.assert_called_once_with("GET", "/openapi.json", authenticated=False, refresh=False)

    def test_preflight_accepts_post_step_route_without_authentication_or_writes(self):
        path = "/api/recipes/{recipe_id}/steps/{step_id}/image"
        self.api.request = Mock(return_value={"paths": {path: {"post": {"responses": {}}}}})
        self.api.ensure_step_images_supported()
        self.assertTrue(self.api.step_images_checked)
        self.api.request.assert_called_once_with("GET", "/openapi.json", authenticated=False, refresh=False)

    def test_required_step_support_is_checked_before_category_or_recipe_reads(self):
        api = RecipeAPI("http://localhost:1331", require_step_images=True)
        api.request = Mock(return_value={"paths": {}})
        with self.assertRaises(APIError):
            api.prepare()
        api.request.assert_called_once_with("GET", "/openapi.json", authenticated=False, refresh=False)

    def test_optional_step_support_does_not_require_openapi_for_cover_only_runs(self):
        self.api.request = Mock(side_effect=[[], {"items": [], "total": 0}])
        self.assertEqual(self.api.prepare(), (set(), set()))
        self.assertFalse(self.api.step_images_checked)
        self.assertEqual(self.api.request.call_args_list[0].args, ("GET", "/api/categories"))
        self.assertFalse(any(call.args[1] == "/openapi.json" for call in self.api.request.call_args_list))

    def test_missing_step_after_successful_preflight_reports_deleted_step(self):
        self.api.step_images_checked = True
        self.api.request = Mock(side_effect=APIError(
            "Service API POST /api/recipes/10/steps/20/image returned HTTP 404", fatal=False))
        with self.assertRaisesRegex(APIError, "step no longer exists") as raised:
            self.api.upload_step_image(10, 20, b"synthetic image", "image/jpeg")
        self.assertTrue(raised.exception.fatal)
        self.assertNotIn("update the running service", str(raised.exception))
        self.assertEqual(self.api.request.call_count, 1)

    def test_malformed_step_details_fail_before_upload(self):
        for value in ([{"text": "Missing ID"}], [{"id": 20}], "Not a list"):
            with self.subTest(value=value):
                self.api.request = Mock(return_value={"steps": value})
                with self.assertRaises(APIError):
                    self.api.recipe_steps(10)


if __name__ == "__main__":
    unittest.main()
