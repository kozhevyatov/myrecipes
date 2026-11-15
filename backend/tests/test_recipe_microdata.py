"""Generic recipe microdata retains fields, instruction order and scope boundaries."""
from __future__ import annotations

import unittest

from recipe_microdata import find_microdata_recipe


class RecipeMicrodataTests(unittest.TestCase):
    def test_common_recipe_retains_ingredients_step_order_and_images(self):
        recipe = find_microdata_recipe('''
            <article itemscope itemtype="https://schema.org/Recipe">
              <h1 itemprop="name">Суп &amp; хлеб</h1>
              <p itemprop="description">Простой <strong>обед</strong>.</p>
              <img itemprop="image" src="/cover.jpg">
              <time itemprop="cookTime" datetime="PT20M">20 минут</time>
              <span itemprop="recipeYield">2 порции</span>
              <ul><li itemprop="recipeIngredient"><b>Вода</b> 200 мл</li>
                  <li itemprop="recipeIngredient"><span itemprop="name">Соль</span> по вкусу</li></ul>
              <ol><li itemprop="recipeInstructions" itemscope itemtype="http://schema.org/HowToStep">
                  <p itemprop="text">Вскипятите <b>воду</b>.</p><img itemprop="image" src="/step-1.jpg">
                  </li><li itemprop="recipeInstructions" itemscope itemtype="https://schema.org/HowToStep">
                  <p itemprop="text">Добавьте соль.</p></li></ol>
            </article>
        ''')
        self.assertEqual(recipe['@type'], 'Recipe')
        self.assertEqual(recipe['name'], 'Суп & хлеб')
        self.assertEqual(recipe['description'], 'Простой обед.')
        self.assertEqual(recipe['cookTime'], 'PT20M')
        self.assertEqual(recipe['recipeYield'], '2 порции')
        self.assertEqual(recipe['recipeIngredient'], ['Вода 200 мл', 'Соль по вкусу'])
        self.assertEqual(recipe['recipeInstructions'], [
            {'@type': 'HowToStep', 'text': 'Вскипятите воду.', 'image': '/step-1.jpg'},
            {'@type': 'HowToStep', 'text': 'Добавьте соль.'},
        ])

    def test_nested_scopes_do_not_override_recipe_or_supply_steps(self):
        recipe = find_microdata_recipe('''
            <div itemscope itemtype="https://schema.org/Recipe">
              <h1 itemprop="name">Основной рецепт</h1>
              <div itemprop="author" itemscope itemtype="https://schema.org/Person">
                <span itemprop="name">Автор</span>
                <span itemprop="recipeIngredient">Неправильный ингредиент</span>
              </div>
              <div itemscope itemtype="https://schema.org/Recipe">
                <span itemprop="name">Рекомендация</span>
                <span itemprop="recipeIngredient">Ещё один чужой ингредиент</span>
                <span itemprop="recipeInstructions">Чужая инструкция</span>
              </div>
              <span itemprop="recipeIngredient">Молоко 200 мл</span>
              <p itemprop="recipeInstructions">Нагрейте молоко.</p>
            </div>
        ''')
        self.assertEqual(recipe['name'], 'Основной рецепт')
        self.assertEqual(recipe['recipeIngredient'], ['Молоко 200 мл'])
        self.assertEqual(recipe['recipeInstructions'], ['Нагрейте молоко.'])

    def test_sections_and_image_objects_keep_structure(self):
        recipe = find_microdata_recipe('''
            <div itemscope itemtype="https://schema.org/Recipe">
              <span itemprop="name">Хлеб</span><span itemprop="recipeIngredient">Мука 200 г</span>
              <div itemprop="image" itemscope itemtype="https://schema.org/ImageObject">
                <link itemprop="url" href="/bread.jpg">
              </div>
              <section itemprop="recipeInstructions" itemscope itemtype="https://schema.org/HowToSection">
                <h2 itemprop="name">Тесто</h2>
                <div itemprop="itemListElement" itemscope itemtype="https://schema.org/HowToStep">
                  <span itemprop="text">Замесите тесто.</span>
                  <div itemprop="image" itemscope itemtype="https://schema.org/ImageObject">
                    <meta itemprop="contentUrl" content="/dough.jpg">
                  </div>
                </div>
              </section>
            </div>
        ''')
        section = recipe['recipeInstructions'][0]
        self.assertEqual(recipe['image']['url'], '/bread.jpg')
        self.assertEqual(section['@type'], 'HowToSection')
        self.assertEqual(section['itemListElement'][0]['image']['contentUrl'], '/dough.jpg')
        self.assertEqual(section['itemListElement'][0]['text'], 'Замесите тесто.')

    def test_unscoped_instruction_container_keeps_paragraph_breaks(self):
        recipe = find_microdata_recipe('''
            <div itemscope itemtype="https://schema.org/Recipe">
              <span itemprop="name">Чай</span><span itemprop="recipeIngredient">Вода 200 мл</span>
              <div itemprop="recipeInstructions"><p>Вскипятите воду.</p><p>Заварите чай.</p></div>
            </div>
        ''')
        self.assertEqual(recipe['recipeInstructions'], ['Вскипятите воду.\nЗаварите чай.'])

    def test_unscoped_instruction_container_can_wrap_item_list(self):
        recipe = find_microdata_recipe('''
            <div itemscope itemtype="https://schema.org/Recipe">
              <span itemprop="name">Чай</span><span itemprop="recipeIngredient">Вода 200 мл</span>
              <ol itemprop="recipeInstructions">
                <li itemprop="itemListElement" itemscope itemtype="https://schema.org/HowToStep">
                  <span itemprop="text">Вскипятите воду.</span>
                </li>
              </ol>
            </div>
        ''')
        self.assertEqual(recipe['recipeInstructions'], [
            {'@type': 'HowToSection', 'itemListElement': [{'@type': 'HowToStep', 'text': 'Вскипятите воду.'}]},
        ])

    def test_meta_data_and_multiple_image_values(self):
        recipe = find_microdata_recipe('''
            <article itemscope itemtype="http://schema.org/Recipe">
              <meta itemprop="name" content="Soup">
              <data itemprop="recipeYield" value="4">four servings</data>
              <meta itemprop="prepTime" content="PT5M"/>
              <meta itemprop="recipeIngredient" content="Water 200 ml">
              <meta itemprop="recipeInstructions" content="Boil the water.">
              <img itemprop="image" src="/first.jpg"><link itemprop="image" href="/second.jpg">
            </article>
        ''')
        self.assertEqual(recipe['recipeYield'], '4')
        self.assertEqual(recipe['prepTime'], 'PT5M')
        self.assertEqual(recipe['image'], ['/first.jpg', '/second.jpg'])

    def test_first_complete_top_level_recipe_is_preferred(self):
        recipe = find_microdata_recipe('''
            <div itemscope itemtype="https://schema.org/Recipe"><h2 itemprop="name">Summary</h2></div>
            <div itemscope itemtype="https://schema.org/Recipe">
              <span itemprop="name">Complete</span><span itemprop="recipeIngredient">Water</span>
              <span itemprop="recipeInstructions">Boil</span>
            </div>
        ''')
        self.assertEqual(recipe['name'], 'Complete')

    def test_plain_html_other_schema_and_hidden_templates_are_not_recipes(self):
        for page in (
            '<h1>Soup</h1><ul><li>Water</li></ul><p>Boil water</p>',
            '<article itemscope itemtype="https://schema.org/Product"><span itemprop="name">Soup</span></article>',
            '<template><article itemscope itemtype="https://schema.org/Recipe"><span itemprop="name">Soup</span></article></template>',
        ):
            with self.subTest(page=page):
                self.assertIsNone(find_microdata_recipe(page))

    def test_excessive_nesting_is_rejected_explicitly(self):
        with self.assertRaisesRegex(ValueError, 'nesting limit'):
            find_microdata_recipe('<div>' * 300)

    def test_importer_normalizes_microdata_recipe_and_resolves_step_images(self):
        from app import importer

        recipe = importer.import_from_html('''
            <article itemscope itemtype="https://schema.org/Recipe">
              <h1 itemprop="name">Чай</h1><meta itemprop="recipeYield" content="2">
              <time itemprop="cookTime" datetime="PT10M">10 минут</time>
              <img itemprop="image" src="/cover.jpg">
              <span itemprop="recipeIngredient">Вода 200 мл</span>
              <div itemprop="recipeInstructions" itemscope itemtype="https://schema.org/HowToSection">
                <div itemprop="itemListElement" itemscope itemtype="https://schema.org/HowToStep">
                  <p itemprop="text">Вскипятите воду.</p><img itemprop="image" src="images/boil.jpg">
                </div>
                <div itemprop="itemListElement" itemscope itemtype="https://schema.org/HowToStep">
                  <p itemprop="text">Заварите чай.</p>
                </div>
              </div>
            </article>
        ''', 'https://recipes.example.org/tea/')
        self.assertEqual(recipe.title, 'Чай')
        self.assertEqual(recipe.servings, 2)
        self.assertEqual(recipe.cook_minutes, 10)
        self.assertEqual([(item.product, item.amount, item.unit) for item in recipe.ingredients], [('Вода', 200, 'мл')])
        self.assertEqual(recipe.image_url, 'https://recipes.example.org/cover.jpg')
        self.assertEqual(recipe.steps, ['Вскипятите воду.', 'Заварите чай.'])
        self.assertEqual(recipe.step_images, ['https://recipes.example.org/tea/images/boil.jpg', None])

    def test_existing_jsonld_has_priority_over_microdata_recommendation(self):
        from app import importer

        recipe = importer.import_from_html('''
            <script type="application/ld+json">{"@type":"Recipe","name":"Main recipe",
              "recipeIngredient":["Вода 200 мл"],"recipeInstructions":["Вскипятите воду."]}</script>
            <aside itemscope itemtype="https://schema.org/Recipe">
              <span itemprop="name">Recommendation</span>
              <span itemprop="recipeIngredient">Соль</span><p itemprop="recipeInstructions">Посолите.</p>
            </aside>
        ''', 'https://recipes.example.org/main/')
        self.assertEqual(recipe.title, 'Main recipe')
        self.assertEqual(recipe.steps, ['Вскипятите воду.'])


if __name__ == '__main__':
    unittest.main()
