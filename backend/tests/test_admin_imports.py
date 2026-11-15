"""Admin source/job behavior against an isolated SQLite database and API."""
from __future__ import annotations

import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

BACKEND = Path(__file__).parents[1]
FIXTURES = Path(__file__).parent


class AdminImportTests(unittest.TestCase):
    def run_case(self, body: str, *, router: bool = True):
        script = ("import sys\n" + f"sys.path.insert(0, {str(FIXTURES)!r})\n" +
                  "from import_admin_fixture import environment, ADMIN, MEMBER\n" +
                  f"with environment(router={router!r}) as fixture:\n" + textwrap.indent(textwrap.dedent(body), "    "))
        result = subprocess.run([sys.executable, "-B", "-W", "error::ResourceWarning", "-c", script],
                                cwd=BACKEND, capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_admin_endpoints_reject_anonymous_and_regular_accounts(self):
        self.run_case("""
            client = fixture.client
            assert client.get('/api/admin/imports/sources').status_code == 401
            assert client.get('/api/admin/imports/sources', headers=MEMBER).status_code == 403
            assert client.get('/api/admin/imports/jobs', headers=MEMBER).status_code == 403
            assert client.post('/api/admin/imports/jobs', headers=MEMBER, json={'source_id': 1}).status_code == 403
            assert client.get('/api/recipe-sources').status_code == 401
            assert client.get('/api/recipe-sources', headers=MEMBER).status_code == 200
            with fixture.db._SessionLocal() as session:
                assert session.query(fixture.models.ImportSource).count() == 0
        """)

    def test_presets_are_persistent_but_cannot_import_until_verified(self):
        self.run_case("""
            client = fixture.client
            first = client.get('/api/admin/imports/sources', headers=ADMIN)
            assert first.status_code == 200, first.text
            sources = first.json()
            assert {source['key'] for source in sources} == {'food', 'rambler', 'iamcook'}
            assert all(not source['verified'] for source in sources)
            assert client.get('/api/admin/imports/sources', headers=ADMIN).json() == sources
            rejected = client.post('/api/admin/imports/jobs', headers=ADMIN, json={'source_id': sources[0]['id']})
            assert rejected.status_code == 409, rejected.text
            assert client.get('/api/recipe-sources', headers=MEMBER).json() == []
            with fixture.db._SessionLocal() as session:
                assert session.query(fixture.models.ImportSource).count() == 3
                assert session.query(fixture.models.ImportJob).count() == 0
        """)

    def test_source_check_persists_success_and_failure_and_catalog_visibility(self):
        self.run_case("""
            from types import ModuleType
            from collect_recipes import CollectionError
            probe = ModuleType('app.import_jobs')
            probe.probe_source = lambda definition: {'title': 'Fixture recipe', 'source_url': 'https://food.ru/recipes/1-fixture', 'ingredients': 2, 'steps': 3, 'step_images': 2, 'has_cover': True}
            sys.modules['app.import_jobs'] = probe
            client = fixture.client
            source = client.get('/api/admin/imports/sources', headers=ADMIN).json()[0]
            checked = client.post(f"/api/admin/imports/sources/{source['id']}/check", headers=ADMIN)
            assert checked.status_code == 200, checked.text
            assert checked.json()['verified'] and checked.json()['sample']['ingredients'] == 2
            assert client.get('/api/recipe-sources', headers=MEMBER).json()[0]['id'] == source['id']
            disabled = client.patch(f"/api/admin/imports/sources/{source['id']}", headers=ADMIN, json={'enabled': False})
            assert disabled.status_code == 200 and not disabled.json()['enabled']
            assert client.get('/api/recipe-sources', headers=MEMBER).json() == []
            def failed(definition):
                raise CollectionError('Fixture recipe does not contain ingredients')
            probe.probe_source = failed
            failure = client.post(f"/api/admin/imports/sources/{source['id']}/check", headers=ADMIN)
            assert failure.status_code == 422
            persisted = client.get('/api/admin/imports/sources', headers=ADMIN).json()[0]
            assert not persisted['verified'] and 'ingredients' in persisted['last_error']
        """)

    def test_invalid_probe_is_not_saved_and_host_duplicates_are_rejected(self):
        self.run_case("""
            from types import ModuleType
            from collect_recipes import CollectionError
            probe = ModuleType('app.import_jobs')
            def failed(definition):
                raise CollectionError('Fixture probe failed')
            probe.probe_source = failed
            sys.modules['app.import_jobs'] = probe
            definition = {'canonical_host': 'recipes.example.org', 'hosts': ['recipes.example.org'],
                          'catalog_url': 'https://recipes.example.org/catalog', 'recipe_pattern': '/recipe/[0-9]+', 'catalog_pattern': '/catalog'}
            payload = {'name': 'Fixture source', 'catalog_url': definition['catalog_url'], 'definition': definition}
            client = fixture.client
            rejected = client.post('/api/admin/imports/sources', headers=ADMIN, json=payload)
            assert rejected.status_code == 422, rejected.text
            with fixture.db._SessionLocal() as session:
                assert session.query(fixture.models.ImportSource).count() == 0
            probe.probe_source = lambda definition: {'title': 'Fixture', 'ingredients': 1, 'steps': 1}
            created = client.post('/api/admin/imports/sources', headers=ADMIN, json=payload)
            assert created.status_code == 200, created.text
            assert created.json()['verified']
            duplicate = client.post('/api/admin/imports/sources', headers=ADMIN, json=payload)
            assert duplicate.status_code == 409
            invalid = client.post('/api/admin/imports/sources', headers=ADMIN,
                                  json={**payload, 'catalog_url': 'http://127.0.0.1/catalog'})
            assert invalid.status_code == 422
        """)

    def test_unknown_site_is_detected_verified_and_persisted_without_manual_json(self):
        self.run_case("""
            import json
            from types import ModuleType
            from unittest.mock import Mock
            definition = {'canonical_host': 'recipes.example.org', 'hosts': ['recipes.example.org'],
                          'catalog_url': 'https://recipes.example.org/recipes/', 'recipe_pattern': '/recipes/dish-[^/]+',
                          'catalog_pattern': '/recipes/', 'recipe_trailing_slash': True}
            discovery = ModuleType('source_discovery')
            discovery.detect_source = Mock(return_value=definition)
            sys.modules['source_discovery'] = discovery
            probe = ModuleType('app.import_jobs')
            probe.probe_source = Mock(return_value={'title': 'Discovered recipe', 'ingredients': 2, 'steps': 3})
            sys.modules['app.import_jobs'] = probe
            created = fixture.client.post('/api/admin/imports/sources', headers=ADMIN,
                                          json={'catalog_url': 'https://recipes.example.org'})
            assert created.status_code == 200, created.text
            data = created.json()
            assert data['verified'] and data['catalog_url'] == definition['catalog_url']
            assert data['sample']['title'] == 'Discovered recipe'
            discovery.detect_source.assert_called_once_with('https://recipes.example.org')
            probe.probe_source.assert_called_once_with(definition)
            with fixture.db._SessionLocal() as session:
                stored = session.get(fixture.models.ImportSource, data['id'])
                assert json.loads(stored.definition_json) == definition
            duplicate = fixture.client.post('/api/admin/imports/sources', headers=ADMIN,
                                            json={'catalog_url': 'https://recipes.example.org'})
            assert duplicate.status_code == 409
            assert discovery.detect_source.call_count == 1
            job = fixture.client.post('/api/admin/imports/jobs', headers=ADMIN,
                                      json={'source_id': data['id'], 'urls': ['https://recipes.example.org/recipes/dish-soup']})
            assert job.status_code == 200, job.text
            assert job.json()['parameters']['urls'] == ['https://recipes.example.org/recipes/dish-soup/']
        """)

    def test_failed_autodetection_or_sample_validation_does_not_connect_a_site(self):
        self.run_case("""
            from types import ModuleType
            from unittest.mock import Mock
            from collect_recipes import CollectionError
            discovery = ModuleType('source_discovery')
            discovery.detect_source = Mock(side_effect=CollectionError('Не найден совместимый рецепт'))
            sys.modules['source_discovery'] = discovery
            probe = ModuleType('app.import_jobs')
            probe.probe_source = Mock(side_effect=CollectionError('Обложка недоступна'))
            sys.modules['app.import_jobs'] = probe
            payload = {'catalog_url': 'https://recipes.example.org'}
            failed = fixture.client.post('/api/admin/imports/sources', headers=ADMIN, json=payload)
            assert failed.status_code == 422 and 'совместимый' in failed.json()['detail']
            probe.probe_source.assert_not_called()
            discovery.detect_source.side_effect = None
            discovery.detect_source.return_value = {'canonical_host': 'recipes.example.org', 'hosts': ['recipes.example.org'],
                'catalog_url': 'https://recipes.example.org/recipes', 'recipe_pattern': '/recipe/[^/]+', 'catalog_pattern': '/recipes'}
            failed = fixture.client.post('/api/admin/imports/sources', headers=ADMIN, json=payload)
            assert failed.status_code == 422 and 'Обложка' in failed.json()['detail']
            with fixture.db._SessionLocal() as session:
                assert session.query(fixture.models.ImportSource).count() == 0
        """)

    def test_job_scope_validation_stop_and_resume_preserve_previous_job(self):
        self.run_case("""
            import json
            client = fixture.client
            source = client.get('/api/admin/imports/sources', headers=ADMIN).json()[0]
            with fixture.db._SessionLocal() as session:
                session.get(fixture.models.ImportSource, source['id']).verified = True
                session.commit()
            base = {'source_id': source['id'], 'mode': 'import', 'limit': 7, 'is_public': False}
            invalid = client.post('/api/admin/imports/jobs', headers=ADMIN,
                                  json={**base, 'urls': ['https://attacker.example.org/recipes/1-test']})
            assert invalid.status_code == 422
            invalid_catalog = client.post('/api/admin/imports/jobs', headers=ADMIN,
                                          json={**base, 'catalog_url': 'https://attacker.example.org/catalog'})
            assert invalid_catalog.status_code == 422
            created = client.post('/api/admin/imports/jobs', headers=ADMIN,
                                  json={**base, 'urls': ['https://food.ru/recipes/1-fixture?utm_source=fixture']})
            assert created.status_code == 200, created.text
            first = created.json()
            assert first['status'] == 'queued' and first['parameters']['urls'] == ['https://food.ru/recipes/1-fixture']
            assert client.post('/api/admin/imports/jobs', headers=ADMIN, json=base).status_code == 409
            stopped = client.post(f"/api/admin/imports/jobs/{first['id']}/stop", headers=ADMIN).json()
            assert stopped['status'] == 'stopped' and stopped['cancel_requested']
            resumed = client.post(f"/api/admin/imports/jobs/{first['id']}/resume", headers=ADMIN)
            assert resumed.status_code == 200, resumed.text
            second = resumed.json()
            assert second['id'] != first['id'] and second['status'] == 'queued'
            assert second['parameters'] == first['parameters']
            with fixture.db._SessionLocal() as session:
                old = session.get(fixture.models.ImportJob, first['id'])
                new = session.get(fixture.models.ImportJob, second['id'])
                assert old.status == 'stopped' and old.active_slot is None
                assert new.author_id == 1 and new.active_slot == 'collector'
        """)

    def test_stopping_running_job_keeps_slot_until_worker_acknowledges(self):
        self.run_case("""
            client = fixture.client
            source = client.get('/api/admin/imports/sources', headers=ADMIN).json()[0]
            with fixture.db._SessionLocal() as session:
                session.get(fixture.models.ImportSource, source['id']).verified = True
                session.commit()
            created = client.post('/api/admin/imports/jobs', headers=ADMIN, json={'source_id': source['id']}).json()
            with fixture.db._SessionLocal() as session:
                job = session.get(fixture.models.ImportJob, created['id'])
                job.status = 'running'
                session.commit()
            stopped = client.post(f"/api/admin/imports/jobs/{created['id']}/stop", headers=ADMIN)
            assert stopped.status_code == 200 and stopped.json()['status'] == 'stopping'
            assert stopped.json()['cancel_requested']
            another = client.post('/api/admin/imports/jobs', headers=ADMIN, json={'source_id': source['id']})
            assert another.status_code == 409
        """)

    def test_catalog_source_filter_keeps_visibility_and_exact_host_boundaries(self):
        self.run_case("""
            import json
            from dataclasses import asdict
            from recipe_sources import load_sources
            from app.models import ImportSource, Recipe
            from app.routers import recipes
            fixture.app.include_router(recipes.router)
            with fixture.db._SessionLocal() as session:
                source = ImportSource(key='food', name='Food fixture', definition_json=json.dumps(asdict(load_sources()['food'])),
                                      enabled=True, verified=True)
                session.add(source)
                session.flush()
                source_id = source.id
                session.add_all([
                    Recipe(id=11, title='Public Food', author_id=1, is_public=True, source_url='https://food.ru/recipes/11-public'),
                    Recipe(id=12, title='Private Food', author_id=1, is_public=False, source_url='https://food.ru/recipes/12-private'),
                    Recipe(id=13, title='Own Food', author_id=2, is_public=False, source_url='https://food.ru/recipes/13-own'),
                    Recipe(id=14, title='Other site', author_id=1, is_public=True, source_url='https://eda.rambler.ru/recepty/test/other-14'),
                    Recipe(id=15, title='Lookalike host', author_id=1, is_public=True, source_url='https://food.ru.attacker.example/recipes/15-other'),
                    Recipe(id=16, title='Configured alias', author_id=1, is_public=True, source_url='http://www.food.ru/recipes/16-alias'),
                ])
                session.commit()
            member = fixture.client.get(f'/api/recipes?source_id={source_id}', headers=MEMBER)
            assert member.status_code == 200, member.text
            assert member.json()['total'] == 3
            assert {item['id'] for item in member.json()['items']} == {11, 13, 16}
            admin = fixture.client.get(f'/api/recipes?source_id={source_id}', headers=ADMIN)
            assert admin.status_code == 200, admin.text
            assert {item['id'] for item in admin.json()['items']} == {11, 12, 13, 16}
            assert fixture.client.get('/api/recipes?source_id=999', headers=MEMBER).status_code == 404
            with fixture.db._SessionLocal() as session:
                session.get(ImportSource, source_id).enabled = False
                session.commit()
            assert fixture.client.get(f'/api/recipes?source_id={source_id}', headers=MEMBER).status_code == 404
        """)

    def test_only_one_active_job_is_allowed_and_stopped_jobs_release_the_slot(self):
        self.run_case("""
            import json
            from sqlalchemy.exc import IntegrityError
            from recipe_sources import load_sources
            Source, Job = fixture.models.ImportSource, fixture.models.ImportJob
            with fixture.db._SessionLocal() as session:
                source = Source(key='fixture', name='Fixture', definition_json='{}', enabled=True, verified=True)
                session.add(source)
                session.commit()
                first = Job(source_id=source.id, author_id=1, parameters_json='{}', active_slot='collector')
                session.add(first)
                session.commit()
                session.add(Job(source_id=source.id, author_id=2, parameters_json='{}', active_slot='collector'))
                try:
                    session.commit()
                except IntegrityError:
                    session.rollback()
                else:
                    raise AssertionError('Two active jobs were accepted')
                first = session.get(Job, first.id)
                first.status, first.active_slot = 'stopped', None
                session.commit()
                replacement = Job(source_id=source.id, author_id=1, parameters_json='{}', active_slot='collector')
                session.add(replacement)
                session.commit()
                assert replacement.id != first.id
        """, router=False)

    def test_migration_adds_import_tables_and_downgrade_preserves_existing_tables(self):
        self.run_case("""
            import importlib.util
            from pathlib import Path
            from alembic.migration import MigrationContext
            from alembic.operations import Operations
            from sqlalchemy import inspect
            Source, Job = fixture.models.ImportSource, fixture.models.ImportJob
            Job.__table__.drop(fixture.engine)
            Source.__table__.drop(fixture.engine)
            path = Path('migrations/versions/0013_recipe_imports.py')
            spec = importlib.util.spec_from_file_location('fixture_import_migration', path)
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)
            with fixture.engine.begin() as connection:
                migration.op = Operations(MigrationContext.configure(connection))
                migration.upgrade()
            inspector = inspect(fixture.engine)
            assert {'import_sources', 'import_jobs', 'recipes'} <= set(inspector.get_table_names())
            constraints = inspector.get_unique_constraints('import_jobs')
            assert any(c['column_names'] == ['active_slot'] for c in constraints)
            assert {'ix_import_jobs_source_id', 'ix_import_jobs_author_id', 'ix_import_jobs_status'} <= {
                index['name'] for index in inspector.get_indexes('import_jobs')}
            with fixture.engine.begin() as connection:
                migration.op = Operations(MigrationContext.configure(connection))
                migration.downgrade()
            tables = set(inspect(fixture.engine).get_table_names())
            assert 'recipes' in tables and 'import_sources' not in tables and 'import_jobs' not in tables
        """, router=False)

    def test_large_job_json_fields_use_longtext_on_mysql_and_mariadb(self):
        self.run_case("""
            import importlib.util
            from pathlib import Path
            import sqlalchemy as sa
            from sqlalchemy.dialects import mysql, sqlite
            from sqlalchemy.dialects.mysql.mariadb import MariaDBDialect
            path = Path('migrations/versions/0013_recipe_imports.py')
            spec = importlib.util.spec_from_file_location('fixture_import_types_migration', path)
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)
            tables = {}
            class CaptureOperations:
                def create_table(self, name, *columns, **options):
                    tables[name] = {column.name: column.type for column in columns if isinstance(column, sa.Column)}
                def create_index(self, *args, **kwargs):
                    pass
            migration.op = CaptureOperations()
            migration.upgrade()
            for name in ('parameters_json', 'report_json'):
                types = [fixture.models.ImportJob.__table__.c[name].type, tables['import_jobs'][name]]
                for column_type in types:
                    assert column_type.compile(dialect=mysql.dialect()) == 'LONGTEXT'
                    assert column_type.compile(dialect=MariaDBDialect()) == 'LONGTEXT'
                    assert column_type.compile(dialect=sqlite.dialect()) == 'TEXT'
        """, router=False)


if __name__ == "__main__":
    unittest.main()
