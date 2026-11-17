"""Tag suggestions count accessible recipes and refine multiple selected tags."""
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
from app.models import Category, Favorite, ImportSource, Recipe, Tag
from app.routers import catalog, recipes

fixture.app.include_router(catalog.router)
fixture.app.include_router(recipes.router)

def add_recipe(recipe_id, title='Fixture recipe', *, tags=(), **fields):
    with fixture.db._SessionLocal() as session:
        attached = []
        for name in tags:
            tag = session.scalar(select(Tag).where(Tag.name == name))
            if tag is None:
                tag = Tag(name=name)
                session.add(tag)
                session.flush()
            attached.append(tag)
        session.add(Recipe(id=recipe_id, title=title, tags=attached,
            author_id=fields.pop('author_id', 1), is_public=fields.pop('is_public', True),
            updated_at=datetime(2024, 1, 1), **fields))
        session.commit()

def suggestions(q, *, headers=MEMBER, **params):
    response = fixture.client.get('/api/tags/suggestions', params={'q': q, **params}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()

def search(*, headers=MEMBER, **params):
    response = fixture.client.get('/api/recipes', params=params, headers=headers)
    assert response.status_code == 200, response.text
    result = response.json()
    return [item['id'] for item in result['items']], result['total']
'''


class TagSuggestionTests(unittest.TestCase):
    def run_case(self, body: str):
        script = ('import sys\n' + f'sys.path.insert(0, {str(FIXTURES)!r})\n' +
                  'from import_admin_fixture import environment, ADMIN, MEMBER\n' +
                  'with environment() as fixture:\n' +
                  textwrap.indent(SETUP + '\n' + textwrap.dedent(body), '    '))
        result = subprocess.run([sys.executable, '-B', '-W', 'error::ResourceWarning', '-c', script],
                                cwd=BACKEND, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_counts_merge_tag_variants_without_duplicates_or_private_recipe_leaks(self):
        self.run_case('''
            add_recipe(1, tags=[' Итальянская ', 'итальянская', 'ИТАЛЬЯНСКАЯ'])
            add_recipe(2, tags=['итальянская'], author_id=2, is_public=False)
            add_recipe(3, tags=['итальянская'], author_id=1, is_public=False)
            add_recipe(4, tags=['итальянская секретная'], author_id=1, is_public=False)
            with fixture.db._SessionLocal() as session:
                session.add(Tag(name='итальянская неиспользуемая'))
                session.commit()
            assert suggestions('  ИТА  ') == [{'name': 'итальянская', 'recipe_count': 2}]
            assert suggestions('ита', headers=ADMIN) == [
                {'name': 'итальянская', 'recipe_count': 3},
                {'name': 'итальянская секретная', 'recipe_count': 1}]
            response = fixture.client.get('/api/tags/suggestions', params={'q': 'ита'})
            assert response.status_code == 401, response.text
        ''')

    def test_selected_tags_require_cooccurrence_and_do_not_reappear_in_suggestions(self):
        self.run_case('''
            add_recipe(1, tags=['итальянская', 'паста', 'сыр'])
            add_recipe(2, tags=['итальянская', 'паста', 'овощная'])
            add_recipe(3, tags=['итальянская', 'суп', 'овощная'])
            add_recipe(4, tags=['французская', 'паста', 'сыр'])
            assert suggestions('сы') == [{'name': 'сыр', 'recipe_count': 2}]
            assert suggestions('сы', tags=['итальянская', 'паста']) == [
                {'name': 'сыр', 'recipe_count': 1}]
            assert suggestions('ов', tags=['итальянская', 'паста']) == [
                {'name': 'овощная', 'recipe_count': 1}]
            assert suggestions('ит', tags=[' ИТАЛЬЯНСКАЯ ']) == []
            assert suggestions('па', tag='ИТАЛЬЯНСКАЯ') == [
                {'name': 'паста', 'recipe_count': 2}]
            assert suggestions('сы', tags=['итальянская'], tag='паста') == [
                {'name': 'сыр', 'recipe_count': 1}]
        ''')

    def test_recipe_list_accepts_multiple_exact_tags_and_preserves_legacy_tag(self):
        self.run_case('''
            add_recipe(1, 'Паста с сыром', tags=[' Итальянская ', 'итальянская', 'паста', 'сыр'])
            add_recipe(2, 'Паста с овощами', tags=['итальянская', 'паста'])
            add_recipe(3, 'Суп', tags=['итальянская', 'сыр'])
            add_recipe(4, 'Паста', tags=['французская', 'паста', 'сыр'])
            assert search(tags=[' ИТАЛЬЯНСКАЯ ', 'паста', 'итальянская']) == ([2, 1], 2)
            assert search(tags=['итальянская', 'паста'], tag='сыр') == ([1], 1)
            assert search(tag=' ИТАЛЬЯНСКАЯ ') == ([3, 2, 1], 3)
            assert search(q='сыр', tags=['итальянская', 'паста']) == ([1], 1)
            assert search(tags=['итальянская', 'паста'], limit=1) == ([2], 2)
            assert search(tags=['итальянская', 'паста'], limit=1, offset=1) == ([1], 2)
            assert search(tags=['несуществующий']) == ([], 0)
        ''')

    def test_counts_honor_category_owner_favorites_and_source_filters(self):
        self.run_case('''
            with fixture.db._SessionLocal() as session:
                session.add(Category(id=1, name='Основные блюда'))
                session.add(ImportSource(id=1, key='tags-fixture', name='Fixture source',
                    enabled=True, verified=True,
                    definition_json=json.dumps({'hosts': ['recipes.example.org']})))
                session.commit()
            add_recipe(1, tags=['итальянская'], author_id=2, category_id=1,
                       source_url='https://recipes.example.org/recipe/1')
            add_recipe(2, tags=['итальянская'], author_id=1, category_id=1,
                       source_url='http://recipes.example.org/recipe/2')
            add_recipe(3, tags=['итальянская'], author_id=2, category_id=1,
                       source_url='https://recipes.example.org.evil.test/recipe/3')
            add_recipe(4, tags=['итальянская'], author_id=2,
                       source_url='https://recipes.example.org/recipe/4')
            with fixture.db._SessionLocal() as session:
                session.add_all([Favorite(user_id=2, recipe_id=1), Favorite(user_id=2, recipe_id=2)])
                session.commit()
            assert suggestions('ита', category_id=1) == [{'name': 'итальянская', 'recipe_count': 3}]
            assert suggestions('ита', mine=True) == [{'name': 'итальянская', 'recipe_count': 3}]
            assert suggestions('ита', favorites=True) == [{'name': 'итальянская', 'recipe_count': 2}]
            assert suggestions('ита', source_id=1) == [{'name': 'итальянская', 'recipe_count': 3}]
            assert suggestions('ита', category_id=1, mine=True, favorites=True, source_id=1) == [
                {'name': 'итальянская', 'recipe_count': 1}]
            response = fixture.client.get('/api/tags/suggestions', headers=MEMBER,
                                          params={'q': 'ита', 'source_id': 99})
            assert response.status_code == 404, response.text
        ''')

    def test_query_wildcards_remain_literal(self):
        self.run_case(r'''
            add_recipe(1, tags=['50% какао', 'п_домашний', r'a\b'])
            add_recipe(2, tags=['50 граммов какао', 'пирог домашний', 'ab'])
            assert suggestions('50%') == [{'name': '50% какао', 'recipe_count': 1}]
            assert suggestions('п_') == [{'name': 'п_домашний', 'recipe_count': 1}]
            assert suggestions('a' + chr(92)) == [{'name': r'a\b', 'recipe_count': 1}]
        ''')

    def test_exact_and_prefix_matches_precede_substrings_and_results_are_bounded(self):
        self.run_case('''
            add_recipe(1, tags=['рис', 'рисовая', 'рисовый', 'бурый рис'])
            add_recipe(2, tags=['рисовая', 'бурый рис'])
            add_recipe(3, tags=['бурый рис'])
            assert suggestions('РИС') == [
                {'name': 'рис', 'recipe_count': 1},
                {'name': 'рисовая', 'recipe_count': 2},
                {'name': 'рисовый', 'recipe_count': 1},
                {'name': 'бурый рис', 'recipe_count': 3}]
            assert suggestions('рис', limit=2) == [
                {'name': 'рис', 'recipe_count': 1}, {'name': 'рисовая', 'recipe_count': 2}]
            for number in range(10):
                add_recipe(10 + number, tags=[f'кухня {number:02d}'])
            bounded = suggestions('ку')
            assert len(bounded) == 8, bounded
            assert [item['name'] for item in bounded] == [f'кухня {number:02d}' for number in range(8)]
        ''')

    def test_short_queries_and_invalid_limits_or_selected_tags(self):
        self.run_case('''
            add_recipe(1, tags=['итальянская'])
            for query in ('', ' ', 'и', ' и '):
                assert suggestions(query) == []
            for params in ({'q': 'x' * 101}, {'q': 'ита', 'limit': 0}, {'q': 'ита', 'limit': 9}):
                response = fixture.client.get('/api/tags/suggestions', headers=MEMBER, params=params)
                assert response.status_code == 422, (params, response.status_code, response.text)
            invalid_tags = [{'tags': [f'tag-{number}' for number in range(21)]},
                            {'tags': ['x' * 65]}, {'tag': 'x' * 65}]
            for path in ('/api/recipes', '/api/tags/suggestions'):
                for params in invalid_tags:
                    response = fixture.client.get(path, headers=MEMBER, params={'q': 'ита', **params})
                    assert response.status_code == 422, (path, params, response.status_code, response.text)
        ''')


if __name__ == '__main__':
    unittest.main()
