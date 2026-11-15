"""Persistent source settings, metadata categories, migrations and import idempotency."""
from __future__ import annotations

import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

BACKEND = Path(__file__).parents[1]
FIXTURES = Path(__file__).parent


class SourceCatalogAdminTests(unittest.TestCase):
    def run_case(self, body: str, *, router: bool = True):
        script = ("import sys\n" + f"sys.path.insert(0, {str(FIXTURES)!r})\n" +
                  "from import_admin_fixture import environment, ADMIN, MEMBER\n" +
                  f"with environment(router={router!r}) as fixture:\n" + textwrap.indent(textwrap.dedent(body), "    "))
        result = subprocess.run([sys.executable, "-B", "-W", "error::ResourceWarning", "-c", script],
                                cwd=BACKEND, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_rename_delete_preserves_default_source_history_and_personal_recipes(self):
        self.run_case('''
            from app.models import ImportSource, ImportJob, Recipe
            source = fixture.client.get('/api/admin/imports/sources', headers=ADMIN).json()[0]
            source_id = source['id']
            with fixture.db._SessionLocal() as session:
                session.get(ImportSource, source_id).verified = True
                session.add(Recipe(title='Personal recipe', author_id=1, source_url='https://food.ru/recipes/1-fixture', image='owned.png'))
                session.commit()
            image = fixture.root / 'uploads' / 'owned.png'
            image.write_bytes(b'synthetic preserved image')
            renamed = fixture.client.patch(f'/api/admin/imports/sources/{source_id}', headers=ADMIN, json={'name': 'My Food'})
            assert renamed.status_code == 200 and renamed.json()['name'] == 'My Food'
            assert fixture.client.patch(f'/api/admin/imports/sources/{source_id}', headers=ADMIN, json={'name': '  '}).status_code == 422
            job = fixture.client.post('/api/admin/imports/jobs', headers=ADMIN, json={'source_id':source_id, 'limit':0}).json()
            assert job['parameters']['limit'] == 0
            assert fixture.client.delete(f'/api/admin/imports/sources/{source_id}', headers=MEMBER).status_code == 403
            deleted = fixture.client.delete(f'/api/admin/imports/sources/{source_id}', headers=ADMIN)
            assert deleted.status_code == 200
            assert fixture.client.delete(f'/api/admin/imports/sources/{source_id}', headers=ADMIN).status_code == 200
            assert all(row['key'] != 'food' for row in fixture.client.get('/api/admin/imports/sources', headers=ADMIN).json())
            with fixture.db._SessionLocal() as session:
                assert session.query(ImportSource).count() == 3
                assert session.get(ImportJob, job['id']).status == 'stopped'
                assert session.query(Recipe).one().image == 'owned.png'
            assert image.read_bytes() == b'synthetic preserved image'
            assert fixture.client.post('/api/admin/imports/jobs', headers=ADMIN, json={'source_id':source_id}).status_code == 404
        ''')

    def test_deleted_default_can_be_reconnected_after_successful_probe(self):
        self.run_case('''
            from types import ModuleType
            probe = ModuleType('app.import_jobs')
            probe.probe_source = lambda definition: {'title':'Sample','ingredients':1,'steps':1,'has_cover':False}
            sys.modules['app.import_jobs'] = probe
            source = fixture.client.get('/api/admin/imports/sources', headers=ADMIN).json()[0]
            fixture.client.delete(f"/api/admin/imports/sources/{source['id']}", headers=ADMIN)
            response = fixture.client.post('/api/admin/imports/sources', headers=ADMIN, json={'catalog_url':'https://food.ru/sitemap.xml', 'name':'Reconnected'})
            assert response.status_code == 200, response.text
            assert response.json()['id'] == source['id'] and response.json()['name'] == 'Reconnected'
            assert not response.json()['visible_in_catalog'] and not response.json()['auto_refresh']
        ''')

    def test_auto_refresh_is_opt_in_durable_and_stops_for_revoked_administrator(self):
        self.run_case('''
            from app.models import ImportSource, ImportJob, User
            from app.source_catalog import enqueue_scheduled_index
            source = fixture.client.get('/api/admin/imports/sources', headers=ADMIN).json()[0]
            assert not source['auto_refresh'] and source['total_recipes'] is None
            assert fixture.client.patch(f"/api/admin/imports/sources/{source['id']}", headers=ADMIN, json={'auto_refresh':True}).status_code == 409
            with fixture.db._SessionLocal() as session:
                session.get(ImportSource, source['id']).verified = True
                session.commit()
            enabled = fixture.client.patch(f"/api/admin/imports/sources/{source['id']}", headers=ADMIN,
                                           json={'auto_refresh':True,'refresh_interval_hours':12,'visible_in_catalog':True})
            assert enabled.status_code == 200 and enabled.json()['next_refresh_at']
            with fixture.db._SessionLocal() as session:
                enqueue_scheduled_index(session)
                enqueue_scheduled_index(session)
                job = session.query(ImportJob).one()
                assert job.mode == 'index' and job.author_id == 1 and job.status == 'queued'
                job.status, job.active_slot = 'completed', None
                source_row = session.get(ImportSource, source['id'])
                source_row.next_refresh_at = None
                session.get(User, 1).is_admin = False
                session.commit()
                enqueue_scheduled_index(session)
                assert not session.get(ImportSource, source['id']).auto_refresh
                assert session.query(ImportJob).count() == 1
        ''')

    def test_metadata_only_categories_can_scope_jobs_without_an_invented_url(self):
        self.run_case('''
            import json
            from app import importer
            from app.models import ImportSource, SourceRecipe, SourceCategory
            from app.source_catalog import cache_metadata, store_reference
            source = fixture.client.get('/api/admin/imports/sources', headers=ADMIN).json()[0]
            with fixture.db._SessionLocal() as session:
                session.get(ImportSource, source['id']).verified = True
                external = store_reference(session, source['id'], 'https://food.ru/recipes/1-fixture')
                cache_metadata(session, external, importer.ImportedRecipe(title='Soup', category='Soups', source_url=external.url,
                    ingredients=[importer.ParsedIngredient(product='Water')], steps=['Boil water.']))
                session.commit()
                category = session.query(SourceCategory).one()
                category_id = category.id
                assert category.url is None and external.category_id == category.id
            categories = fixture.client.get(f"/api/admin/imports/sources/{source['id']}/categories", headers=ADMIN).json()
            assert categories[0]['url'] is None and categories[0]['recipes_count'] == 1
            result = fixture.client.post('/api/admin/imports/jobs', headers=ADMIN,
                                         json={'source_id':source['id'],'category_id':category_id,'limit':0})
            assert result.status_code == 200, result.text
            assert result.json()['parameters']['catalog_url'] is None
            assert result.json()['parameters']['category_id'] == category_id
        ''')

    def test_metadata_category_is_promoted_when_a_real_category_page_is_discovered(self):
        self.run_case('''
            import json
            from dataclasses import asdict
            from recipe_sources import load_sources
            from app import importer
            from app.models import ImportSource, SourceCategory
            from app.source_catalog import cache_metadata, store_category, store_reference
            with fixture.db._SessionLocal() as session:
                source = ImportSource(key='fixture',name='Fixture',definition_json=json.dumps(asdict(load_sources()['food'])),verified=True)
                session.add(source)
                session.flush()
                external = store_reference(session,source.id,'https://food.ru/recipes/1-fixture')
                cache_metadata(session,external,importer.ImportedRecipe(title='Soup',category='Soups',source_url=external.url,
                    ingredients=[importer.ParsedIngredient(product='Water')],steps=['Boil water.']))
                session.flush()
                category_id = external.category_id
                promoted = store_category(session,source.id,{'url':'https://food.ru/categories/soups','title':'Soups'})
                session.commit()
                assert promoted.id == category_id
                assert promoted.url == 'https://food.ru/categories/soups'
                assert session.query(SourceCategory).count() == 1
        ''', router=False)

    def test_explicit_import_is_idempotent_for_simultaneous_requests(self):
        self.run_case('''
            import concurrent.futures
            from app import importer
            from app.models import ImportSource, Recipe, SourceRecipeImport
            from app.source_catalog import cache_metadata, create_user_import, store_reference
            from recipe_sources import load_sources
            from dataclasses import asdict
            import json
            with fixture.db._SessionLocal() as session:
                source = ImportSource(key='fixture', name='Fixture', definition_json=json.dumps(asdict(load_sources()['food'])),
                                      enabled=True, verified=True, visible_in_catalog=True)
                session.add(source)
                session.flush()
                external = store_reference(session, source.id, 'https://food.ru/recipes/1-fixture')
                cache_metadata(session, external, importer.ImportedRecipe(title='Soup', source_url=external.url,
                    ingredients=[importer.ParsedIngredient(product='Water')], steps=['Boil water.']))
                session.commit()
                external_id = external.id
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: create_user_import(external_id, 2, False), range(2)))
            assert results[0][0] == results[1][0]
            assert sorted(result[1] for result in results) == [False, True]
            with fixture.db._SessionLocal() as session:
                assert session.query(Recipe).count() == 1
                assert session.query(SourceRecipeImport).count() == 1
                assert session.query(Recipe).one().author_id == 2
        ''', router=False)

    def test_worker_manual_urls_and_metadata_category_never_expand_to_the_whole_site(self):
        self.run_case('''
            import json
            import threading
            from dataclasses import asdict
            from app import import_jobs as jobs, importer
            from app.models import ImportSource, ImportJob, Recipe, SourceCategory
            from app.source_catalog import cache_metadata, store_reference
            from recipe_sources import load_sources
            definition = json.loads(json.dumps(asdict(load_sources()['food'])))
            first, second = 'https://food.ru/recipes/1-first', 'https://food.ru/recipes/2-second'
            allowed = {first}
            class FixtureClient(jobs.JobClient):
                def fetch(self, url, limit, accept='text/html'):
                    self.check_cancel()
                    assert url in allowed, 'Unexpected discovery outside selected recipes: ' + url
                    title = 'First soup' if url == first else 'Second soup'
                    page = '<script type="application/ld+json">' + json.dumps({'@type':'Recipe','name':title,
                            'recipeIngredient':['Water 200 ml'],'recipeInstructions':['Boil water.']}) + '</script>'
                    return page.encode(), 'text/html', url
            jobs.JobClient = FixtureClient
            with fixture.db._SessionLocal() as session:
                source = ImportSource(key='fixture', name='Fixture', definition_json=json.dumps(definition), verified=True)
                session.add(source)
                session.flush()
                parameters = {'definition':definition,'limit':0,'urls':[first],'catalog_url':None,'no_step_images':False}
                job = ImportJob(source_id=source.id, author_id=1, parameters_json=json.dumps(parameters), active_slot='collector')
                session.add(job)
                session.commit()
                job_id, source_id = job.id, source.id
                assert jobs.claim_job(session,'owner') == job_id
            jobs.run_job(job_id,'owner',threading.Event())
            with fixture.db._SessionLocal() as session:
                assert session.get(ImportJob,job_id).status == 'completed'
                external = store_reference(session,source_id,second)
                cache_metadata(session,external,importer.ImportedRecipe(title='Second soup',category='Soups',source_url=second,
                    ingredients=[importer.ParsedIngredient(product='Water')],steps=['Boil water.']))
                session.flush()
                category_id = session.query(SourceCategory).one().id
                parameters = {'definition':definition,'limit':0,'urls':[],'catalog_url':None,'category_id':category_id,'no_step_images':False}
                job = ImportJob(source_id=source_id,author_id=1,parameters_json=json.dumps(parameters),active_slot='collector')
                session.add(job)
                session.commit()
                job_id = job.id
                assert jobs.claim_job(session,'owner') == job_id
            allowed.clear()
            allowed.add(second)
            jobs.run_job(job_id,'owner',threading.Event())
            with fixture.db._SessionLocal() as session:
                assert session.get(ImportJob,job_id).status == 'completed'
                assert {recipe.source_url for recipe in session.query(Recipe)} == {first,second}
        ''', router=False)

    def test_index_only_deactivates_missing_recipes_after_a_complete_scan(self):
        self.run_case('''
            import json
            from dataclasses import asdict
            from app.models import ImportSource, Recipe, SourceRecipe
            from app.source_catalog import create_user_import, index_source
            from recipe_sources import load_sources
            definition = json.loads(json.dumps(asdict(load_sources()['food'])))
            first,second = 'https://food.ru/recipes/1-first','https://food.ru/recipes/2-second'
            urls = [first,second]
            class FixtureClient:
                def fetch(self,url,limit,accept='text/html'):
                    if url == definition['catalog_url']:
                        xml = '<urlset>' + ''.join('<url><loc>'+value+'</loc></url>' for value in urls) + '</urlset>'
                        return xml.encode(),'application/xml',url
                    node = {'@type':'Recipe','name':'First soup' if url == first else 'Second soup',
                            'recipeIngredient':['Water 200 ml'],'recipeInstructions':['Boil water.']}
                    return ('<script type="application/ld+json">'+json.dumps(node)+'</script>').encode(),'text/html',url
            with fixture.db._SessionLocal() as session:
                source = ImportSource(key='fixture',name='Fixture',definition_json=json.dumps(definition),
                                      verified=True,visible_in_catalog=True)
                session.add(source)
                session.commit()
                source_id = source.id
            report = index_source(source_id,definition,FixtureClient(),lambda:None,lambda report:None)
            assert report['complete'] and report['indexed'] == 2
            with fixture.db._SessionLocal() as session:
                assert session.query(Recipe).count() == 0
                external = session.query(SourceRecipe).filter_by(url=second).one()
                second_id = external.id
            personal_id,already = create_user_import(second_id,2,False)
            assert not already
            urls[:] = [first]
            partial = index_source(source_id,definition,FixtureClient(),lambda:None,lambda report:None,limit=1)
            assert not partial['complete']
            with fixture.db._SessionLocal() as session:
                assert session.get(SourceRecipe,second_id).active
            complete = index_source(source_id,definition,FixtureClient(),lambda:None,lambda report:None)
            assert complete['complete']
            with fixture.db._SessionLocal() as session:
                assert not session.get(SourceRecipe,second_id).active
                assert session.get(Recipe,personal_id).title == 'Second soup'
                assert session.query(Recipe).count() == 1
            assert list((fixture.root/'uploads').iterdir()) == []
        ''', router=False)

    def test_migration_new_defaults_and_longtext_compile_for_mysql(self):
        self.run_case('''
            import importlib.util
            from pathlib import Path
            import sqlalchemy as sa
            from sqlalchemy.dialects import mysql
            spec = importlib.util.spec_from_file_location('fixture_catalog_ddl',Path('migrations/versions/0014_source_catalog.py'))
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)
            fields,tables = {},{}
            class Capture:
                def add_column(self,table,column): fields[column.name] = column
                def create_table(self,name,*columns,**options): tables[name] = {c.name:c for c in columns if isinstance(c,sa.Column)}
                def create_index(self,*args,**kwargs): pass
            migration.op = Capture()
            migration.upgrade()
            for column in fields.values():
                if not column.nullable: assert column.server_default is not None, column.name
            assert tables['source_recipes']['payload_json'].type.compile(dialect=mysql.dialect()) == 'LONGTEXT'
            assert fields['index_error'].type.compile(dialect=mysql.dialect()) == 'VARCHAR(2000)'
            assert all(not column.foreign_keys for column in fields.values())
        ''', router=False)

    def test_migration_upgrades_populated_sqlite_without_recreating_the_parent_table(self):
        self.run_case('''
            import importlib.util
            import json
            from pathlib import Path
            from sqlalchemy import inspect, text
            from alembic.migration import MigrationContext
            from alembic.operations import Operations
            from app.models import ImportSource, ImportJob, Recipe, SourceRecipe, SourceCategory, SourceRecipeImport
            from dataclasses import asdict
            from recipe_sources import load_sources
            with fixture.db._SessionLocal() as session:
                source = ImportSource(key='fixture', name='Fixture', definition_json=json.dumps(asdict(load_sources()['food'])))
                session.add(source)
                session.flush()
                session.add(ImportJob(source_id=source.id, author_id=1, parameters_json='{}'))
                session.add(Recipe(title='Preserved', author_id=1))
                session.commit()
            for model in (SourceRecipeImport, SourceRecipe, SourceCategory):
                model.__table__.drop(fixture.engine)
            columns = ('deleted_at','index_error','index_complete','next_refresh_at','last_indexed_at','refresh_author_id',
                       'refresh_interval_hours','auto_refresh','visible_in_catalog')
            with fixture.engine.begin() as connection:
                assert connection.execute(text('PRAGMA foreign_keys')).scalar() == 1
                for name in columns:
                    connection.execute(text(f'ALTER TABLE import_sources DROP COLUMN {name}'))
            spec = importlib.util.spec_from_file_location('fixture_catalog_migration', Path('migrations/versions/0014_source_catalog.py'))
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)
            with fixture.engine.begin() as connection:
                migration.op = Operations(MigrationContext.configure(connection))
                migration.upgrade()
            with fixture.db._SessionLocal() as session:
                source = session.query(ImportSource).one()
                assert not source.auto_refresh and not source.visible_in_catalog and source.refresh_interval_hours == 24
                assert session.query(Recipe).one().title == 'Preserved'
                assert session.query(ImportJob).one().source_id == source.id
                assert {'source_categories','source_recipes','source_recipe_imports'} <= set(inspect(fixture.engine).get_table_names())
            with fixture.engine.begin() as connection:
                migration.op = Operations(MigrationContext.configure(connection))
                migration.downgrade()
                assert connection.execute(text('SELECT title FROM recipes')).scalar() == 'Preserved'
                assert connection.execute(text('SELECT count(*) FROM import_jobs')).scalar() == 1
        ''', router=False)


if __name__ == '__main__':
    unittest.main()
