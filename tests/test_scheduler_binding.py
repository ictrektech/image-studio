import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.services import scheduler_binding as binding
from app.services.scheduler import RUNTIME_PARAMETER_FIELDS
from app.models import JobRecord


class BindingTests(unittest.TestCase):
    def test_native_scheduler_origin_is_not_an_openai_v1_endpoint(self):
        self.assertEqual(binding.UPSTREAM, 'http://image-studio-backend:5000')

    def test_binding_requires_scheduler_identity_and_preserves_revision(self):
        app = FastAPI()
        app.include_router(binding.router)
        config = {'protocol_version': 1, 'binding_revision': 2, 'app_id': binding.APP_ID, 'url': binding.URL, 'upstream_url': binding.UPSTREAM, 'token': 'a' * 32, 'executor_token': 'b' * 32, 'models': {'model': 'app.model'}, 'model_limits': {'model': {'width': 512, 'height': 512, 'steps': 10, 'batch_count': 1, 'video_frames': 0}}}
        config['execution_settings'] = binding.execution_settings()
        config['model_limits']['model'].update(prompt_characters=32, negative_prompt_characters=32)
        config['model_parameters'] = {'model': {**{field: JobRecord.model_fields[field].default for field in RUNTIME_PARAMETER_FIELDS}, 'has_reference': False}}
        client = AsyncMock()
        client.__aenter__.return_value = client
        executor = {'id': 'app.model', 'app_id': binding.APP_ID, 'contract_version': '1', 'task_type': 'image.generate', 'upstream_urls': [binding.UPSTREAM]}
        with patch("app.services.scheduler.start", new_callable=AsyncMock), patch.object(settings, "scheduler_url", ""), patch.object(settings, "scheduler_token", ""), patch.object(settings, "scheduler_executor_token", ""), patch.object(settings, "scheduler_models", {}), patch.object(settings, "scheduler_model_limits", {}), tempfile.TemporaryDirectory() as directory, patch.object(binding, 'config_path', return_value=Path(directory) / 'binding.json'), patch.object(binding.httpx, 'AsyncClient', return_value=client), patch.object(binding, 'controller', return_value=[executor]), patch.dict(os.environ, {'VOS_USERINFO_URL': 'http://identity/userinfo'}):
            client.get.return_value = httpx.Response(200, json={'sub': 'ordinary-user', 'enable': 1}, request=httpx.Request('GET', 'http://identity/userinfo'))
            with TestClient(app) as api:
                self.assertEqual(api.post('/api/v1/scheduler/binding', json=config).status_code, 403)
                client.get.return_value = httpx.Response(200, json={'sub': 'com.ictrek.v-scheduler', 'enable': 1}, request=httpx.Request('GET', 'http://identity/userinfo'))
                legacy = binding.config_path()
                legacy.write_text(json.dumps({'url': 'http://v-scheduler:38120/api/v1', 'token': 'x' * 32, 'executor_token': 'y' * 32}))
                legacy.chmod(0o600)
                self.assertEqual(api.get('/api/v1/scheduler/binding').json()['configured'], False)
                response = api.post('/api/v1/scheduler/binding', json=config)
                self.assertEqual(response.status_code, 200, response.text)
                saved = binding.config_path()
                self.assertEqual(saved.stat().st_mode & 0o777, 0o600)
                self.assertEqual(json.loads(saved.read_text()), config)
                self.assertEqual(api.post('/api/v1/scheduler/binding', json=config).status_code, 200)
                self.assertNotIn(config['token'], api.get('/api/v1/scheduler/binding').text)
                self.assertEqual(api.post('/api/v1/scheduler/binding', json={**config, 'binding_revision': 1}).status_code, 409)
                saved.write_text(json.dumps({**config, 'execution_settings': {'profile': 'old'}}))
                self.assertEqual(api.get('/api/v1/scheduler/binding').json()['configured'], False)
                self.assertEqual(api.post('/api/v1/scheduler/binding', json={**config, 'binding_revision': 3}).status_code, 200)
                pending = SimpleNamespace(status="queued", metadata={"scheduler_managed": True})
                with patch('app.services.storage.load_job', return_value=pending), patch.object(Path, 'glob', return_value=[Path('owned/pending.json')]):
                    response = api.post('/api/v1/scheduler/binding', json={**config, 'binding_revision': 4})
                    self.assertEqual(response.status_code, 200, response.text)
                    pending.metadata['scheduler_task_id'] = 'accepted'
                    self.assertEqual(api.post('/api/v1/scheduler/binding', json={**config, 'binding_revision': 5}).status_code, 409)
                    pending.status = 'failed'
                    self.assertEqual(api.post('/api/v1/scheduler/binding', json={**config, 'binding_revision': 5}).status_code, 200)
                saved.chmod(0o644)
                self.assertEqual(api.post('/api/v1/scheduler/binding', json={**config, 'binding_revision': 4}).status_code, 503)
