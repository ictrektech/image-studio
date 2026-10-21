from __future__ import annotations

import asyncio
import json
import hashlib
import os
import secrets
import threading
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Request


APP_ID = "com.ictrek.image-studio"
PREFIX = "IMAGE_STUDIO"
UPSTREAM = "http://image-studio-backend:5000"
URL = "http://v-router:8080/scheduler/api/v1"
router = APIRouter(prefix="/api/v1/scheduler")
lock = threading.RLock()


def execution_settings():
    from app.config import settings
    return {"profile": settings.profile, "runtime": "stable-diffusion.cpp", "logical_cpu_count": os.cpu_count(), "max_concurrency": settings.max_concurrency, "sd_cpp_extra_args_sha256": hashlib.sha256(settings.sd_cpp_extra_args.encode()).hexdigest()}


def required():
    return os.getenv(PREFIX + "_SCHEDULER_REQUIRED") == "true"


def config_path():
    return Path(os.getenv(PREFIX + "_SCHEDULER_CONFIG", "/data/scheduler.json"))


def read_config(*, for_rebinding=False):
    path = config_path()
    try:
        info = path.lstat()
        if path.is_symlink() or not path.is_file() or info.st_mode & 0o077 or info.st_size > 262144:
            raise ValueError("private configuration required")
        value = json.loads(path.read_text())
        legacy = for_rebinding and value.get("url") == "http://v-scheduler:38120/api/v1" and all(field not in value for field in ("app_id", "upstream_url", "binding_revision", "protocol_version"))
        if not legacy and (value.get("url") != URL or value.get("app_id") != APP_ID or value.get("upstream_url") != UPSTREAM):
            raise ValueError("invalid service binding")
        if len(value.get("token", "")) < 32:
            raise ValueError("missing service identity")
        if not for_rebinding and value.get("execution_settings") != execution_settings():
            raise ValueError("runtime settings no longer match approval")
        return value
    except (OSError, ValueError, TypeError, AttributeError):
        raise HTTPException(503, "V-Scheduler binding required") from None


def controller(config, method, path, body=None, key=""):
    headers = {"Authorization": "Bearer " + config["token"]}
    if key:
        headers["Idempotency-Key"] = key
    try:
        response = httpx.request(method, URL + path, headers=headers, json=body, timeout=8, follow_redirects=False)
        if response.status_code == 429:
            raise HTTPException(429, "Compute resources busy", headers={"Retry-After": "1"})
        response.raise_for_status()
        value = response.json()
        if value.get("code") != "OK":
            raise ValueError("invalid scheduler response")
        return value["data"]
    except (httpx.HTTPError, ValueError, KeyError):
        raise HTTPException(503, "V-Scheduler unavailable") from None


@router.get("/binding")
def binding_status():
    try:
        config = read_config()
    except HTTPException:
        return {"protocol_version": 1, "configured": False}
    return {"protocol_version": 1, "configured": True, "binding_revision": config.get("binding_revision"), "approved_model_count": len(config.get("models", {}))}


@router.post("/binding")
async def bind(request: Request):
    identity_url = os.getenv("VOS_USERINFO_URL")
    if not identity_url:
        port = os.getenv("VOS_API_GW_PORT_INTERNAL", "")
        if not port.isdigit():
            raise HTTPException(503, "VOS identity service unavailable")
        identity_url = "http://host.docker.internal:" + port + "/v1000/oauth2/userinfo"
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
            identity = await client.get(identity_url, headers={"Authorization": request.headers.get("authorization", "")})
            if identity.status_code == 401 and identity.json().get("error") == "invalid_token":
                from urllib.parse import urlsplit, urlunsplit
                endpoint = urlsplit(identity_url)
                checked = await client.get(urlunsplit((endpoint.scheme, endpoint.netloc, "/v1000/user/check", "", "")), headers={"Authorization": request.headers.get("authorization", "")})
                checked.raise_for_status()
                envelope = checked.json()
                verified = envelope.get("data", {})
                if not (envelope.get("code") == 0 and verified.get("username") == "com.ictrek.v-scheduler" and verified.get("role_code") == "system_admin" and verified.get("enable") == 1 and verified.get("delete") == 0 and verified.get("id")):
                    raise HTTPException(403, "V-Scheduler application identity required")
                user = {"sub": verified["username"], "enable": verified["enable"]}
            else:
                identity.raise_for_status()
                user = identity.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(401, "VOS application identity required") from None
    if not isinstance(user, dict) or user.get("sub") != "com.ictrek.v-scheduler" or user.get("enable") != 1:
        raise HTTPException(403, "V-Scheduler application identity required")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 262144:
            raise HTTPException(413, "Binding too large")
    try:
        config = json.loads(body)
        if config.get("protocol_version") != 1 or type(config.get("binding_revision")) is not int or config["binding_revision"] < 1:
            raise ValueError()
        if config.get("app_id") != APP_ID or config.get("url") != URL or config.get("upstream_url") != UPSTREAM:
            raise ValueError()
        for field in ("token", "executor_token"):
            if not isinstance(config.get(field), str) or not 32 <= len(config[field]) <= 4096 or any(character.isspace() for character in config[field]):
                raise ValueError()
        if not isinstance(config.get("models"), dict) or not 1 <= len(config["models"]) <= 512:
            raise ValueError()
        if not isinstance(config.get("model_limits"), dict):
            raise ValueError()
        if config.get("execution_settings") != execution_settings():
            raise ValueError()
        for model in config["models"]:
            limits = config["model_limits"].get(model, {})
            if not isinstance(limits, dict) or any(type(limits.get(field)) is not int or limits[field] < 0 for field in ("width", "height", "steps", "batch_count", "video_frames", "prompt_characters", "negative_prompt_characters")):
                raise ValueError()
            from app.services.scheduler import RUNTIME_PARAMETER_FIELDS
            parameters = config.get("model_parameters", {}).get(model)
            if not isinstance(parameters, dict) or set(parameters) != set(RUNTIME_PARAMETER_FIELDS) | {"has_reference"}:
                raise ValueError()
        for field in ("models", "gateway_executors"):
            mapping = config.get(field, {})
            if not isinstance(mapping, dict) or len(mapping) > 512 or any(not isinstance(model, str) or not isinstance(executor, str) or not model or not executor for model, executor in mapping.items()):
                raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(422, "Invalid application binding") from None
    executors = await asyncio.to_thread(controller, config, "GET", "/executors")
    approved = {row["id"] for row in executors if row.get("app_id") == APP_ID and row.get("task_type") in {"image.generate", "video.generate"} and row.get("contract_version") == "1"}
    if any(executor not in approved for executor in config["models"].values()):
        raise HTTPException(422, "Executor not approved for this application")
    from app.services import scheduler
    # Unaccepted outbox entries may follow the new approved binding. Accepted
    # tasks and native executions retain their original identity until stopped.
    async with scheduler._submission_lock:
        with lock:
            from app.services.storage import load_job
            from app.config import settings
            pending = [load_job(path.parent.name, path.stem) for path in settings.jobs_dir.glob("*/*.json")]
            if any(not task.done() for task in scheduler._executions.values()) or any(job and job.metadata.get("scheduler_managed") and job.metadata.get("scheduler_task_id") and job.status not in {"succeeded", "failed"} for job in pending):
                raise HTTPException(409, "Binding waits for active execution")
            path = config_path()
            if path.exists():
                previous = read_config(for_rebinding=True)
                if previous.get("binding_revision", 0) >= config["binding_revision"]:
                    if previous != config:
                        raise HTTPException(409, "Binding revision conflict")
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
            with open(temporary, "x", opener=lambda filename, flags: os.open(filename, flags, 0o600)) as stream:
                json.dump(config, stream)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(path)
        settings.scheduler_url = config["url"]
        settings.scheduler_token = config["token"]
        settings.scheduler_executor_token = config["executor_token"]
        settings.scheduler_models = config["models"]
        settings.scheduler_model_limits = config["model_limits"]
        settings.scheduler_model_parameters = config["model_parameters"]
        settings.scheduler_config = config
    await scheduler.start()
    return {"configured": True, "binding_revision": config["binding_revision"]}
