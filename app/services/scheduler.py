"""Optional V-Scheduler submission outbox and authenticated execution adapter.

Business routes remain unchanged. Never fall back to local execution on broker failure.
"""
from __future__ import annotations
import asyncio
import hmac
import json
import os
import re
import time
from pathlib import Path
import httpx
from fastapi import APIRouter, Header, HTTPException
from app.config import settings
from app.models import JobRecord
from app.services.storage import load_job, save_job

router = APIRouter(prefix="/api/v1/scheduler")
_loop: asyncio.Task | None = None
_executions: dict[str, asyncio.Task] = {}
_locks: dict[str, asyncio.Lock] = {}


def _atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w") as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _path(attempt: str) -> Path:
    if not re.fullmatch(r"[a-f0-9-]{36}", attempt):
        raise HTTPException(422, "invalid attempt ID")
    return settings.data_dir / "scheduler" / f"{attempt}.json"


def _read(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def _authorize(authorization: str) -> None:
    token = authorization.removeprefix("Bearer ")
    if not settings.scheduler_executor_token or not hmac.compare_digest(token, settings.scheduler_executor_token):
        raise HTTPException(401, "executor authentication required")


async def _controller(method: str, path: str, **kwargs) -> dict:
    if not settings.scheduler_token:
        raise HTTPException(503, "scheduler service credential missing")
    async with httpx.AsyncClient(timeout=8) as client:
        headers = {"Authorization": f"Bearer {settings.scheduler_token}", **kwargs.pop("headers", {})}
        response = await client.request(method, settings.scheduler_url + path, headers=headers, **kwargs)
        response.raise_for_status()
        return response.json()["data"]


def model_id(job: JobRecord) -> str:
    return job.model_key + ("@" + job.model_variant if job.model_variant else "")


def validate_limits(job: JobRecord) -> None:
    if not settings.scheduler_required:
        return
    from app.services.scheduler_binding import execution_settings
    if settings.scheduler_config.get("execution_settings") != execution_settings():
        raise HTTPException(503, "Runtime settings no longer match calibrated binding")
    limits = settings.scheduler_model_limits.get(model_id(job), {})
    for field in ("width", "height", "steps", "batch_count", "video_frames"):
        maximum = limits.get(field)
        if type(maximum) is not int or maximum < 0 or getattr(job, field) > maximum:
            raise HTTPException(422, "Job exceeds calibrated model limit: " + field)
    if job.hires:
        width = job.hires_width or int(job.width * job.hires_scale)
        height = job.hires_height or int(job.height * job.hires_scale)
        for field, value in (("hires_width", width), ("hires_height", height), ("hires_steps", job.hires_steps or job.steps)):
            maximum = limits.get(field)
            if type(maximum) is not int or value > maximum:
                raise HTTPException(422, "Job exceeds calibrated model limit: " + field)


async def submit(job: JobRecord) -> None:
    validate_limits(job)
    executor = settings.scheduler_models.get(model_id(job))
    if not executor:
        if settings.scheduler_required:
            raise HTTPException(503, "Model executor is not approved")
        executor = settings.scheduler_executor_id
    task = await _controller("POST", "/tasks", headers={"Idempotency-Key": job.job_id}, json={
        "protocol_version": 1, "app_task_id": job.job_id,
        "executor": {"id": executor, "contract_version": "1", "task_type": "video.generate" if job.video_frames else "image.generate"},
        "parameters": {"user_key": job.user_key, "job_id": job.job_id}, "inputs": [],
    })
    # Reload so an execution finishing during submission cannot be overwritten by queued state.
    current = load_job(job.user_key, job.job_id)
    if current:
        current.metadata["scheduler_task_id"] = task["task_id"]
        save_job(current)


async def prepare(job: JobRecord) -> None:
    if settings.scheduler_required and not settings.scheduler_models.get(model_id(job)):
        raise HTTPException(503, "V-Scheduler model binding required")
    validate_limits(job)
    job.metadata["scheduler_managed"] = True
    job.metadata["scheduler_state"] = "queued"
    save_job(job)  # durable local outbox before trying the remote controller
    try:
        await submit(job)
    except (httpx.HTTPError, HTTPException):
        pass  # startup/background outbox replays the same idempotency key


async def request_cancel(user_key: str, job_id: str) -> bool:
    job = load_job(user_key, job_id)
    if not job:
        return False
    job.metadata["scheduler_cancel_requested"] = True
    save_job(job)
    if not job.metadata.get("scheduler_task_id"):
        await submit(job)
        job = load_job(user_key, job_id)
    task_id = job.metadata["scheduler_task_id"]
    await _controller("POST", f"/tasks/{task_id}/cancel", json={})
    for _ in range(12):
        state = await _controller("GET", f"/tasks/{task_id}")
        if state["status"] in {"cancelled", "succeeded", "failed"}:
            return True
        await asyncio.sleep(1)
    raise HTTPException(409, "任务尚未确认停止，已保留任务与输出，请稍后重试")


async def _outbox() -> None:
    while True:
        for path in settings.jobs_dir.glob("*/*.json"):
            try:
                job = JobRecord.model_validate_json(path.read_text())
                if not job.metadata.get("scheduler_managed"):
                    continue
                if not job.metadata.get("scheduler_task_id"):
                    await submit(job)
                    job = load_job(job.user_key, job.job_id)
                task_id = job.metadata["scheduler_task_id"]
                if job.metadata.get("scheduler_cancel_requested"):
                    await _controller("POST", f"/tasks/{task_id}/cancel", json={})
                state = await _controller("GET", f"/tasks/{task_id}")
                current = load_job(job.user_key, job.job_id)
                if not current:
                    continue
                current.metadata["scheduler_state"] = state["status"]
                current.metadata["scheduler_wait_reasons"] = state.get("wait_reasons", [])
                if state["status"] in {"cancelled", "failed"}:
                    current.status = "failed"
                    current.outputs = []
                    current.error = "调度任务已取消" if state["status"] == "cancelled" else "调度执行失败，请查看执行记录"
                save_job(current)
            except (OSError, ValueError, httpx.HTTPError, HTTPException):
                continue
        await asyncio.sleep(2)


async def start() -> None:
    global _loop
    if _loop and not _loop.done():
        return
    if settings.scheduler_url:
        if len(settings.scheduler_token) < 32 or len(settings.scheduler_executor_token) < 32:
            raise RuntimeError("V-Scheduler enabled but scoped credentials are missing/too short")
        _loop = asyncio.create_task(_outbox())


async def stop() -> None:
    if _loop:
        _loop.cancel()
        await asyncio.gather(_loop, return_exceptions=True)
    for task in list(_executions.values()):
        task.cancel()
    await asyncio.gather(*list(_executions.values()), return_exceptions=True)


def _lease(path: Path, seconds: int) -> None:
    _atomic(path.with_suffix(".lease"), {"deadline": time.monotonic() + seconds})


def _marker(path: Path) -> dict:
    return _read(path.with_suffix(".process"))


def _alive(marker: dict) -> bool:
    if marker.get("stopped"):
        return False
    for prefix in ("", "child_"):
        pid = marker.get(prefix + "pid")
        if not pid:
            continue
        try:
            text = Path(f"/proc/{pid}/stat").read_text()
            if text.rsplit(")", 1)[1].split()[19] == marker.get(prefix + "birth"):
                return True
        except (OSError, IndexError):
            pass
    return False


async def _execute(path: Path, record: dict, job: JobRecord) -> None:
    from app.services.generation import run_job, cancel_job
    async def watchdog() -> None:
        while True:
            await asyncio.sleep(0.5)
            if _read(path.with_suffix(".lease")).get("deadline", 0) <= time.monotonic():
                running = _executions.get(record["attempt_id"])
                if running:
                    running.cancel()
                return
    watcher = asyncio.create_task(watchdog())
    try:
        await run_job(job)
        state = load_job(job.user_key, job.job_id)
        cancelled = _read(path).get("cancel_requested", False) or _read(path.with_suffix(".lease")).get("deadline", 0) <= time.monotonic()
        record["status"] = "cancelled" if cancelled else (state.status if state and state.status in {"succeeded", "failed"} else "failed")
        record["result"] = {"job_id": job.job_id, "outputs": state.outputs if state else [], "error": state.error if state else "job unavailable"}
    except asyncio.CancelledError:
        # run_job handles cancellation and terminates its child; do not report stopped before this returns.
        await cancel_job(job.user_key, job.job_id, local_only=True)
        record["status"] = "cancelled"
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)
        marker = _marker(path)
        record["stopped"] = not _alive(marker)
        if not record["stopped"]:
            record["status"] = "unknown"
        _atomic(path, record)


@router.post("/executions/{attempt}/start")
async def execute(attempt: str, body: dict, authorization: str = Header(default="")):
    _authorize(authorization)
    path = _path(attempt)
    async with _locks.setdefault(attempt, asyncio.Lock()):
        old = _read(path)
        if old:
            if old["fence"] != body.get("fence") or old["parameters"] != body.get("parameters"):
                raise HTTPException(409, "attempt conflict")
            if old["status"] == "running" and attempt in _executions and not _executions[attempt].done():
                _lease(path, min(30, int(body.get("lease_seconds", 30))))
            return await inspect(attempt, body, authorization)
        parameters = body.get("parameters") or {}
        user, job_id = parameters.get("user_key", ""), parameters.get("job_id", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", user) or not re.fullmatch(r"[A-Za-z0-9_-]+", job_id):
            raise HTTPException(422, "invalid job reference")
        job = load_job(user, job_id)
        if not job or not job.metadata.get("scheduler_managed"):
            raise HTTPException(409, "job unavailable")
        previous = job.metadata.get("scheduler_attempt_id")
        if previous:
            previous_record = _read(_path(previous))
            if not previous_record.get("stopped") or previous_record.get("status") != "failed" or body.get("fence", 0) <= previous_record.get("fence", 0):
                raise HTTPException(409, "previous attempt not safely retryable")
            job.status, job.progress, job.outputs, job.error = "queued", 0, [], ""
            job.metadata.pop("scheduler_cancel_requested", None)
        if job.metadata.get("scheduler_task_id") != body.get("task_id"):
            raise HTTPException(409, "task/job binding conflict")
        if job.model_key.startswith("v-router/"):
            raise HTTPException(422, "Executor accepts local jobs only")
        validate_limits(job)
        record = {"attempt_id": attempt, "fence": body["fence"], "parameters": parameters, "status": "running", "stopped": False, "result": {}}
        _atomic(path, record)
        _lease(path, min(30, int(body.get("lease_seconds", 30))))
        job.metadata["scheduler_attempt_id"] = attempt
        job.metadata["_scheduler_lease_path"] = str(path.with_suffix(".lease"))
        save_job(job)
        _executions[attempt] = asyncio.create_task(_execute(path, record, job))
        return {"status": "running", "stopped": False, "progress": {"percent": 0}}


@router.post("/executions/{attempt}/inspect")
async def inspect(attempt: str, body: dict, authorization: str = Header(default="")):
    _authorize(authorization)
    path = _path(attempt)
    record = _read(path)
    if not record:
        return {"status": "unknown", "stopped": False}
    if record["fence"] != body.get("fence"):
        raise HTTPException(409, "stale fence")
    running = _executions.get(attempt)
    if record["status"] == "running" and (not running or running.done()):
        # A restart never blindly replays a job. Surviving wrapper stops on its own lease.
        marker = _marker(path)
        if not marker or _alive(marker) or (not marker.get("child_pid") and not marker.get("stopped")):
            return {"status": "unknown", "stopped": False}
        record.update(status="failed", stopped=True, result={"error": "executor restarted; old execution confirmed stopped", "code": "EXECUTOR_RESTARTED", "retryable": True})
        _atomic(path, record)
    if record["status"] == "unknown" and _marker(path).get("stopped"):
        record.update(status="cancelled" if record.get("cancel_requested") else "failed", stopped=True)
        if record["status"] == "failed":
            record["result"] = {"error": "execution stopped after recovery", "retryable": True}
        _atomic(path, record)
    job = load_job(record["parameters"]["user_key"], record["parameters"]["job_id"])
    return {"status": record["status"], "stopped": record["stopped"], "progress": {"percent": job.progress if job else 0}, "result": record.get("result", {})}


@router.post("/executions/{attempt}/cancel")
async def cancel(attempt: str, body: dict, authorization: str = Header(default="")):
    _authorize(authorization)
    path = _path(attempt)
    async with _locks.setdefault(attempt, asyncio.Lock()):
        record = _read(path)
        if not record:
            record = {"attempt_id": attempt, "fence": body["fence"], "parameters": body["parameters"], "status": "cancelled", "stopped": True, "result": {}}
            _atomic(path, record)
        if record["fence"] != body.get("fence"):
            raise HTTPException(409, "stale fence")
        record["cancel_requested"] = True
        _atomic(path, record)
        _lease(path, 0)
        task = _executions.get(attempt)
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        return await inspect(attempt, body, authorization)
