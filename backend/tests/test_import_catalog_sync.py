"""Administrative imports reuse public metadata and fill the external catalog once."""
from __future__ import annotations

import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

BACKEND = Path(__file__).parents[1]
FIXTURES = Path(__file__).parent

SETUP = r'''
import io
import json
import threading
from collections import Counter
from unittest.mock import patch
from PIL import Image
from app import importer, import_jobs as jobs
from app.models import ImportSource, ImportJob, Recipe, RecipeStep, SourceCategory, SourceRecipe
from app.source_catalog import cache_metadata, store_reference

origin = 'https://sync.example.org'
urls = [origin + '/recipe/' + str(number) for number in range(1, 4)]
definition = {'canonical_host': 'sync.example.org', 'hosts': ['sync.example.org'],
    'catalog_url': origin + '/catalog', 'recipe_pattern': r'/recipe/\d+',
    'catalog_pattern': r'/catalog(?:/[^/]+)?'}
pages = {
    origin + '/catalog': '<html><a href="/catalog/soups">Soups</a><a href="/catalog/mains">Mains</a></html>',
    origin + '/catalog/soups': '<html><a href="/recipe/1">Soup</a></html>',
    origin + '/catalog/mains': '<html><a href="/recipe/2">Rice</a></html>',
}
for number, url in enumerate(urls):
    node = {'@type': 'Recipe', 'name': ['Soup', 'Rice', 'Beans'][number], 'description': 'Public source description',
        'recipeYield': '2', 'recipeCategory': ['Soups', 'Mains', 'Mains'][number],
        'recipeIngredient': ['Молоко 100 мл'], 'image': origin + '/cover.png', 'recipeInstructions': [
            {'@type': 'HowToStep', 'text': 'Prepare the milk.', 'image': origin + '/step-1.png'},
            {'@type': 'HowToStep', 'text': 'Stir and serve.', 'image': origin + '/step-2.png'}]}
    pages[url] = '<html><script type="application/ld+json">' + json.dumps(node) + '</script></html>'
picture = io.BytesIO()
Image.new('RGB', (3, 3), 'orange').save(picture, format='PNG')

class Client:
    page_calls = Counter()
    image_calls = Counter()
    def __init__(self, *args, **kwargs):
        self.check_cancel = args[0] if args and callable(args[0]) else lambda: None
        self.current_url = args[1] if len(args) > 1 and callable(args[1]) else lambda url: None
        self.blocked = set()
    def pacing_summary(self):
        return {}
    def fetch(self, url, limit, accept='text/html'):
        self.check_cancel()
        self.current_url(url)
        self.page_calls[url] += 1
        assert url in pages, 'Unexpected page download: ' + url
        return pages[url].encode(), 'text/html', url
    def fetch_cover(self, url):
        self.check_cancel()
        self.image_calls[url] += 1
        return picture.getvalue(), 'image/png', url

with fixture.db._SessionLocal() as session:
    source = ImportSource(key='sync', name='Sync fixture', definition_json=json.dumps(definition),
                          enabled=True, verified=True, visible_in_catalog=True)
    session.add(source)
    session.commit()
    source_id = source.id

def execute(*, selected=None, limit=0, category_id=None):
    payload = {'source_id': source_id, 'mode': 'import', 'limit': limit, 'is_public': False}
    if selected is not None:
        payload['urls'] = selected
    if category_id is not None:
        payload['category_id'] = category_id
    response = fixture.client.post('/api/admin/imports/jobs', headers=ADMIN, json=payload)
    assert response.status_code == 200, response.text
    job_id = response.json()['id']
    with fixture.db._SessionLocal() as session:
        assert jobs.claim_job(session, 'sync-worker') == job_id
    with patch.object(jobs, 'JobClient', Client), patch.object(jobs, 'configure_tls', return_value=(None, 'Fixture TLS')):
        jobs.run_job(job_id, 'sync-worker', threading.Event())
    with fixture.db._SessionLocal() as session:
        job = session.get(ImportJob, job_id)
        return job.status, json.loads(job.report_json)

def preload(url):
    public = importer.import_from_html(pages[url], url)
    with fixture.db._SessionLocal() as session:
        external = store_reference(session, source_id, url)
        cache_metadata(session, external, public)
        session.commit()
        return external.id
'''


class ImportCatalogSyncTests(unittest.TestCase):
    def run_case(self, body: str):
        script = ('import sys\n' + f'sys.path.insert(0, {str(FIXTURES)!r})\n' +
                  'from import_admin_fixture import environment, ADMIN\n' +
                  'with environment() as fixture:\n' + textwrap.indent(SETUP + '\n' + textwrap.dedent(body), '    '))
        result = subprocess.run([sys.executable, '-B', '-W', 'error::ResourceWarning', '-c', script],
                                cwd=BACKEND, capture_output=True, text=True, timeout=55)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_fresh_import_fills_public_catalog_and_categories_without_second_recipe_fetch(self):
        self.run_case('''
            status, report = execute()
            assert status == 'completed' and report['created'] == 2, report
            assert report['downloaded_pages'] == 2 and report['cache_hits'] == 0, report
            assert [Client.page_calls[url] for url in urls] == [1, 1, 0], Client.page_calls
            with fixture.db._SessionLocal() as session:
                assert session.query(Recipe).count() == 2
                external = session.query(SourceRecipe).order_by(SourceRecipe.url).all()
                assert len(external) == 2 and all(item.payload_json for item in external)
                for item in external:
                    public = json.loads(item.payload_json)
                    assert public['description'] == 'Public source description'
                    assert public['steps'] == ['Prepare the milk.', 'Stir and serve.']
                    assert public['step_images'] == [origin + '/step-1.png', origin + '/step-2.png']
                categories_before = session.query(SourceCategory).count()
                assert session.query(SourceCategory).filter(SourceCategory.title == 'Soups').count() == 1
                source = session.get(ImportSource, source_id)
                assert not source.index_complete and source.last_indexed_at is None
            status, repeated = execute()
            assert status == 'completed' and repeated['created'] == 0 and repeated['duplicates'] == 2, repeated
            assert repeated['downloaded_pages'] == 0, repeated
            assert [Client.page_calls[url] for url in urls] == [1, 1, 0], Client.page_calls
            with fixture.db._SessionLocal() as session:
                assert session.query(Recipe).count() == 2 and session.query(SourceRecipe).count() == 2
                assert session.query(SourceCategory).count() == categories_before
            public_list = fixture.client.get('/api/site-recipes', headers=ADMIN)
            assert public_list.status_code == 200 and public_list.json()['total'] == 2, public_list.text
        ''')

    def test_cached_external_recipe_is_imported_with_photos_without_fetching_its_html(self):
        self.run_case('''
            external_id = preload(urls[0])
            status, report = execute(selected=[urls[0]])
            assert status == 'completed' and report['created'] == 1, report
            assert report['cache_hits'] == 1 and report['downloaded_pages'] == 0, report
            assert not Client.page_calls, Client.page_calls
            assert Client.image_calls[origin + '/cover.png'] == 1
            assert Client.image_calls[origin + '/step-1.png'] == 1
            assert Client.image_calls[origin + '/step-2.png'] == 1
            with fixture.db._SessionLocal() as session:
                assert session.query(SourceRecipe).count() == 1
                assert session.get(SourceRecipe, external_id).payload_json
                personal = session.query(Recipe).one()
                assert personal.image and len(personal.steps) == 2 and all(step.image for step in personal.steps)
                assert personal.description == 'Public source description'
        ''')

    def test_legacy_personal_duplicate_adds_reference_without_publishing_private_edits(self):
        self.run_case('''
            with fixture.db._SessionLocal() as session:
                personal = Recipe(author_id=1, title='Private edited title', source_url=urls[0],
                                  description='Private household changes', is_public=False)
                session.add(personal)
                session.flush()
                session.add(RecipeStep(recipe_id=personal.id, position=0, text='Private preparation notes'))
                session.commit()
            status, report = execute(selected=[urls[0]])
            assert status == 'completed' and report['created'] == 0 and report['duplicates'] == 1, report
            assert not Client.page_calls and not Client.image_calls
            with fixture.db._SessionLocal() as session:
                external = session.query(SourceRecipe).one()
                assert external.url == urls[0] and external.payload_json is None
                assert 'Private' not in external.title and 'Private' not in external.description
                assert session.query(Recipe).count() == 1
                assert session.query(Recipe).one().description == 'Private household changes'
            assert fixture.client.get('/api/site-recipes', headers=ADMIN).json()['total'] == 0
        ''')

    def test_duplicate_personal_title_still_caches_original_public_recipe(self):
        self.run_case('''
            with fixture.db._SessionLocal() as session:
                personal = Recipe(author_id=1, title='Soup', source_url=None, description='Private altered soup', is_public=False)
                session.add(personal)
                session.commit()
            status, report = execute(selected=[urls[0]])
            assert status == 'completed' and report['created'] == 0 and report['duplicates'] == 1, report
            assert Client.page_calls == Counter({urls[0]: 1}), Client.page_calls
            with fixture.db._SessionLocal() as session:
                assert session.query(Recipe).count() == 1
                assert session.query(Recipe).one().description == 'Private altered soup'
                external = session.query(SourceRecipe).one()
                assert external.url == urls[0] and json.loads(external.payload_json)['description'] == 'Public source description'
                assert external.title == 'Soup'
            assert not Client.image_calls
        ''')

    def test_partial_import_preserves_unseen_entries_and_last_complete_scan_provenance(self):
        self.run_case('''
            from datetime import datetime, timezone
            existing_id = preload(urls[1])
            old_scan = datetime(2024, 1, 1, tzinfo=timezone.utc)
            with fixture.db._SessionLocal() as session:
                source = session.get(ImportSource, source_id)
                source.index_complete, source.last_indexed_at = True, old_scan
                session.commit()
            status, report = execute(selected=[urls[2]], limit=1)
            assert status == 'completed' and report['created'] == 1, report
            assert Client.page_calls == Counter({urls[2]: 1}), Client.page_calls
            with fixture.db._SessionLocal() as session:
                assert session.get(SourceRecipe, existing_id).active
                source = session.get(ImportSource, source_id)
                assert source.index_complete and source.last_indexed_at.year == 2024
                assert session.query(SourceRecipe).count() == 2
        ''')

    def test_corrupt_cache_stops_explicitly_without_redownloading_or_creating_personal_recipe(self):
        self.run_case('''
            external_id = preload(urls[0])
            with fixture.db._SessionLocal() as session:
                session.get(SourceRecipe, external_id).payload_json = '{broken'
                session.commit()
            status, report = execute(selected=[urls[0]])
            assert status == 'failed' and report.get('fatal'), report
            assert report['errors'], report
            assert not Client.page_calls and not Client.image_calls
            with fixture.db._SessionLocal() as session:
                assert session.query(Recipe).count() == 0
                assert session.get(SourceRecipe, external_id).payload_json == '{broken'
        ''')

    def test_cached_payload_cannot_substitute_a_different_source_recipe(self):
        self.run_case('''
            external_id = preload(urls[0])
            with fixture.db._SessionLocal() as session:
                external = session.get(SourceRecipe, external_id)
                payload = json.loads(external.payload_json)
                payload['source_url'] = 'https://outside.example.org/recipe/1'
                external.payload_json = json.dumps(payload)
                session.commit()
            status, report = execute(selected=[urls[0]])
            assert status == 'failed' and report.get('fatal'), report
            assert not Client.page_calls and not Client.image_calls
            with fixture.db._SessionLocal() as session:
                assert session.query(Recipe).count() == 0
        ''')


if __name__ == '__main__':
    unittest.main()
