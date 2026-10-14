from __future__ import annotations

import hashlib
import logging
import mimetypes
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx

logger = logging.getLogger("image-studio.immich")

# 响应体只记录摘要：Immich 的错误 body 通常很短，截断即可定位，又不会把大 payload 写进日志。
# 注意：请求头（含 x-api-key）任何情况下都不输出。
BODY_SUMMARY_LIMIT = 500

# Immich 以 (deviceId, deviceAssetId) 标识来源设备与资产，两者都是 POST /assets 的必填字段。
DEVICE_ID = "image-studio"


class ImmichError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class ImmichAuthError(ImmichError):
    """API Key 被 Immich 拒绝（HTTP 401/403）：应丢弃缓存凭据、重换一次再重试。"""


@dataclass(frozen=True)
class ImmichUploadResult:
    status: str
    asset_id: str | None = None
    checksum: str = ""


def normalize_base_url(value: str) -> str:
    raw = value.strip().rstrip("/")
    parts = urlsplit(raw)
    if parts.scheme not in {"http", "https"} or not parts.netloc or parts.query or parts.fragment:
        raise ValueError("Immich API 地址必须是有效的 http(s) URL，且不能包含 query 或 fragment")
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def sha1_file(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ImmichClient:
    def __init__(self, base_url: str, api_key: str, *, verify_ssl: bool = True, transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = normalize_base_url(base_url)
        self.api_key = api_key.strip()
        if not self.api_key:
            raise ValueError("Immich API Key 未配置")
        self.verify_ssl = verify_ssl
        self.transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            # Keep the configured gateway path when joining endpoint URLs.
            base_url=f"{self.base_url}/",
            headers={"x-api-key": self.api_key, "accept": "application/json"},
            timeout=httpx.Timeout(3600.0, connect=10.0),
            verify=self.verify_ssl,
            transport=self.transport,
        )

    async def upload(self, path: Path, client_id: str, created_at: datetime) -> ImmichUploadResult:
        started = time.monotonic()
        size = path.stat().st_size
        checksum = sha1_file(path)
        logger.info(
            "Immich 上传开始: client_id=%s file=%s size=%d checksum=%s api=%s verify_ssl=%s",
            client_id, path.name, size, checksum, self.base_url, self.verify_ssl,
        )
        async with self._client() as client:
            check = await self._request(
                client,
                "POST",
                "assets/bulk-upload-check",
                json={"assets": [{"id": client_id, "checksum": checksum}]},
            )
            result = self._check_result(check, client_id)
            if result is not None:
                logger.info(
                    "Immich 已存在相同资产，跳过上传: client_id=%s asset_id=%s elapsed=%.2fs",
                    client_id, result.asset_id, time.monotonic() - started,
                )
                return ImmichUploadResult(result.status, result.asset_id, checksum)

            data = {
                "deviceAssetId": client_id,
                "deviceId": DEVICE_ID,
                "filename": path.name,
                "fileCreatedAt": created_at.isoformat(),
                "fileModifiedAt": created_at.isoformat(),
            }
            with path.open("rb") as stream:
                response = await self._request(
                    client,
                    "POST",
                    "assets",
                    data=data,
                    files={"assetData": (path.name, stream, mimetypes.guess_type(path.name)[0] or "application/octet-stream")},
                )
            payload = self._json(response)
            status = payload.get("status")
            elapsed = time.monotonic() - started
            if status == "duplicate" or response.status_code == 200:
                logger.info(
                    "Immich 判定为重复资产: client_id=%s asset_id=%s http=%d elapsed=%.2fs",
                    client_id, _asset_id(payload), response.status_code, elapsed,
                )
                return ImmichUploadResult("duplicate", _asset_id(payload), checksum)
            if response.status_code == 201 or status == "created":
                logger.info(
                    "Immich 上传完成: client_id=%s asset_id=%s size=%d http=%d elapsed=%.2fs",
                    client_id, _asset_id(payload), size, response.status_code, elapsed,
                )
                return ImmichUploadResult("uploaded", _asset_id(payload), checksum)
            logger.error(
                "Immich 返回无法识别的上传结果: client_id=%s http=%d status=%s body=%s",
                client_id, response.status_code, status, _summarize(response),
            )
            raise ImmichError("Immich 返回了无法识别的上传结果")

    async def _request(self, client: httpx.AsyncClient, method: str, path: str, **kwargs) -> httpx.Response:
        started = time.monotonic()
        try:
            response = await client.request(method, path, **kwargs)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            logger.warning(
                "Immich 网络异常: %s %s api=%s elapsed=%.2fs verify_ssl=%s (%s: %s)%s",
                method, path, self.base_url, time.monotonic() - started, self.verify_ssl,
                exc.__class__.__name__, exc, _ssl_hint(exc),
            )
            raise ImmichError("Immich 连接失败或请求超时", retryable=True) from exc
        elapsed = time.monotonic() - started
        if response.status_code in {408, 429} or response.status_code >= 500:
            logger.warning(
                "Immich 服务端错误（可重试）: %s %s -> HTTP %d elapsed=%.2fs body=%s",
                method, path, response.status_code, elapsed, _summarize(response),
            )
            raise ImmichError(f"Immich 服务暂时不可用（HTTP {response.status_code}）", retryable=True)
        if response.status_code >= 400:
            detail = _error_detail(response)
            suffix = f"：{detail}" if detail else ""
            if response.status_code in {401, 403}:
                logger.error(
                    "Immich 鉴权失败: %s %s -> HTTP %d api=%s body=%s",
                    method, path, response.status_code, self.base_url, _summarize(response),
                )
                raise ImmichAuthError("Immich API Key 无效或没有上传权限" + suffix)
            logger.error(
                "Immich 请求被拒绝: %s %s -> HTTP %d elapsed=%.2fs body=%s",
                method, path, response.status_code, elapsed, _summarize(response),
            )
            raise ImmichError(f"Immich 请求失败（HTTP {response.status_code}）" + suffix)
        logger.debug("Immich 请求成功: %s %s -> HTTP %d elapsed=%.2fs", method, path, response.status_code, elapsed)
        return response

    @staticmethod
    def _json(response: httpx.Response) -> dict:
        try:
            payload = response.json()
        except ValueError as exc:
            logger.error(
                "Immich 返回非 JSON 响应: HTTP %d content_type=%s body=%s",
                response.status_code, response.headers.get("content-type", "-"), _summarize(response),
            )
            raise ImmichError("Immich 返回了无效响应") from exc
        if not isinstance(payload, dict):
            logger.error(
                "Immich 返回 JSON 结构无效: HTTP %d type=%s body=%s",
                response.status_code, type(payload).__name__, _summarize(response),
            )
            raise ImmichError("Immich 返回了无效响应")
        return payload

    def _check_result(self, response: httpx.Response, client_id: str) -> ImmichUploadResult | None:
        payload = self._json(response)
        results = payload.get("results")
        if not isinstance(results, list):
            logger.error(
                "Immich bulk-upload-check 返回格式无效: client_id=%s body=%s",
                client_id, _summarize(response),
            )
            raise ImmichError("Immich bulk upload check 返回格式无效")
        item = next((item for item in results if isinstance(item, dict) and item.get("id") == client_id), None)
        if item is None or item.get("action") == "accept":
            logger.debug("Immich bulk-upload-check 接受上传: client_id=%s", client_id)
            return None
        if item.get("reason") == "duplicate":
            logger.info("Immich bulk-upload-check 命中重复: client_id=%s asset_id=%s", client_id, _asset_id(item))
            return ImmichUploadResult("duplicate", _asset_id(item))
        reason = str(item.get("reason") or "rejected")
        logger.error("Immich 拒绝文件: client_id=%s reason=%s item=%s", client_id, reason, item)
        raise ImmichError(f"Immich 拒绝文件：{reason}")


def _error_detail(response: httpx.Response) -> str:
    """提取 Immich 错误响应里的 message，让用户不翻日志也能看懂失败原因。"""
    try:
        payload = response.json()
    except ValueError:
        return ""
    message = payload.get("message") if isinstance(payload, dict) else None
    if isinstance(message, list):
        return "; ".join(str(item) for item in message)
    return str(message) if message else ""


def _ssl_hint(exc: Exception) -> str:
    """证书校验失败时补一句可操作的处置办法，避免日志里只剩一行 SSL 报错无从下手。"""
    text = str(exc).lower()
    if "certificate_verify_failed" in text or "certificate verify failed" in text:
        return "；若为自签名证书，请在「Immich 设置」取消勾选 HTTPS 证书验证"
    return ""


def _summarize(response: httpx.Response) -> str:
    """把响应体压成单行摘要，便于定位错误；不可读时给出占位说明。"""
    try:
        body = " ".join(response.text.split())
    except Exception:
        return "<unreadable body>"
    if not body:
        return "<empty body>"
    return body[:BODY_SUMMARY_LIMIT] + ("...(truncated)" if len(body) > BODY_SUMMARY_LIMIT else "")


def _asset_id(payload: dict) -> str | None:
    value = payload.get("assetId") or payload.get("id")
    return str(value) if value else None
