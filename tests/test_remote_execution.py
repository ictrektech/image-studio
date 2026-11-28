import asyncio
import base64
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI

from app.config import settings
from app.models import JobRecord
from app.routers import compute
from app.services import remote_execution, scheduler, weight_sync
from app.services.storage import job_dir, load_job, save_job


class RemoteExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_backend_lifecycle_is_scoped_and_uses_scheduler(self):
        deployment = "a" * 32
        route = f"/api/v1/compute/deployments/{deployment}"
        app = FastAPI()
        app.include_router(compute.router)
        app.dependency_overrides[compute.require_compute_admin] = lambda: None
        worker = {"app_id": compute.APP_ID, "config": {"mode": compute.WORKER_MODE}}
        path = f"backend-deployments/{deployment}"
        with (
            patch.object(settings, "scheduler_url", "http://scheduler.test/api/v1"),
            patch.object(settings, "scheduler_token", "fixture-service"),
            patch.object(compute, "deployment_request", new_callable=AsyncMock) as upstream,
        ):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://studio.test") as client:
                for method, suffix, forwarded, state in (
                    ("POST", "/stop", path + "/stop", "stopping"),
                    ("POST", "/start", path + "/start", "pending"),
                    ("DELETE", "", path, "deleting"),
                ):
                    upstream.reset_mock()
                    upstream.side_effect = [worker, {"id": deployment, "state": state}]
                    response = await client.request(method, route + suffix)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json(), {"id": deployment, "state": state})
                    self.assertEqual([call.args[1:] for call in upstream.await_args_list], [("GET", path), (method, forwarded)])

                upstream.reset_mock()
                upstream.side_effect = [{"app_id": "com.example.other", "config": {"mode": compute.WORKER_MODE}}]
                self.assertEqual((await client.delete(route)).status_code, 404)
                self.assertEqual(upstream.await_count, 1)

                upstream.reset_mock()
                with patch.dict(compute._pending, {(deployment, "sd-turbo"): object()}):
                    blocked = await client.delete(route)
                self.assertEqual(blocked.json(), {"detail": "COMPUTE_MODEL_PREPARATION_ACTIVE"})
                upstream.assert_not_awaited()

    async def test_overview_names_deployed_nodes_and_keeps_undeployed_targets(self):
        inventory = {"items": [
            {"id": "spark-a", "name": "Spark A", "profile": "dgx-spark"},
            {"id": "spark-b", "name": "Spark B", "profile": "dgx-spark"},
        ]}
        image = "registry.test/app/backend:thor_20261125"
        catalog = {"jetson-thor": {"image": image, "profile": "thor"}}
        grant = {"targets": [{"kind": "ssh", "id": name, "profile": "dgx-spark"}
                             for name in ("spark-a", "spark-b")], "repositories": ["registry.test/app/backend"]}
        deployments = {"items": [{
            "id": "a" * 32, "target_kind": "ssh", "target_id": "spark-a", "app_id": compute.APP_ID,
            "config": {"mode": compute.WORKER_MODE}, "profile": "dgx-spark", "image": image,
            "state": "running", "last_error": None,
        }]}
        directory = self.enterContext(tempfile.TemporaryDirectory())
        with (
            patch.object(settings, "data_dir", Path(directory)),
            patch.object(settings, "scheduler_url", "http://scheduler.test/api/v1"),
            patch.object(settings, "scheduler_token", "fixture-service"),
            patch.object(compute, "_catalog", return_value=catalog),
            patch.object(compute, "deployment_request", new_callable=AsyncMock, side_effect=[inventory, grant, deployments]),
        ):
            overview = await compute.compute_overview()
        self.assertEqual([target["name"] for target in overview["targets"]], ["Spark A", "Spark B"])
        self.assertEqual([(row["node_name"], row["state"]) for row in overview["deployments"]], [("Spark A", "running")])

    async def test_user_can_match_a_placement_to_the_scheduler_node(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(settings, "data_dir", Path(directory)))
        self.enterContext(patch.object(settings, "scheduler_url", "http://scheduler.test/api/v1"))
        self.enterContext(patch.object(settings, "scheduler_token", "fixture-service"))
        deployment = "a" * 32
        model = "sd-turbo"
        registered = compute._preparation_path(deployment, model).with_suffix(".registered")
        registered.parent.mkdir(parents=True)
        registered.write_text(json.dumps({
            "deployment_id": deployment, "model_id": model, "runtime_profile": "thor",
            "node_id": "spark-worker", "executor_id": "app-remote-image-studio-fixture",
            "model_parameters": {"has_reference": False, "weight_type": "f16"},
        }))
        app = FastAPI()
        app.include_router(compute.placement_router)
        scheduler_receipt = {"items": [{"id": deployment, "app_id": compute.APP_ID, "state": "running",
                                         "endpoint": "http://worker.test", "target_kind": "ssh", "target_id": "spark"}]}
        inventory = {"items": [{"id": "spark", "name": "Spark test node"}]}
        with (
            patch.object(compute, "_catalog", return_value={"jetson-thor": {}}),
            patch.object(compute, "deployment_request", new_callable=AsyncMock, side_effect=[scheduler_receipt, inventory]),
            patch("app.services.session.verify_vos_identity", new_callable=AsyncMock, return_value=True),
        ):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://studio.test") as client:
                response = await client.get("/api/v1/compute/placements", headers={"Authorization": "Bearer user-fixture"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [{
            "deployment_id": deployment, "model_id": model, "profile": "thor", "node_id": "spark-worker", "node_name": "Spark test node",
            "executor_id": "app-remote-image-studio-fixture", "runtime_parameters": {"weight_type": "f16"},
            "has_reference": False,
        }])

        registration = json.loads(registered.read_text())
        registration.update(model_limits={}, model_parameters={"policy": "direct"})
        registered.write_text(json.dumps(registration))
        with (
            patch.object(compute, "_catalog", return_value={"jetson-thor": {}}),
            patch.object(compute, "deployment_request", new_callable=AsyncMock, side_effect=[scheduler_receipt, inventory]),
            patch("app.services.session.verify_vos_identity", new_callable=AsyncMock, return_value=True),
        ):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://studio.test") as client:
                response = await client.get("/api/v1/compute/placements", headers={"Authorization": "Bearer user-fixture"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["runtime_parameters"], {})
        self.assertIsNone(response.json()[0]["has_reference"])
        self.assertEqual(response.json()[0]["node_id"], "spark-worker")

    async def test_execution_uses_selected_deployment_with_fence_and_returns_verified_output(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(settings, "data_dir", Path(directory)))
        self.enterContext(patch.object(settings, "scheduler_url", "http://scheduler.test/api/v1"))
        self.enterContext(patch.object(settings, "scheduler_token", "fixture-service"))
        self.enterContext(patch.object(settings, "scheduler_executor_token", "fixture-callback"))
        deployment_id = "a" * 32
        executor = "app-remote-image-studio-fixture"
        now = datetime.now(timezone.utc)
        job = JobRecord(
            job_id="job_fixture", user_key="owner", status="queued", prompt="a fixture",
            model_key="sd-turbo", model_path="", width=512, height=512, steps=4,
            cfg_scale=1, sampler="euler_a", seed=1, batch_count=1, created_at=now, updated_at=now,
            metadata={"compute_deployment_id": deployment_id, "compute_executor_id": executor,
                      "scheduler_managed": True, "scheduler_task_id": "task-fixture"},
        )
        policy = {
            "executor_id": executor, "transfer_id": "b" * 64,
            "model_limits": {"width": 512, "height": 512, "steps": 4, "batch_count": 1, "video_frames": 0,
                             "prompt_characters": 200, "negative_prompt_characters": 200},
            "model_parameters": scheduler.runtime_parameters(job),
        }
        save_job(job)
        attempt = "cccccccc-cccc-cccc-cccc-cccccccccccc"
        command = {"task_id": "task-fixture", "executor_id": executor, "fence": 7,
                   "parameters": {"user_key": "owner", "job_id": "job_fixture"}, "lease_seconds": 30}
        headers = "Bearer fixture-callback"
        image = b"verified output bytes"
        calls = []

        def bridge(request):
            path = request.url.path.removeprefix(f"/api/v1/backend-deployments/{deployment_id}/executions/{attempt}/")
            self.assertEqual(request.headers["Authorization"], "Bearer fixture-service")
            calls.append(path)
            if path == "start":
                payload = json.loads(request.content)
                self.assertEqual(payload["task_id"], command["task_id"])
                self.assertEqual(payload["fence"], 7)
                self.assertEqual(payload["job"]["user_key"], "owner")
                self.assertNotIn("metadata", payload["job"])
                return httpx.Response(200, json={"code": "OK", "data": {"status": "running", "stopped": False}})
            if path == "inspect":
                return httpx.Response(200, json={"code": "OK", "data": {
                    "status": "succeeded", "stopped": True, "result": {"outputs": ["output.png"]},
                }})
            self.assertEqual(path, "outputs/output.png")
            self.assertEqual(request.headers["X-Scheduler-Fence"], "7")
            return httpx.Response(200, json={"code": "OK", "data": {
                "offset": 0, "size_bytes": len(image), "sha256": hashlib.sha256(image).hexdigest(),
                "data_b64": base64.b64encode(image).decode(),
            }})

        factory = httpx.AsyncClient
        with (
            patch("app.routers.compute.registered_compute_model", return_value=policy),
            patch.object(weight_sync.httpx, "AsyncClient", side_effect=lambda **opts: factory(
                transport=httpx.MockTransport(bridge), **opts,
            )),
        ):
            started = await scheduler.execute(attempt, command, headers)
            self.assertEqual(started["status"], "running")
            waiting = await scheduler.inspect(attempt, command, headers)
            self.assertEqual(waiting, {"status": "running", "stopped": False, "progress": {"percent": 0.99}})
            await asyncio.wait_for(remote_execution._output_tasks[attempt], 5)
            completed = await scheduler.inspect(attempt, command, headers)
            self.assertEqual(completed["status"], "succeeded")
            self.assertEqual(load_job(job.user_key, job.job_id).outputs, ["output.png"])
            self.assertEqual((job_dir(job.user_key, job.job_id) / "output.png").read_bytes(), image)
            self.assertEqual(calls, ["start", "inspect", "outputs/output.png"])
