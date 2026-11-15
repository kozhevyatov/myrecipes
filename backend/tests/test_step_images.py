"""Step photographs remain paired with the text that describes them."""
from __future__ import annotations

import json
import unittest

from app import importer


def page(instructions, body="", **fields):
    node = {"@type": "Recipe", "name": "Sample", "recipeInstructions": instructions}
    node.update(fields)
    return '<script type="application/ld+json">' + json.dumps(node) + "</script>" + body


class StepImageTests(unittest.TestCase):
    def test_jsonld_nested_sections_and_image_shapes_keep_exact_alignment(self):
        instructions = [
            {"@type": "HowToSection", "name": "Preparation", "itemListElement": [
                {"@type": "HowToStep", "text": "1. Wash.", "image": "/wash.jpg"},
                {"@type": "HowToStep", "text": "2. Cut.", "image": {"@type": "ImageObject", "url": "//cdn.example.org/cut.jpg"}},
                {"@type": "HowToStep", "text": "<br/>", "image": "/not-a-step.jpg"},
            ]},
            {"@type": "HowToStep", "text": "3. Stir."},
            {"@type": "HowToStep", "text": "4. Serve.", "image": [None, {"contentUrl": "serve.jpg"}]},
        ]
        recipe = importer.import_from_html(page(instructions), "https://example.org/recipes/sample")
        self.assertEqual(recipe.steps, ["Wash.", "Cut.", "Stir.", "Serve."])
        self.assertEqual(recipe.step_images, [
            "https://example.org/wash.jpg", "https://cdn.example.org/cut.jpg", None,
            "https://example.org/recipes/serve.jpg",
        ])

    def test_strings_without_images_and_empty_labels_do_not_shift_photos(self):
        instructions = ["1. Heat.\n2. Stir.", {"text": "3.", "image": "/empty.jpg"},
                        {"text": "4. Serve.", "image": "/serve.jpg"}]
        recipe = importer.import_from_html(page(instructions), "https://example.org/recipe")
        self.assertEqual(recipe.steps, ["Heat.", "Stir.", "Serve."])
        self.assertEqual(recipe.step_images, [None, None, "https://example.org/serve.jpg"])
        self.assertEqual(importer._steps(instructions), recipe.steps)

    def test_step_limit_applies_to_text_and_images_together(self):
        instructions = [{"text": f"Step {index}", "image": f"/{index}.jpg"} for index in range(101)]
        recipe = importer.import_from_html(page(instructions), "https://example.org/recipe")
        self.assertEqual(len(recipe.steps), 100)
        self.assertEqual(len(recipe.step_images), 100)
        self.assertEqual(recipe.step_images[-1], "https://example.org/99.jpg")

    @staticmethod
    def iamcook_body():
        return """
        <img src="/cover.jpg"/>
        <div class="instructions">
          <p>Introduction without a photograph.</p>
          <p>1. Wash.</p><p><br/></p>
          <p><div class="primg"><img src="/wash.jpg"/></div></p>
          <p>2. Cut.</p>
          <p><div class="primg"><img src="/placeholder.gif" data-src="/cut.jpg"/></div></p>
          <p><div class="primg"><img src="/extra-cut.jpg"/></div></p>
          <p>3. Serve.</p>
          <div class="primg"><img src="/result.jpg" class="result-photo"/></div>
        </div>
        <div class="instructions"><p>Related recipe.</p><div class="primg"><img src="/related.jpg"/></div></div>
        """

    def test_iamcook_images_follow_text_and_exclude_cover_result_and_extras(self):
        recipe = importer.import_from_html(page([], self.iamcook_body()), "https://www.iamcook.ru/showrecipe/123")
        self.assertEqual(recipe.steps, ["Introduction without a photograph.", "Wash.", "Cut.", "Serve."])
        self.assertEqual(recipe.step_images, [None, "https://www.iamcook.ru/wash.jpg", "https://www.iamcook.ru/cut.jpg", None])

    def test_iamcook_inline_photo_and_image_only_lead_do_not_invent_steps(self):
        body = """<div class="instructions">
          <p><div class="primg"><img src="/lead.jpg"/></div></p>
          <p>Mix.<span><div class="primg"><img src="/mix.jpg"/></div></span></p>
          <p>Cook.</p><p><div class="primg"><img src="/cook.jpg"/></div></p>
        </div>"""
        recipe = importer.import_from_html(page([], body), "https://www.iamcook.ru/showrecipe/123")
        self.assertEqual(recipe.steps, ["Mix.", "Cook."])
        self.assertEqual(recipe.step_images, ["https://www.iamcook.ru/mix.jpg", "https://www.iamcook.ru/cook.jpg"])

    def test_iamcook_preserves_jsonld_photos_and_only_fills_matching_text(self):
        instructions = ["Introduction without a photograph.", {"text": "Wash.", "image": "/json-wash.jpg"},
                        "Cut.", "Serve."]
        recipe = importer.import_from_html(page(instructions, self.iamcook_body()), "https://www.iamcook.ru/showrecipe/123")
        self.assertEqual(recipe.step_images, [None, "https://www.iamcook.ru/json-wash.jpg", "https://www.iamcook.ru/cut.jpg", None])
        unrelated = importer.import_from_html(page(["Different text."], self.iamcook_body()), "https://www.iamcook.ru/showrecipe/123")
        self.assertEqual(unrelated.steps, ["Different text."])
        self.assertEqual(unrelated.step_images, [None])

    def test_iamcook_adapter_never_assigns_its_html_photos_to_other_hosts(self):
        recipe = importer.import_from_html(page(["Wash."], self.iamcook_body()), "https://example.org/showrecipe/123")
        self.assertEqual(recipe.steps, ["Wash."])
        self.assertEqual(recipe.step_images, [None])

    def test_step_anchor_url_is_not_treated_as_an_image(self):
        recipe = importer.import_from_html(page([{"text": "Mix.", "url": "https://example.org/recipe#step1"}]),
                                           "https://example.org/recipe")
        self.assertEqual(recipe.step_images, [None])


if __name__ == "__main__":
    unittest.main()
