from __future__ import annotations

import asyncio
import fnmatch
import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx

# 必须在 import huggingface_hub 之前设置：国内环境默认走 hf-mirror 镜像加速，
# 可通过 HF_ENDPOINT 或 IMAGE_STUDIO_HF_ENDPOINT 覆盖。
os.environ.setdefault("HF_ENDPOINT", os.getenv("IMAGE_STUDIO_HF_ENDPOINT", "https://hf-mirror.com"))
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

from huggingface_hub import hf_hub_download  # noqa: E402
from huggingface_hub import HfApi  # noqa: E402

from app.config import settings  # noqa: E402

logger = logging.getLogger("image-studio.hf-downloader")

_tasks: dict[str, dict[str, Any]] = {}


def task_state(key: str) -> dict[str, Any] | None:
    return _tasks.get(key)


def is_downloading(key: str) -> bool:
    state = _tasks.get(key)
    return bool(state and state.get("status") == "running")


def snapshot_dir(spec: dict[str, Any]) -> Path:
    """按 Model Hub 兼容布局返回仓库的 snapshots 根目录。

    Model Hub 约定: <shared>/export/<source>/<org>/<repo>/{blobs,snapshots,<current 链接>}。
    """
    parts = [part for part in spec["model_id"].replace("\\", "/").split("/") if part and part not in (".", "..")]
    return settings.modelhub_root / "export" / spec["source"] / Path(*parts) / "snapshots"


async def start_download(key: str, sources: list[dict[str, Any]]) -> bool:
    """为模型启动后台 HF 直连下载；已在下载中时返回 False。"""
    if is_downloading(key):
        return False
    _tasks[key] = {
        "status": "running",
        "progress": 0.0,
        "downloaded_bytes": 0,
        "total_bytes": 0,
        "current_file": "",
        "error": "",
        "started_at": time.time(),
    }
    asyncio.create_task(_run(key, sources))
    return True


async def _run(key: str, sources: list[dict[str, Any]]) -> None:
    state = _tasks[key]
    try:
        specs = [(spec["model_id"], list(spec.get("files") or [])) for spec in sources if spec["source"] == "hf"]
        total_bytes = await asyncio.to_thread(_expected_bytes, specs)
        state["total_bytes"] = total_bytes
        logger.info("HF 下载开始: %s, 共 %d 个文件, 预计 %d 字节", key, sum(len(f) for _, f in specs), total_bytes)

        heartbeat = asyncio.create_task(_heartbeat(key, specs))
        try:
            for repo_id, files in specs:
                revision = await asyncio.to_thread(_latest_revision, repo_id)
                target = snapshot_dir({"source": "hf", "model_id": repo_id}) / revision
                for filename in files:
                    state["current_file"] = f"{repo_id}/{filename}"
                    await asyncio.to_thread(_download_file, repo_id, filename, target)
        finally:
            heartbeat.cancel()

        state["progress"] = 1.0
        state["current_file"] = ""
        state["status"] = "done"
        logger.info("HF 下载完成: %s", key)
        await _sync_model_hub()
    except Exception as exc:
        state["status"] = "failed"
        state["error"] = str(exc)
        logger.error("HF 下载失败: %s, error=%s", key, exc)


def _download_file(repo_id: str, filename: str, target_dir: Path) -> str:
    return hf_hub_download(
        repo_id=repo_id,
        filename=filename,
        local_dir=str(target_dir),
    )


def _latest_revision(repo_id: str) -> str:
    """取远端当前 commit 作为 snapshot 目录名，与 HF 缓存约定一致；失败退回 main。"""
    try:
        info = HfApi().model_info(repo_id)
        return info.sha or "main"
    except Exception as exc:
        logger.warning("获取 %s 版本信息失败，使用 main: %s", repo_id, exc)
        return "main"


def _expected_bytes(specs: list[tuple[str, list[str]]]) -> int:
    """按文件清单汇总远端文件大小；失败返回 0（进度退化为纯字节数展示）。"""
    api = HfApi()
    total = 0
    for repo_id, files in specs:
        if not files:
            continue
        try:
            for entry in api.list_repo_tree(repo_id, recursive=True):
                size = getattr(entry, "size", None)
                if size and any(fnmatch.fnmatch(entry.path, pattern) for pattern in files):
                    total += size
        except Exception as exc:
            logger.warning("获取 %s 文件大小失败: %s", repo_id, exc)
    return total


async def _heartbeat(key: str, specs: list[tuple[str, list[str]]]) -> None:
    state = _tasks.get(key)
    if not state:
        return
    while True:
        await asyncio.sleep(2)
        downloaded = 0
        for repo_id, _ in specs:
            downloaded += await asyncio.to_thread(_dir_bytes, snapshot_dir({"source": "hf", "model_id": repo_id}))
        state["downloaded_bytes"] = downloaded
        if state["total_bytes"] > 0:
            state["progress"] = min(downloaded / state["total_bytes"], 0.999)


def _dir_bytes(root: Path) -> int:
    """统计已落盘字节数。

    下载中的大文件位于 .cache/huggingface/download/*.incomplete（hf_hub_download
    的断点续传缓冲），必须计入才能反映真实进度；只排除锁与元数据小文件。
    """
    total = 0
    if not root.exists():
        return 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        name = path.name
        if name.endswith((".lock", ".metadata")) or name in (".gitignore", "CACHEDIR.TAG"):
            continue
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return total


async def _sync_model_hub() -> None:
    """下载完成后触发 Model Hub 同步，把新 snapshot 注册进 Model Hub 界面。"""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            await client.post(f"{settings.model_hub_api_url}/api/v1/models/sync")
    except Exception as exc:
        logger.warning("触发 Model Hub 同步失败（不影响下载结果）: %s", exc)


def merge_state(key: str, info: dict[str, Any]) -> None:
    """把本应用的下载任务状态合并进模型信息。

    running 始终展示为下载中（重新拉取场景）；failed 只在本地文件缺失时展示，
    避免覆盖已就绪模型的状态。
    """
    state = _tasks.get(key)
    if not state or state.get("status") == "done":
        return
    if state["status"] == "running":
        info["status"] = "downloading"
        info["progress"] = state.get("progress", 0.0)
        info["current_file"] = state.get("current_file", "")
        info["downloaded_bytes"] = state.get("downloaded_bytes", 0)
        info["total_bytes"] = state.get("total_bytes", 0)
    elif state["status"] == "failed" and info["status"] == "missing":
        info["status"] = "failed"
        info["error"] = state.get("error", "")
