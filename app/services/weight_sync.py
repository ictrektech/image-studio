"""Send Image Studio model weights through the deployment's Scheduler channel."""

from __future__ import annotations

import asyncio
import re
from contextlib import ExitStack
from pathlib import Path
from time import monotonic
from typing import Callable

import httpx
from fastapi import HTTPException

from app.config import settings
from app.services.models import assert_model_hub_ready, model_path_for, runtime_paths_for
from app.services.weight_transfers import MAX_CHUNK_BYTES, WeightFile, WeightManifest, sha256_file


Progress = Callable[[str, int, int], None]
_CHANNEL_ERRORS = {"BACKEND_CHANNEL_UNAVAILABLE", "COMPUTE_SCHEDULER_UNAVAILABLE"}


def _describe_bundle(key: str, variant: str, progress: Progress | None = None) -> tuple[WeightManifest, dict[str, Path], dict[str, str]]:
    paths = {"model": model_path_for(key, variant), **runtime_paths_for(key, variant)}
    files = []
    sources = {}
    shared_paths = {}
    sizes = {}
    for file_id, path in paths.items():
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(settings.modelhub_root) or not resolved.is_file():
            raise ValueError("Model weight is outside the shared storage")
        sizes[file_id] = resolved.stat().st_size
        sources[file_id] = resolved
        shared_paths[file_id] = path.relative_to(settings.modelhub_root).as_posix()
    checked = 0
    total = sum(sizes.values())
    for file_id, path in paths.items():
        def update(size: int) -> None:
            if progress:
                progress("source_check", checked + size, total)

        files.append(WeightFile(
            file_id=file_id, path=path.name, size_bytes=sizes[file_id], sha256=sha256_file(sources[file_id], update),
        ))
        checked += sizes[file_id]
    model_id = f"{key}@{variant}" if variant else key
    return WeightManifest(model_id=model_id, files=files), sources, shared_paths


def deployment_client() -> httpx.AsyncClient:
    if not settings.scheduler_url or not settings.scheduler_token:
        raise HTTPException(503, "COMPUTE_SCHEDULER_UNAVAILABLE")
    return httpx.AsyncClient(
        base_url=settings.scheduler_url.rstrip("/") + "/",
        headers={"Authorization": "Bearer " + settings.scheduler_token},
        follow_redirects=False,
        timeout=httpx.Timeout(30, connect=5),
    )


async def deployment_request(client: httpx.AsyncClient, method: str, path: str, **kwargs) -> dict:
    try:
        response = await client.request(method, path, **kwargs)
        envelope = response.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(503, "COMPUTE_SCHEDULER_UNAVAILABLE") from None
    if not isinstance(envelope, dict):
        raise HTTPException(503, "COMPUTE_SCHEDULER_INVALID_RESPONSE")
    if response.is_error:
        code = envelope.get("code")
        detail = code if isinstance(code, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{1,95}", code) else "COMPUTE_SCHEDULER_REJECTED"
        raise HTTPException(response.status_code, detail)
    data = envelope.get("data")
    if envelope.get("code") != "OK" or not isinstance(data, dict):
        raise HTTPException(503, "COMPUTE_SCHEDULER_INVALID_RESPONSE")
    return data


async def _begin(client: httpx.AsyncClient, path: str, manifest: WeightManifest) -> tuple[str, dict]:
    response = await deployment_request(
        client, "POST", f"{path}/transfers", json=manifest.model_dump(exclude_defaults=True),
    )
    transfer_id = response.get("transfer_id")
    if not isinstance(transfer_id, str) or not re.fullmatch(r"[0-9a-f]{64}", transfer_id):
        raise HTTPException(503, "WEIGHT_SYNC_INVALID_RESPONSE")
    return transfer_id, response


async def _complete(
    client: httpx.AsyncClient, path: str, transfer_id: str, manifest: WeightManifest,
    supports_progress: bool, progress: Progress | None,
) -> None:
    transfer = f"{path}/transfers/{transfer_id}"
    total = sum(item.size_bytes for item in manifest.files)
    if progress:
        progress("target_check", 0, total)
    if supports_progress:
        verified = await _follow_verification(client, transfer, total, progress)
    else:
        verified = await deployment_request(client, "POST", f"{transfer}/complete", timeout=300)
    if verified.get("verified") is not True or verified.get("model_id") != manifest.model_id:
        raise HTTPException(503, "WEIGHT_SYNC_NOT_VERIFIED")
    if progress:
        progress("registering", total, total)


async def _follow_verification(client: httpx.AsyncClient, transfer: str, total: int, progress: Progress | None) -> dict:
    completion = asyncio.create_task(deployment_request(client, "POST", f"{transfer}/complete", timeout=300))
    last_change = monotonic()
    last_size = 0
    pending_error = None
    try:
        while True:
            if completion.done() and pending_error is None:
                try:
                    return completion.result()
                except HTTPException as exc:
                    if exc.detail not in _CHANNEL_ERRORS:
                        raise
                    pending_error = exc
            try:
                status = await deployment_request(client, "GET", transfer, timeout=10)
            except HTTPException as exc:
                if exc.detail not in _CHANNEL_ERRORS:
                    raise
                if pending_error and monotonic() - last_change >= 60:
                    raise pending_error
                await asyncio.sleep(2)
                continue
            check = status.get("verification", {})
            size = check.get("bytes")
            if type(size) is not int or not 0 <= size <= total:
                raise HTTPException(503, "WEIGHT_SYNC_INVALID_RESPONSE")
            if status.get("verified") is True:
                return status
            if pending_error and check.get("state") == "failed":
                if check.get("error") == "WEIGHT_SHARED_UNAVAILABLE":
                    raise HTTPException(409, "BACKEND_SHARED_MODEL_HUB_UNAVAILABLE")
                raise HTTPException(409, "WEIGHT_SYNC_NOT_VERIFIED")
            if size > last_size:
                last_change, last_size = monotonic(), size
                if progress:
                    progress("target_check", size, total)
            if pending_error and (check.get("state") != "verifying" or monotonic() - last_change >= 60):
                raise pending_error
            if completion.done():
                await asyncio.sleep(2)
            else:
                await asyncio.wait({completion}, timeout=2)
    finally:
        if not completion.done():
            completion.cancel()
        await asyncio.gather(completion, return_exceptions=True)


async def _register(client: httpx.AsyncClient, path: str, transfer_id: str, manifest: WeightManifest) -> dict:
    registration = await deployment_request(
        client, "POST", f"{path}/models", json={"model_id": manifest.model_id, "transfer_id": transfer_id},
    )
    return {**registration, "transfer_id": transfer_id, "weight_source": manifest.source}


async def sync_weights(
    deployment_id: str,
    model_key: str,
    model_variant: str = "",
    progress: Progress | None = None,
) -> dict:
    if not re.fullmatch(r"[0-9a-f]{32}", deployment_id):
        raise HTTPException(422, "INVALID_BACKEND_DEPLOYMENT_ID")
    model_variant = model_variant.strip()
    try:
        await assert_model_hub_ready(model_key, model_variant)
        loop = asyncio.get_running_loop()

        def source_progress(phase: str, received: int, total: int) -> None:
            if progress:
                loop.call_soon_threadsafe(progress, phase, received, total)

        manifest, sources, shared_paths = await asyncio.to_thread(_describe_bundle, model_key, model_variant, source_progress)
    except (OSError, KeyError, ValueError):
        raise HTTPException(409, "WEIGHT_SOURCE_NOT_READY") from None
    path = f"backend-deployments/{deployment_id}"
    total = sum(file.size_bytes for file in manifest.files)
    async with deployment_client() as client:
        model_hub = await deployment_request(client, "GET", f"{path}/model-hub")
        if model_hub.get("state") not in {"ready", "unavailable"}:
            raise HTTPException(503, "WEIGHT_SYNC_INVALID_RESPONSE")
        if model_hub["state"] == "ready":
            shared = manifest.model_copy(update={
                "source": "shared",
                "files": [file.model_copy(update={"shared_path": shared_paths[file.file_id]}) for file in manifest.files],
            })
            try:
                transfer_id, receipt = await _begin(client, path, shared)
                await _complete(client, path, transfer_id, shared, "verification" in receipt, progress)
            except HTTPException as exc:
                if exc.detail != "BACKEND_SHARED_MODEL_HUB_UNAVAILABLE":
                    raise
            else:
                return await _register(client, path, transfer_id, shared)

        with ExitStack() as stack:
            return await _copy_weights(client, stack, path, manifest, sources, total, progress)


async def _copy_weights(
    client: httpx.AsyncClient,
    stack: ExitStack,
    path: str,
    manifest: WeightManifest,
    sources: dict[str, Path],
    total: int,
    progress: Progress | None,
) -> dict:
    try:
        streams = {file_id: stack.enter_context(source.open("rb")) for file_id, source in sources.items()}
    except OSError:
        raise HTTPException(409, "WEIGHT_SOURCE_NOT_READY") from None
    transfer_id, transfer = await _begin(client, path, manifest)
    transfer_path = f"{path}/transfers/{transfer_id}"
    records = transfer.get("files")
    if not isinstance(records, list) or not all(isinstance(row, dict) for row in records):
        raise HTTPException(503, "WEIGHT_SYNC_INVALID_RESPONSE")
    offsets = {row["file_id"]: row.get("received_bytes") for row in records if isinstance(row.get("file_id"), str)}
    for file in manifest.files:
        offset = offsets.get(file.file_id)
        if type(offset) is not int or not 0 <= offset <= file.size_bytes:
            raise HTTPException(503, "WEIGHT_SYNC_INVALID_RESPONSE")
    received = sum(offsets[file.file_id] for file in manifest.files)
    if progress:
        progress("copying", received, total)
    for file in manifest.files:
        offset = offsets[file.file_id]
        stream = streams[file.file_id]
        stream.seek(offset)
        while offset < file.size_bytes:
            chunk = await asyncio.to_thread(stream.read, min(MAX_CHUNK_BYTES, file.size_bytes - offset))
            if not chunk:
                raise HTTPException(409, "WEIGHT_SOURCE_CHANGED")
            receipt = await deployment_request(
                client, "PUT", f"{transfer_path}/files/{file.file_id}",
                params={"offset": offset}, content=chunk,
                headers={"Content-Type": "application/octet-stream"},
            )
            next_offset = receipt.get("received_bytes")
            if type(next_offset) is not int or not offset + len(chunk) <= next_offset <= file.size_bytes:
                raise HTTPException(503, "WEIGHT_SYNC_INVALID_RESPONSE")
            received += next_offset - offset
            offset = next_offset
            stream.seek(offset)
            if progress:
                progress("copying", received, total)
    await _complete(client, path, transfer_id, manifest, "verification" in transfer, progress)
    return await _register(client, path, transfer_id, manifest)
