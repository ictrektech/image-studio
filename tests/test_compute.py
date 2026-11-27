import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.config import settings
from app.routers import compute


class ComputeTests(unittest.TestCase):
    def test_preparation_persists_progress_below_one_percent(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "progress.json"
            record = {
                "deployment_id": "a" * 32, "model_id": "sd-turbo", "state": "transferring",
                "phase": "source_check", "received_bytes": 0, "total_bytes": 0,
            }

            async def sync(deployment_id, model_key, variant, progress):
                progress("copying", 0, 5_000_000_000)
                progress("copying", 1_048_576, 5_000_000_000)
                self.assertEqual(json.loads(receipt.read_text())["received_bytes"], 0)
                progress("copying", 2_097_152, 5_000_000_000)
                self.assertEqual(json.loads(receipt.read_text())["received_bytes"], 2_097_152)
                raise HTTPException(503, "COMPUTE_SCHEDULER_UNAVAILABLE")

            with (
                patch.object(compute, "sync_weights", side_effect=sync),
                patch.object(compute, "monotonic", side_effect=[10, 10.5, 11.5]),
            ):
                asyncio.run(compute._prepare(receipt, record, compute.PrepareModelRequest(model_key="sd-turbo")))
            self.assertEqual(json.loads(receipt.read_text())["state"], "failed")

    def test_delete_remote_model_clears_receipts_only_after_scheduler_confirms(self):
        app = FastAPI()
        app.include_router(compute.router)
        app.dependency_overrides[compute.require_compute_admin] = lambda: None
        deployment_id = "b" * 32
        model_id = "sd-turbo"
        deployment = {
            "app_id": compute.APP_ID, "config": {"mode": compute.WORKER_MODE},
            "state": "running", "endpoint": "http://worker.test:42000",
        }
        route = f"/api/v1/compute/deployments/{deployment_id}/models/{model_id}"
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(settings, "data_dir", Path(directory)),
            patch.object(compute, "deployment_client", side_effect=httpx.AsyncClient),
            patch.object(compute, "deployment_request", new_callable=AsyncMock) as call,
            TestClient(app) as client,
        ):
            path = compute._preparation_path(deployment_id, model_id)
            path.parent.mkdir(parents=True)
            path.write_text("{}")
            registered = path.with_suffix(".registered")
            registered.write_text("{}")
            call.side_effect = [deployment, HTTPException(409, "BACKEND_TASKS_ACTIVE")]
            self.assertEqual(client.delete(route).json(), {"detail": "BACKEND_TASKS_ACTIVE"})
            self.assertTrue(path.is_file())
            self.assertTrue(registered.is_file())
            call.side_effect = [deployment, {"deleted_transfers": 2}]
            self.assertEqual(client.delete(route).json(), {"deleted_transfers": 2})
            self.assertEqual(call.await_args.args[1:], ("DELETE", f"backend-deployments/{deployment_id}/models/{model_id}"))
            self.assertFalse(path.exists())
            self.assertFalse(registered.exists())

    def test_deployment_uses_authorized_fixed_profile_and_packaged_image(self):
        app = FastAPI()
        app.include_router(compute.router)
        image = "registry.example.test/team/backend:orin"
        catalog = {"jetson-orin": {"image": image, "profile": "l4t"}}
        env = {"IMAGE_STUDIO_BACKEND_IMAGES": json.dumps(catalog)}
        target = {"kind": "ssh", "id": "node-orin", "profile": "jetson-orin"}
        received = []
        new_client = httpx.AsyncClient

        def scheduler(request):
            self.assertEqual(request.headers["Authorization"], "Bearer fixture-application")
            if request.url.path.endswith("/managed-nodes"):
                data = {"items": [{"id": "node-orin", "profile": "jetson-orin", "name": "Orin"}]}
            elif request.url.path.endswith(f"/backend-deployment-access/{compute.APP_ID}"):
                data = {"targets": [target], "repositories": [image.rsplit(":", 1)[0]]}
            else:
                received.append(json.loads(request.content))
                data = {"id": "a" * 32, "state": "pending"}
            return httpx.Response(200, json={"code": "OK", "data": data})

        response = {"code": 0, "data": {"id": "operator", "enable": 1, "delete": 0, "role_code": "normal_user"}}
        identity = AsyncMock(return_value=httpx.Response(200, json=response))
        with (
            patch.dict(os.environ, env),
            patch.object(settings, "scheduler_url", "http://scheduler.test/api/v1"),
            patch.object(settings, "scheduler_token", "fixture-application"),
            patch("app.routers.compute.deployment_client", side_effect=lambda: new_client(
                base_url=settings.scheduler_url + "/", headers={"Authorization": "Bearer " + settings.scheduler_token},
                transport=httpx.MockTransport(scheduler),
            )),
            patch.object(httpx.AsyncClient, "get", identity),
            TestClient(app) as api,
        ):
            request = {"kind": "ssh", "node_id": "node-orin", "request_key": "first-deploy"}
            route = "/api/v1/compute/deployments"
            self.assertEqual(api.post(route, json=request).status_code, 401)
            headers = {"Authorization": "Bearer fixture-vos"}
            self.assertEqual(api.post(route, json=request, headers=headers).status_code, 403)
            self.assertEqual(received, [])
            response["data"]["role_code"] = "system_admin"
            identity.return_value = httpx.Response(200, json=response)
            self.assertEqual(api.post(route, json={**request, "node_id": "ungranted"}, headers=headers).status_code, 403)
            reply = api.post(route, json=request, headers=headers)
            self.assertEqual(reply.status_code, 200, reply.text)
            self.assertEqual(received, [{
                "request_key": "first-deploy", "target": target, "image": image, "container_port": 5000,
                "config": {"mode": "image-studio-worker-v1", "profile": "l4t"},
            }])
