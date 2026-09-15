from __future__ import annotations

from typing import Any

import httpx

from app.config import settings


def model_capability_spec(capabilities: list[str]) -> dict[str, Any]:
    """Map Image Studio native caps to V-Router endpoint/capability metadata."""
    endpoints: list[str] = []
    caps: list[str] = []

    def add(endpoint: str, cap: str) -> None:
        if endpoint not in endpoints:
            endpoints.append(endpoint)
        if cap not in caps:
            caps.append(cap)

    normalized = {str(c).strip().lower() for c in capabilities}
    if normalized & {"txt2img", "text2image", "text_to_image", "image_generation"}:
        add("images/generations", "image_generation")
    if normalized & {"img2img", "image2image", "image_to_image", "edit", "image_edit"}:
        add("images/edits", "image_edit")
    if normalized & {"video", "txt2video", "text2video", "text_to_video", "img2video", "image2video", "image_to_video", "video_generation"}:
        add("videos/generations", "video_generation")
    return {"endpoints": endpoints, "capabilities": caps, "model_kind": "unknown"}


def model_metadata(model_key: str, capabilities: list[str], *, variant_id: str = "", status: str = "unknown") -> dict[str, Any]:
    spec = model_capability_spec(capabilities)
    model_id = model_key if not variant_id else f"{model_key}@{variant_id}"
    return {
        "model": model_id,
        "qualified": f"image-studio/{model_id}",
        "protocol": "image_studio",
        "status": status,
        **spec,
    }


def registration_payload(models: list[dict[str, Any]], *, ready_only: bool = True) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for model in models:
        base_meta = model.get("v_router") or {}
        if base_meta.get("protocol") != "image_studio":
            continue
        if base_meta.get("endpoints") and (not ready_only or base_meta.get("status") == "ready"):
            rows.append({
                "id": base_meta["model"],
                "endpoints": base_meta["endpoints"],
                "capabilities": base_meta["capabilities"],
                "model_kind": base_meta.get("model_kind", "unknown"),
            })
        for variant in model.get("variants") or []:
            meta = variant.get("v_router") or {}
            if meta.get("protocol") != "image_studio":
                continue
            if meta.get("endpoints") and (not ready_only or meta.get("status") == "ready"):
                rows.append({
                    "id": meta["model"],
                    "endpoints": meta["endpoints"],
                    "capabilities": meta["capabilities"],
                    "model_kind": meta.get("model_kind", "unknown"),
                })
    return {
        "service_id": "image-studio",
        "name": settings.service_name,
        "visibility": "public",
        "protocol": "image_studio",
        "base_url": settings.v_router_base_url,
        "model_kind": "unknown",
        "models": rows,
        "ttl_seconds": 90,
    }


def endpoint_capabilities(endpoints: list[str]) -> list[str]:
    caps: list[str] = []

    def add(cap: str) -> None:
        if cap not in caps:
            caps.append(cap)

    normalized = {str(e).strip().lower().lstrip('/').removeprefix('v1/') for e in endpoints}
    if 'images/generations' in normalized:
        add('txt2img')
    if 'images/edits' in normalized or 'images/variations' in normalized:
        add('img2img')
        add('edit')
    if 'videos/generations' in normalized:
        add('video')
    return caps


def endpoint_runtime(endpoints: list[str]) -> dict[str, Any]:
    normalized = {str(e).strip().lower().lstrip('/').removeprefix('v1/') for e in endpoints}
    video = 'videos/generations' in normalized and 'images/generations' not in normalized and 'images/edits' not in normalized
    return {
        'mode': 'video' if video else 'image',
        'defaults': {
            'width': 1024 if not video else 832,
            'height': 1024 if not video else 480,
            'steps': 30 if not video else 20,
            'cfg_scale': 7.0 if not video else 6.0,
            'sampler': 'euler_a' if not video else 'euler',
            'video_frames': 33 if video else 0,
            'fps': 24 if video else 0,
        },
        'parameters': {
            'reference_image': 'images/edits' in normalized or 'images/variations' in normalized,
            'strength': 'images/edits' in normalized,
            'batch_count': not video,
            'video_frames': video,
            'fps': video,
            'scheduler': False,
            'clip_skip': False,
            'guidance': False,
            'img_cfg_scale': False,
            'eta': False,
            'flow_shift': False,
            'high_noise_steps': False,
            'high_noise_cfg_scale': False,
            'high_noise_sampler': False,
            'slg_scale': False,
            'rng': False,
            'sampler_rng': False,
            'prediction': False,
            'weight_type': False,
            'tensor_type_rules': False,
            'cache_mode': False,
            'cache_option': False,
            'qwen_image_layers': False,
            'hires': False,
            'vae_tiling': False,
            'temporal_tiling': False,
            'max_vram': False,
            'stream_layers': False,
            'auto_fit': False,
            'clip_on_cpu': False,
            'offload_to_cpu': False,
            'vae_cpu_fallback': False,
            'backend': False,
            'params_backend': False,
        },
    }


def v_router_model_info(row: dict[str, Any]) -> dict[str, Any] | None:
    qualified = str(row.get('qualified') or row.get('id') or '').strip()
    if not qualified or qualified.startswith('image-studio/'):
        return None
    endpoints = [str(e) for e in row.get('endpoints') or []]
    caps = endpoint_capabilities(endpoints)
    if not caps:
        return None
    label = qualified.removeprefix('v-router/')
    return {
        'key': f'v-router/{qualified}',
        'name': label,
        'model_id': qualified,
        'source': 'v-router',
        'sources': [],
        'files': [],
        'family': 'V-Router',
        'capabilities': caps,
        'preferred': False,
        'params': str(row.get('upstream_name') or row.get('owned_by') or ''),
        'runtime': endpoint_runtime(endpoints),
        'description': f'V-Router model {qualified}',
        'expected_files': [],
        'variants': [],
        'access_path': settings.v_router_api_url,
        'resolved_path': settings.v_router_api_url,
        'status': 'ready',
        'size': None,
        'total_bytes': None,
        'v_router': {
            'model': qualified,
            'qualified': qualified,
            'protocol': 'v_router',
            'status': 'ready',
            'endpoints': endpoints,
            'capabilities': row.get('capabilities') or [],
            'model_kind': row.get('kind') or 'unknown',
        },
    }


async def fetch_v_router_generation_models(access_token: str = "") -> list[dict[str, Any]]:
    """Read V-Router model metadata for Image Studio's remote backend picker.

    Image Studio consumes V-Router models as a separate source and never feeds
    them into its own registration payload. `image-studio/` rows are filtered
    out here to prevent Image Studio -> V-Router -> Image Studio routing loops.
    """
    if not settings.v_router_api_url:
        return []
    headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}
    url = f"{settings.v_router_api_url}/api/v1/models"
    async with httpx.AsyncClient(timeout=8.0) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        rows = resp.json().get("models") or []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        info = v_router_model_info(row)
        if info:
            out.append(info)
    return out
