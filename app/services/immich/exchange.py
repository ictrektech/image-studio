"""零接触凭据：用当前 VOS access_token 向 Immich 换取该用户的专属 API Key。

Immich 侧提供 ``POST /oauth/vos-exchange``：校验 VOS token（JWKS 验签 + iss/aud）
→ 按 sub 查找/创建 Immich 用户 → 建一个仅含 ``asset.upload`` 权限的 Key → 返回明文。

Key 只存进程内存（见 ``_keys``），不落盘；用于 401/403 后重换的 VOS 令牌
（见 ``_tokens``）同样只进内存。
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from app.config import settings

logger = logging.getLogger("image-studio.immich")

REQUEST_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
EXCHANGE_PATH = "oauth/vos-exchange"


class ExchangeError(ValueError):
    """凭据交换失败（缺少令牌、VOS 登录失效、Immich 拒绝等）。"""


# 进程内凭据缓存：user_key → Immich 上传 Key。凭据不落盘，后端重启即失效，
# 由下一次上传请求（用户在场、持新令牌）重新换取。
# 约束：每个 Immich 只对应一个 image-studio 进程——第二个实例的交换会轮换掉
# 本进程缓存的 Key（immich 侧按 用户×app 单槽位），届时需重启本进程重新换取。
_keys: dict[str, str] = {}
# 最近一次成功交换所用的 VOS 令牌：仅供缓存 Key 被 Immich 拒绝（401/403）后
# 在进程内重换一次使用。只存内存、不落盘、绝不进日志。
_tokens: dict[str, str] = {}
# 每用户最近一次开通失败原因（成功后清除），供连通性状态展示。
_last_errors: dict[str, str] = {}
# 交换串行锁：交换会轮换 Immich 侧 Key，并发首次上传不能各换各的。
_lock = asyncio.Lock()


def zero_touch_available() -> bool:
    """零接触开关是否打开。"""
    return settings.immich_auto_provision


def cached_api_key(user_key: str) -> str:
    """返回本进程内该用户当前有效的 Immich Key（无则空串）。"""
    return _keys.get(user_key, "")


def last_error(user_key: str) -> str:
    """返回该用户最近一次开通失败原因（无则空串）。"""
    return _last_errors.get(user_key, "")


async def check_reachable() -> str:
    """探测 Immich 连通性：返回空串表示可达，否则返回原因。"""
    url = f"{settings.immich_default_api_url}/server/ping"
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(5.0, connect=3.0), verify=settings.immich_verify_ssl
        ) as client:
            response = await client.get(url)
    except httpx.HTTPError as exc:
        # URL 只进日志不进返回值：detail 会经无鉴权的 GET /immich 返回给调用方。
        logger.warning("Immich 连通性探测失败: %s (%s)", url, exc.__class__.__name__)
        return f"连接失败：{exc.__class__.__name__}"
    if response.status_code >= 400:
        logger.warning("Immich 连通性探测异常: %s HTTP %s", url, response.status_code)
        return f"HTTP {response.status_code}"
    return ""


async def ensure_api_key(user_key: str, access_token: str) -> str:
    """换取（或复用本进程缓存的）该用户的 Immich 上传 Key。

    同一用户在本进程内只交换一次；交换会轮换 Immich 侧的 ``vos:<app>``
    Key，所以绝不能在已有缓存时重复调用（锁只负责并发首传的去重）。
    """
    if key := _keys.get(user_key):
        return key
    async with _lock:
        if key := _keys.get(user_key):
            return key
        if not access_token:
            # 匿名/无令牌请求不做交换，否则会把多个匿名会话混到同一个 Immich 用户下。
            raise ExchangeError("自动配置 Immich 需要携带 VOS 登录令牌；当前请求没有令牌，请登录后重试")
        try:
            key = await exchange_user_api_key(
                access_token, settings.immich_default_api_url, verify_ssl=settings.immich_verify_ssl
            )
        except ExchangeError as exc:
            _last_errors[user_key] = str(exc)
            raise
        _last_errors.pop(user_key, None)
        _keys[user_key] = key
        _tokens[user_key] = access_token
        logger.info("Immich 凭据已换取并缓存到进程内存: user=%s", user_key)
        return key


async def refresh_api_key(user_key: str) -> str:
    """缓存 Key 被 Immich 拒绝（401/403）后，丢弃旧 Key 并用记住的令牌重换一次。

    调用方必须限制频次（见 ``uploads._process``：每次上传尝试最多重换一次），
    否则「换成功→仍 401→再换」会无限循环。换取失败时直接抛错，由调用方判最终失败。
    """
    async with _lock:
        _keys.pop(user_key, None)
        try:
            key = await exchange_user_api_key(
                _tokens.get(user_key, ""), settings.immich_default_api_url, verify_ssl=settings.immich_verify_ssl
            )
        except ExchangeError as exc:
            _last_errors[user_key] = str(exc)
            raise
        _last_errors.pop(user_key, None)
        _keys[user_key] = key
        logger.info("Immich 凭据已重换并更新进程内缓存: user=%s", user_key)
        return key


async def exchange_user_api_key(access_token: str, api_url: str, *, verify_ssl: bool = True) -> str:
    """用 VOS access_token 换取该用户的 Immich API Key（明文仅此一次返回）。"""
    if not access_token:
        raise ExchangeError("缺少 VOS 登录令牌，无法自动配置 Immich")
    if not api_url:
        raise ExchangeError("未配置 Immich API 地址，无法自动配置")

    # access_token 与返回的 API Key 都不写日志、不进异常文案。
    headers = {"Authorization": f"Bearer {access_token}", "accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, verify=verify_ssl) as client:
            response = await client.post(f"{api_url.rstrip('/')}/{EXCHANGE_PATH}", headers=headers)
    except httpx.HTTPError as exc:
        raise ExchangeError(f"Immich 换取凭据请求失败：{exc.__class__.__name__}") from exc

    if response.status_code == 401:
        # 令牌缺失/过期/签名或 aud 不匹配，以及 Immich 侧未启用免密交换，都是 401，
        # 带上上游 message 才能区分（例如 "VOS token exchange is not configured"）。
        raise ExchangeError(
            "Immich 拒绝该 VOS 登录令牌（HTTP 401）：登录可能已过期，或 Immich 未启用 VOS 免密交换"
            + _error_detail(response)
        )
    if response.status_code >= 400:
        raise ExchangeError(f"Immich 换取凭据被拒绝（HTTP {response.status_code}）{_error_detail(response)}")

    try:
        payload = response.json()
    except ValueError:
        payload = None
    data = payload if isinstance(payload, dict) else {}
    api_key = str(data.get("apiKey") or "").strip()
    if not api_key:
        raise ExchangeError("Immich 换取凭据成功但未返回 API Key")
    logger.info(
        "Immich 凭据交换完成: api=%s user_id=%s created=%s",
        api_url,
        data.get("userId") or "-",
        data.get("created"),
    )
    return api_key


def _error_detail(response: httpx.Response) -> str:
    """透出 Immich 的 message，便于定位（403/409 通常是映射或配置问题）。"""
    try:
        payload = response.json()
    except ValueError:
        return ""
    message = payload.get("message") if isinstance(payload, dict) else None
    text = "; ".join(str(item) for item in message) if isinstance(message, list) else str(message or "")
    return f"：{text}" if text else ""
