"""Recipe search uses titles and tags with stable relevance and visibility rules."""
from __future__ import annotations

import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

BACKEND = Path(__file__).parents[1]
FIXTURES = Path(__file__).parent

SETUP = r'''
import json
from datetime import datetime
from sqlalchemy import select
from app.models import Category, Favorite, ImportSource, Product, Recipe, RecipeIngredient, Tag
from app.routers import recipes

fixture.app.include_router(recipes.router)

def add_recipe(recipe_id, title, *, tags=(), updated='2024-01-01', **fields):
    with fixture.db._SessionLocal() as session:
        attached_tags = []
        for name in tags:
            tag = session.scalar(select(Tag).where(Tag.name == name))
            if tag is None:
                tag = Tag(name=name)
                session.add(tag)
                session.flush()
            attached_tags.append(tag)
        session.add(Recipe(id=recipe_id, title=title, author_id=fields.pop('author_id', 1),
                           is_public=fields.pop('is_public', True), tags=attached_tags,
                           updated_at=datetime.fromisoformat(updated), **fields))
        session.commit()

def search(q=None, *, headers=MEMBER, **params):
    if q is not None:
        params['q'] = q
    response = fixture.client.get('/api/recipes', params=params, headers=headers)
    assert response.status_code == 200, response.text
    result = response.json()
    return [item['id'] for item in result['items']], result['total']
'''


class RecipeSearchTests(unittest.TestCase):
    def run_case(self, body: str):
        script = ('import sys\n' + f'sys.path.insert(0, {str(FIXTURES)!r})\n' +
                  'from import_admin_fixture import environment, ADMIN, MEMBER\n' +
                  'with environment() as fixture:\n' +
                  textwrap.indent(SETUP + '\n' + textwrap.dedent(body), '    '))
        result = subprocess.run([sys.executable, '-B', '-W', 'error::ResourceWarning', '-c', script],
                                cwd=BACKEND, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_dish_search_excludes_description_ingredients_and_category_only_matches(self):
        self.run_case('''
            with fixture.db._SessionLocal() as session:
                session.add_all([Category(id=1, name='Борщ'), Category(id=2, name='Салаты'),
                                 Product(id=1, name='Салат листовой')])
                session.commit()
            add_recipe(1, 'Борщ вкуснейший')
            add_recipe(2, 'Зелёный суп', tags=['борщ'])
            add_recipe(3, 'Сало с чесноком', description='Подайте к борщу или салату.')
            add_recipe(4, 'Тако с индейкой')
            add_recipe(5, 'Свекольный суп', category_id=1)
            add_recipe(6, 'Салат с огурцом')
            add_recipe(7, 'Овощная закуска', tags=['салат'])
            add_recipe(8, 'Огуречная закуска', category_id=2)
            with fixture.db._SessionLocal() as session:
                session.add(RecipeIngredient(recipe_id=4, product_id=1))
                session.commit()
            assert search('БОРЩ') == ([1, 2], 2), search('БОРЩ')
            assert search('САЛАТ') == ([6, 7], 2), search('САЛАТ')
        ''')

    def test_every_word_must_match_title_or_tags_case_insensitively(self):
        self.run_case('''
            add_recipe(1, 'Курица с рисом')
            add_recipe(2, 'КУРИЦА домашняя', tags=['рис'])
            add_recipe(3, 'Каша', tags=['курица', 'рис'])
            add_recipe(4, 'Курица', description='С рисом')
            add_recipe(5, 'Рис отварной')
            add_recipe(6, 'Курица с гречкой')
            assert search('  кУрИцА   РИС  ') == ([1, 2, 3], 3), search('  кУрИцА   РИС  ')
            assert search('курица рис гречка') == ([], 0)
        ''')

    def test_like_wildcards_are_literal_in_titles_and_tags(self):
        self.run_case(r'''
            add_recipe(1, 'Шоколад 70%')
            add_recipe(2, 'Шоколад 70 граммов')
            add_recipe(3, 'Пирог_домашний')
            add_recipe(4, 'Пирог домашний')
            add_recipe(5, r'Торт\пирог')
            add_recipe(6, 'Торт пирог')
            add_recipe(7, 'Десерт', tags=['70%', 'пирог_домашний', r'торт\пирог'])
            assert search('70%') == ([1, 7], 2), search('70%')
            assert search('пирог_') == ([3, 7], 2), search('пирог_')
            backslash_query = 'торт' + chr(92)
            assert search(backslash_query) == ([5, 7], 2), search(backslash_query)
        ''')

    def test_relevance_precedes_recency_and_pages_have_no_duplicates(self):
        self.run_case('''
            add_recipe(1, 'Салат рис', updated='2020-01-01')
            add_recipe(2, 'Салат с рисом', updated='2023-01-01')
            add_recipe(3, 'Салат домашний', tags=['рис'], updated='2025-01-01')
            add_recipe(4, 'Закуска', tags=['салат рис', 'салат', 'рис'], updated='2026-01-01')
            add_recipe(5, 'Рисовый салат', updated='2023-01-01')
            first = search('салат рис', limit=2)
            second = search('салат рис', limit=2, offset=2)
            third = search('салат рис', limit=2, offset=4)
            assert first == ([1, 5], 5), first
            assert second == ([2, 3], 5), second
            assert third == ([4], 5), third
            assert search('салат рис', limit=2) == first
        ''')

    def test_search_preserves_visibility_and_other_filters(self):
        self.run_case('''
            with fixture.db._SessionLocal() as session:
                session.add(Category(id=1, name='Завтраки'))
                session.add(ImportSource(id=1, key='search-fixture', name='Fixture source',
                    enabled=True, verified=True, definition_json=json.dumps({'hosts': ['recipes.example.org']})))
                session.commit()
            add_recipe(1, 'Салат', author_id=1, is_public=False)
            add_recipe(2, 'Салат', author_id=2, is_public=False, category_id=1, tags=['овощи'],
                       source_url='https://recipes.example.org/recipe/2')
            add_recipe(3, 'Салат', author_id=1, category_id=1, tags=['овощи'],
                       source_url='https://recipes.example.org/recipe/3')
            add_recipe(4, 'Салат', author_id=2, source_url='https://elsewhere.example.org/recipe/4')
            with fixture.db._SessionLocal() as session:
                session.add_all([Favorite(user_id=2, recipe_id=2), Favorite(user_id=2, recipe_id=3)])
                session.commit()
            assert search('салат') == ([4, 3, 2], 3), search('салат')
            assert search('салат', headers=ADMIN) == ([4, 3, 2, 1], 4)
            assert search('салат', mine=True) == ([4, 2], 2)
            assert search('салат', favorites=True) == ([3, 2], 2)
            assert search('салат', category_id=1, tag='овощи', source_id=1) == ([3, 2], 2)
            assert search('салат', category_id=1, tag='овощи', source_id=1,
                          mine=True, favorites=True) == ([2], 1)
        ''')

    def test_empty_or_whitespace_search_keeps_newest_first(self):
        self.run_case('''
            add_recipe(1, 'Борщ', updated='2025-01-01')
            add_recipe(2, 'Салат', updated='2024-01-01')
            add_recipe(3, 'Тако', updated='2025-01-01')
            expected = ([3, 1, 2], 3)
            assert search() == expected
            assert search('') == expected
            assert search('   ') == expected
        ''')


if __name__ == '__main__':
    unittest.main()
