import asyncio
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from app.config import settings
from app.models import ImmichUploadRecord, JobRecord
from app.services.immich import ImmichAuthError, ImmichClient, ImmichError, normalize_base_url
from app.services import storage
from app.services.immich import exchange as immich_exchange
from app.services.immich import uploads as immich_uploads


def reset_exchange_state() -> None:
    immich_exchange._keys.clear()
    immich_exchange._tokens.clear()
    immich_exchange._last_errors.clear()
    immich_exchange._lock = asyncio.Lock()


def make_job_and_output(root: Path) -> tuple[JobRecord, Path]:
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


def immich_uploads_immich_result():
    from app.services.immich import ImmichUploadResult
    return ImmichUploadResult("uploaded", "asset-1", "checksum")


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

    async def test_enqueue_records_status_and_file_checksum_after_upload(self):
        class Client:
            def __init__(self, *args, **kwargs):
                pass

            async def upload(self, *args, **kwargs):
                return immich_uploads_immich_result()

        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            job, _ = make_job_and_output(root)
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
            job, _ = make_job_and_output(root)
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
            job, _ = make_job_and_output(root)
            with patch.object(storage.settings, "data_dir", root):
                storage.save_job(job)
                job.immich_uploads["../bad"] = ImmichUploadRecord(status="queued", updated_at=datetime.now(timezone.utc))
                storage.save_job(job)
                with self.assertRaises(immich_uploads.ImmichUploadError):
                    await immich_uploads._process("user", job.job_id, "../bad")


STALE_KEY = "stale-key"


def rejecting_client(rejected: set[str]) -> type:
    """构造 ImmichClient 替身：`rejected` 里的 Key 一律返回 401，其余上传成功。"""

    class RejectingClient:
        def __init__(self, base_url, api_key, **kwargs):
            self.api_key = api_key

        async def upload(self, *args, **kwargs):
            if self.api_key in rejected:
                raise ImmichAuthError("Immich API Key 无效或没有上传权限：Invalid API key")
            return immich_uploads_immich_result()

    return RejectingClient


class ImmichUploadCredentialRefreshTest(unittest.IsolatedAsyncioTestCase):
    """缓存 Key 失效（401/403）时应自愈：丢弃旧 Key、重换一次、用新 Key 重试。"""

    def setUp(self):
        reset_exchange_state()
        self.addCleanup(reset_exchange_state)

    async def asyncTearDown(self):
        stored_queue = immich_uploads._queue
        immich_uploads.stop()
        while not stored_queue.empty():
            stored_queue.get_nowait()
            stored_queue.task_done()

    def prepare(self, root: Path) -> JobRecord:
        """造一个已成功的任务，并让进程内缓存持有一个已失效的 Key（带记住的 VOS 令牌）。"""
        job, _ = make_job_and_output(root)
        job.immich_uploads["output.png"] = ImmichUploadRecord(status="queued", updated_at=datetime.now(timezone.utc))
        storage.save_job(job)
        immich_exchange._keys["user"] = STALE_KEY
        immich_exchange._tokens["user"] = "vos-token"
        return job

    async def test_stale_key_is_reexchanged_and_upload_retried(self):
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            with patch.object(storage.settings, "data_dir", root):
                job = self.prepare(root)
                with patch.object(immich_uploads, "ImmichClient", rejecting_client({STALE_KEY})), \
                     patch.object(immich_exchange, "exchange_user_api_key", AsyncMock(return_value="fresh-key")) as mock:
                    await immich_uploads._process("user", job.job_id, "output.png")
                    saved = storage.load_job("user", job.job_id)

        self.assertEqual(saved.immich_uploads["output.png"].status, "uploaded")
        self.assertEqual(saved.immich_uploads["output.png"].error, "")
        self.assertEqual(immich_exchange.cached_api_key("user"), "fresh-key")
        # 重换复用的是入队时记住的 VOS 令牌。
        mock.assert_awaited_once()
        self.assertEqual(mock.await_args.args[0], "vos-token")

    async def test_reexchange_is_bounded_per_upload_attempt(self):
        """换成新 Key 仍被拒时不再继续重换：每次上传尝试最多换一次。"""
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            with patch.object(storage.settings, "data_dir", root):
                job = self.prepare(root)
                with patch.object(immich_uploads, "ImmichClient", rejecting_client({STALE_KEY, "also-bad-key"})), \
                     patch.object(immich_exchange, "exchange_user_api_key", AsyncMock(return_value="also-bad-key")) as mock:
                    await immich_uploads._process("user", job.job_id, "output.png")
                    saved = storage.load_job("user", job.job_id)

        self.assertEqual(saved.immich_uploads["output.png"].status, "failed")
        self.assertIn("重换后仍被拒", saved.immich_uploads["output.png"].error)
        self.assertEqual(mock.await_count, 1)
        # 重换回来的 Key 留在缓存：下次点击由 _ensure_key 命中它，
        # 只需在本次上传里再重换一次，而不是「用户换取 + 自动重换」两次。
        self.assertEqual(immich_exchange.cached_api_key("user"), "also-bad-key")

    async def test_upload_fails_when_reexchange_itself_fails(self):
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            with patch.object(storage.settings, "data_dir", root):
                job = self.prepare(root)
                with patch.object(immich_uploads, "ImmichClient", rejecting_client({STALE_KEY})), \
                     patch.object(
                         immich_exchange,
                         "exchange_user_api_key",
                         AsyncMock(side_effect=immich_exchange.ExchangeError("Immich 拒绝该 VOS 登录令牌（HTTP 401）")),
                     ) as mock:
                    await immich_uploads._process("user", job.job_id, "output.png")
                    saved = storage.load_job("user", job.job_id)

        self.assertEqual(saved.immich_uploads["output.png"].status, "failed")
        self.assertIn("HTTP 401", saved.immich_uploads["output.png"].error)
        self.assertEqual(mock.await_count, 1)
        self.assertEqual(immich_exchange.cached_api_key("user"), "")
        self.assertIn("401", immich_exchange.last_error("user"))

    async def test_repeated_redeploys_each_heal_within_one_attempt(self):
        """同一进程内接连多次重部署：无需用户多点，每次上传尝试都能自愈。"""
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            with patch.object(storage.settings, "data_dir", root):
                job = self.prepare(root)
                with patch.object(immich_uploads, "ImmichClient", rejecting_client({STALE_KEY})), \
                     patch.object(immich_exchange, "exchange_user_api_key", AsyncMock(side_effect=["k2", "k3", "k4"])) as mock:
                    for expected in ("k2", "k3", "k4"):
                        # 每次循环模拟一次新的 Immich 重部署：缓存中的 Key 失效
                        immich_exchange._keys["user"] = STALE_KEY
                        job.immich_uploads["output.png"] = ImmichUploadRecord(
                            status="queued", updated_at=datetime.now(timezone.utc)
                        )
                        storage.save_job(job)
                        await immich_uploads._process("user", job.job_id, "output.png")
                        self.assertEqual(immich_exchange.cached_api_key("user"), expected)
                        self.assertEqual(
                            storage.load_job("user", job.job_id).immich_uploads["output.png"].status, "uploaded"
                        )

        self.assertEqual(mock.await_count, 3)


class ImmichStaleKeyEndToEndTest(unittest.IsolatedAsyncioTestCase):
    """旧 Key 被 401 拒绝后自动重换，同一请求用新 Key 成功。"""

    def setUp(self):
        reset_exchange_state()
        self.addCleanup(reset_exchange_state)
        for patcher in (
            patch.object(settings, "immich_default_api_url", "http://immich.test/api"),
            patch.object(settings, "immich_verify_ssl", True),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    async def asyncTearDown(self):
        stored_queue = immich_uploads._queue
        immich_uploads.stop()
        while not stored_queue.empty():
            stored_queue.get_nowait()
            stored_queue.task_done()

    async def test_upload_self_heals_after_immich_redeploy(self):
        seen_keys: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/oauth/vos-exchange"):
                # 换取接口返回新 Key
                return httpx.Response(200, json={"apiKey": "fresh-key", "userId": "u2", "created": True})
            seen_keys.append(request.headers["x-api-key"])
            if request.headers["x-api-key"] == STALE_KEY:
                return httpx.Response(401, json={"message": "Invalid API key", "statusCode": 401})
            if request.url.path.endswith("/assets/bulk-upload-check"):
                return httpx.Response(200, json={"results": [{"id": "image-studio:job_1:output.png", "action": "accept"}]})
            return httpx.Response(201, json={"id": "asset-9", "status": "created"})

        transport = httpx.MockTransport(handler)
        real_async_client = httpx.AsyncClient  # patch 前抓牢真身，避免自递归

        def fake_async_client(**kwargs):
            kwargs.setdefault("transport", transport)
            return real_async_client(**kwargs)

        class TransportClient(ImmichClient):
            def __init__(self, base_url, api_key, **kwargs):
                super().__init__(base_url, api_key, transport=transport, **kwargs)

        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            with patch.object(storage.settings, "data_dir", root):
                job, _ = make_job_and_output(root)
                job.immich_uploads["output.png"] = ImmichUploadRecord(status="queued", updated_at=datetime.now(timezone.utc))
                storage.save_job(job)
                immich_exchange._keys["user"] = STALE_KEY
                immich_exchange._tokens["user"] = "vos-token"
                with patch.object(immich_uploads, "ImmichClient", TransportClient), \
                     patch("httpx.AsyncClient", fake_async_client):
                    await immich_uploads._process("user", job.job_id, "output.png")
                    saved = storage.load_job("user", job.job_id)

        self.assertEqual(saved.immich_uploads["output.png"].status, "uploaded")
        self.assertEqual(saved.immich_uploads["output.png"].asset_id, "asset-9")
        self.assertEqual(immich_exchange.cached_api_key("user"), "fresh-key")
        # bulk-upload-check 用旧 Key 被拒，重试全程只用新 Key。
        self.assertEqual(seen_keys, [STALE_KEY, "fresh-key", "fresh-key"])


if __name__ == "__main__":
    unittest.main()
