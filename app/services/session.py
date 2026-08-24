from __future__ import annotations

import hashlib
import re

import httpx
from fastapi import Request

from app.config import settings


async def current_user_key(request: Request) -> str:
    token = bearer_token(request)
    if settings.vos_sso_enabled and token:
        identity = await verify_vos_identity(token)
        if identity:
            return sanitize(identity)

    candidates = [
        request.headers.get("x-vos-sub"),
        request.headers.get("x-vos-username"),
        request.headers.get("x-vos-user-id"),
        request.headers.get("x-vivibit-user-id"),
        request.headers.get("x-user-id"),
        request.headers.get("x-forwarded-user"),
    ]
    for value in candidates:
        if value:
            return sanitize(value)

    auth = request.headers.get("authorization") or request.client.host if request.client else "anonymous"
    digest = hashlib.sha256(auth.encode("utf-8")).hexdigest()[:16]
    return f"user-{digest}"


def bearer_token(request: Request) -> str:
    auth = request.headers.get("authorization", "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


async def verify_vos_identity(token: str) -> str:
    for endpoint in (settings.vos_oidc_userinfo_url, settings.vos_userinfo_url):
        value = await fetch_vos_identity(endpoint, token)
        if value:
            return value
    return ""


async def fetch_vos_identity(endpoint: str, token: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(endpoint, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        if resp.status_code < 200 or resp.status_code >= 300:
            return ""
        payload = resp.json()
    except Exception:
        return ""

    if isinstance(payload, dict) and payload.get("code") not in (None, 0):
        return ""
    data = payload.get("data") if isinstance(payload, dict) else None
    data = data if isinstance(data, dict) else {}
    user = data.get("user") if isinstance(data.get("user"), dict) else {}
    claims = data or (payload if isinstance(payload, dict) else {})

    return first_non_empty(
        text(claims.get("sub")),
        text(user.get("id")),
        text(user.get("user_id")),
        text(claims.get("id")),
        text(claims.get("user_id")),
        text(claims.get("preferred_username")),
        text(claims.get("username")),
        text(user.get("username")),
        text(claims.get("email")),
        text(claims.get("name")),
        text(user.get("name")),
    )


def text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def first_non_empty(*values: str) -> str:
    for value in values:
        if value:
            return value
    return ""


def sanitize(value: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip())
    return clean[:80] or "anonymous"
