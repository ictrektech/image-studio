from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from app.config import settings
from app.models import ModelInfo


MODEL_DEFS = [
    {
        "key": "sd15",
        "name": "Stable Diffusion v1.5 EMA",
        "model_id": "vivibit/stable-diffusion-v1-5",
        "source": "modelscope",
        "description": "SD 1.5 ema-only safetensors prepared for stable-diffusion.cpp.",
        "expected_files": ["v1-5-pruned-emaonly.safetensors", "v1-inference.yaml"],
        "relative_candidates": [
            "export/ms/vivibit/stable-diffusion-v1-5/current/v1-5-pruned-emaonly.safetensors",
            "modelscope/vivibit/stable-diffusion-v1-5/v1-5-pruned-emaonly.safetensors",
            "vivibit/stable-diffusion-v1-5/v1-5-pruned-emaonly.safetensors",
        ],
    }
]


def list_model_defs() -> list[ModelInfo]:
    return [model_info(item) for item in MODEL_DEFS]


def get_model(key: str) -> ModelInfo:
    for item in MODEL_DEFS:
        if item["key"] == key:
            return model_info(item)
    raise KeyError(key)


def model_info(item: dict[str, Any]) -> ModelInfo:
    resolved = None
    size = None
    for rel in item["relative_candidates"]:
        candidate = settings.modelhub_root / rel
        if candidate.exists():
            resolved = candidate
            size = candidate.stat().st_size
            break

    fallback = settings.modelhub_root / item["relative_candidates"][0]
    return ModelInfo(
        key=item["key"],
        name=item["name"],
        model_id=item["model_id"],
        source=item["source"],
        description=item["description"],
        expected_files=item["expected_files"],
        access_path=str(fallback),
        resolved_path=str(resolved) if resolved else None,
        status="ready" if resolved else "missing",
        size=size,
    )


async def pull_model(key: str) -> dict[str, Any]:
    info = get_model(key)
    payload = {"source": info.source, "model_id": info.model_id}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{settings.model_hub_api_url}/api/v1/models/pull", json=payload)
        resp.raise_for_status()
        return resp.json()


async def sync_model_hub() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{settings.model_hub_api_url}/api/v1/models/sync")
        resp.raise_for_status()
        return resp.json()


def model_path_for(key: str) -> Path:
    info = get_model(key)
    if not info.resolved_path:
        raise FileNotFoundError(info.access_path)
    return Path(info.resolved_path)

