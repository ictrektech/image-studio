from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.config import settings
from app.models import JobRecord


def ensure_storage() -> None:
    settings.sessions_dir.mkdir(parents=True, exist_ok=True)
    settings.jobs_dir.mkdir(parents=True, exist_ok=True)


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
