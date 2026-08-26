from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from app.config import settings
from app.models import JobRecord

INPUT_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
MAX_INPUT_BYTES = 20 * 1024 * 1024


def ensure_storage() -> None:
    settings.sessions_dir.mkdir(parents=True, exist_ok=True)
    settings.jobs_dir.mkdir(parents=True, exist_ok=True)
    reconcile_orphaned_active_jobs()


def user_dir(user_key: str) -> Path:
    path = settings.sessions_dir / user_key
    path.mkdir(parents=True, exist_ok=True)
    return path


def job_dir(user_key: str, job_id: str) -> Path:
    path = user_dir(user_key) / job_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def job_path(user_key: str, job_id: str) -> Path:
    path = settings.jobs_dir / user_key
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{job_id}.json"


def save_job(job: JobRecord) -> None:
    job.updated_at = datetime.utcnow()
    job_path(job.user_key, job.job_id).write_text(job.model_dump_json(indent=2), encoding="utf-8")


def load_job(user_key: str, job_id: str) -> JobRecord | None:
    path = job_path(user_key, job_id)
    if not path.exists():
        return None
    return JobRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))


def list_jobs(user_key: str) -> list[JobRecord]:
    path = settings.jobs_dir / user_key
    if not path.exists():
        return []
    jobs = []
    for item in sorted(path.glob("*.json"), reverse=True):
        try:
            jobs.append(JobRecord.model_validate(json.loads(item.read_text(encoding="utf-8"))))
        except Exception:
            continue
    return sorted(jobs, key=lambda job: job.created_at, reverse=True)


def reconcile_orphaned_active_jobs() -> None:
    if not settings.jobs_dir.exists():
        return
    for path in settings.jobs_dir.glob("*/*.json"):
        try:
            job = JobRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
        if job.status not in {"queued", "running"}:
            continue
        job.status = "failed"
        job.progress = 0
        job.error = "服务重启后已清理未完成任务，请重新提交。"
        save_job(job)


def delete_job(user_key: str, job_id: str) -> bool:
    item = load_job(user_key, job_id)
    if not item:
        return False
    path = job_path(user_key, job_id)
    if path.exists():
        path.unlink()
    output_dir = user_dir(user_key) / job_id
    if output_dir.exists():
        shutil.rmtree(output_dir)
    return True


def settings_path(user_key: str) -> Path:
    return user_dir(user_key) / "settings.json"


def load_settings(user_key: str) -> dict:
    path = settings_path(user_key)
    if not path.exists():
        return {"language": "zh-CN"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"language": "zh-CN"}
    language = data.get("language")
    return {"language": language if language in {"zh-CN", "en"} else "zh-CN"}


def save_settings(user_key: str, data: dict) -> dict:
    current = load_settings(user_key)
    language = data.get("language")
    if language in {"zh-CN", "en"}:
        current["language"] = language
    settings_path(user_key).write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    return current


def inputs_dir(user_key: str) -> Path:
    path = user_dir(user_key) / "inputs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_input(user_key: str, filename: str, data: bytes) -> dict:
    """保存上传的参考图，返回列表条目。扩展名白名单外的文件抛 ValueError。"""
    suffix = Path(filename).suffix.lower()
    if suffix not in INPUT_EXTENSIONS:
        raise ValueError(f"unsupported image type: {suffix or '(none)'}, expect png/jpg/jpeg/webp")
    if len(data) > MAX_INPUT_BYTES:
        raise ValueError("image too large (max 20MB)")
    input_id = f"in_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    stored = inputs_dir(user_key) / f"{input_id}{suffix}"
    stored.write_bytes(data)
    return {
        "input_id": input_id,
        "filename": filename,
        "size": len(data),
        "created_at": datetime.utcnow().isoformat(),
        "url": f"/api/v1/inputs/{input_id}",
    }


def list_inputs(user_key: str) -> list[dict]:
    result = []
    for path in sorted(inputs_dir(user_key).glob("in_*.*"), reverse=True):
        stat = path.stat()
        result.append({
            "input_id": path.stem,
            "filename": path.name,
            "size": stat.st_size,
            "created_at": datetime.utcfromtimestamp(stat.st_mtime).isoformat(),
            "url": f"/api/v1/inputs/{path.stem}",
        })
    return result


def input_path(user_key: str, input_id: str) -> Path | None:
    if not input_id.startswith("in_") or "/" in input_id or "\\" in input_id:
        return None
    for path in inputs_dir(user_key).glob(f"{input_id}.*"):
        return path
    return None


def delete_input(user_key: str, input_id: str) -> bool:
    path = input_path(user_key, input_id)
    if not path:
        return False
    path.unlink()
    return True
