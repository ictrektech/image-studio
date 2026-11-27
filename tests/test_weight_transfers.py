import base64
import asyncio
import hashlib
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.config import settings
from app.services import weight_sync
from app.services.weight_transfers import MAX_CHUNK_BYTES, WeightTransfers
from app.worker import WORKER_MODE, deployed_worker


class WeightTransferTests(unittest.TestCase):
    headers = {"Authorization": "Bearer fixture-worker-channel"}
    chunk_type = {"Content-Type": "application/octet-stream"}
    route = "/scheduler/transfers"

    def setUp(self):
        temporary = self.enterContext(tempfile.TemporaryDirectory())
        deployment = {"mode": WORKER_MODE, "profile": "l4t"}
        self.enterContext(patch.dict(os.environ, {
            "V_SCHEDULER_BACKEND_CONFIG_B64": base64.b64encode(json.dumps(deployment).encode()).decode(),
            "V_SCHEDULER_BACKEND_CHANNEL_TOKEN": "fixture-worker-channel",
        }))
        self.enterContext(patch.object(settings, "data_dir", Path(temporary)))
        self.enterContext(patch.object(settings, "profile", "original"))
        self.enterContext(patch.object(settings, "sd_cpp_extra_args", ""))
        self.enterContext(patch.object(settings, "scheduler_executor_token", ""))
        self.enterContext(patch.object(settings, "scheduler_required", False))
        self.enterContext(patch.object(settings, "mock_when_runtime_missing", True))
        self.api = self.enterContext(TestClient(deployed_worker(), headers=self.headers))

    def manifest(self, content):
        return {"model_id": "sd-turbo", "files": [{
            "file_id": "model",
            "path": "sd_turbo.safetensors",
            "size_bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }]}

    def begin(self, manifest):
        response = self.api.post(self.route, json=manifest)
        self.assertEqual(response.status_code, 200, response.text)
        return self.route + "/" + response.json()["transfer_id"]

    def append(self, route, offset, content, api=None):
        return (api or self.api).put(
            route + "/files/model",
            params={"offset": offset},
            content=content,
            headers=self.chunk_type,
        )

    def test_requires_private_channel_and_validates_manifest(self):
        manifest = self.manifest(b"weights")
        self.assertEqual(self.api.post(self.route, json=manifest, headers={"Authorization": "wrong"}).status_code, 401)
        with patch.dict(os.environ, {"V_SCHEDULER_BACKEND_CHANNEL_TOKEN": ""}):
            self.assertEqual(self.api.post(self.route, json=manifest).status_code, 401)
        manifest["files"][0]["path"] = "../sd_turbo.safetensors"
        self.assertEqual(self.api.post(self.route, json=manifest).status_code, 422)
        manifest["model_id"] = "flux-schnell"
        self.assertEqual(self.api.post(self.route, json=manifest).status_code, 422)
        self.assertEqual(self.api.get("/api/v1/models").status_code, 404)

    def test_reports_only_verified_models_on_a_compute_worker(self):
        route = self.begin(self.manifest(b"weights"))
        url = "/scheduler/capabilities"
        self.assertEqual(self.api.get(url, headers={"Authorization": "wrong"}).status_code, 401)
        with patch("app.worker.shutil.which", return_value="/runtime/sd-cli"):
            self.assertEqual(self.api.get(url).json()["async_models"], [])
            self.assertEqual(self.append(route, 0, b"weights").status_code, 200)
            self.assertEqual(self.api.post(route + "/complete").json()["model_id"], "sd-turbo")
            response = self.api.get(url).json()
            self.assertEqual(response["async_models"], [{"id": "sd-turbo", "task_type": "image.generate"}])
            self.assertEqual(response["execution_settings"]["profile"], "l4t")

    def test_retries_resume_and_complete_after_worker_restart(self):
        first = b"x" * MAX_CHUNK_BYTES
        last = b"bytes"
        manifest = self.manifest(first + last)
        route = self.begin(manifest)
        self.assertEqual(self.append(route, 0, first + last).status_code, 413)
        self.assertEqual(self.append(route, 5, first).status_code, 409)
        self.assertEqual(self.append(route, 0, first).json(), {"received_bytes": len(first)})
        self.assertEqual(self.append(route, 0, first).json(), {"received_bytes": len(first)})
        self.assertEqual(self.append(route, 0, b"different").status_code, 409)
        self.assertEqual(self.api.post(route + "/complete").status_code, 409)
        with TestClient(deployed_worker(), headers=self.headers) as restarted:
            self.assertEqual(restarted.post(self.route, json=manifest).json()["files"][0]["received_bytes"], len(first))
            self.assertEqual(self.append(route, len(first), last, api=restarted).status_code, 200)
            result = restarted.post(route + "/complete")
            self.assertEqual(result.status_code, 200)
            self.assertTrue(result.json()["verified"])
            self.assertEqual(restarted.post(route + "/complete").json(), result.json())

    def test_checksum_failure_allows_reupload(self):
        route = self.begin(self.manifest(b"correct"))
        self.assertEqual(self.append(route, 0, b"invalid").status_code, 200)
        self.assertEqual(self.api.post(route + "/complete").json()["detail"], "WEIGHT_CHECKSUM_MISMATCH")
        status = self.api.get(route).json()
        self.assertFalse(status["verified"])
        self.assertEqual(status["files"][0]["received_bytes"], 0)
        self.assertEqual(self.append(route, 0, b"correct").status_code, 200)
        self.assertTrue(self.api.post(route + "/complete").json()["verified"])

    def test_read_only_share_is_verified_without_a_copy_and_pins_snapshot(self):
        share = Path(settings.data_dir) / "share"
        source = share / "export" / "model"
        snapshot = source / "snapshots" / "first"
        snapshot.mkdir(parents=True)
        blob = source / "blob"
        blob.write_bytes(b"weights")
        (snapshot / "sd_turbo.safetensors").symlink_to(blob)
        (source / "current").symlink_to(snapshot, target_is_directory=True)
        manifest = self.manifest(b"weights")
        manifest["source"] = "shared"
        manifest["files"][0]["shared_path"] = "export/model/current/sd_turbo.safetensors"
        with patch("app.worker.SHARED_MODELS", share), TestClient(deployed_worker(), headers=self.headers) as worker:
            self.assertEqual(worker.get("/scheduler/model-hub").json(), {"state": "unavailable"})
            with patch("app.services.weight_transfers.os.statvfs", return_value=SimpleNamespace(f_flag=os.ST_RDONLY)):
                self.assertEqual(worker.get("/scheduler/model-hub").json(), {"state": "ready"})
                start = worker.post(self.route, json=manifest)
                self.assertEqual(start.status_code, 200, start.text)
                transfer_id = start.json()["transfer_id"]
                route = self.route + "/" + transfer_id
                self.assertEqual(self.append(route, 0, b"weights", api=worker).status_code, 409)
                completed = worker.post(route + "/complete")
                self.assertEqual(completed.status_code, 200, completed.text)
                self.assertTrue(completed.json()["verified"])
                self.assertEqual(completed.json()["source"], "shared")
                (source / "current").unlink()
                store = WeightTransfers(Path(settings.data_dir) / "weight-transfers", share)
                self.assertEqual(store.verified_paths(transfer_id, "sd-turbo")["model"], snapshot / "sd_turbo.safetensors")
                self.assertFalse((store.root / transfer_id / "model").exists())

    def test_status_reports_shared_bytes_while_worker_is_still_verifying(self):
        share = Path(settings.data_dir) / "share"
        share.mkdir()
        weight = b"weights"
        (share / "sd_turbo.safetensors").write_bytes(weight)
        manifest = self.manifest(weight)
        manifest["source"] = "shared"
        manifest["files"][0]["shared_path"] = "sd_turbo.safetensors"
        started, release = Event(), Event()

        def slow_hash(path, progress):
            progress(3)
            started.set()
            if not release.wait(5):
                raise TimeoutError("test did not release hashing")
            return hashlib.sha256(path.read_bytes()).hexdigest()

        with (
            patch("app.worker.SHARED_MODELS", share),
            patch("app.services.weight_transfers.os.statvfs", return_value=SimpleNamespace(f_flag=os.ST_RDONLY)),
            patch("app.services.weight_transfers.sha256_file", side_effect=slow_hash),
            TestClient(deployed_worker(), headers=self.headers) as worker,
            ThreadPoolExecutor(max_workers=1) as pool,
        ):
            transfer_id = worker.post(self.route, json=manifest).json()["transfer_id"]
            route = self.route + "/" + transfer_id
            call = pool.submit(worker.post, route + "/complete")
            try:
                self.assertTrue(started.wait(5))
                status = worker.get(route).json()
                self.assertEqual(status["verification"], {"state": "verifying", "bytes": 3})
                self.assertFalse(status["verified"])
                self.assertEqual(status["files"][0]["received_bytes"], 0)
            finally:
                release.set()
            self.assertTrue(call.result(timeout=5).json()["verified"])

    def test_main_follows_worker_verification_after_channel_timeout(self):
        async def probe():
            progress = []
            calls = iter([2, 5, 8])

            async def request(client, method, path, **kwargs):
                if method == "POST":
                    raise HTTPException(502, "BACKEND_CHANNEL_UNAVAILABLE")
                checked = next(calls)
                return {
                    "model_id": "sd-turbo", "verified": checked == 8,
                    "verification": {"state": "verified" if checked == 8 else "verifying", "bytes": checked},
                }

            with patch.object(weight_sync, "deployment_request", side_effect=request):
                status = await weight_sync._follow_verification(None, "transfer", 8, lambda *update: progress.append(update))
            self.assertTrue(status["verified"])
            self.assertEqual(progress, [("target_check", 2, 8), ("target_check", 5, 8)])

        asyncio.run(probe())

    def test_main_node_resumes_through_scheduler_and_registers_verified_weights(self):
        weight = Path(settings.data_dir) / "sd_turbo.safetensors"
        weight.write_bytes(b"a" * MAX_CHUNK_BYTES + b"b")
        deployment = "a" * 32
        gateway = f"/api/v1/backend-deployments/{deployment}/"
        uploads = []
        registrations = []
        client_type = httpx.AsyncClient

        def scheduler(request):
            self.assertEqual(request.headers["Authorization"], "Bearer fixture-service")
            self.assertTrue(request.url.path.startswith(gateway))
            operation = request.url.path.removeprefix(gateway)
            if operation == "models":
                body = json.loads(request.content)
                self.assertTrue(self.api.get(f"{self.route}/{body['transfer_id']}").json()["verified"])
                registrations.append(body["model_id"])
                return httpx.Response(200, json={"code": "OK", "data": {"executor_id": "executor", "node_id": "node"}})
            if request.method == "PUT":
                uploads.append(int(request.url.params["offset"]))
                if len(uploads) == 2:
                    raise httpx.ReadTimeout("simulated interrupted transfer")
            response = self.api.request(
                request.method,
                "/scheduler/" + operation,
                params=request.url.params,
                headers={"content-type": request.headers.get("content-type", "")},
                content=request.content,
            )
            self.assertEqual(response.status_code, 200, response.text)
            return httpx.Response(200, json={"code": "OK", "data": response.json()})

        with (
            patch.object(settings, "modelhub_root", Path(settings.data_dir)),
            patch.object(settings, "scheduler_url", "http://scheduler.test/api/v1"),
            patch.object(settings, "scheduler_token", "fixture-service"),
            patch.object(weight_sync, "assert_model_hub_ready", new_callable=AsyncMock),
            patch.object(weight_sync, "model_path_for", return_value=weight),
            patch.object(weight_sync, "runtime_paths_for", return_value={}),
            patch.object(weight_sync.httpx, "AsyncClient", side_effect=lambda **kwargs: client_type(
                transport=httpx.MockTransport(scheduler), **kwargs,
            )),
        ):
            with self.assertRaises(HTTPException) as error:
                asyncio.run(weight_sync.sync_weights(deployment, "sd-turbo"))
            self.assertEqual(error.exception.status_code, 503)
            self.assertEqual(registrations, [])
            registration = asyncio.run(weight_sync.sync_weights(deployment, "sd-turbo"))
            self.assertEqual(registration["executor_id"], "executor")
            self.assertEqual(registration["node_id"], "node")
            self.assertRegex(registration["transfer_id"], r"^[0-9a-f]{64}$")
            self.assertEqual(registrations, ["sd-turbo"])
            self.assertEqual(uploads, [0, MAX_CHUNK_BYTES, MAX_CHUNK_BYTES])

    def test_main_node_prefers_shared_and_only_falls_back_when_unavailable(self):
        source = Path(settings.data_dir) / "sd_turbo.safetensors"
        source.write_bytes(b"weights")
        deployment = "a" * 32
        factory = httpx.AsyncClient
        for share_fails in (False, True):
            with self.subTest(share_fails=share_fails):
                uploads = []
                sources = []

                def bridge(request):
                    path = request.url.path
                    if path.endswith("/model-hub"):
                        data = {"state": "ready"}
                    elif path.endswith("/transfers"):
                        submitted = json.loads(request.content)
                        sources.append(submitted.get("source", "copy"))
                        if submitted.get("source") == "shared":
                            self.assertEqual(submitted["files"][0]["shared_path"], "sd_turbo.safetensors")
                            if share_fails:
                                return httpx.Response(409, json={"code": "BACKEND_SHARED_MODEL_HUB_UNAVAILABLE"})
                        data = {"transfer_id": "b" * 64, "files": [{"file_id": "model", "received_bytes": 0}]}
                    elif request.method == "PUT":
                        uploads.append(request.content)
                        data = {"received_bytes": len(request.content)}
                    elif path.endswith("/complete"):
                        data = {"verified": True, "model_id": "sd-turbo"}
                    else:
                        data = {"executor_id": "executor", "node_id": "node"}
                    return httpx.Response(200, json={"code": "OK", "data": data})

                with (
                    patch.object(settings, "modelhub_root", Path(settings.data_dir)),
                    patch.object(settings, "scheduler_url", "http://scheduler.test/api/v1"),
                    patch.object(settings, "scheduler_token", "fixture-service"),
                    patch.object(weight_sync, "assert_model_hub_ready", new_callable=AsyncMock),
                    patch.object(weight_sync, "model_path_for", return_value=source),
                    patch.object(weight_sync, "runtime_paths_for", return_value={}),
                    patch.object(weight_sync.httpx, "AsyncClient", side_effect=lambda **opts: factory(
                        transport=httpx.MockTransport(bridge), **opts,
                    )),
                ):
                    result = asyncio.run(weight_sync.sync_weights(deployment, "sd-turbo"))
                self.assertEqual(result["weight_source"], "copy" if share_fails else "shared")
                self.assertEqual(sources, ["shared", "copy"] if share_fails else ["shared"])
                self.assertEqual(uploads, [b"weights"] if share_fails else [])
