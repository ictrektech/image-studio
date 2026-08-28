import asyncio
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from app.models import JobRecord
from app.services import generation, hf_downloader
from app.services.models import MODEL_DEFS, MODEL_SCOPE_FILES, MODEL_SIZES, merge_model_hub_state, model_info


class ModelRegistryTest(unittest.TestCase):
    def test_all_models_use_dedicated_modelscope_repos(self):
        self.assertEqual(len(MODEL_DEFS), 45)
        for item in MODEL_DEFS:
            key = item["key"]
            repo = f"vivibit/image-studio-{key}"
            with self.subTest(key=key):
                self.assertEqual(item["source"], "ms")
                self.assertEqual(item["model_id"], repo)
                self.assertEqual(item["sources"], [{"source": "ms", "model_id": repo, "files": MODEL_SCOPE_FILES[key]}])
                self.assertEqual(item["files"], MODEL_SCOPE_FILES[key])
                self.assertEqual(item["expected_files"], MODEL_SCOPE_FILES[key])
                self.assertGreater(MODEL_SIZES[key], 0)

                info = model_info(item)
                self.assertEqual(info.source, "ms")
                self.assertEqual(info.model_id, repo)
                self.assertEqual(info.total_bytes, MODEL_SIZES[key])

                files = set(item["files"])
                for role_path in (item["runtime"].get("roles") or {}).values():
                    self.assertIn(role_path, files)

    def test_ready_model_hub_state_wins_over_stale_task_progress(self):
        info = model_info(MODEL_DEFS[0]).model_dump()
        info["status"] = "ready"
        info["size"] = MODEL_SIZES[MODEL_DEFS[0]["key"]]

        merge_model_hub_state(
            {
                "status": "ready",
                "size": MODEL_SIZES[MODEL_DEFS[0]["key"]],
                "progress": 1.0,
            },
            info,
        )

        self.assertEqual(info["status"], "ready")
        self.assertIsNone(info.get("progress"))


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

    async def test_video_args_include_base_and_video_parameters(self):
        job = JobRecord(
            job_id="job_video",
            user_key="user",
            status="queued",
            prompt="a dancer",
            negative_prompt="",
            model_key="wan21",
            model_path="/models/wan.safetensors",
            width=832,
            height=480,
            steps=20,
            cfg_scale=6.0,
            strength=0.75,
            sampler="euler",
            seed=42,
            batch_count=4,
            flow_shift=3.0,
            video_frames=120,
            fps=24,
            vae_tiling=True,
            max_vram=-2.0,
            stream_layers=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        with patch.object(generation, "runtime_paths_for", return_value={}):
            args = generation.build_sd_args(job, Path("/tmp/output.webm"))

        self.assertIn("-M", args)
        self.assertIn("vid_gen", args)
        self.assertEqual(args[args.index("-o") + 1], "/tmp/output.webm")
        self.assertEqual(args[args.index("--width") + 1], "832")
        self.assertEqual(args[args.index("--height") + 1], "480")
        self.assertEqual(args[args.index("--steps") + 1], "20")
        self.assertEqual(args[args.index("--cfg-scale") + 1], "6.0")
        self.assertEqual(args[args.index("--sampling-method") + 1], "euler")
        self.assertEqual(args[args.index("--seed") + 1], "42")
        self.assertEqual(args[args.index("--video-frames") + 1], "120")
        self.assertEqual(args[args.index("--fps") + 1], "24")
        self.assertEqual(args[args.index("--flow-shift") + 1], "3.0")
        self.assertEqual(args[args.index("--max-vram") + 1], "-2.0")
        self.assertIn("--vae-tiling", args)
        self.assertIn("--stream-layers", args)
        self.assertNotIn("--strength", args)

    async def test_create_job_normalizes_unsupported_parameters(self):
        async def fake_run(_job):
            return None

        with (
            patch.object(generation, "assert_model_hub_ready"),
            patch.object(generation, "model_path_for", return_value=Path("/models/wan.safetensors")),
            patch.object(generation, "run_job", fake_run),
            patch.object(generation, "save_job"),
        ):
            job = await generation.create_job(
                "user",
                generation.GenerateRequest(
                    prompt="a dancer",
                    model_key="wan21",
                    negative_prompt="ignored",
                    cfg_scale=9,
                    strength=0.75,
                    batch_count=4,
                    video_frames=120,
                    fps=24,
                ),
            )

        self.assertEqual(job.negative_prompt, "ignored")
        self.assertEqual(job.cfg_scale, 9)
        self.assertEqual(job.strength, 0)
        self.assertEqual(job.batch_count, 1)
        self.assertEqual(job.video_frames, 120)
        self.assertEqual(job.fps, 24)

    async def test_image_job_ignores_video_parameters(self):
        async def fake_run(_job):
            return None

        with (
            patch.object(generation, "assert_model_hub_ready"),
            patch.object(generation, "model_path_for", return_value=Path("/models/sd15.safetensors")),
            patch.object(generation, "run_job", fake_run),
            patch.object(generation, "save_job"),
        ):
            job = await generation.create_job(
                "user",
                generation.GenerateRequest(
                    prompt="a cabin",
                    model_key="sd15",
                    init_input_id="in_1",
                    strength=0.6,
                    batch_count=2,
                    video_frames=48,
                    fps=24,
                ),
            )

        self.assertEqual(job.strength, 0.6)
        self.assertEqual(job.batch_count, 2)
        self.assertEqual(job.video_frames, 0)
        self.assertEqual(job.fps, 0)
        self.assertEqual(job.metadata["init_input_id"], "in_1")

    async def test_fixed_cfg_model_uses_runtime_default(self):
        job = JobRecord(
            job_id="job_flux",
            user_key="user",
            status="queued",
            prompt="a cabin",
            negative_prompt="ignored negative",
            model_key="flux-schnell",
            model_path="/models/flux.gguf",
            width=1024,
            height=1024,
            steps=4,
            cfg_scale=7.0,
            strength=0.75,
            sampler="euler",
            seed=-1,
            batch_count=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            metadata={"init_input_id": "in_1"},
        )

        with patch.object(generation, "runtime_paths_for", return_value={}):
            args = generation.build_sd_args(job, Path("/tmp/output.png"))

        self.assertEqual(args[args.index("--cfg-scale") + 1], "1.0")
        self.assertNotIn("-n", args)
        self.assertNotIn("-i", args)
        self.assertNotIn("--strength", args)

    async def test_all_model_runtime_specs_build_expected_command_shape(self):
        now = datetime.now(timezone.utc)
        for item in MODEL_DEFS:
            runtime = item["runtime"]
            defaults = runtime.get("defaults") or {}
            video_mode = runtime.get("mode") == "video"
            params = runtime.get("parameters") or {}
            job = JobRecord(
                job_id=f"job_{item['key']}",
                user_key="user",
                status="queued",
                prompt="prompt",
                negative_prompt="negative",
                model_key=item["key"],
                model_path="/models/main.safetensors",
                width=int(defaults.get("width", 768)),
                height=int(defaults.get("height", 768)),
                steps=int(defaults.get("steps", 20)),
                cfg_scale=float(defaults.get("cfg_scale", 7.0)),
                strength=0.75,
                sampler=str(defaults.get("sampler", "euler")),
                seed=1,
                batch_count=2,
                video_frames=int(defaults.get("video_frames", 0)),
                fps=int(defaults.get("fps", 0)),
                vae_tiling=bool(defaults.get("vae_tiling", False)),
                temporal_tiling=bool(defaults.get("temporal_tiling", False)),
                max_vram=float(defaults.get("max_vram", 0.0)),
                stream_layers=bool(defaults.get("stream_layers", False)),
                created_at=now,
                updated_at=now,
                metadata={"init_input_id": "in_1"},
            )
            output = Path("/tmp/output.webm" if video_mode else "/tmp/output.png")

            with self.subTest(key=item["key"]):
                with (
                    patch.object(generation, "runtime_paths_for", return_value={}),
                    patch.object(generation, "init_image_path", return_value=Path("/tmp/input.png")),
                ):
                    args = generation.build_sd_args(job, output)
                self.assertEqual(args[args.index("-o") + 1], str(output))
                if video_mode:
                    self.assertIn("-M", args)
                    self.assertIn("vid_gen", args)
                    self.assertIn("--video-frames", args)
                    self.assertIn("--fps", args)
                    self.assertIn("--vae-tiling", args)
                    self.assertIn("--max-vram", args)
                else:
                    self.assertNotIn("vid_gen", args)
                if params.get("negative_prompt", runtime.get("negative", True)):
                    self.assertIn("-n", args)
                else:
                    self.assertNotIn("-n", args)
                if params.get("reference_image", False):
                    self.assertIn(runtime.get("ref_flag", "-i"), args)
                else:
                    self.assertNotIn("-i", args)
                    self.assertNotIn("-r", args)


if __name__ == "__main__":
    unittest.main()
