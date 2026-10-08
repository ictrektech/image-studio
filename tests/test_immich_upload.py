import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import httpx

from app.models import ImmichUploadRecord, JobRecord
from app.services.immich import ImmichClient, ImmichError, normalize_base_url
from app.services import storage
from app.services.immich import exchange as immich_exchange
from app.services.immich import uploads as immich_uploads


class ImmichClientTest(unittest.IsolatedAsyncioTestCase):
    async def test_normalizes_instance_api_url(self):
        self.assertEqual(
            normalize_base_url("https://example.test/app/com.ictrek.ai-album/api/"),
            "https://example.test/app/com.ictrek.ai-album/api",
        )

    async def test_bulk_check_and_upload(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            if request.url.path.endswith("/assets/bulk-upload-check"):
                return httpx.Response(200, json={"results": [{"id": "job/output.png", "action": "accept"}]})
            return httpx.Response(201, json={"id": "asset-1", "status": "created"})

        client = ImmichClient(
            "https://example.test/api",
            "secret",
            transport=httpx.MockTransport(handler),
        )
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "output.png"
            path.write_bytes(b"png-data")
            result = await client.upload(path, "job/output.png", datetime.now(timezone.utc))

        self.assertEqual(result.status, "uploaded")
        self.assertEqual(result.asset_id, "asset-1")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].headers["x-api-key"], "secret")
        self.assertNotIn("secret", calls[0].content.decode(errors="ignore"))

    async def test_upload_sends_required_device_fields(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            if request.url.path.endswith("/assets/bulk-upload-check"):
                return httpx.Response(200, json={"results": []})
            return httpx.Response(201, json={"id": "asset-1", "status": "created"})

        client = ImmichClient("https://example.test/api", "secret", transport=httpx.MockTransport(handler))
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "output.png"
            path.write_bytes(b"png-data")
            await client.upload(path, "image-studio:job_1:output.png", datetime.now(timezone.utc))

        body = calls[1].content.decode(errors="ignore")
        # Immich 用 (deviceId, deviceAssetId) 去重，两者缺失会导致 HTTP 400。
        self.assertIn('name="deviceId"', body)
        self.assertIn('name="deviceAssetId"', body)
        self.assertIn("image-studio:job_1:output.png", body)
        self.assertIn('name="assetData"', body)

    async def test_error_message_includes_immich_detail(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"message": ["deviceAssetId must be a string"], "statusCode": 400})

        client = ImmichClient("https://example.test/api", "secret", transport=httpx.MockTransport(handler))
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "output.png"
            path.write_bytes(b"png-data")
            with self.assertRaises(ImmichError) as ctx:
                await client.upload(path, "job/output.png", datetime.now(timezone.utc))

        self.assertIn("deviceAssetId must be a string", str(ctx.exception))
        self.assertIn("HTTP 400", str(ctx.exception))

    async def test_upload_error_body_does_not_leak_api_key(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"message": ["bad request"], "statusCode": 400})

        client = ImmichClient("https://example.test/api", "secret", transport=httpx.MockTransport(handler))
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "output.png"
            path.write_bytes(b"png-data")
            with self.assertRaises(ImmichError) as ctx:
                await client.upload(path, "job/output.png", datetime.now(timezone.utc))

        self.assertNotIn("secret", str(ctx.exception))

    async def test_duplicate_is_returned_without_upload(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, json={"results": [{"id": "job/output.png", "action": "reject", "reason": "duplicate", "assetId": "asset-2"}]})

        client = ImmichClient("https://example.test/api", "secret", transport=httpx.MockTransport(handler))
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "output.png"
            path.write_bytes(b"png-data")
            result = await client.upload(path, "job/output.png", datetime.now(timezone.utc))

        self.assertEqual(result.status, "duplicate")
        self.assertEqual(result.asset_id, "asset-2")
        self.assertEqual(len(calls), 1)


class ImmichUploadServiceTest(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        stored_queue = immich_uploads._queue
        immich_uploads.stop()
        while not stored_queue.empty():
            stored_queue.get_nowait()
            stored_queue.task_done()

    def job_and_output(self, root: Path) -> tuple[JobRecord, Path]:
        now = datetime.now(timezone.utc)
        job = JobRecord(
            job_id="job_1",
            user_key="user",
            status="succeeded",
            prompt="test",
            model_key="sd15",
            model_path="/model.safetensors",
            width=512,
            height=512,
            steps=4,
            cfg_scale=1.0,
            sampler="euler",
            seed=-1,
            batch_count=1,
            created_at=now,
            updated_at=now,
            outputs=["output.png"],
        )
        path = root / "sessions" / "user" / "job_1" / "output.png"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"image")
        return job, path

    async def test_enqueue_records_status_and_file_checksum_after_upload(self):
        class Client:
            def __init__(self, *args, **kwargs):
                pass

            async def upload(self, *args, **kwargs):
                return immich_uploads_immich_result()

        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            job, _ = self.job_and_output(root)
            with patch.object(storage.settings, "data_dir", root):
                immich_exchange._keys["user"] = "secret-key"  # 凭据来自进程内存缓存
                storage.save_job(job)
                with patch.object(immich_uploads, "ImmichClient", Client):
                    updated = await immich_uploads.enqueue_job("user", job.job_id)
                    await immich_uploads._process("user", job.job_id, "output.png")
                saved = storage.load_job("user", job.job_id)

        self.assertEqual(updated.immich_uploads["output.png"].status, "queued")
        self.assertEqual(saved.immich_uploads["output.png"].status, "uploaded")
        self.assertTrue(saved.immich_uploads["output.png"].checksum)

    async def test_completed_outputs_are_skipped_unless_forced(self):
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            job, _ = self.job_and_output(root)
            with patch.object(storage.settings, "data_dir", root):
                immich_exchange._keys["user"] = "secret-key"  # 凭据来自进程内存缓存
                job.immich_uploads["output.png"] = ImmichUploadRecord(
                    status="uploaded",
                    asset_id="asset-1",
                    checksum="c" * 40,
                    attempts=1,
                    updated_at=datetime.now(timezone.utc),
                )
                storage.save_job(job)

                first = await immich_uploads.enqueue_job("user", job.job_id)
                self.assertEqual(first.immich_uploads["output.png"].status, "uploaded")

                forced = await immich_uploads.enqueue_job("user", job.job_id, force=True)
                self.assertEqual(forced.immich_uploads["output.png"].status, "queued")
                # 重传保留累计尝试次数和已有 asset_id，便于追溯同一输出的上传历史。
                self.assertEqual(forced.immich_uploads["output.png"].attempts, 1)

    async def test_malformed_output_filename_is_rejected(self):
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            job, _ = self.job_and_output(root)
            with patch.object(storage.settings, "data_dir", root):
                storage.save_job(job)
                job.immich_uploads["../bad"] = ImmichUploadRecord(status="queued", updated_at=datetime.now(timezone.utc))
                storage.save_job(job)
                with self.assertRaises(immich_uploads.ImmichUploadError):
                    await immich_uploads._process("user", job.job_id, "../bad")


def immich_uploads_immich_result():
    from app.services.immich import ImmichUploadResult
    return ImmichUploadResult("uploaded", "asset-1", "checksum")


if __name__ == "__main__":
    unittest.main()
