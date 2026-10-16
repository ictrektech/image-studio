import asyncio
import json
import sys
import os
import subprocess
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import HTTPException
from app.config import settings
from app.services.scheduler import RUNTIME_PARAMETER_FIELDS, _atomic, _authorize, _path, model_id, runtime_parameters, validate_limits
from app.models import JobRecord


class SchedulerAdapterTests(unittest.TestCase):
    def test_calibrated_limits_cover_variant_video_and_high_resolution(self):
        job = SimpleNamespace(model_key="model", model_variant="q4", width=512, height=512, steps=10, batch_count=1, video_frames=0, hires=False, hires_width=0, hires_height=0, hires_scale=2, hires_steps=0, prompt="test", negative_prompt="", metadata={}, **{field: JobRecord.model_fields[field].default for field in RUNTIME_PARAMETER_FIELDS})
        limits = {"width": 512, "height": 512, "steps": 10, "batch_count": 1, "video_frames": 0, "prompt_characters": 32, "negative_prompt_characters": 32}
        from app.services.scheduler_binding import execution_settings
        with patch.object(settings, "scheduler_required", True), patch.object(settings, "scheduler_config", {"execution_settings": execution_settings()}), patch.object(settings, "scheduler_model_limits", {"model@q4": limits}), patch.object(settings, "scheduler_model_parameters", {"model@q4": runtime_parameters(job)}):
            self.assertEqual(model_id(job), "model@q4")
            validate_limits(job)
            job.backend = "cpu"
            with self.assertRaises(HTTPException):
                validate_limits(job)
            job.backend = ""
            job.video_frames = 16
            with self.assertRaises(HTTPException):
                validate_limits(job)
            job.video_frames = 0
            job.hires = True
            with self.assertRaises(HTTPException):
                validate_limits(job)
            job.hires = False
            job.model_variant = "q8"
            with self.assertRaises(HTTPException):
                validate_limits(job)

    def test_private_storage_config_and_explicit_override(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "scheduler.json").write_text(json.dumps({"url": "http://scheduler/api/v1", "token": "x" * 32, "executor_token": "y" * 32}))
            env = {k: v for k, v in os.environ.items() if not k.startswith("IMAGE_STUDIO_SCHEDULER_")}
            env["IMAGE_STUDIO_DATA_DIR"] = folder
            code = "from app.config import settings as s; assert s.scheduler_url=='http://scheduler/api/v1'; assert s.scheduler_executor_token=='y'*32; assert s.scheduler_token=='x'*32"
            subprocess.run([sys.executable, "-c", code], env=env, check=True)
            env["IMAGE_STUDIO_SCHEDULER_TOKEN"] = "z" * 32
            subprocess.run([sys.executable, "-c", "from app.config import settings as s; assert s.scheduler_token=='z'*32"], env=env, check=True)

    def test_internal_execution_requires_dedicated_credential(self):
        with patch.object(settings, "scheduler_executor_token", "x" * 32):
            with self.assertRaises(HTTPException):
                _authorize("Bearer wrong")
            _authorize("Bearer " + "x" * 32)

    def test_attempt_reference_cannot_escape_storage(self):
        with self.assertRaises(HTTPException):
            _path("../../outside")

    def test_atomic_files_with_same_stem_keep_separate_contents(self):
        # These three files previously shared one .tmp name across processes.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            paths = [root / ("attempt" + suffix) for suffix in [".json", ".lease", ".process"]]
            from concurrent.futures import ThreadPoolExecutor
            def writer(item):
                i, path = item
                for n in range(100):
                    _atomic(path, {"file": i, "sequence": n})
            with ThreadPoolExecutor(max_workers=3) as pool:
                list(pool.map(writer, enumerate(paths)))
            self.assertEqual([json.loads(p.read_text())["file"] for p in paths], [0, 1, 2])


class AdapterCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def check_cancellation(self, native_alive):
        from app.services import generation, scheduler
        entered = asyncio.Event()
        finished = asyncio.Event()
        job = SimpleNamespace(user_key="synthetic", job_id="synthetic", status="running", outputs=[], error="", progress=0.5)

        async def native_work(_job):
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                finished.set()

        with tempfile.TemporaryDirectory() as folder, patch.object(settings, "data_dir", Path(folder)), patch.object(settings, "scheduler_executor_token", "x" * 32), patch.object(generation, "run_job", native_work), patch.object(scheduler, "load_job", return_value=job), patch.object(scheduler, "_marker", return_value={"stopped": not native_alive}), patch.object(scheduler, "_alive", return_value=native_alive):
            attempt = str(uuid.uuid4())
            body = {"fence": 1, "parameters": {"user_key": job.user_key, "job_id": job.job_id}}
            record = {"attempt_id": attempt, "fence": 1, "parameters": body["parameters"], "status": "running", "stopped": False}
            path = scheduler._path(attempt)
            scheduler._atomic(path, record)
            scheduler._lease(path, time.monotonic() + 60)
            task = asyncio.create_task(scheduler._execute(path, record, job))
            scheduler._executions[attempt] = task
            try:
                await entered.wait()
                result = await scheduler.cancel(attempt, body, "Bearer " + "x" * 32)
                self.assertTrue(task.done())
                self.assertTrue(finished.is_set())
                self.assertEqual(job.status, "running")
                self.assertEqual(result["status"], "unknown" if native_alive else "cancelled")
                self.assertEqual(result["stopped"], not native_alive)
                persisted = json.loads(path.read_text())
                self.assertEqual(persisted["status"], result["status"])
            finally:
                scheduler._executions.pop(attempt, None)
                scheduler._locks.pop(attempt, None)

    async def test_cancelled_adapter_is_terminal_even_before_business_job_status_sync(self):
        await self.check_cancellation(False)

    async def test_native_process_still_alive_never_reports_stopped(self):
        await self.check_cancellation(True)


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux process supervisor")
class LeaseSupervisorTests(unittest.IsolatedAsyncioTestCase):
    async def test_child_is_reaped_when_lease_expires_without_agent(self):
        with tempfile.TemporaryDirectory() as folder:
            lease = Path(folder) / "attempt.lease"
            _atomic(lease, {"deadline": time.monotonic() + 0.5})
            process = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "app.services.scheduler_process", str(lease),
                sys.executable, "-c", "import time; time.sleep(60)",
            )
            await asyncio.wait_for(process.wait(), 8)
            marker = json.loads(lease.with_suffix(".process").read_text())
            self.assertTrue(marker["stopped"])
            self.assertFalse(Path(f"/proc/{marker.get('child_pid', 0)}").exists())
            self.assertEqual(json.loads(lease.read_text()).keys(), {"deadline"})
