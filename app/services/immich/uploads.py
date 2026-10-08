from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.models import ImmichUploadRecord, JobRecord
from app.services.storage import job_dir, list_jobs, load_job, save_job

from .client import ImmichClient, ImmichError
from .exchange import cached_api_key

logger = logging.getLogger("image-studio.immich")
_queue: asyncio.Queue[tuple[str, str, str]] = asyncio.Queue()
_worker_task: asyncio.Task | None = None
_active: set[tuple[str, str, str]] = set()
MAX_ATTEMPTS = 3


class ImmichUploadError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _client_for(user_key: str) -> ImmichClient:
    # 凭据来自 vos-exchange 的进程内缓存（api 层在入队前已确保换取成功）。
    # 重启后缓存清空，恢复的旧任务会走到这里失败并标记，由用户重新点击上传换取。
    api_key = cached_api_key(user_key)
    if not api_key:
        raise ImmichUploadError("Immich 凭据未就绪（服务已重启），请重新点击上传以自动换取")
    return ImmichClient(settings.immich_default_api_url, api_key, verify_ssl=settings.immich_verify_ssl)


def _output_path(user_key: str, job_id: str, filename: str) -> Path:
    if Path(filename).name != filename or filename.startswith("."):
        raise ImmichUploadError("输出文件名无效")
    return job_dir(user_key, job_id) / filename


def _record(status: str, previous: ImmichUploadRecord | None = None) -> ImmichUploadRecord:
    if previous:
        return previous.model_copy(update={"status": status, "error": "", "updated_at": _now()})
    return ImmichUploadRecord(status=status, updated_at=_now())


async def start() -> None:
    global _worker_task
    if _worker_task and not _worker_task.done():
        return
    _worker_task = asyncio.create_task(_worker())
    resumed = 0
    for user_dir in _job_user_dirs():
        user_key = user_dir.name
        for job in list_jobs(user_key):
            for filename, record in job.immich_uploads.items():
                if record.status in {"queued", "uploading"}:
                    record.status = "queued"
                    record.updated_at = _now()
                    save_job(job)
                    await _enqueue(user_key, job.job_id, filename)
                    resumed += 1
    logger.info("Immich 上传 worker 已启动，恢复未完成上传 %d 个", resumed)


def stop() -> None:
    global _worker_task
    pending = len(_active)
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
    _worker_task = None
    _active.clear()
    logger.info("Immich 上传 worker 已停止，丢弃待处理 %d 个", pending)


def _job_user_dirs() -> list[Path]:
    return [item for item in settings.jobs_dir.iterdir() if item.is_dir()] if settings.jobs_dir.exists() else []


async def _enqueue(user_key: str, job_id: str, filename: str) -> None:
    key = (user_key, job_id, filename)
    if key in _active:
        logger.debug("Immich 上传已在队列中，重复触发已忽略: user=%s job=%s file=%s", user_key, job_id, filename)
        return
    _active.add(key)
    await _queue.put(key)
    logger.info("Immich 上传入队: user=%s job=%s file=%s queue=%d", user_key, job_id, filename, _queue.qsize())


async def enqueue_job(user_key: str, job_id: str, force: bool = False) -> JobRecord:
    job = load_job(user_key, job_id)
    if not job:
        raise FileNotFoundError("job not found")
    if job.status != "succeeded":
        raise ImmichUploadError("只有已成功的生成任务可以上传到 Immich")
    if not job.outputs:
        raise ImmichUploadError("任务没有可上传的输出文件")
    _client_for(user_key)
    enqueue = []
    skipped = []
    for filename in job.outputs:
        path = _output_path(user_key, job_id, filename)
        if not path.is_file():
            raise ImmichUploadError(f"输出文件不存在: {filename}")
        current = job.immich_uploads.get(filename)
        # queued/uploading 说明已有任务在跑，强制与否都不重复入队，避免同文件并发上传。
        if current and current.status in {"queued", "uploading"}:
            skipped.append(f"{filename}:{current.status}")
            continue
        if current and current.status in {"uploaded", "duplicate"} and not force:
            skipped.append(f"{filename}:{current.status}")
            continue
        job.immich_uploads[filename] = _record("queued", current)
        enqueue.append(filename)
    save_job(job)
    for filename in enqueue:
        await _enqueue(user_key, job_id, filename)
    logger.info(
        "Immich 上传已受理: user=%s job=%s force=%s 入队=[%s] 跳过=[%s]",
        user_key, job_id, force, ", ".join(enqueue) or "-", ", ".join(skipped) or "-",
    )
    return job


async def retry_job(user_key: str, job_id: str) -> JobRecord:
    job = load_job(user_key, job_id)
    if not job:
        raise FileNotFoundError("job not found")
    enqueue = []
    for filename, current in job.immich_uploads.items():
        if current.status == "failed":
            job.immich_uploads[filename] = _record("queued", current)
            enqueue.append(filename)
    save_job(job)
    for filename in enqueue:
        await _enqueue(user_key, job_id, filename)
    logger.info(
        "Immich 上传手动重试: user=%s job=%s 重新入队=[%s]",
        user_key, job_id, ", ".join(enqueue) or "-",
    )
    return job


async def cancel_job_uploads(user_key: str, job_id: str) -> None:
    cancelled = 0
    for key in list(_active):
        if key[:2] == (user_key, job_id):
            _active.discard(key)
            cancelled += 1
    if cancelled:
        logger.info("Immich 上传已取消: user=%s job=%s 取消待处理 %d 个", user_key, job_id, cancelled)


async def _worker() -> None:
    while True:
        key = await _queue.get()
        try:
            await _process(*key)
        except asyncio.CancelledError:
            logger.info("Immich 上传 worker 被取消: user=%s job=%s file=%s", *key)
            raise
        except Exception:
            logger.exception("Immich 上传 worker 未捕获异常: user=%s job=%s file=%s", *key)
        finally:
            _active.discard(key)
            _queue.task_done()


async def _process(user_key: str, job_id: str, filename: str) -> None:
    job = load_job(user_key, job_id)
    if not job:
        logger.warning("Immich 上传跳过，任务不存在: user=%s job=%s file=%s", user_key, job_id, filename)
        return
    path = _output_path(user_key, job_id, filename)
    if filename not in job.outputs:
        logger.warning("Immich 上传跳过，文件不属于该任务输出: user=%s job=%s file=%s", user_key, job_id, filename)
        return
    current = job.immich_uploads.get(filename)
    if not current or current.status != "queued":
        logger.debug(
            "Immich 上传跳过，状态已变更: user=%s job=%s file=%s status=%s",
            user_key, job_id, filename, current.status if current else "-",
        )
        return
    if not path.is_file():
        current.status = "failed"
        current.error = "输出文件不存在"
        current.updated_at = _now()
        save_job(job)
        logger.error("Immich 上传失败，输出文件已不存在: user=%s job=%s file=%s path=%s", user_key, job_id, filename, path)
        return

    started = time.monotonic()
    current.status = "uploading"
    current.attempts += 1
    current.updated_at = _now()
    save_job(job)
    logger.info(
        "Immich 上传处理开始: user=%s job=%s file=%s size=%d 第 %d/%d 次",
        user_key, job_id, filename, path.stat().st_size, current.attempts, MAX_ATTEMPTS,
    )
    while True:
        try:
            client = _client_for(user_key)
            result = await client.upload(path, f"image-studio:{job_id}:{filename}", job.created_at)
            break
        except ImmichError as exc:
            current.error = str(exc)
            current.updated_at = _now()
            if exc.retryable and current.attempts < MAX_ATTEMPTS:
                current.status = "queued"
                save_job(job)
                delay = 2 ** (current.attempts - 1)
                logger.warning(
                    "Immich 上传将重试: user=%s job=%s file=%s 第 %d/%d 次，%d 秒后重试",
                    user_key, job_id, filename, current.attempts, MAX_ATTEMPTS, delay,
                )
                await asyncio.sleep(delay)
                job = load_job(user_key, job_id)
                current = job.immich_uploads.get(filename) if job else None
                if not current or current.status != "queued":
                    logger.warning(
                        "Immich 上传重试前任务已删除或状态变更: user=%s job=%s file=%s",
                        user_key, job_id, filename,
                    )
                    return
                current.status = "uploading"
                current.attempts += 1
                current.updated_at = _now()
                save_job(job)
                continue
            current.status = "failed"
            save_job(job)
            logger.error(
                "Immich 上传最终失败: user=%s job=%s file=%s 第 %d/%d 次 retryable=%s elapsed=%.2fs error=%s",
                user_key, job_id, filename, current.attempts, MAX_ATTEMPTS,
                exc.retryable, time.monotonic() - started, exc,
            )
            return
        except (OSError, ValueError) as exc:
            current.status = "failed"
            current.error = str(exc)
            current.updated_at = _now()
            save_job(job)
            logger.error(
                "Immich 上传失败（不可重试）: user=%s job=%s file=%s elapsed=%.2fs error=%s",
                user_key, job_id, filename, time.monotonic() - started, exc,
            )
            return

    current.status = "duplicate" if result.status == "duplicate" else "uploaded"
    current.asset_id = result.asset_id
    current.checksum = result.checksum
    current.error = ""
    current.updated_at = _now()
    save_job(job)
    logger.info(
        "Immich 上传处理完成: user=%s job=%s file=%s status=%s asset_id=%s checksum=%s elapsed=%.2fs",
        user_key, job_id, filename, current.status, result.asset_id, result.checksum, time.monotonic() - started,
    )
