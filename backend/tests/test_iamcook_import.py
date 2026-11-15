"""IamCook's metadata-only JSON-LD is completed from its explicit recipe blocks."""
from __future__ import annotations

import json
import unittest

from app import importer

URL = "https://www.iamcook.ru/showrecipe/12345"


def page(**fields) -> str:
    node = {
        "@type": "Recipe", "name": "Synthetic recipe", "recipeYield": "4",
        "prepTime": "PT10M", "cookTime": "PT20M", "image": "/cover.jpg",
    }
    node.update(fields)
    return '<script type="application/ld+json">' + json.dumps(node) + "</script>" + """
    <div class="ingredients">
      <h2>Ingredients</h2>
      <div class="ilist extra-class">
        <div>
          <p>Молоко - 200 мл</p>
          <strong>Для соуса:</strong>
          <p>Мука - 20 г</p>
          <p>Соль - по вкусу</p>
        </div>
        <div class="tackles"><p>Equipment that is not an ingredient</p></div>
        <ul class="ilparams"><li>Nutrition <strong>Protein:</strong> 15</li></ul>
      </div>
    </div>
    <div class="instructions extra-class">
      <p>Mix <strong>carefully</strong>.<br/>Keep warm.</p>
      <p> <br/> </p>
      <p><div class="primg"><img src="/step.jpg"/></div></p>
      <p>Cook.<script>ignored script</script><style>ignored style</style></p>
    </div>
    <div class="instructions"><p>Unrelated later block</p></div>
    <p>Comments outside the instructions</p>
    """


class IamCookImportTests(unittest.TestCase):
    def test_missing_fields_are_filled_without_losing_jsonld_metadata(self):
        recipe = importer.import_from_html(page(), URL)
        self.assertEqual(recipe.title, "Synthetic recipe")
        self.assertEqual((recipe.servings, recipe.prep_minutes, recipe.cook_minutes), (4, 10, 20))
        self.assertEqual(recipe.image_url, "https://www.iamcook.ru/cover.jpg")
        self.assertEqual(recipe.source_url, URL)
        self.assertEqual(len(recipe.ingredients), 3)
        self.assertEqual(recipe.steps, ["Mix carefully. Keep warm.", "Cook."])

    def test_ingredient_sections_are_preserved_and_equipment_and_nutrition_excluded(self):
        recipe = importer.import_from_html(page(), URL)
        self.assertEqual([(i.product, i.amount, i.unit, i.group) for i in recipe.ingredients], [
            ("Молоко", 200, "мл", ""),
            ("Мука", 20, "г", "Для соуса"),
            ("Соль", None, "по вкусу", "Для соуса"),
        ])

    def test_populated_jsonld_fields_take_priority_over_html(self):
        recipe = importer.import_from_html(page(
            recipeIngredient=["Масло - 10 г"], recipeInstructions=["Use JSON-LD instructions."]), URL)
        self.assertEqual([i.product for i in recipe.ingredients], ["Масло"])
        self.assertEqual(recipe.steps, ["Use JSON-LD instructions."])

    def test_only_missing_jsonld_field_is_completed(self):
        recipe = importer.import_from_html(page(recipeIngredient=["Масло - 10 г"]), URL)
        self.assertEqual([i.product for i in recipe.ingredients], ["Масло"])
        self.assertEqual(len(recipe.steps), 2)
        recipe = importer.import_from_html(page(recipeInstructions=["Use JSON-LD."]), URL)
        self.assertEqual(len(recipe.ingredients), 3)
        self.assertEqual(recipe.steps, ["Use JSON-LD."])

    def test_legacy_jsonld_ingredient_alias_is_preserved(self):
        recipe = importer.import_from_html(page(ingredients=["Масло - 10 г"]), URL)
        self.assertEqual([i.product for i in recipe.ingredients], ["Масло"])
        self.assertTrue(recipe.steps)

    def test_adapter_is_limited_to_iamcook_recipe_hosts_and_paths(self):
        for url in ("https://food.ru/recipes/123-test", "https://www.iamcook.ru.attacker.test/showrecipe/12345",
                    "https://www.iamcook.ru/theme/test", "https://www.iamcook.ru/showrecipe/not-a-number"):
            with self.subTest(url=url):
                recipe = importer.import_from_html(page(), url)
                self.assertEqual(recipe.ingredients, [])
                self.assertEqual(recipe.steps, [])
        recipe = importer.import_from_html(page(), "https://iamcook.ru/showrecipe/12345/")
        self.assertTrue(recipe.ingredients)
        self.assertTrue(recipe.steps)

    def test_absent_blocks_do_not_guess_from_comments_or_other_content(self):
        content = '<script type="application/ld+json">{"@type":"Recipe","name":"Sample"}</script><p>Comment</p>'
        recipe = importer.import_from_html(content, URL)
        self.assertEqual(recipe.ingredients, [])
        self.assertEqual(recipe.steps, [])

    def test_missing_jsonld_still_raises_explicit_import_error(self):
        with self.assertRaises(importer.ImportError_):
            importer.import_from_html('<div class="instructions"><p>Text</p></div>', URL)


if __name__ == "__main__":
    unittest.main()
