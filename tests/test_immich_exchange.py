import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException
from starlette.requests import Request

from app.config import settings
from app.routers import api
from app.services.immich import exchange


def make_request(headers: dict[str, str] | None = None) -> Request:
    raw = [(key.lower().encode(), value.encode()) for key, value in (headers or {}).items()]
    return Request({"type": "http", "method": "POST", "path": "/api/v1/jobs/j1/immich-upload", "headers": raw, "query_string": b""})


def make_client(calls: list[httpx.Request], response: httpx.Response) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return response

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def reset_exchange_state() -> None:
    """清进程内状态；锁需重建，否则 IsolatedAsyncioTestCase 的新事件循环会撞 loop 绑定。"""
    exchange._keys.clear()
    exchange._last_errors.clear()
    exchange._lock = asyncio.Lock()


class ZeroTouchAvailableTest(unittest.TestCase):
    def test_follows_toggle(self):
        with patch.object(settings, "immich_auto_provision", True):
            self.assertTrue(exchange.zero_touch_available())
        with patch.object(settings, "immich_auto_provision", False):
            self.assertFalse(exchange.zero_touch_available())


class ExchangeUserApiKeyTest(unittest.IsolatedAsyncioTestCase):
    async def exchange_with(self, response: httpx.Response, token: str = "vos-token") -> tuple[str, list[httpx.Request]]:
        calls: list[httpx.Request] = []
        client = make_client(calls, response)
        with patch.object(exchange.httpx, "AsyncClient", lambda **kwargs: client):
            api_key = await exchange.exchange_user_api_key(token, "http://immich.test/api")
        return api_key, calls

    async def test_posts_to_exchange_endpoint_with_user_token(self):
        api_key, calls = await self.exchange_with(
            httpx.Response(200, json={"apiKey": "raw-key", "userId": "u1", "created": True})
        )

        self.assertEqual(api_key, "raw-key")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].method, "POST")
        self.assertEqual(str(calls[0].url), "http://immich.test/api/oauth/vos-exchange")
        self.assertEqual(calls[0].headers["authorization"], "Bearer vos-token")

    async def test_401_exposes_upstream_cause_without_leaking_token(self):
        calls: list[httpx.Request] = []
        client = make_client(calls, httpx.Response(401, json={"message": "VOS token exchange is not configured"}))
        with patch.object(exchange.httpx, "AsyncClient", lambda **kwargs: client):
            with self.assertRaises(exchange.ExchangeError) as ctx:
                await exchange.exchange_user_api_key("secret-vos-token", "http://immich.test/api")

        message = str(ctx.exception)
        self.assertIn("401", message)
        self.assertIn("not configured", message)
        self.assertNotIn("secret-vos-token", message)

    async def test_rejection_surfaces_upstream_message(self):
        with self.assertRaises(exchange.ExchangeError) as ctx:
            await self.exchange_with(httpx.Response(403, json={"message": ["no email", "auto register disabled"]}))

        self.assertIn("403", str(ctx.exception))
        self.assertIn("no email", str(ctx.exception))

    async def test_missing_api_key_in_response_raises(self):
        with self.assertRaises(exchange.ExchangeError):
            await self.exchange_with(httpx.Response(200, json={}))

    async def test_empty_token_raises_without_request(self):
        calls: list[httpx.Request] = []
        client = make_client(calls, httpx.Response(200, json={"apiKey": "raw-key"}))
        with patch.object(exchange.httpx, "AsyncClient", lambda **kwargs: client):
            with self.assertRaises(exchange.ExchangeError):
                await exchange.exchange_user_api_key("", "http://immich.test/api")

        self.assertEqual(calls, [])

    async def test_network_error_is_wrapped(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom", request=request)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with patch.object(exchange.httpx, "AsyncClient", lambda **kwargs: client):
            with self.assertRaises(exchange.ExchangeError) as ctx:
                await exchange.exchange_user_api_key("vos-token", "http://immich.test/api")

        self.assertIn("请求失败", str(ctx.exception))


class EnsureApiKeyCacheTest(unittest.IsolatedAsyncioTestCase):
    """凭据只在进程内存：换一次、重复调用绝不轮换、重启（清缓存）后重新换。"""

    def setUp(self):
        reset_exchange_state()
        self.addCleanup(reset_exchange_state)
        for patcher in (
            patch.object(settings, "immich_default_api_url", "http://immich.test/api"),
            patch.object(settings, "immich_verify_ssl", True),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_exchanges_once_then_reuses_cache(self):
        mock = AsyncMock(return_value="k1")
        with patch.object(exchange, "exchange_user_api_key", mock):
            self.assertEqual(await exchange.ensure_api_key("alice", "tok"), "k1")
            self.assertEqual(await exchange.ensure_api_key("alice", "tok2"), "k1")

        # 交换会轮换 Immich 侧的 Key，第二次命中缓存时绝不能再交换。
        mock.assert_awaited_once_with("tok", "http://immich.test/api", verify_ssl=True)

    async def test_missing_token_raises_without_exchange(self):
        mock = AsyncMock(return_value="k1")
        with patch.object(exchange, "exchange_user_api_key", mock):
            with self.assertRaises(exchange.ExchangeError) as ctx:
                await exchange.ensure_api_key("alice", "")

        self.assertIn("VOS 登录令牌", str(ctx.exception))
        mock.assert_not_awaited()

    async def test_restart_clears_cache_and_next_upload_reexchanges(self):
        with patch.object(exchange, "exchange_user_api_key", AsyncMock(side_effect=["k1", "k2"])) as mock:
            self.assertEqual(await exchange.ensure_api_key("alice", "tok"), "k1")
            exchange._keys.clear()  # 模拟后端重启
            self.assertEqual(await exchange.ensure_api_key("alice", "tok"), "k2")

        self.assertEqual(mock.await_count, 2)

    def test_cached_api_key_is_empty_when_nothing_exchanged(self):
        self.assertEqual(exchange.cached_api_key("nobody"), "")


class EnsureKeyRouteTest(unittest.IsolatedAsyncioTestCase):
    """上传路由前置检查：未启用 / 无令牌 → 409；正常 → 透传用户与令牌。"""

    async def test_missing_token_is_409_without_exchange(self):
        reset_exchange_state()
        self.addCleanup(reset_exchange_state)
        mock = AsyncMock(return_value="k1")
        with patch.object(settings, "immich_auto_provision", True), \
             patch.object(settings, "immich_default_api_url", "http://immich.test/api"), \
             patch.object(exchange, "exchange_user_api_key", mock):
            exchange._keys.clear()
            with self.assertRaises(HTTPException) as ctx:
                await api._ensure_key(make_request(), "alice")

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("VOS 登录令牌", str(ctx.exception.detail))
        mock.assert_not_awaited()

    async def test_disabled_is_409(self):
        with patch.object(settings, "immich_auto_provision", False):
            with self.assertRaises(HTTPException) as ctx:
                await api._ensure_key(make_request({"authorization": "Bearer vos-token"}), "alice")

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("未启用", str(ctx.exception.detail))

    async def test_success_passes_user_and_token_to_exchange(self):
        ensure_mock = AsyncMock(return_value="k1")
        with patch.object(api, "ensure_api_key", ensure_mock):
            await api._ensure_key(make_request({"authorization": "Bearer vos-token"}), "alice")

        ensure_mock.assert_awaited_once_with("alice", "vos-token")


class ImmichStatusTest(unittest.IsolatedAsyncioTestCase):
    """GET /immich 返回连通性状态：disabled / unreachable / error / connected / pending。"""

    def setUp(self):
        reset_exchange_state()
        self.addCleanup(reset_exchange_state)

    async def test_disabled_when_toggle_off(self):
        with patch.object(settings, "immich_auto_provision", False):
            response = await api.immich_status(make_request())
        self.assertEqual(response.state, "disabled")

    async def test_unreachable_when_ping_fails(self):
        with patch.object(settings, "immich_auto_provision", True), \
             patch.object(api, "check_reachable", AsyncMock(return_value="无法访问 x：ConnectError")):
            response = await api.immich_status(make_request())
        self.assertEqual(response.state, "unreachable")
        self.assertIn("ConnectError", response.detail)

    async def test_error_when_last_provisioning_failed(self):
        with patch.object(settings, "immich_auto_provision", True), \
             patch.object(api, "check_reachable", AsyncMock(return_value="")), \
             patch.object(api, "current_user_key", AsyncMock(return_value="alice")):
            exchange._last_errors["alice"] = "HTTP 401"
            response = await api.immich_status(make_request())
        self.assertEqual(response.state, "error")
        self.assertEqual(response.detail, "HTTP 401")

    async def test_connected_when_key_cached(self):
        with patch.object(settings, "immich_auto_provision", True), \
             patch.object(api, "check_reachable", AsyncMock(return_value="")), \
             patch.object(api, "current_user_key", AsyncMock(return_value="alice")):
            exchange._keys["alice"] = "k1"
            response = await api.immich_status(make_request())
        self.assertEqual(response.state, "connected")

    async def test_pending_when_enabled_but_not_provisioned(self):
        with patch.object(settings, "immich_auto_provision", True), \
             patch.object(api, "check_reachable", AsyncMock(return_value="")):
            response = await api.immich_status(make_request())
        self.assertEqual(response.state, "pending")


if __name__ == "__main__":
    unittest.main()
