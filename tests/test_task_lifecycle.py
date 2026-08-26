import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import generation, hf_downloader


class DownloadLifecycleTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        hf_downloader._tasks.clear()
        hf_downloader._workers.clear()
        hf_downloader._restart_tasks.clear()
        hf_downloader._bridges.clear()
        hf_downloader._repo_locks.clear()

    async def asyncTearDown(self):
        pending = [
            *hf_downloader._workers.values(),
            *hf_downloader._restart_tasks.values(),
        ]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def test_force_waits_for_old_worker_before_restart(self):
        old_release = asyncio.Event()
        restarted = asyncio.Event()

        async def fake_run(key, sources, force=False):
            if force:
                restarted.set()
                return
            await old_release.wait()

        sources = [{"source": "hf", "model_id": "org/repo", "files": ["model.gguf"]}]
        with patch.object(hf_downloader, "_run", fake_run):
            self.assertEqual(await hf_downloader.start_download("model", sources), "started")
            self.assertEqual(
                await hf_downloader.start_download("model", sources, force=True),
                "waiting",
            )
            await asyncio.sleep(0)
            self.assertFalse(restarted.is_set())
            old_release.set()
            await asyncio.wait_for(restarted.wait(), timeout=1)

    async def test_pending_restart_blocks_a_second_worker(self):
        gate = asyncio.Event()

        async def pending_restart():
            await gate.wait()

        restart = asyncio.create_task(pending_restart())
        hf_downloader._restart_tasks["model"] = restart
        self.assertEqual(await hf_downloader.start_download("model", []), "active")
        self.assertEqual(
            await hf_downloader.start_download("model", [], force=True),
            "waiting",
        )
        self.assertNotIn("model", hf_downloader._workers)
        gate.set()
        await restart

    async def test_stop_cancels_pending_restart(self):
        restart = asyncio.create_task(asyncio.Event().wait())
        hf_downloader._restart_tasks["model"] = restart
        self.assertTrue(hf_downloader.request_cancel("model"))
        await asyncio.gather(restart, return_exceptions=True)
        self.assertTrue(restart.cancelled())

    async def test_restart_cancel_does_not_cancel_old_worker(self):
        old_release = asyncio.Event()

        async def old_worker():
            await old_release.wait()

        worker = asyncio.create_task(old_worker())
        restart = asyncio.create_task(
            hf_downloader._restart_after_worker("model", [], worker)
        )
        await asyncio.sleep(0)
        restart.cancel()
        await asyncio.gather(restart, return_exceptions=True)
        self.assertFalse(worker.cancelled())
        self.assertFalse(worker.done())
        old_release.set()
        await worker

    def test_force_download_preserves_repository_and_replaces_one_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shared = root / "shared-encoder.gguf"
            shared.write_bytes(b"ready")
            captured = {}

            def fake_download(**kwargs):
                captured.update(kwargs)
                return str(root / kwargs["filename"])

            with patch.object(hf_downloader, "hf_hub_download", fake_download):
                hf_downloader._download_file(
                    "org/repo",
                    "selected.gguf",
                    root,
                    force=True,
                )
            self.assertTrue(shared.exists())
            self.assertTrue(captured["force_download"])


class GenerationLifecycleTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        generation._job_tasks.clear()
        generation._job_processes.clear()

    async def test_cancel_job_waits_for_task_completion(self):
        finished = asyncio.Event()

        async def worker():
            try:
                await asyncio.Event().wait()
            finally:
                finished.set()

        task = asyncio.create_task(worker())
        await asyncio.sleep(0)
        generation._job_tasks[("user", "job")] = task
        self.assertTrue(await generation.cancel_job("user", "job"))
        self.assertTrue(task.done())
        self.assertTrue(finished.is_set())

    async def test_process_lookup_race_is_ignored(self):
        class ExitedProcess:
            returncode = None

            def terminate(self):
                raise ProcessLookupError

        await generation._terminate_process(ExitedProcess())


if __name__ == "__main__":
    unittest.main()
