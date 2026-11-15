"""Durable import leases, cancellation and in-process recipe writes."""
from __future__ import annotations

import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

BACKEND = Path(__file__).parents[1]
FIXTURES = Path(__file__).parent


class ImportJobTests(unittest.TestCase):
    def run_case(self, body: str):
        script = ("import sys\n" + f"sys.path.insert(0, {str(FIXTURES)!r})\n" +
                  "from import_admin_fixture import environment\n" +
                  "with environment(router=False) as fixture:\n" + textwrap.indent(textwrap.dedent(body), "    "))
        result = subprocess.run([sys.executable, "-B", "-W", "error::ResourceWarning", "-c", script],
                                cwd=BACKEND, capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_claim_is_exclusive_and_stale_recovery_keeps_progress_without_reimport(self):
        self.run_case("""
            import json
            from datetime import timedelta
            from app import import_jobs as jobs
            from app.models import ImportJob, ImportSource, utcnow
            with fixture.db._SessionLocal() as session:
                source = ImportSource(key='fixture', name='Fixture', definition_json='{}')
                session.add(source)
                session.commit()
                job = ImportJob(source_id=source.id, author_id=1, parameters_json='{}', active_slot='collector',
                                report_json=json.dumps({'created': 3, 'recipes': [{'id': 17}]}))
                session.add(job)
                session.commit()
                job_id = job.id
                assert jobs.claim_job(session, 'owner-one') == job_id
            with fixture.db._SessionLocal() as session:
                assert jobs.claim_job(session, 'owner-two') is None
                job = session.get(ImportJob, job_id)
                assert job.owner_id == 'owner-one' and job.status == 'running'
            assert not jobs.refresh_lease(job_id, 'owner-two')
            assert jobs.refresh_lease(job_id, 'owner-one')
            with fixture.db._SessionLocal() as session:
                job = session.get(ImportJob, job_id)
                job.heartbeat_at = utcnow() - timedelta(seconds=jobs.LEASE_SECONDS + 1)
                session.commit()
                assert jobs.claim_job(session, 'owner-two') is None
                session.expire_all()
                recovered = session.get(ImportJob, job_id)
                assert recovered.status == 'stopped' and recovered.active_slot is None
                report = json.loads(recovered.report_json)
                assert report['created'] == 3 and report['recipes'] == [{'id': 17}] and report['interrupted']
        """)

    def test_active_admin_is_rechecked_before_each_adapter_operation(self):
        self.run_case("""
            from app import import_jobs as jobs
            from app.models import User
            from recipe_api import APIError
            adapter = jobs.DatabaseImportAPI(1)
            assert adapter.prepare() == (set(), set())
            with fixture.db._SessionLocal() as session:
                session.get(User, 1).is_admin = False
                session.commit()
            try:
                adapter.prepare()
            except APIError as error:
                assert error.fatal and 'administrator' in str(error)
            else:
                raise AssertionError('Revoked administrator retained import access')
            try:
                jobs.DatabaseImportAPI(2).prepare()
            except APIError:
                pass
            else:
                raise AssertionError('Nonadministrator adapter accepted')
        """)

    def test_adapter_reuses_recipe_operations_and_preserves_content_during_photo_updates(self):
        self.run_case("""
            import io
            from PIL import Image
            from app import import_jobs as jobs
            from app.models import Recipe
            from recipe_api import APIError
            item = {'title': 'Fixture milk recipe', 'description': 'Keep this description', 'category': 'Fixture category',
                    'servings': 2, 'prep_minutes': 1, 'cook_minutes': 2, 'difficulty': None, 'is_public': False,
                    'source_url': 'https://food.ru/recipes/1-fixture', 'tags': ['fixture'],
                    'ingredients': [{'product': 'Milk', 'amount': 100, 'unit': 'мл', 'note': '', 'group': ''}],
                    'steps': [{'text': 'Mix the milk.', 'timer_minutes': 3}], 'image': None, 'photos': []}
            adapter = jobs.DatabaseImportAPI(1)
            recipe_id = adapter.create_recipe(item)
            urls, titles = adapter.prepare()
            assert urls == {item['source_url']} and item['title'].casefold() in titles
            assert len(adapter.owned_recipes) == 1 and not adapter.owned_recipes[0].has_image
            step_id = adapter.recipe_steps(recipe_id)[0].id
            try:
                adapter.create_recipe({**item, 'title': 'Different title for same source'})
            except APIError as error:
                assert not error.fatal
            else:
                raise AssertionError('Duplicate source created another recipe')
            image = io.BytesIO()
            Image.new('RGB', (2, 2), 'red').save(image, format='PNG')
            adapter.upload_cover(recipe_id, image.getvalue(), 'image/png')
            adapter.upload_step_image(recipe_id, step_id, image.getvalue(), 'image/png')
            assert adapter.recipe_has_cover(recipe_id)
            assert adapter.recipe_steps(recipe_id)[0].has_image
            with fixture.db._SessionLocal() as session:
                recipe = session.get(Recipe, recipe_id)
                assert recipe.title == item['title'] and recipe.description == item['description']
                assert not recipe.is_public and recipe.servings == 2 and recipe.category.name == 'Fixture category'
                assert len(recipe.steps) == 1 and recipe.steps[0].id == step_id
                assert recipe.steps[0].text == 'Mix the milk.' and recipe.steps[0].timer_minutes == 3
                original_image = recipe.steps[0].image
                assert session.query(Recipe).count() == 1
            adapter.upload_step_image(recipe_id, step_id, image.getvalue(), 'image/png')
            with fixture.db._SessionLocal() as session:
                assert session.get(Recipe, recipe_id).steps[0].image == original_image
        """)

    def test_cancelled_run_preserves_checkpointed_progress_and_releases_active_slot(self):
        self.run_case("""
            import json
            import threading
            from dataclasses import asdict
            from unittest.mock import patch
            from recipe_sources import load_sources
            from app import import_jobs as jobs
            from app.models import ImportSource, ImportJob
            definition = asdict(load_sources()['food'])
            parameters = {'definition': definition, 'limit': 5, 'is_public': False, 'urls': [], 'no_step_images': True}
            with fixture.db._SessionLocal() as session:
                source = ImportSource(key='food', name='Fixture', definition_json=json.dumps(definition), verified=True)
                session.add(source)
                session.commit()
                job = ImportJob(source_id=source.id, author_id=1, parameters_json=json.dumps(parameters), active_slot='collector')
                session.add(job)
                session.commit()
                job_id = jobs.claim_job(session, 'fixture-owner')
            def collect(args, client, adapter):
                report = {'created': 1, 'recipes': [{'id': 19}], 'errors': [], 'warnings': []}
                args.progress_callback(report)
                with fixture.db._SessionLocal() as session:
                    job = session.get(ImportJob, job_id)
                    job.cancel_requested, job.status = True, 'stopping'
                    session.commit()
                args.progress_callback(report)
                raise AssertionError('Collection did not stop on cancellation')
            with patch.object(jobs, 'collect', side_effect=collect), patch.object(jobs, 'configure_tls', return_value=(None, 'Fixture TLS')):
                jobs.run_job(job_id, 'fixture-owner', threading.Event())
            with fixture.db._SessionLocal() as session:
                job = session.get(ImportJob, job_id)
                assert job.status == 'stopped' and job.active_slot is None
                report = json.loads(job.report_json)
                assert report['created'] == 1 and report['recipes'] == [{'id': 19}]
        """)

    def test_lost_lease_stops_old_worker_before_it_can_continue_writes(self):
        self.run_case("""
            import json
            import threading
            from dataclasses import asdict
            from unittest.mock import patch
            from recipe_sources import load_sources
            from app import import_jobs as jobs
            from app.models import ImportSource, ImportJob
            definition = asdict(load_sources()['food'])
            parameters = {'definition': definition, 'limit': 5, 'urls': [], 'no_step_images': True}
            with fixture.db._SessionLocal() as session:
                source = ImportSource(key='food', name='Fixture', definition_json=json.dumps(definition), verified=True)
                session.add(source)
                session.commit()
                job = ImportJob(source_id=source.id, author_id=1, parameters_json=json.dumps(parameters), active_slot='collector')
                session.add(job)
                session.commit()
                job_id = jobs.claim_job(session, 'fixture-owner')
            continued = []
            def collect(args, client, adapter):
                with fixture.db._SessionLocal() as session:
                    job = session.get(ImportJob, job_id)
                    job.status, job.active_slot = 'stopped', None
                    session.commit()
                args.progress_callback({'created': 0, 'errors': []})
                continued.append(True)
                return {'created': 0, 'errors': []}
            with patch.object(jobs, 'collect', side_effect=collect), patch.object(jobs, 'configure_tls', return_value=(None, 'Fixture TLS')):
                jobs.run_job(job_id, 'fixture-owner', threading.Event())
            assert not continued, 'A worker continued after its lease had been revoked'
            with fixture.db._SessionLocal() as session:
                job = session.get(ImportJob, job_id)
                assert job.status == 'stopped' and job.active_slot is None
        """)

    def test_category_scope_is_validated_and_passed_to_the_shared_collector(self):
        self.run_case("""
            import json
            import threading
            from dataclasses import asdict
            from unittest.mock import patch
            from recipe_sources import load_sources
            from app import import_jobs as jobs
            from app.models import ImportSource, ImportJob
            definition = asdict(load_sources()['rambler'])
            category = 'https://eda.rambler.ru/recepty/supy?page=2'
            parameters = {'definition': definition, 'limit': 5, 'urls': [], 'no_step_images': True,
                          'catalog_url': category, 'is_public': False}
            with fixture.db._SessionLocal() as session:
                source = ImportSource(key='rambler', name='Fixture', definition_json=json.dumps(definition), verified=True)
                session.add(source)
                session.commit()
                job = ImportJob(source_id=source.id, author_id=1, parameters_json=json.dumps(parameters), active_slot='collector')
                session.add(job)
                session.commit()
                job_id = jobs.claim_job(session, 'fixture-owner')
            seen = []
            def collect(args, client, adapter):
                scoped = args.source_config['source']
                assert scoped.catalog_url == category and scoped.accepts_catalog(category)
                assert args.public is False and args.limit == 5 and args.no_step_images is True
                assert not scoped.accepts_catalog('https://attacker.example.org/recepty/supy')
                seen.append(True)
                return {'created': 0, 'duplicates': 1, 'errors': [], 'warnings': []}
            with patch.object(jobs, 'collect', side_effect=collect), patch.object(jobs, 'configure_tls', return_value=(None, 'Fixture TLS')):
                jobs.run_job(job_id, 'fixture-owner', threading.Event())
            assert seen
            with fixture.db._SessionLocal() as session:
                job = session.get(ImportJob, job_id)
                assert job.status == 'completed' and job.active_slot is None
                assert json.loads(job.report_json)['duplicates'] == 1
        """)

    def test_real_collector_imports_recipe_and_step_photos_and_checkpoints_database_report(self):
        self.run_case("""
            import io
            import json
            import threading
            from dataclasses import asdict
            from unittest.mock import patch
            from PIL import Image
            from recipe_sources import load_sources
            from app import import_jobs as jobs
            from app.models import ImportSource, ImportJob, Recipe
            source_url = 'https://food.ru/recipes/1-fixture'
            cover_url = 'https://cdn.food.ru/cover.png'
            step_url = 'https://cdn.food.ru/step.png'
            node = {'@type': 'Recipe', 'name': 'Shared collector fixture', 'recipeYield': '2', 'image': cover_url,
                    'recipeIngredient': ['Молоко 100 мл'], 'recipeInstructions': [
                        {'@type': 'HowToStep', 'text': 'Pour the milk.', 'image': step_url},
                        {'@type': 'HowToStep', 'text': 'Stir the milk.', 'image': step_url}]}
            page = ('<script type="application/ld+json">' + json.dumps(node) + '</script>').encode()
            image = io.BytesIO()
            Image.new('RGB', (2, 2), 'red').save(image, format='PNG')
            class Client:
                def __init__(self, check_cancel, current_url, **kwargs):
                    self.check_cancel, self.current_url = check_cancel, current_url
                def fetch(self, url, limit, accept='text/html'):
                    assert url == source_url
                    self.check_cancel()
                    self.current_url(url)
                    return page, 'text/html', url
                def fetch_cover(self, url):
                    assert url in (cover_url, step_url)
                    self.check_cancel()
                    self.current_url(url)
                    return image.getvalue(), 'image/png', url
            definition = asdict(load_sources()['food'])
            parameters = {'definition': definition, 'limit': 1, 'urls': [source_url], 'is_public': False, 'no_step_images': False}
            with fixture.db._SessionLocal() as session:
                source = ImportSource(key='food', name='Fixture', definition_json=json.dumps(definition), verified=True)
                session.add(source)
                session.commit()
                job = ImportJob(source_id=source.id, author_id=1, parameters_json=json.dumps(parameters), active_slot='collector')
                session.add(job)
                session.commit()
                job_id = jobs.claim_job(session, 'fixture-owner')
            with patch.object(jobs, 'JobClient', Client), patch.object(jobs, 'configure_tls', return_value=(None, 'Fixture TLS')):
                jobs.run_job(job_id, 'fixture-owner', threading.Event())
            with fixture.db._SessionLocal() as session:
                job = session.get(ImportJob, job_id)
                assert job.status == 'completed' and job.active_slot is None
                report = json.loads(job.report_json)
                assert report['created'] == 1 and report['step_images'] == 2, report
                assert report['current_url'] == step_url
                recipe = session.get(Recipe, report['recipes'][0]['id'])
                assert recipe.title == 'Shared collector fixture' and recipe.image and not recipe.is_public
                assert recipe.source_url == source_url and len(recipe.ingredients) == 1
                assert [step.text for step in recipe.steps] == ['Pour the milk.', 'Stir the milk.']
                assert all(step.image for step in recipe.steps)
                assert session.query(Recipe).count() == 1
        """)

    def test_probe_rejects_invalid_mime_and_corrupt_image_bytes_without_network(self):
        self.run_case("""
            import json
            from dataclasses import asdict
            from unittest.mock import patch
            from recipe_sources import load_sources
            from collect_recipes import CollectionError
            from app import import_jobs as jobs
            source_url = 'https://food.ru/recipes/1-fixture'
            node = {'@type': 'Recipe', 'name': 'Fixture', 'recipeYield': '2', 'image': 'https://cdn.food.ru/image',
                    'recipeIngredient': ['Молоко 100 мл'], 'recipeInstructions': ['Mix.']}
            page = ('<script type="application/ld+json">' + json.dumps(node) + '</script>').encode()
            class Client:
                mime = 'text/plain'
                def __init__(self, *args, **kwargs): pass
                def fetch(self, url, limit): return page, 'text/html', url
                def fetch_cover(self, url): return b'Not an image', self.mime, url
            definition = json.loads(json.dumps(asdict(load_sources()['food'])))
            for mime in ('text/plain', 'image/png'):
                Client.mime = mime
                with patch.object(jobs, 'Client', Client), patch.object(jobs, 'discover', return_value=iter([source_url])), \
                     patch.object(jobs, 'configure_tls', return_value=(None, 'Fixture TLS')):
                    try:
                        jobs.probe_source(definition)
                    except CollectionError:
                        pass
                    else:
                        raise AssertionError('Invalid sample cover accepted')
        """)


if __name__ == "__main__":
    unittest.main()
