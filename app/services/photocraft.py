"""Short-lived access to one owned output for an audience-isolated VOS editor."""
import secrets
import time
from urllib.parse import quote

from fastapi import HTTPException

from app.services.storage import job_dir, load_job

_tickets: dict[str, tuple[float, str, str, str]] = {}
LIFETIME_SECONDS = 300


def output_path(user: str, job_id: str, filename: str):
    job = load_job(user, job_id)
    if not job or job.status != "succeeded" or filename not in job.outputs or filename.rsplit(".", 1)[-1].lower() not in {"png", "jpg", "jpeg", "webp"}:
        raise HTTPException(404, "output not found")
    root = job_dir(user, job_id).resolve()
    path = (root / filename).resolve()
    if path.parent != root or not path.is_file():
        raise HTTPException(404, "output not found")
    return path


def issue(user: str, job_id: str, filename: str) -> dict:
    output_path(user, job_id, filename)
    now = time.time()
    for key, record in list(_tickets.items()):
        if record[0] <= now:
            _tickets.pop(key, None)
    if len(_tickets) >= 1024:
        raise HTTPException(429, "too many pending image handoffs")
    ticket = secrets.token_urlsafe(32)
    expires = now + LIFETIME_SECONDS
    _tickets[ticket] = (expires, user, job_id, filename)
    return {"url": f"/api/com.ictrek.image-studio/api/v1/photocraft/handoffs/{ticket}/{quote(filename, safe='')}", "expires_at": expires}


def resolve(ticket: str, filename: str):
    record = _tickets.get(ticket)
    if not record or record[0] <= time.time() or filename != record[3]:
        if record and record[0] <= time.time():
            _tickets.pop(ticket, None)
        raise HTTPException(404, "image handoff expired or unavailable")
    return output_path(record[1], record[2], filename)
