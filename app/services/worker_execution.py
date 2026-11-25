"""Execute a Scheduler-admitted Image Studio job inside its deployed worker."""

from __future__ import annotations

import asyncio
import base64
import hmac
import os
import re
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.models import JobRecord
from app.services import scheduler
from app.services.storage import INPUT_EXTENSIONS, MAX_INPUT_BYTES, job_dir, load_job, save_job
from app.services.weight_transfers import (
    MAX_CHUNK_BYTES, WeightTransfers, _bounded_body, require_worker_channel, sha256_file,
)

_ID = r"^[A-Za-z0-9_-]{1,96}$"
_stage_lock = asyncio.Lock()


class JobReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_key: str = Field(pattern=_ID)
    job_id: str = Field(pattern=_ID)


class ReferenceFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    extension: Literal[".png", ".jpg", ".jpeg", ".webp"]
    size_bytes: int = Field(strict=True, gt=0, le=MAX_INPUT_BYTES)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class StartWorkerJob(BaseModel):
    model_config = ConfigDict(extra="ignore")
    task_id: str = Field(min_length=1, max_length=96)
    fence: int = Field(strict=True, ge=0)
    parameters: JobReference
    lease_seconds: int = Field(default=30, ge=1, le=30)
    transfer_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    job: JobRecord
    model_limits: dict
    model_parameters: dict
    reference: ReferenceFile | None = None


def _attempt_file(attempt: str, suffix: str) -> Path:
    return scheduler._path(attempt).with_suffix(suffix)


def _write_reference(attempt: str, offset: int, content: bytes) -> dict:
    path = _attempt_file(attempt, ".reference")
    current = path.stat().st_size if path.is_file() else 0
    end = offset + len(content)
    if not content or offset > current or end > MAX_INPUT_BYTES:
        raise HTTPException(409, "WORKER_REFERENCE_OFFSET_MISMATCH")
    if offset < current:
        with path.open("rb") as stream:
            stream.seek(offset)
            if end > current or stream.read(len(content)) != content:
                raise HTTPException(409, "WORKER_REFERENCE_OFFSET_MISMATCH")
        return {"received_bytes": current}
    if scheduler._path(attempt).is_file():
        raise HTTPException(409, "WORKER_JOB_ALREADY_STARTED")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("ab") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        if path.exists():
            with path.open("r+b") as stream:
                stream.truncate(current)
        raise
    return {"received_bytes": end}


def _prepare_reference(attempt: str, reference: ReferenceFile | None) -> Path | None:
    if reference is None:
        return None
    if reference.extension not in INPUT_EXTENSIONS:
        raise HTTPException(422, "INVALID_WORKER_REFERENCE_TYPE")
    pending = _attempt_file(attempt, ".reference")
    path = _attempt_file(attempt, ".reference" + reference.extension)
    candidate = path if path.exists() else pending
    if not candidate.is_file() or candidate.stat().st_size != reference.size_bytes:
        raise HTTPException(409, "WORKER_REFERENCE_INCOMPLETE")
    if not hmac.compare_digest(sha256_file(candidate), reference.sha256):
        candidate.unlink()
        raise HTTPException(422, "WORKER_REFERENCE_CHECKSUM_MISMATCH")
    if candidate != path:
        candidate.replace(path)
    return path


def _read_output(attempt: str, file_id: str, offset: int) -> dict:
    record = scheduler._read(scheduler._path(attempt))
    if (
        record.get("status") != "succeeded"
        or not record["stopped"]
        or not re.fullmatch(r"output(?:_[0-9]{2})?\.(?:png|webm)", file_id)
        or file_id not in record.get("result", {}).get("outputs", [])
    ):
        raise HTTPException(404, "WORKER_OUTPUT_NOT_FOUND")
    parameters = JobReference.model_validate(record["parameters"])
    path = job_dir(parameters.user_key, parameters.job_id) / file_id
    if not path.is_file():
        raise HTTPException(404, "WORKER_OUTPUT_NOT_FOUND")
    size = path.stat().st_size
    if not 0 <= offset < size:
        raise HTTPException(416, "WORKER_OUTPUT_OFFSET_OUT_OF_RANGE")
    checksum_path = _attempt_file(attempt, "." + file_id + ".sha256.json")
    checksum = scheduler._read(checksum_path).get("sha256")
    if not checksum:
        checksum = sha256_file(path)
        scheduler._atomic(checksum_path, {"sha256": checksum})
    with path.open("rb") as stream:
        stream.seek(offset)
        content = stream.read(MAX_CHUNK_BYTES)
    return {"file_id": file_id, "offset": offset, "size_bytes": size, "sha256": checksum,
            "data_b64": base64.b64encode(content).decode("ascii")}


def _execution_view(result: dict) -> dict:
    receipt = result.get("result", {})
    if "error" in receipt:
        return {**result, "result": {**receipt, "error": "Worker execution failed"}}
    return result


def worker_execution_routes(transfers: WeightTransfers) -> APIRouter:
    router = APIRouter(prefix="/scheduler/executions", dependencies=[Depends(require_worker_channel)])

    @router.put("/{attempt}/inputs/reference")
    async def upload_reference(attempt: str, offset: Annotated[int, Query(ge=0)], request: Request):
        if request.headers.get("content-type") != "application/octet-stream":
            raise HTTPException(415, "WORKER_REFERENCE_CONTENT_TYPE_REQUIRED")
        content = await _bounded_body(request, MAX_CHUNK_BYTES)
        async with _stage_lock:
            return await run_in_threadpool(_write_reference, attempt, offset, content)

    @router.post("/{attempt}/start")
    async def start(attempt: str, request: Request, authorization: str = Header(default="")):
        body = await _bounded_body(request, 64 * 1024)
        try:
            command = StartWorkerJob.model_validate_json(body)
        except ValidationError:
            raise HTTPException(422, "WORKER_JOB_INVALID") from None
        lifecycle = command.model_dump(include={"task_id", "fence", "lease_seconds", "parameters"})
        async with _stage_lock:
            attempt_path = scheduler._path(attempt)
            job = command.job
            if (job.user_key, job.job_id) != (command.parameters.user_key, command.parameters.job_id):
                raise HTTPException(409, "WORKER_JOB_ID_MISMATCH")
            previous = load_job(job.user_key, job.job_id)
            if previous and previous.metadata.get("scheduler_task_id") != command.task_id:
                raise HTTPException(409, "WORKER_TASK_ID_MISMATCH")
            if attempt_path.is_file():
                return _execution_view(await scheduler.execute(attempt, lifecycle, authorization))
            previous_id = previous.metadata.get("scheduler_attempt_id") if previous else None
            if previous_id:
                previous_attempt = scheduler._read(scheduler._path(previous_id))
                if (
                    previous_attempt.get("stopped") is not True
                    or previous_attempt.get("status") != "failed"
                    or command.fence <= previous_attempt["fence"]
                ):
                    raise HTTPException(409, "WORKER_PREVIOUS_ATTEMPT_ACTIVE")
            paths = await run_in_threadpool(transfers.verified_paths, command.transfer_id, scheduler.model_id(job))
            reference = await run_in_threadpool(_prepare_reference, attempt, command.reference)
            job.model_path = str(paths.pop("model"))
            job.status, job.progress, job.outputs, job.error, job.immich_uploads = "queued", 0, [], "", {}
            job.metadata = {
                "scheduler_managed": True, "scheduler_task_id": command.task_id,
                "_worker_role_paths": {key: str(path) for key, path in paths.items()},
            }
            if previous_id:
                job.metadata["scheduler_attempt_id"] = previous_id
            if reference is not None:
                job.metadata.update(_worker_reference_path=str(reference), init_input_id="in_worker_reference")
            scheduler.validate_calibrated_job(job, command.model_limits, command.model_parameters)
            save_job(job)
            return await scheduler.execute(attempt, lifecycle, authorization)

    @router.post("/{attempt}/inspect")
    async def inspect(attempt: str, body: dict, authorization: str = Header(default="")):
        return _execution_view(await scheduler.inspect(attempt, body, authorization))

    @router.post("/{attempt}/cancel")
    async def cancel(attempt: str, body: dict, authorization: str = Header(default="")):
        async with _stage_lock:
            return _execution_view(await scheduler.cancel(attempt, body, authorization))

    @router.get("/{attempt}/outputs/{file_id}")
    async def output(attempt: str, file_id: str, offset: Annotated[int, Query(ge=0)]):
        async with _stage_lock:
            return await run_in_threadpool(_read_output, attempt, file_id, offset)

    return router
