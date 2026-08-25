from __future__ import annotations

import asyncio
import fnmatch
import json
import logging
import os
import time
import uuid
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

# HF endpoint 候选列表：默认 hf-mirror 优先，失败自动切 huggingface.co；
# 可用 IMAGE_STUDIO_HF_ENDPOINTS 配置更多镜像（逗号分隔）。hf-mirror 偶发
# "Server disconnected" 不应让整次下载卡死或停掉。
_HF_ENDPOINTS: list[str] = [
    e.strip() for e in os.getenv(
        "IMAGE_STUDIO_HF_ENDPOINTS",
        "https://hf-mirror.com,https://huggingface.co",
    ).split(",") if e.strip()
]

_tasks: dict[str, dict[str, Any]] = {}
# 每个模型 key 当前活跃的桥接（用于新下载接管时立即关闭旧记录，
# 避免旧循环在文件边界退出前与新模式同时刷新任务记录）
_bridges: dict[str, "_TaskBridge"] = {}


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


async def start_download(key: str, sources: list[dict[str, Any]], force: bool = False) -> bool:
    """为模型启动后台 HF 直连下载；已在下载中且未强制时返回 False。

    force=True 用于"重新下载"：先请求取消旧任务（旧线程会在当前文件
    边界退出），再立即启动新任务接管状态。
    """
    if is_downloading(key):
        if not force:
            return False
        request_cancel(key)
    # 旧循环可能还在当前大文件的写入中（到文件边界才退出），先关闭它的
    # 任务记录并停止其后续写入，避免两条记录并行刷新造成界面横跳。
    old_bridge = _bridges.get(key)
    if old_bridge is not None:
        old_bridge.supersede()
    _tasks[key] = {
        "status": "running",
        "progress": 0.0,
        "downloaded_bytes": 0,
        "total_bytes": 0,
        "current_file": "",
        "error": "",
        "cancel": False,
        "started_at": time.time(),
    }
    asyncio.create_task(_run(key, sources))
    return True


def request_cancel(key: str) -> bool:
    """请求停止下载：立即生效于状态展示，实际线程在当前文件写完后退出。

    已落盘的部分文件保留，之后重新下载会断点续传。
    """
    state = _tasks.get(key)
    if not state or state.get("status") != "running":
        return False
    state["cancel"] = True
    state["status"] = "cancelled"
    return True


async def _run(key: str, sources: list[dict[str, Any]]) -> None:
    state = _tasks[key]
    specs = [(spec["model_id"], list(spec.get("files") or [])) for spec in sources if spec["source"] == "hf"]
    bridge = _TaskBridge(specs)
    _bridges[key] = bridge
    # 先启动进度上报（立刻进入 DOWNLOADING），文件清单/总大小后台并行获取，
    # 避免清单查询期间任务停留在"等待中"。
    per_repo_totals: dict[str, int] = {}
    heartbeat = asyncio.create_task(_heartbeat(key, specs, per_repo_totals, bridge))
    try:
        fetched = await asyncio.to_thread(_expected_bytes_per_repo, specs)
        per_repo_totals.update(fetched)
        state["total_bytes"] = sum(fetched.values())
        logger.info("HF 下载开始: %s, 共 %d 个文件, 预计 %d 字节", key, sum(len(f) for _, f in specs), state["total_bytes"])

        cancelled = False
        for repo_id, files in specs:
            if state.get("cancel"):
                cancelled = True
                break
            # 同一仓库的所有文件必须下到同一个 snapshot 目录，否则 current
            # 链接只指向其中一个 revision，其余文件会找不到。优先复用仓库
            # 已有的 snapshot 目录（之前下载可能已建），避免新解析的 revision
            # 与旧目录漂移（_latest_revision 在 endpoint 间可能返回不同值）。
            revision = _existing_snapshot_revision(repo_id) or await asyncio.to_thread(_latest_revision, repo_id)
            target = snapshot_dir({"source": "hf", "model_id": repo_id}) / revision
            for filename in files:
                if state.get("cancel"):
                    cancelled = True
                    break
                state["current_file"] = f"{repo_id}/{filename}"
                await asyncio.to_thread(_download_file, repo_id, filename, target)
            if cancelled:
                break
        heartbeat.cancel()

        if cancelled:
            bridge.fail("已手动停止，可随时重新下载（支持断点续传）")
            state["current_file"] = ""
            logger.info("HF 下载已手动停止: %s", key)
            return

        state["progress"] = 1.0
        state["current_file"] = ""
        state["status"] = "done"
        bridge.finish()
        logger.info("HF 下载完成: %s", key)
        await _sync_model_hub()
    except Exception as exc:
        state["status"] = "failed"
        state["error"] = str(exc)
        bridge.fail(str(exc))
        logger.error("HF 下载失败: %s, error=%s", key, exc)
    finally:
        heartbeat.cancel()
        # 仅当自己仍是当前注册的桥接才移除：被 supersede 之后可能已有新下载
        # 以同一 key 重新注册，此时旧循环退出不应干扰新桥接。
        if _bridges.get(key) is bridge:
            _bridges.pop(key, None)


class _TaskBridge:
    """把下载进度以任务记录形式写入 Model Hub 的共享任务目录。

    与 wa-drug 的对接方式一致：Model Hub 的任务页扫描 shared/tasks/*.json，
    这里按仓库粒度写 DOWNLOADING 记录并实时刷新进度，结束/失败时收尾。
    """

    def __init__(self, specs: list[tuple[str, list[str]]]) -> None:
        self._superseded = False
        self.records = {
            repo_id: {"task_id": f"is_{uuid.uuid4().hex[:12]}", "last_write": 0.0, "last_bytes": 0, "last_time": 0.0}
            for repo_id, _ in specs
        }
        for repo_id, rec in self.records.items():
            self._write(rec["task_id"], repo_id, "PENDING")

    def supersede(self) -> None:
        """关闭旧任务的桥接：停止后续写入，并把已写记录收尾为 FAILED（由新下载接管）。

        触发场景："重新下载"时旧循环可能还在当前大文件的写入中，若等它
        自己收尾，会与新的下载记录并行刷新，造成任务页进度横跳。
        """
        self._superseded = True
        for repo_id, rec in list(self.records.items()):
            self._write(rec["task_id"], repo_id, "FAILED", error_msg="已被新的下载任务接管")

    def update(self, repo_id: str, downloaded: int, total: int) -> None:
        if self._superseded:
            return
        rec = self.records.get(repo_id)
        if not rec:
            return
        now = time.monotonic()
        if now - rec["last_write"] < 5:
            return
        speed = None
        eta = None
        if rec["last_time"] and now > rec["last_time"]:
            speed = max(0.0, (downloaded - rec["last_bytes"]) / (now - rec["last_time"]))
            if speed > 0 and total > downloaded:
                eta = (total - downloaded) / speed
        rec.update(last_write=now, last_bytes=downloaded, last_time=now)
        progress = min(downloaded / total, 0.999) if total > 0 else 0.005
        self._write(rec["task_id"], repo_id, "DOWNLOADING", progress=progress, speed=speed, eta=eta)

    def finish(self) -> None:
        if self._superseded:
            return
        for repo_id, rec in self.records.items():
            self._write(rec["task_id"], repo_id, "READY", progress=1.0)

    def fail(self, error: str) -> None:
        if self._superseded:
            return
        for repo_id, rec in self.records.items():
            self._write(rec["task_id"], repo_id, "FAILED", error_msg=error[:500])

    def _write(self, task_id: str, model_id: str, phase: str, progress: float = 0.0, speed: float | None = None, eta: float | None = None, error_msg: str | None = None) -> None:
        record = {
            "task_id": task_id,
            "model_id": f"hf://{model_id}",
            "progress": progress,
            "speed": speed,
            "eta": eta,
            "phase": phase,
            "error_msg": error_msg,
        }
        try:
            tasks_dir = settings.modelhub_root / "shared" / "tasks"
            tasks_dir.mkdir(parents=True, exist_ok=True)
            path = tasks_dir / f"{task_id}.json"
            tmp = tasks_dir / f"{task_id}.json.tmp"
            tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
        except Exception as exc:
            logger.warning("写入 Model Hub 任务记录失败（不影响下载）: %s", exc)


def _expected_bytes_per_repo(specs: list[tuple[str, list[str]]]) -> dict[str, int]:
    """按仓库汇总远端文件大小。

    遍历 _HF_ENDPOINTS 依次重试，任一 endpoint 成功即停止；全部失败才
    返回 0（此时下载进度无法按百分比计算，但不会阻断下载本身）。
    """
    totals: dict[str, int] = {}
    for repo_id, files in specs:
        if not files:
            totals[repo_id] = 0
            continue
        total = 0
        for ep in _HF_ENDPOINTS:
            try:
                api = HfApi(endpoint=ep)
                for entry in api.list_repo_tree(repo_id, recursive=True):
                    size = getattr(entry, "size", None)
                    if size and any(fnmatch.fnmatch(entry.path, pattern) for pattern in files):
                        total += size
                break  # 本仓库成功拿到大小，不再尝试下一个 endpoint
            except Exception as exc:
                logger.warning("获取 %s 文件大小失败 (%s): %s", repo_id, ep, exc)
                continue
        if total == 0:
            logger.warning("所有 endpoint 均未能获取 %s 文件大小，进度将按已下载量显示", repo_id)
        totals[repo_id] = total
    return totals


def _download_file(repo_id: str, filename: str, target_dir: Path) -> str:
    """下载单个文件，失败时在多个 endpoint 间重试（共 3 轮）。

    hf_hub_download 读取全局 HF_ENDPOINT，这里在重试时切换它；下载是顺序
    执行的（max_concurrency=1），切换全局环境变量的竞态可忽略。断点续传
    由 hf_hub_download 的 .incomplete 机制保证，重试不会从头来。
    """
    last_exc: Exception | None = None
    for attempt in range(3):
        for ep in _HF_ENDPOINTS:
            try:
                os.environ["HF_ENDPOINT"] = ep
                return hf_hub_download(
                    repo_id=repo_id,
                    filename=filename,
                    local_dir=str(target_dir),
                )
            except Exception as exc:
                last_exc = exc
                logger.warning("下载 %s/%s 失败 (%s, 第 %d 轮): %s", repo_id, filename, ep, attempt + 1, exc)
                continue
    assert last_exc is not None
    raise last_exc


def _latest_revision(repo_id: str) -> str:
    """取远端当前 commit 作为 snapshot 目录名，与 HF 缓存约定一致；失败退回 main。"""
    for ep in _HF_ENDPOINTS:
        try:
            info = HfApi(endpoint=ep).model_info(repo_id)
            return info.sha or "main"
        except Exception as exc:
            logger.warning("获取 %s 版本信息失败 (%s)，尝试下一个 endpoint: %s", repo_id, ep, exc)
            continue
    return "main"


def _existing_snapshot_revision(repo_id: str) -> str | None:
    """返回该仓库已存在的 snapshot 目录名（优先 current 指向的，其次任意非空）。

    用于复用历史下载的 revision 目录，避免 _latest_revision 在 endpoint 间
    漂移导致同一仓库多文件分散到不同 snapshot。
    """
    _MODEL_EXTS = {".safetensors", ".ckpt", ".pt", ".pth", ".gguf"}
    root = snapshot_dir({"source": "hf", "model_id": repo_id})
    if not root.is_dir():
        return None
    # 优先 current 指向的 revision
    current_link = root.parent / "current"
    try:
        if current_link.is_symlink():
            target = current_link.resolve()
            if target.is_dir():
                return target.name
    except OSError:
        pass
    # 任意已存在且含实际模型文件的 snapshot 目录
    for snap in sorted(root.iterdir(), reverse=True):
        if not snap.is_dir():
            continue
        for f in snap.rglob("*"):
            if f.is_file() and f.suffix.lower() in _MODEL_EXTS:
                return snap.name
    return None


async def _heartbeat(key: str, specs: list[tuple[str, list[str]]], per_repo_totals: dict[str, int], bridge: _TaskBridge) -> None:
    state = _tasks.get(key)
    if not state:
        return
    last_total_retry = 0.0
    while True:
        await asyncio.sleep(2)
        # 一开始没拿到远端文件大小（endpoint 抖动）时定期重试补全，
        # 否则 total_bytes 恒为 0、progress 永远停在 0%。
        if state.get("total_bytes", 0) == 0 and time.monotonic() - last_total_retry > 30:
            last_total_retry = time.monotonic()
            try:
                fetched = await asyncio.to_thread(_expected_bytes_per_repo, specs)
                if any(fetched.values()):
                    per_repo_totals.update(fetched)
                    state["total_bytes"] = sum(fetched.values())
                    logger.info("补全下载总大小: %s = %d 字节", key, state["total_bytes"])
            except Exception as exc:
                logger.warning("重试获取下载总大小失败: %s", exc)
        downloaded_total = 0
        for repo_id, _ in specs:
            downloaded = await asyncio.to_thread(_dir_bytes, snapshot_dir({"source": "hf", "model_id": repo_id}))
            downloaded_total += downloaded
            bridge.update(repo_id, downloaded, per_repo_totals.get(repo_id, 0))
        state["downloaded_bytes"] = downloaded_total
        if state["total_bytes"] > 0:
            state["progress"] = min(downloaded_total / state["total_bytes"], 0.999)


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
