"""Administrator controls for Image Studio compute deployments."""

from __future__ import annotations

import asyncio
import json
import os
import re
from hashlib import sha256
from pathlib import Path
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.config import settings
from app.services.scheduler import RUNTIME_PARAMETER_FIELDS, _atomic
from app.services.weight_sync import deployment_client, deployment_request, sync_weights
from app.worker import WORKER_MODE, WORKER_PROFILES

APP_ID = "com.ictrek.image-studio"
_DEPLOYMENT_ID = r"^[0-9a-f]{32}$"
_pending: dict[str, asyncio.Task] = {}
DeploymentState = Literal["pending", "running", "failed", "stopping", "deleting", "stopped", "removed", "cleanup_failed"]


async def require_compute_admin(authorization: str = Header(default="")) -> None:
    pieces = authorization.split()
    if len(pieces) != 2 or pieces[0].lower() != "bearer":
        raise HTTPException(401, "COMPUTE_VOS_LOGIN_REQUIRED")
    try:
        async with httpx.AsyncClient(timeout=5, follow_redirects=False) as client:
            response = await client.get(settings.vos_userinfo_url, headers={"Authorization": authorization})
            payload = response.json()
    except (ValueError, httpx.HTTPError):
        raise HTTPException(503, "COMPUTE_VOS_AUTH_UNAVAILABLE") from None
    if not response.is_success or not isinstance(payload, dict) or payload.get("code") in (10001, 10099):
        raise HTTPException(401, "COMPUTE_VOS_LOGIN_REQUIRED")
    identity = payload.get("data", payload)
    if (
        payload.get("code", 0) != 0
        or not isinstance(identity, dict)
        or identity.get("role_code") != "system_admin"
        or identity.get("enable") not in (1, True)
        or identity.get("delete") in (1, True)
        or not any(isinstance(identity.get(field), str) and identity[field] for field in ("id", "sub"))
    ):
        raise HTTPException(403, "COMPUTE_ADMIN_REQUIRED")


router = APIRouter(prefix="/api/v1/compute", dependencies=[Depends(require_compute_admin)])
placement_router = APIRouter(prefix="/api/v1/compute")


class DeployRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["ssh", "cluster"]
    node_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,96}$")
    request_key: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,96}$")


class PrepareModelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_key: str = Field(pattern=r"^[a-z0-9_.-]{1,96}$")
    model_variant: str = Field(default="", pattern=r"^[a-z0-9_.-]{0,96}$")


class ComputeTarget(BaseModel):
    kind: Literal["ssh", "cluster"]
    node_id: str
    name: str
    profile: str
    runtime_profile: str
    image: str


class DeployReceipt(BaseModel):
    id: str
    state: DeploymentState


class ComputeDeployment(DeployReceipt):
    target_kind: Literal["ssh", "cluster"]
    target_id: str
    node_name: str | None = Field(default=None, description="Deployment target display name when available. 可发现时返回部署节点显示名称。")
    profile: str
    image: str
    last_error: str | None


class Preparation(BaseModel):
    deployment_id: str
    model_id: str
    state: Literal["transferring", "interrupted", "registered", "failed"]
    received_bytes: int
    total_bytes: int
    executor_id: str | None
    node_id: str | None
    error: str | None
    weight_source: Literal["copy", "shared"] | None = None


class ComputeOverview(BaseModel):
    targets: list[ComputeTarget]
    deployments: list[ComputeDeployment]
    preparations: list[Preparation]


class ModelPlacement(BaseModel):
    deployment_id: str
    model_id: str
    node_id: str = Field(description="The V-Scheduler node assigned to this deployment. 部署绑定的 V-Scheduler 节点 ID。")
    node_name: str | None = Field(default=None, description="Display name of the deployment target, when discoverable. 可发现时返回部署节点显示名称。")
    executor_id: str = Field(description="The registered V-Scheduler executor. 已注册的 V-Scheduler 执行器 ID。")
    profile: str
    runtime_parameters: dict[str, str | int | float | bool]
    has_reference: bool


def _catalog() -> dict:
    try:
        catalog = json.loads(os.environ.get("IMAGE_STUDIO_BACKEND_IMAGES", "{}"))
        if not isinstance(catalog, dict) or any(
            not isinstance(entry, dict)
            or not isinstance(entry.get("profile"), str)
            or entry["profile"] not in WORKER_PROFILES
            or not isinstance(entry.get("image"), str)
            for entry in catalog.values()
        ):
            raise ValueError()
        return catalog
    except ValueError:
        raise HTTPException(503, "COMPUTE_IMAGE_CATALOG_INVALID") from None


def _node_name(node: dict) -> str | None:
    return next((value for key in ("name", "hostname") if isinstance(value := node.get(key), str)
                 and value.strip() and value != node["id"]), None)


def _node_names(inventory: dict) -> dict[tuple[str, str], str | None]:
    return {(kind, node["id"]): _node_name(node) for kind, field in (("ssh", "items"), ("cluster", "cluster_nodes"))
            for node in inventory.get(field, [])}


async def _targets(client: httpx.AsyncClient, inventory: dict | None = None) -> list[dict]:
    catalog = _catalog()
    if not catalog:
        return []
    if inventory is None:
        inventory = await deployment_request(client, "GET", "managed-nodes")
    grant = await deployment_request(client, "GET", f"backend-deployment-access/{APP_ID}")
    authorized = {(row["kind"], row["id"], row["profile"]) for row in grant["targets"]}
    targets = []
    for kind, rows in (("ssh", inventory["items"]), ("cluster", inventory.get("cluster_nodes", []))):
        for node in rows:
            profile = node.get("profile")
            image_profile = "jetson-thor" if profile == "dgx-spark" and profile not in catalog else profile
            entry = catalog.get(image_profile)
            if not entry or (kind, node["id"], profile) not in authorized:
                continue
            image = entry["image"]
            if image.rsplit(":", 1)[0] not in grant["repositories"]:
                continue
            targets.append({
                "kind": kind, "node_id": node["id"], "name": _node_name(node) or profile,
                "profile": profile, "runtime_profile": entry["profile"], "image": image,
            })
    return targets


def _preparations() -> Path:
    return settings.data_dir / "compute" / "preparations"


def _preparation_path(deployment_id: str, model_id: str) -> Path:
    key = sha256(json.dumps([deployment_id, model_id]).encode()).hexdigest()
    return _preparations() / f"{key}.json"


def registered_compute_model(deployment_id: str, model_id: str) -> dict:
    path = _preparation_path(deployment_id, model_id).with_suffix(".registered")
    try:
        record = json.loads(path.read_text())
    except (OSError, ValueError):
        raise HTTPException(409, "COMPUTE_MODEL_NOT_REGISTERED") from None
    if record.get("state") != "registered":
        raise HTTPException(409, "COMPUTE_MODEL_NOT_REGISTERED")
    return record


@placement_router.get("/placements", response_model=list[ModelPlacement])
async def compute_placements(authorization: str = Header(default="")):
    from app.services.session import verify_vos_identity

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or not await verify_vos_identity(parts[1]):
        raise HTTPException(401, "COMPUTE_VOS_LOGIN_REQUIRED")
    if not _catalog():
        return []
    registrations = [json.loads(file.read_text()) for file in _preparations().glob("*.registered")]
    if not registrations:
        return []
    async with deployment_client() as client:
        data = await deployment_request(client, "GET", "backend-deployments")
        try:
            inventory = await deployment_request(client, "GET", "managed-nodes")
        except HTTPException:
            inventory = {}
    running = {row["id"]: row for row in data["items"] if row["app_id"] == APP_ID and row["state"] == "running" and row.get("endpoint")}
    names = _node_names(inventory)
    return [
        {
            "deployment_id": row["deployment_id"], "model_id": row["model_id"], "profile": row["runtime_profile"],
            "node_id": row["node_id"], "executor_id": row["executor_id"],
            "node_name": names.get((running[row["deployment_id"]].get("target_kind"), running[row["deployment_id"]].get("target_id"))),
            "runtime_parameters": {key: value for key, value in row["model_parameters"].items() if key != "has_reference"},
            "has_reference": row["model_parameters"].get("has_reference") is True,
        }
        for row in registrations if row["deployment_id"] in running
    ]


@router.get("", response_model=ComputeOverview)
async def compute_overview():
    if not _catalog():
        return {"targets": [], "deployments": [], "preparations": []}
    async with deployment_client() as client:
        inventory = await deployment_request(client, "GET", "managed-nodes")
        targets = await _targets(client, inventory)
        result = await deployment_request(client, "GET", "backend-deployments")
    names = _node_names(inventory)
    fields = ("id", "target_kind", "target_id", "profile", "image", "state", "last_error")
    deployments = [
        {**{key: row.get(key) for key in fields}, "node_name": names.get((row["target_kind"], row["target_id"]))}
        for row in result["items"] if row.get("app_id") == APP_ID and row.get("config", {}).get("mode") == WORKER_MODE
    ]
    visible = {row["id"] for row in deployments}
    preparations = []
    for path in _preparations().glob("*.json"):
        record = json.loads(path.read_text())
        if record["deployment_id"] in visible:
            if record["state"] == "transferring" and path.stem not in _pending:
                record.update(state="interrupted", error="COMPUTE_TRANSFER_INTERRUPTED")
            preparations.append(record)
    return {"targets": targets, "deployments": deployments, "preparations": preparations}


@router.post("/deployments", response_model=DeployReceipt)
async def deploy_backend(payload: DeployRequest):
    async with deployment_client() as client:
        target = next((
            row for row in await _targets(client)
            if (row["kind"], row["node_id"]) == (payload.kind, payload.node_id)
        ), None)
        if target is None:
            raise HTTPException(403, "COMPUTE_TARGET_NOT_APPROVED")
        record = await deployment_request(client, "POST", "backend-deployments", json={
            "request_key": payload.request_key,
            "target": {"kind": payload.kind, "id": payload.node_id, "profile": target["profile"]},
            "image": target["image"],
            "container_port": 5000,
            "config": {"mode": WORKER_MODE, "profile": target["runtime_profile"]},
        })
    return {"id": record["id"], "state": record["state"]}


async def _prepare(path: Path, record: dict, model: PrepareModelRequest) -> None:
    def progress(received: int, total: int) -> None:
        # Write the durable UI receipt only when the percentage changes.
        previous = record["received_bytes"] * 100 // max(1, record["total_bytes"])
        current = received * 100 // max(1, total)
        initial = record["total_bytes"] == 0
        record.update(received_bytes=received, total_bytes=total)
        if initial or current != previous:
            _atomic(path, record)

    try:
        result = await sync_weights(record["deployment_id"], model.model_key, model.model_variant, progress)
        if (
            not isinstance(result.get("model_limits"), dict)
            or not isinstance(result.get("model_parameters"), dict)
            or set(result["model_parameters"]) != set(RUNTIME_PARAMETER_FIELDS) | {"has_reference"}
        ):
            raise HTTPException(503, "COMPUTE_CALIBRATION_RECEIPT_INVALID")
        record.update(
            state="registered", executor_id=result["executor_id"], node_id=result["node_id"],
            transfer_id=result["transfer_id"], model_limits=result["model_limits"],
            model_parameters=result["model_parameters"], weight_source=result["weight_source"],
        )
        _atomic(path.with_suffix(".registered"), record)
    except HTTPException as exc:
        record.update(state="failed", error=exc.detail)
    except (KeyError, ValueError, OSError):
        record.update(state="failed", error="COMPUTE_TRANSFER_FAILED")
    finally:
        try:
            _atomic(path, record)
        finally:
            _pending.pop(path.stem, None)


@router.post("/deployments/{deployment_id}/models", status_code=202, response_model=Preparation)
async def prepare_backend_model(deployment_id: str, payload: PrepareModelRequest):
    if not re.fullmatch(_DEPLOYMENT_ID, deployment_id):
        raise HTTPException(422, "INVALID_BACKEND_DEPLOYMENT_ID")
    async with deployment_client() as client:
        deployment = await deployment_request(client, "GET", f"backend-deployments/{deployment_id}")
    if deployment.get("app_id") != APP_ID or deployment.get("config", {}).get("mode") != WORKER_MODE:
        raise HTTPException(404, "COMPUTE_DEPLOYMENT_NOT_FOUND")
    if deployment["state"] != "running" or not deployment.get("endpoint"):
        raise HTTPException(409, "COMPUTE_BACKEND_NOT_RUNNING")
    model_id = f"{payload.model_key}@{payload.model_variant}" if payload.model_variant else payload.model_key
    path = _preparation_path(deployment_id, model_id)
    key = path.stem
    if key in _pending:
        return json.loads(path.read_text())
    record = {
        "deployment_id": deployment_id, "model_id": model_id, "state": "transferring",
        "received_bytes": 0, "total_bytes": 0, "executor_id": None, "node_id": None, "error": None,
        "runtime_profile": deployment["config"]["profile"],
    }
    _atomic(path, record)
    _pending[key] = asyncio.create_task(_prepare(path, record, payload))
    return record
