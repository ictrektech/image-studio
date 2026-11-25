"""Use a Scheduler deployment channel for a job already authorized at the main node."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import re
from pathlib import Path

from fastapi import HTTPException

from app.models import JobRecord
from app.services.storage import INPUT_EXTENSIONS, MAX_INPUT_BYTES, input_path, job_dir, load_job, save_job
from app.services.weight_sync import deployment_client, deployment_request
from app.services.weight_transfers import MAX_CHUNK_BYTES, sha256_file

_FILE_ID = r"output(?:_[0-9]{2})?\.(?:png|webm)"
_HEX = r"[0-9a-f]{64}"
_output_tasks: dict[str, asyncio.Task] = {}


def compute_policy(job: JobRecord) -> dict | None:
    deployment = job.metadata.get("compute_deployment_id")
    if not deployment:
        return None
    from app.routers.compute import registered_compute_model
    from app.services.scheduler import model_id

    policy = registered_compute_model(deployment, model_id(job))
    if policy["executor_id"] != job.metadata.get("compute_executor_id"):
        raise HTTPException(409, "COMPUTE_EXECUTOR_CHANGED")
    return policy


def _reference_path(job: JobRecord) -> Path | None:
    input_id = job.metadata.get("init_input_id")
    source_id = job.metadata.get("init_job_id")
    filename = job.metadata.get("init_filename")
    if input_id:
        if not re.fullmatch(r"in_[A-Za-z0-9_]{1,85}", input_id):
            raise HTTPException(422, "COMPUTE_REFERENCE_NOT_FOUND")
        path = input_path(job.user_key, input_id)
    elif source_id and filename:
        if not re.fullmatch(r"job_[A-Za-z0-9_]{1,85}", source_id) or not re.fullmatch(_FILE_ID, filename):
            raise HTTPException(422, "COMPUTE_REFERENCE_NOT_FOUND")
        previous = load_job(job.user_key, source_id)
        path = job_dir(job.user_key, source_id) / filename if previous and filename in previous.outputs else None
    else:
        return None
    if not path or not path.is_file() or path.suffix.lower() not in INPUT_EXTENSIONS:
        raise HTTPException(422, "COMPUTE_REFERENCE_NOT_FOUND")
    if not 0 < path.stat().st_size <= MAX_INPUT_BYTES:
        raise HTTPException(422, "COMPUTE_REFERENCE_SIZE_INVALID")
    return path


def _exec_path(deployment: str, attempt: str) -> str:
    return f"backend-deployments/{deployment}/executions/{attempt}"


async def _upload_reference(client, path: str, job: JobRecord, fence: int) -> dict | None:
    source = _reference_path(job)
    if source is None:
        return None
    digest = await asyncio.to_thread(sha256_file, source)
    size = source.stat().st_size
    offset = 0
    with source.open("rb") as stream:
        while offset < size:
            chunk = await asyncio.to_thread(stream.read, min(MAX_CHUNK_BYTES, size - offset))
            if not chunk:
                raise HTTPException(409, "COMPUTE_REFERENCE_CHANGED")
            receipt = await deployment_request(
                client, "PUT", f"{path}/inputs/reference", params={"offset": offset},
                content=chunk,
                headers={"Content-Type": "application/octet-stream", "X-Scheduler-Fence": str(fence)},
            )
            end = receipt.get("received_bytes")
            if type(end) is not int or not offset + len(chunk) <= end <= size:
                raise HTTPException(503, "COMPUTE_REFERENCE_RECEIPT_INVALID")
            offset = end
            stream.seek(offset)
    return {"extension": source.suffix.lower(), "size_bytes": size, "sha256": digest}


async def start_remote(attempt: str, job: JobRecord, command: dict, record: dict) -> dict:
    from app.services.scheduler import _atomic, _path

    policy = compute_policy(job)
    path = _exec_path(record["compute_deployment_id"], attempt)
    async with deployment_client() as client:
        if "reference" not in record:
            record["reference"] = await _upload_reference(client, path, job, record["fence"])
            _atomic(_path(attempt), record)
        return await deployment_request(
            client, "POST", f"{path}/start", json={
                **command,
                "transfer_id": policy["transfer_id"],
                "job": job.model_dump(mode="json", exclude={"metadata", "outputs", "error", "immich_uploads"}),
                "reference": record["reference"],
            },
        )


async def _download(client, path: str, filename: str, destination: Path, fence: int) -> None:
    temporary = destination.with_name("." + destination.name + ".remote-part")
    size = offset = 0
    checksum = ""
    digest = hashlib.sha256()
    try:
        with temporary.open("wb") as stream:
            while not size or offset < size:
                receipt = await deployment_request(
                    client, "GET", f"{path}/outputs/{filename}", params={"offset": offset},
                    headers={"X-Scheduler-Fence": str(fence)},
                )
                if type(receipt.get("size_bytes")) is not int or receipt.get("offset") != offset:
                    raise ValueError("Invalid output receipt")
                if not size:
                    size, checksum = receipt["size_bytes"], receipt.get("sha256", "")
                    if size <= 0 or not re.fullmatch(_HEX, checksum):
                        raise ValueError("Invalid output metadata")
                if receipt["size_bytes"] != size or receipt.get("sha256") != checksum:
                    raise ValueError("Conflicting output metadata")
                chunk = base64.b64decode(receipt["data_b64"], validate=True)
                if not chunk or len(chunk) > MAX_CHUNK_BYTES or offset + len(chunk) > size:
                    raise ValueError("Invalid output chunk")
                stream.write(chunk)
                digest.update(chunk)
                offset += len(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        if digest.hexdigest() != checksum:
            raise ValueError("Invalid output checksum")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


async def _restore_outputs(attempt: str, record: dict, filenames: list[str], reply: dict) -> None:
    from app.services.scheduler import _atomic, _path

    parameters = record["parameters"]
    path = _exec_path(record["compute_deployment_id"], attempt)
    try:
        async with deployment_client() as client:
            for filename in filenames:
                await _download(
                    client, path, filename, job_dir(parameters["user_key"], parameters["job_id"]) / filename, record["fence"],
                )
        job = load_job(parameters["user_key"], parameters["job_id"])
        if job:
            job.status, job.progress, job.outputs, job.error = "succeeded", 1, filenames, ""
            save_job(job)
    except (HTTPException, OSError, KeyError, TypeError, ValueError):
        reply = {"status": "failed", "stopped": True, "result": {"code": "COMPUTE_OUTPUT_TRANSFER_FAILED", "retryable": False}}
    _atomic(_path(attempt), {**record, "remote_receipt": reply})


async def inspect_remote(attempt: str, command: dict, record: dict) -> dict:
    if record.get("remote_receipt"):
        return record["remote_receipt"]
    path = _exec_path(record["compute_deployment_id"], attempt)
    async with deployment_client() as client:
        result = await deployment_request(client, "POST", f"{path}/inspect", json=command)
    if result.get("status") != "succeeded" or not result.get("stopped"):
        return result
    filenames = result.get("result", {}).get("outputs")
    if not isinstance(filenames, list) or not 1 <= len(filenames) <= 4 or not all(
        isinstance(name, str) and re.fullmatch(_FILE_ID, name) for name in filenames
    ):
        return {"status": "failed", "stopped": True, "result": {"code": "COMPUTE_OUTPUT_RECEIPT_INVALID", "retryable": False}}
    if attempt not in _output_tasks:
        task = asyncio.create_task(_restore_outputs(attempt, record, filenames, result))
        _output_tasks[attempt] = task
        task.add_done_callback(lambda _: _output_tasks.pop(attempt, None))
    return {"status": "running", "stopped": False, "progress": {"percent": 0.99}}


async def cancel_remote(attempt: str, command: dict, record: dict) -> dict:
    path = _exec_path(record["compute_deployment_id"], attempt)
    async with deployment_client() as client:
        return await deployment_request(client, "POST", f"{path}/cancel", json=command)
