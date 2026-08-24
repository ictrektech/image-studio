from __future__ import annotations

import hashlib
import re

from fastapi import Request


def current_user_key(request: Request) -> str:
    candidates = [
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


def sanitize(value: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip())
    return clean[:80] or "anonymous"

