"""External indexing, browsing and explicit import form one persistent workflow."""
from __future__ import annotations

import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

BACKEND = Path(__file__).parents[1]
FIXTURES = Path(__file__).parent


class SourceCatalogIntegrationTests(unittest.TestCase):
    def test_background_index_survives_navigation_and_browsing_creates_no_personal_recipes(self):
        body = '''
            import io
            import json
            import threading
            from unittest.mock import patch
            from PIL import Image
            from collect_recipes import CollectionError
            from app import import_jobs as jobs, source_catalog as catalog
            from app.models import ImportSource, ImportJob, Recipe

            origin = 'https://catalog.example.org'
            urls = [origin + '/recipe/1', origin + '/recipe/2']
            definition = {'canonical_host': 'catalog.example.org', 'hosts': ['catalog.example.org'],
                'catalog_url': origin + '/catalog', 'recipe_pattern': r'/recipe/\\d+',
                'catalog_pattern': r'/(?:catalog(?:/[^/]+)?|sitemap\\.xml)'}
            pages = {
                origin + '/robots.txt': ('User-agent: *\\nAllow: /\\nSitemap: ' + origin + '/sitemap.xml', 'text/plain'),
                origin + '/': ('<html><a href="/catalog">Recipes</a></html>', 'text/html'),
                origin + '/catalog': ('<html><a href="/catalog/soups">Soups</a><a href="/catalog/mains">Mains</a></html>', 'text/html'),
                origin + '/catalog/soups': ('<html><a href="/recipe/1">Soup</a></html>', 'text/html'),
                origin + '/catalog/mains': ('<html><a href="/recipe/2">Rice</a></html>', 'text/html'),
                origin + '/sitemap.xml': ('<urlset>' + ''.join('<url><loc>' + url + '</loc></url>' for url in urls) + '</urlset>', 'application/xml'),
            }
            for number, url in enumerate(urls):
                node = {'@type': 'Recipe', 'name': ['Soup', 'Rice'][number], 'recipeYield': '2',
                    'recipeCategory': ['Soups', 'Mains'][number], 'image': origin + '/cover.png',
                    'recipeIngredient': ['Молоко 100 мл'], 'recipeInstructions': [
                        {'@type': 'HowToStep', 'text': 'Prepare the milk.', 'image': origin + '/step.png'},
                        {'@type': 'HowToStep', 'text': 'Stir and serve.', 'image': origin + '/step.png'}]}
                pages[url] = ('<html><script type="application/ld+json">' + json.dumps(node) + '</script></html>', 'text/html')
            picture = io.BytesIO()
            Image.new('RGB', (3, 3), 'orange').save(picture, format='PNG')
            reached_second = threading.Event()
            continue_second = threading.Event()

            class Client:
                def __init__(self, *args, **kwargs):
                    self.check_cancel = args[0] if args and callable(args[0]) else lambda: None
                    self.current_url = args[1] if len(args) > 1 and callable(args[1]) else lambda url: None
                    self.blocked = set()
                def pacing_summary(self):
                    return {}
                def fetch(self, url, limit, accept='text/html'):
                    self.check_cancel()
                    self.current_url(url)
                    if url == urls[1]:
                        reached_second.set()
                        if not continue_second.wait(10):
                            raise CollectionError('Fixture navigation did not finish')
                    if url not in pages:
                        raise CollectionError('No fixture catalog at ' + url)
                    text, mime = pages[url]
                    return text.encode(), mime, url
                def fetch_cover(self, url):
                    self.check_cancel()
                    return picture.getvalue(), 'image/png', url

            with fixture.db._SessionLocal() as session:
                source = ImportSource(key='fixture', name='Fixture site', definition_json=json.dumps(definition),
                                      enabled=True, verified=True, visible_in_catalog=True)
                session.add(source)
                session.commit()
                source_id = source.id
            created = fixture.client.post('/api/admin/imports/jobs', headers=ADMIN,
                json={'source_id': source_id, 'mode': 'index', 'limit': 0})
            assert created.status_code == 200, created.text
            job_id = created.json()['id']
            failures = []
            def execute():
                try:
                    with fixture.db._SessionLocal() as session:
                        assert jobs.claim_job(session, 'integration-worker') == job_id
                    jobs.run_job(job_id, 'integration-worker', threading.Event())
                except BaseException as exc:
                    failures.append(exc)
            with patch.object(jobs, 'JobClient', Client), patch.object(jobs, 'configure_tls', return_value=(None, 'Fixture TLS')):
                thread = threading.Thread(target=execute)
                thread.start()
                try:
                    assert reached_second.wait(8), failures
                    # Navigating away only performs ordinary API requests; it must not cancel the server worker.
                    assert fixture.client.get('/api/recipe-sources', headers=MEMBER).status_code == 200
                    status = fixture.client.get('/api/admin/imports/jobs', headers=ADMIN)
                    assert status.status_code == 200 and status.json()[0]['status'] == 'running', status.text
                    with fixture.db._SessionLocal() as session:
                        assert session.query(Recipe).count() == 0
                    assert not list((fixture.root / 'uploads').iterdir())
                finally:
                    continue_second.set()
                    thread.join(12)
                assert not thread.is_alive() and not failures, failures
            with fixture.db._SessionLocal() as session:
                job = session.get(ImportJob, job_id)
                assert job.status == 'completed', job.report_json
                assert session.query(Recipe).count() == 0
            listed = fixture.client.get('/api/site-recipes', headers=MEMBER)
            assert listed.status_code == 200 and listed.json()['total'] == 2, listed.text
            card = listed.json()['items'][0]
            detail = fixture.client.get('/api/site-recipes/' + str(card['id']), headers=MEMBER)
            assert detail.status_code == 200 and len(detail.json()['steps']) == 2, detail.text
            assert detail.json()['steps'][0]['image_url'] == origin + '/step.png'
            with fixture.db._SessionLocal() as session:
                assert session.query(Recipe).count() == 0
            assert not list((fixture.root / 'uploads').iterdir())
            categories = fixture.client.get('/api/admin/imports/sources/' + str(source_id) + '/categories', headers=ADMIN)
            assert categories.status_code == 200 and len(categories.json()) >= 2, categories.text
            with patch.object(catalog, 'Client', Client), patch.object(catalog, 'configure_tls', return_value=(None, 'Fixture TLS')):
                imported = fixture.client.post('/api/site-recipes/' + str(card['id']) + '/import', headers=MEMBER)
                assert imported.status_code == 200, imported.text
                again = fixture.client.post('/api/site-recipes/' + str(card['id']) + '/import', headers=MEMBER)
                assert again.status_code == 200 and again.json()['already_imported'], again.text
                assert again.json()['recipe_id'] == imported.json()['recipe_id']
            with fixture.db._SessionLocal() as session:
                assert session.query(Recipe).count() == 1
                personal = session.get(Recipe, imported.json()['recipe_id'])
                assert personal.author_id == 2 and not personal.is_public
                assert personal.image and all(step.image for step in personal.steps)
            hidden = fixture.client.patch('/api/admin/imports/sources/' + str(source_id), headers=ADMIN,
                json={'visible_in_catalog': False})
            assert hidden.status_code == 200, hidden.text
            assert fixture.client.get('/api/site-recipes', headers=MEMBER).json()['total'] == 0
            assert fixture.client.get('/api/site-recipes/' + str(card['id']), headers=MEMBER).status_code == 404
            assert fixture.client.post('/api/site-recipes/' + str(card['id']) + '/import', headers=MEMBER).status_code == 404
            uploaded = {path.relative_to(fixture.root / 'uploads') for path in (fixture.root / 'uploads').rglob('*') if path.is_file()}
            removed = fixture.client.delete('/api/admin/imports/sources/' + str(source_id), headers=ADMIN)
            assert removed.status_code == 200, removed.text
            listed_sources = fixture.client.get('/api/admin/imports/sources', headers=ADMIN)
            assert listed_sources.status_code == 200
            assert source_id not in {item['id'] for item in listed_sources.json()}
            with fixture.db._SessionLocal() as session:
                personal = session.get(Recipe, imported.json()['recipe_id'])
                assert personal and personal.image and all(step.image for step in personal.steps)
                assert session.query(Recipe).count() == 1
            assert uploaded == {path.relative_to(fixture.root / 'uploads') for path in (fixture.root / 'uploads').rglob('*') if path.is_file()}
        '''
        script = ('import sys\n' + f'sys.path.insert(0, {str(FIXTURES)!r})\n' +
                  'from import_admin_fixture import environment, ADMIN, MEMBER\n' +
                  'with environment() as fixture:\n' + textwrap.indent(textwrap.dedent(body), '    '))
        result = subprocess.run([sys.executable, '-B', '-W', 'error::ResourceWarning', '-c', script],
                                cwd=BACKEND, capture_output=True, text=True, timeout=55)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
