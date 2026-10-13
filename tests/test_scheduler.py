import asyncio
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import HTTPException
from app.config import settings
from app.services.scheduler import _atomic, _authorize, _path


class SchedulerAdapterTests(unittest.TestCase):
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
