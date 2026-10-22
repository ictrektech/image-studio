from __future__ import annotations

import asyncio
import base64
import logging
import mimetypes
import re
import shlex
import shutil
import subprocess
import sys
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

from app.config import settings
from app.models import GenerateRequest, JobRecord
from app.services.models import assert_model_hub_ready, get_model_def, model_path_for, runtime_paths_for
from app.services.storage import input_path, job_dir, load_job, save_job, user_dir
from app.services.v_router import fetch_v_router_generation_models
logger = logging.getLogger("image-studio.sd")


_semaphore = asyncio.Semaphore(settings.max_concurrency)
# Forwarding waits on a remote service; it must not occupy local compute slots.
_router_semaphore = asyncio.Semaphore(settings.max_concurrency)
_job_tasks: dict[tuple[str, str], asyncio.Task] = {}
_job_processes: dict[tuple[str, str], asyncio.subprocess.Process] = {}

# sd.cpp 旗标与 runtime 角色的对应关系
ROLE_FLAGS = {
    "vae": "--vae",
    "audio_vae": "--audio-vae",
    "clip_l": "--clip_l",
    "clip_g": "--clip_g",
    "t5xxl": "--t5xxl",
    "llm": "--llm",
    "llm_vision": "--llm_vision",
    "clip_vision": "--clip_vision",
    "embeddings_connectors": "--embeddings-connectors",
    "high_noise": "--high-noise-diffusion-model",
    "uncond": "--uncond-diffusion-model",
}

# 前端 sampler 选项 -> sd.cpp --sampling-method 值
SAMPLER_MAP = {
    "euler_a": "euler_a",
    "euler": "euler",
    "heun": "heun",
    "dpm++2m": "dpm++_2m",
    "dpm2": "dpm2",
    "dpm++2s_a": "dpm++2s_a",
    "dpm++2mv2": "dpm++2mv2",
    "ipndm": "ipndm",
    "ipndm_v": "ipndm_v",
    "lcm": "lcm",
    "ddim_trailing": "ddim_trailing",
    "tcd": "tcd",
    "res_multistep": "res_multistep",
    "res_2s": "res_2s",
    "er_sde": "er_sde",
    "euler_cfg_pp": "euler_cfg_pp",
    "euler_a_cfg_pp": "euler_a_cfg_pp",
    "euler_ge": "euler_ge",
    "dpm++2m_sde": "dpm++2m_sde",
    "dpm++2m_sde_bt": "dpm++2m_sde_bt",
    "lms": "lms",
}

SCHEDULERS = {
    "discrete", "karras", "exponential", "ays", "gits", "sgm_uniform", "simple",
    "smoothstep", "kl_optimal", "lcm", "bong_tangent", "ltx2", "logit_normal",
    "flux2", "flux", "beta", "normal",
}
RNGS = {"std_default", "cuda", "cpu"}
PREDICTIONS = {"eps", "v", "edm_v", "sd3_flow", "flux_flow", "sefi_flow"}
WEIGHT_TYPES = {"f32", "f16", "q4_0", "q4_1", "q5_0", "q5_1", "q8_0", "q2_K", "q3_K", "q4_K"}
CACHE_MODES = {"easycache", "ucache", "dbcache", "taylorseer", "cache-dit", "spectrum"}
MEMORY_ERROR_MARKERS = (
    "failed to allocate",
    "out of memory",
    "cuda error",
    "alloc compute buffer failed",
    "vae decode compute failed",
    "ggml_gallocr_reserve_n_impl",
)
_PERCENT_RE = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d+)?)\s*%")
_STEP_RE = re.compile(r"\b(?:step|steps|sampling|sample|denoise|denoising)\D{0,32}(\d+)\s*/\s*(\d+)", re.IGNORECASE)
_FRAME_RE = re.compile(r"\b(?:frame|frames|video)\D{0,32}(\d+)\s*/\s*(\d+)", re.IGNORECASE)


async def create_job(user_key: str, request: GenerateRequest, access_token: str = "") -> JobRecord:
    if request.model_key.startswith("v-router/"):
        return await create_v_router_job(user_key, request, access_token)
    runtime = get_model_def(request.model_key, request.model_variant)["runtime"]
    video_mode = runtime.get("mode") == "video"
    defaults = runtime.get("defaults") or {}
    parameters = runtime.get("parameters") or {}
    # API callers and the model picker use the same family/profile defaults.
    # Preserve explicit values, including values equal to the request schema defaults.
    request = request.model_copy(update={
        field: defaults[field]
        for field in ("width", "height", "steps", "cfg_scale", "sampler", "vae_tile_size")
        if field not in request.model_fields_set and field in defaults
    })
    await assert_model_hub_ready(request.model_key, request.model_variant)
    model_path = model_path_for(request.model_key, request.model_variant)
    now = datetime.now(timezone.utc)
    supports_reference = parameters.get("reference_image", False)
    effective_video_frames = request.video_frames or int(defaults.get("video_frames", 0) or 0)
    if video_mode and effective_video_frames <= 1:
        # sd-cli 以 --video-frames > 1 区分视频生成，缺省时强制使用家族默认
        effective_video_frames = int(defaults.get("video_frames", 33) or 33)
    job = JobRecord(
        job_id=f"job_{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}",
        user_key=user_key,
        status="queued",
        prompt=request.prompt,
        negative_prompt=request.negative_prompt if parameters.get("negative_prompt", runtime.get("negative", True)) else "",
        model_key=request.model_key,
        model_variant=request.model_variant,
        model_path=str(model_path),
        width=request.width,
        height=request.height,
        steps=request.steps,
        cfg_scale=request.cfg_scale if parameters.get("cfg_scale", True) else float(defaults.get("cfg_scale", 1.0) or 1.0),
        strength=request.strength if parameters.get("strength", False) else 0,
        sampler=_string_choice(request.sampler, SAMPLER_MAP, str(defaults.get("sampler", "euler"))),
        seed=request.seed,
        batch_count=request.batch_count if parameters.get("batch_count", True) else 1,
        scheduler=_runtime_string(request.scheduler, defaults, parameters, "scheduler", SCHEDULERS),
        clip_skip=_runtime_int(request.clip_skip, defaults, parameters, "clip_skip", -1),
        guidance=_runtime_float(request.guidance, defaults, parameters, "guidance", 0.0),
        img_cfg_scale=_runtime_float(request.img_cfg_scale, defaults, parameters, "img_cfg_scale", 0.0),
        eta=_runtime_float(request.eta, defaults, parameters, "eta", 0.0),
        flow_shift=_runtime_float(request.flow_shift, defaults, parameters, "flow_shift", 0.0),
        high_noise_steps=_runtime_int(request.high_noise_steps, defaults, parameters, "high_noise_steps", 0),
        high_noise_cfg_scale=_runtime_float(request.high_noise_cfg_scale, defaults, parameters, "high_noise_cfg_scale", 0.0),
        high_noise_sampler=_runtime_string(request.high_noise_sampler, defaults, parameters, "high_noise_sampler", SAMPLER_MAP),
        slg_scale=_runtime_float(request.slg_scale, defaults, parameters, "slg_scale", 0.0),
        skip_layer_start=_runtime_float(request.skip_layer_start, defaults, parameters, "skip_layer_start", 0.01),
        skip_layer_end=_runtime_float(request.skip_layer_end, defaults, parameters, "skip_layer_end", 0.2),
        rng=_runtime_string(request.rng, defaults, parameters, "rng", RNGS),
        sampler_rng=_runtime_string(request.sampler_rng, defaults, parameters, "sampler_rng", RNGS),
        prediction=_runtime_string(request.prediction, defaults, parameters, "prediction", PREDICTIONS),
        weight_type=_runtime_string(request.weight_type, defaults, parameters, "weight_type", WEIGHT_TYPES),
        tensor_type_rules=request.tensor_type_rules.strip() if parameters.get("tensor_type_rules", True) else "",
        cache_mode=_runtime_string(request.cache_mode, defaults, parameters, "cache_mode", CACHE_MODES),
        cache_option=request.cache_option.strip() if parameters.get("cache_option", True) else "",
        qwen_image_layers=_runtime_int(request.qwen_image_layers, defaults, parameters, "qwen_image_layers", 0),
        hires=bool(request.hires) if parameters.get("hires", False) else False,
        hires_scale=_runtime_float(request.hires_scale, defaults, parameters, "hires_scale", 2.0),
        hires_width=_runtime_int(request.hires_width, defaults, parameters, "hires_width", 0),
        hires_height=_runtime_int(request.hires_height, defaults, parameters, "hires_height", 0),
        hires_steps=_runtime_int(request.hires_steps, defaults, parameters, "hires_steps", 0),
        hires_denoising_strength=_runtime_float(request.hires_denoising_strength, defaults, parameters, "hires_denoising_strength", 0.7),
        video_frames=effective_video_frames if parameters.get("video_frames", False) else 0,
        fps=(request.fps or int(defaults.get("fps", 0) or 0)) if parameters.get("fps", False) else 0,
        vae_tiling=_runtime_bool(request.vae_tiling, defaults, parameters, "vae_tiling", False),
        vae_tile_size=(request.vae_tile_size.strip() or str(defaults.get("vae_tile_size", ""))) if parameters.get("vae_tile_size", True) else "",
        vae_tile_overlap=_runtime_float(request.vae_tile_overlap, defaults, parameters, "vae_tile_overlap", 0.5),
        temporal_tiling=_runtime_bool(request.temporal_tiling, defaults, parameters, "temporal_tiling", False),
        temporal_tile_frames=_runtime_int(request.temporal_tile_frames, defaults, parameters, "temporal_tile_frames", 4),
        temporal_tile_overlap=_runtime_int(request.temporal_tile_overlap, defaults, parameters, "temporal_tile_overlap", 1),
        max_vram=_runtime_float(request.max_vram, defaults, parameters, "max_vram", 0.0),
        stream_layers=_runtime_bool(request.stream_layers, defaults, parameters, "stream_layers", False),
        auto_fit=_runtime_bool(request.auto_fit, defaults, parameters, "auto_fit", False),
        clip_on_cpu=_runtime_bool(request.clip_on_cpu, defaults, parameters, "clip_on_cpu", False),
        offload_to_cpu=_runtime_bool(request.offload_to_cpu, defaults, parameters, "offload_to_cpu", False),
        vae_cpu_fallback=_runtime_bool(request.vae_cpu_fallback, defaults, parameters, "vae_cpu_fallback", False),
        backend=request.backend.strip() if parameters.get("backend", True) else "",
        params_backend=request.params_backend.strip() if parameters.get("params_backend", True) else "",
        metadata={
            "scheduling": request.scheduling.model_dump() if request.scheduling else {},
            "init_job_id": request.init_job_id if supports_reference else "",
            "init_filename": request.init_filename if supports_reference else "",
            "init_input_id": request.init_input_id if supports_reference else "",
        },
        created_at=now,
        updated_at=now,
    )
    if settings.scheduler_url or settings.scheduler_required:
        from app.services.scheduler import prepare
        await prepare(job, operator_authorization=("Bearer " + access_token) if access_token else "")
        return job
    save_job(job)
    task_key = (job.user_key, job.job_id)
    task = asyncio.create_task(run_job(job))
    _job_tasks[task_key] = task
    task.add_done_callback(lambda _: _job_tasks.pop(task_key, None))
    return job


async def create_v_router_job(user_key: str, request: GenerateRequest, access_token: str = "") -> JobRecord:
    qualified = request.model_key.removeprefix("v-router/")
    rows = await fetch_v_router_generation_models(access_token)
    model = next((row for row in rows if row.get("model_id") == qualified), None)
    if not model:
        raise KeyError(request.model_key)
    endpoints = [str(e) for e in (model.get("v_router") or {}).get("endpoints") or []]
    video_mode = "videos/generations" in endpoints and "images/generations" not in endpoints and "images/edits" not in endpoints
    now = datetime.now(timezone.utc)
    job = JobRecord(
        job_id=f"job_{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}",
        user_key=user_key,
        status="queued",
        prompt=request.prompt,
        negative_prompt=request.negative_prompt,
        model_key=request.model_key,
        model_variant="",
        model_path=str(model.get("resolved_path") or model.get("access_path") or settings.v_router_api_url),
        width=request.width,
        height=request.height,
        steps=request.steps,
        cfg_scale=request.cfg_scale,
        strength=request.strength,
        sampler=request.sampler,
        seed=request.seed,
        batch_count=1 if video_mode else request.batch_count,
        video_frames=request.video_frames if video_mode else 0,
        fps=request.fps if video_mode else 0,
        metadata={
            "init_job_id": request.init_job_id,
            "init_filename": request.init_filename,
            "init_input_id": request.init_input_id,
            "v_router_model": qualified,
            "v_router_endpoints": endpoints,
        },
        created_at=now,
        updated_at=now,
    )
    save_job(job)
    task_key = (job.user_key, job.job_id)
    task = asyncio.create_task(run_v_router_job(job, access_token))
    _job_tasks[task_key] = task
    task.add_done_callback(lambda _: _job_tasks.pop(task_key, None))
    return job


async def cancel_job(user_key: str, job_id: str, local_only: bool = False) -> bool:
    if not local_only:
        item = load_job(user_key, job_id)
        if item and item.metadata.get("scheduler_managed"):
            from app.services.scheduler import request_cancel
            return await request_cancel(user_key, job_id)
    task_key = (user_key, job_id)
    cancelled = False
    task = _job_tasks.get(task_key)
    if task and not task.done():
        task.cancel()
        cancelled = True
        try:
            await task
        except asyncio.CancelledError:
            pass
    process = _job_processes.get(task_key)
    if process and process.returncode is None:
        await _terminate_process(process)
        cancelled = True
    return cancelled


async def run_job(job: JobRecord) -> None:
    try:
        async with _semaphore:
            if load_job(job.user_key, job.job_id) is None:
                return
            job.status = "running"
            job.progress = 0.1
            save_job(job)
            video_mode = get_model_def(job.model_key, job.model_variant)["runtime"].get("mode") == "video"
            output_dir = job_dir(job.user_key, job.job_id)
            has_bin = bool(shutil.which(settings.sd_cpp_bin))
            if not has_bin and not settings.mock_when_runtime_missing:
                raise RuntimeError(f"sd.cpp binary not found: {settings.sd_cpp_bin}")

            async def run_once(output: Path, seed_offset: int = 0, progress_base: float = 0.1, progress_span: float = 0.87) -> None:
                if has_bin:
                    await run_sd_cpp(job, output, seed_offset=seed_offset, progress_base=progress_base, progress_span=progress_span)
                else:
                    await asyncio.to_thread(write_mock_svg_as_png_named, job, output)

            if video_mode:
                # 视频任务固定单输出；batch/strength 等不适用的参数已在装配时忽略
                output = output_dir / "output.webm"
                try:
                    await run_once(output)
                except RuntimeError as exc:
                    if not job.vae_cpu_fallback or not _is_memory_error(str(exc)):
                        raise
                    job.error = "CUDA/VAE 显存不足，正在切换到 CPU VAE 低显存重试"
                    job.progress = 0.12
                    save_job(job)
                    await run_sd_cpp(job, output, low_memory_retry=True, progress_base=0.12, progress_span=0.85)
                await asyncio.to_thread(_ensure_browser_playable_video, output)
                job.outputs = [output.name]
            else:
                names = (
                    ["output.png"]
                    if job.batch_count <= 1
                    else [f"output_{i:02d}.png" for i in range(1, job.batch_count + 1)]
                )
                for i, name in enumerate(names):
                    if load_job(job.user_key, job.job_id) is None:
                        return
                    progress_base = 0.1 + 0.9 * i / len(names)
                    progress_span = 0.9 / len(names)
                    await run_once(output_dir / name, i, progress_base=progress_base, progress_span=progress_span * 0.95)
                    job.outputs = [*job.outputs, name]
                    job.progress = 0.1 + 0.9 * (i + 1) / len(names)
                    save_job(job)
            job.progress = 1
            job.status = "succeeded"
    except asyncio.CancelledError:
        return
    except Exception as exc:
        if load_job(job.user_key, job.job_id) is None:
            return
        job.status = "failed"
        job.error = str(exc)
    if load_job(job.user_key, job.job_id) is not None:
        save_job(job)


async def run_v_router_job(job: JobRecord, access_token: str = "") -> None:
    try:
        async with _router_semaphore:
            if load_job(job.user_key, job.job_id) is None:
                return
            job.status = "running"
            job.progress = 0.1
            save_job(job)
            endpoint = _v_router_endpoint_for_job(job)
            response = await _call_v_router_generation(job, endpoint, access_token)
            output_dir = job_dir(job.user_key, job.job_id)
            outputs = await _save_v_router_outputs(job, response, output_dir, access_token)
            if not outputs:
                raise RuntimeError(f"V-Router response did not include downloadable output: {response}")
            job.outputs = outputs
            job.progress = 1
            job.status = "succeeded"
    except asyncio.CancelledError:
        return
    except Exception as exc:
        if load_job(job.user_key, job.job_id) is None:
            return
        job.status = "failed"
        job.error = str(exc)
    if load_job(job.user_key, job.job_id) is not None:
        save_job(job)


def _v_router_endpoint_for_job(job: JobRecord) -> str:
    endpoints = {str(e).strip().lower().lstrip("/").removeprefix("v1/") for e in job.metadata.get("v_router_endpoints") or []}
    has_init = bool(job.metadata.get("init_input_id") or (job.metadata.get("init_job_id") and job.metadata.get("init_filename")))
    if has_init and "images/edits" in endpoints:
        return "images/edits"
    if "videos/generations" in endpoints and "images/generations" not in endpoints:
        return "videos/generations"
    if "images/generations" in endpoints:
        return "images/generations"
    if "videos/generations" in endpoints:
        return "videos/generations"
    raise RuntimeError("V-Router model does not declare image/video generation endpoints")


async def _call_v_router_generation(job: JobRecord, endpoint: str, access_token: str) -> dict:
    headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}
    url = f"{job.model_path.rstrip('/')}/v1/{endpoint}"
    model = str(job.metadata.get("v_router_model") or "").strip()
    payload = {
        "model": model,
        "prompt": job.prompt,
        "negative_prompt": job.negative_prompt,
        "size": f"{job.width}x{job.height}",
        "width": job.width,
        "height": job.height,
        "steps": job.steps,
        "cfg_scale": job.cfg_scale,
        "strength": job.strength,
        "seed": job.seed,
    }
    if endpoint == "videos/generations":
        payload.update({"video_frames": job.video_frames, "fps": job.fps})
    else:
        payload["n"] = max(1, job.batch_count)
    timeout = settings.video_timeout_seconds if endpoint == "videos/generations" else settings.default_timeout_seconds
    async with httpx.AsyncClient(timeout=timeout) as client:
        if endpoint == "images/edits":
            init = init_image_path(job)
            if not init:
                raise RuntimeError("image edit requires a source image")
            content_type = mimetypes.guess_type(init.name)[0] or "application/octet-stream"
            with init.open("rb") as f:
                files = {"image": (init.name, f, content_type)}
                data = {k: str(v) for k, v in payload.items() if v is not None}
                resp = await client.post(url, headers=headers, data=data, files=files)
        else:
            resp = await client.post(url, headers={**headers, "Content-Type": "application/json"}, json=payload)
        text = resp.text
        if resp.status_code < 200 or resp.status_code >= 300:
            raise RuntimeError(text or f"V-Router status {resp.status_code}")
        try:
            return resp.json()
        except ValueError as exc:
            raise RuntimeError("V-Router returned non-JSON generation response") from exc


async def _save_v_router_outputs(job: JobRecord, response: dict, output_dir: Path, access_token: str) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    items: list[dict] = []
    raw_data = response.get("data")
    if isinstance(raw_data, list):
        items.extend(item for item in raw_data if isinstance(item, dict))
    for key in ("output", "outputs", "videos", "images"):
        value = response.get(key)
        if isinstance(value, list):
            items.extend({"url": item} if isinstance(item, str) else item for item in value if isinstance(item, (str, dict)))
        elif isinstance(value, str):
            items.append({"url": value})
    for key in ("url", "video_url", "image_url", "b64_json"):
        if isinstance(response.get(key), str):
            items.append({key: response[key]})

    outputs: list[str] = []
    for idx, item in enumerate(items, start=1):
        name = await _save_v_router_item(job, item, output_dir, idx, access_token)
        if name:
            outputs.append(name)
            job.outputs = outputs
            job.progress = min(0.95, 0.1 + 0.8 * len(outputs) / max(len(items), 1))
            save_job(job)
    return outputs


async def _save_v_router_item(job: JobRecord, item: dict, output_dir: Path, index: int, access_token: str) -> str:
    if isinstance(item.get("b64_json"), str):
        data = base64.b64decode(item["b64_json"])
        ext = ".webm" if data[:4] == b"\x1a\x45\xdf\xa3" else ".png"
        name = f"output_{index:02d}{ext}" if index > 1 else f"output{ext}"
        (output_dir / name).write_bytes(data)
        return name
    raw_url = item.get("url") or item.get("video_url") or item.get("image_url")
    if not isinstance(raw_url, str) or not raw_url:
        return ""
    url = urljoin(job.model_path.rstrip("/") + "/", raw_url)
    origin = urlsplit(job.model_path)
    target = urlsplit(url)
    same_origin = (origin.scheme, origin.hostname, origin.port) == (target.scheme, target.hostname, target.port)
    headers = {"Authorization": f"Bearer {access_token}"} if access_token and same_origin else {}
    async with httpx.AsyncClient(timeout=settings.video_timeout_seconds, follow_redirects=True) as client:
        for attempt in range(3):
            try:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                break
            except httpx.HTTPStatusError as exc:
                if attempt == 2 or exc.response.status_code not in {404, 408, 429} and exc.response.status_code < 500:
                    raise
            except httpx.TransportError:
                if attempt == 2:
                    raise
            # Retry only the existing result download, never the paid generation.
            await asyncio.sleep(2 * (attempt + 1))
        data = resp.content
        content_type = resp.headers.get("Content-Type", "")
    ext = _extension_for_output(raw_url, content_type, data)
    name = f"output_{index:02d}{ext}" if index > 1 else f"output{ext}"
    (output_dir / name).write_bytes(data)
    return name


def _extension_for_output(url: str, content_type: str, data: bytes) -> str:
    path_ext = Path(url.split("?", 1)[0]).suffix.lower()
    if path_ext in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm", ".mov"}:
        return path_ext
    if "webm" in content_type or data[:4] == b"\x1a\x45\xdf\xa3":
        return ".webm"
    if "mp4" in content_type:
        return ".mp4"
    if "jpeg" in content_type:
        return ".jpg"
    if "webp" in content_type:
        return ".webp"
    return ".png"


def build_sd_args(job: JobRecord, output: Path, seed_offset: int = 0, low_memory_retry: bool = False) -> list[str]:
    """按模型家族的 runtime 规格装配 sd-cli 参数。"""
    item = get_model_def(job.model_key, job.model_variant)
    runtime = item["runtime"]
    video_mode = runtime.get("mode") == "video"
    defaults = runtime.get("defaults") or {}
    parameters = runtime.get("parameters") or {}
    role_paths = runtime_paths_for(job.model_key, job.model_variant)

    args = [settings.sd_cpp_bin]
    if video_mode:
        args.extend(["-M", "vid_gen"])
    args.extend([
        runtime.get("model_flag", "-m"),
        job.model_path,
    ])
    for role, flag in ROLE_FLAGS.items():
        if role in role_paths:
            args.extend([flag, str(role_paths[role])])

    args.extend(["-p", job.prompt])
    args.extend(["-o", str(output)])
    args.extend(["--width", str(job.width)])
    args.extend(["--height", str(job.height)])
    args.extend(["--steps", str(job.steps)])
    cfg_scale = job.cfg_scale if parameters.get("cfg_scale", True) else defaults.get("cfg_scale", 1.0)
    args.extend(["--cfg-scale", str(cfg_scale)])
    args.extend(["--sampling-method", SAMPLER_MAP.get(job.sampler, job.sampler)])
    _append_common_generation_args(args, job, parameters)
    if video_mode:
        if job.video_frames > 1:
            args.extend(["--video-frames", str(job.video_frames)])
        if job.fps > 0:
            args.extend(["--fps", str(job.fps)])
    init_image = init_image_path(job) if parameters.get("reference_image", False) else None
    if init_image:
        ref_flag = runtime.get("ref_flag", "-i")
        args.extend([ref_flag, str(init_image)])
        # 视频家族的 -i 是首帧参考，不使用 --strength
        if ref_flag == "-i" and not video_mode:
            args.extend(["--strength", str(job.strength)])

    if job.negative_prompt and parameters.get("negative_prompt", runtime.get("negative", True)):
        args.extend(["-n", job.negative_prompt])
    if job.seed >= 0:
        # batch 时固定 seed 逐张 +i，保持可复现的同时避免完全相同的图
        args.extend(["--seed", str(job.seed + seed_offset)])
    args.extend(runtime.get("extra_args") or [])
    _append_runtime_memory_args(args, job, parameters)
    if low_memory_retry:
        _append_unique(args, "--vae-tiling")
        _append_assignment(args, "--backend", "vae=cpu")
    if settings.sd_cpp_extra_args:
        args.extend(shlex.split(settings.sd_cpp_extra_args))
    return args


async def run_sd_cpp(
    job: JobRecord,
    output: Path,
    seed_offset: int = 0,
    low_memory_retry: bool = False,
    progress_base: float = 0.1,
    progress_span: float = 0.87,
) -> None:
    args = build_sd_args(job, output, seed_offset=seed_offset, low_memory_retry=low_memory_retry)
    logger.info("sd-cli 启动 (job=%s run=%s): %s", job.job_id, seed_offset, shlex.join(args))
    video_mode = get_model_def(job.model_key, job.model_variant)["runtime"].get("mode") == "video"
    timeout = settings.video_timeout_seconds if video_mode else settings.default_timeout_seconds
    task_key = (job.user_key, job.job_id)
    lease_path = job.metadata.get("_scheduler_lease_path")
    if lease_path:
        args = [sys.executable, "-m", "app.services.scheduler_process", lease_path, *args]
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _job_processes[task_key] = process
    output_tail: deque[str] = deque(maxlen=80)
    stdout_task = asyncio.create_task(_consume_sd_cli_stream(process.stdout, job, output_tail, progress_base, progress_span))
    stderr_task = asyncio.create_task(_consume_sd_cli_stream(process.stderr, job, output_tail, progress_base, progress_span))
    heartbeat_task = asyncio.create_task(_estimate_sd_cli_progress(job, progress_base, progress_span, timeout))
    try:
        await asyncio.wait_for(process.wait(), timeout=timeout)
        await asyncio.gather(stdout_task, stderr_task)
    except asyncio.CancelledError:
        await _terminate_process(process)
        stdout_task.cancel()
        stderr_task.cancel()
        heartbeat_task.cancel()
        await asyncio.gather(stdout_task, stderr_task, heartbeat_task, return_exceptions=True)
        raise
    except asyncio.TimeoutError as exc:
        await _terminate_process(process)
        stdout_task.cancel()
        stderr_task.cancel()
        heartbeat_task.cancel()
        await asyncio.gather(stdout_task, stderr_task, heartbeat_task, return_exceptions=True)
        raise RuntimeError(f"sd-cli 超时（{timeout}s）") from exc
    finally:
        heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)
        _job_processes.pop(task_key, None)
    if process.returncode != 0:
        detail = " | ".join(line.strip() for line in list(output_tail)[-6:] if line.strip())
        logger.error("sd-cli 失败 (job=%s code=%s): %s", job.job_id, process.returncode, shlex.join(args))
        raise RuntimeError(f"sd-cli 退出码 {process.returncode}: {detail or '无错误输出'}")


async def _consume_sd_cli_stream(
    stream: asyncio.StreamReader | None,
    job: JobRecord,
    output_tail: deque[str],
    progress_base: float,
    progress_span: float,
) -> None:
    if stream is None:
        return
    pending = ""
    while True:
        chunk = await stream.read(4096)
        if not chunk:
            break
        text = chunk.decode(errors="replace")
        pending = _consume_sd_cli_text(job, output_tail, pending + text, progress_base, progress_span)
    if pending.strip():
        _consume_sd_cli_text(job, output_tail, pending + "\n", progress_base, progress_span)


def _consume_sd_cli_text(
    job: JobRecord,
    output_tail: deque[str],
    text: str,
    progress_base: float,
    progress_span: float,
) -> str:
    normalized = text.replace("\r", "\n")
    parts = normalized.split("\n")
    if not normalized.endswith("\n"):
        pending = parts.pop()
    else:
        pending = ""
    for part in parts:
        line = part.strip()
        if not line:
            continue
        output_tail.append(line)
        progress = _sd_cli_progress_from_text(line)
        if progress is not None:
            _apply_sd_cli_progress(job, progress, progress_base, progress_span)
    return pending


def _sd_cli_progress_from_text(text: str) -> float | None:
    for pattern in (_FRAME_RE, _STEP_RE):
        match = pattern.search(text)
        if match:
            done = int(match.group(1))
            total = int(match.group(2))
            if total > 0:
                return max(0.0, min(done / total, 1.0))
    percent_matches = _PERCENT_RE.findall(text)
    for raw in reversed(percent_matches):
        value = float(raw)
        if 0 <= value <= 100:
            return value / 100
    return None


def _apply_sd_cli_progress(job: JobRecord, raw_progress: float, progress_base: float, progress_span: float) -> None:
    current = load_job(job.user_key, job.job_id)
    if current is None or current.status != "running":
        return
    mapped = progress_base + max(0.0, min(raw_progress, 1.0)) * progress_span
    mapped = max(progress_base, min(mapped, 0.98))
    if mapped <= current.progress + 0.005:
        return
    current.progress = mapped
    current.updated_at = datetime.now(timezone.utc)
    save_job(current)
    job.progress = current.progress


async def _estimate_sd_cli_progress(job: JobRecord, progress_base: float, progress_span: float, timeout: int) -> None:
    estimated_seconds = _estimated_sd_cli_seconds(job)
    started = asyncio.get_running_loop().time()
    while True:
        await asyncio.sleep(5)
        elapsed = asyncio.get_running_loop().time() - started
        raw_progress = min(elapsed / estimated_seconds, 0.92)
        _apply_sd_cli_progress(job, raw_progress, progress_base, progress_span)
        if elapsed >= timeout:
            return


def _estimated_sd_cli_seconds(job: JobRecord) -> float:
    megapixels = max(job.width * job.height / (512 * 512), 0.25)
    if job.video_frames > 1:
        work_units = max(job.steps, 1) * max(job.video_frames, 1) * megapixels
        return max(90.0, min(work_units * 0.32, settings.video_timeout_seconds * 0.9))
    work_units = max(job.steps, 1) * max(job.batch_count, 1) * megapixels
    return max(15.0, min(work_units * 0.18, settings.default_timeout_seconds * 0.9))


def _ensure_browser_playable_video(output: Path) -> None:
    if output.suffix.lower() != ".webm":
        return
    with output.open("rb") as f:
        data = f.read(65536)
    header = data[:4]
    if header == b"\x1a\x45\xdf\xa3":
        doc_type = _webm_doc_type(data[:4096])
        if doc_type == b"webm":
            return
        if doc_type == b"matroska" and _has_webm_video_codec(data[:65536]):
            _remux_matroska_to_webm(output)
            _assert_webm_doc_type(output)
            return
        actual = doc_type.decode("ascii", errors="replace") if doc_type else "unknown"
        raise RuntimeError(f"sd-cli produced {actual} data for output.webm; expected WebM")
    if header == b"RIFF":
        raise RuntimeError("sd-cli produced AVI data for output.webm; rebuild sd.cpp with SD_WEBM=ON")
    raise RuntimeError("sd-cli produced an invalid output.webm file")


def _assert_webm_doc_type(output: Path) -> None:
    with output.open("rb") as f:
        doc_type = _webm_doc_type(f.read(4096))
    if doc_type != b"webm":
        actual = doc_type.decode("ascii", errors="replace") if doc_type else "unknown"
        raise RuntimeError(f"video remux did not produce WebM output; got {actual}")


def _webm_doc_type(data: bytes) -> bytes | None:
    marker = data.find(b"\x42\x82")
    if marker < 0 or marker + 3 >= len(data):
        return None
    size_byte = data[marker + 2]
    if not size_byte & 0x80:
        return None
    size = size_byte & 0x7F
    start = marker + 3
    end = start + size
    if size <= 0 or end > len(data):
        return None
    return data[start:end]


def _has_webm_video_codec(data: bytes) -> bool:
    return any(codec in data for codec in (b"V_VP8", b"V_VP9", b"V_AV1"))


def _remux_matroska_to_webm(output: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("sd-cli produced Matroska data for output.webm and ffmpeg is not available for remuxing")
    tmp = output.with_name(f"{output.stem}.remux{output.suffix}")
    try:
        subprocess.run(
            [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(output), "-c", "copy", "-f", "webm", str(tmp)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        tmp.replace(output)
    except subprocess.CalledProcessError as exc:
        message = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(f"failed to remux Matroska output to WebM: {message or exc}") from exc
    finally:
        tmp.unlink(missing_ok=True)


def _runtime_string(
    value: str,
    defaults: dict,
    parameters: dict,
    key: str,
    choices: set[str] | dict[str, str],
) -> str:
    if not parameters.get(key, True):
        return ""
    raw = (value or str(defaults.get(key, "") or "")).strip()
    return _string_choice(raw, choices, "")


def _string_choice(value: str, choices: set[str] | dict[str, str], fallback: str) -> str:
    raw = (value or "").strip()
    return raw if raw in choices else fallback


def _runtime_int(value: int, defaults: dict, parameters: dict, key: str, fallback: int) -> int:
    if not parameters.get(key, True):
        return fallback
    default = defaults.get(key, fallback)
    return value if value not in (0, -1) else int(default or fallback)


def _runtime_float(value: float, defaults: dict, parameters: dict, key: str, fallback: float) -> float:
    if not parameters.get(key, True):
        return fallback
    default = defaults.get(key, fallback)
    return value if value != 0 else float(default or fallback)


def _runtime_bool(value: bool | None, defaults: dict, parameters: dict, key: str, fallback: bool) -> bool:
    if not parameters.get(key, True):
        return False
    if value is not None:
        return bool(value)
    return bool(defaults.get(key, fallback))


def _append_common_generation_args(args: list[str], job: JobRecord, parameters: dict) -> None:
    if job.scheduler and parameters.get("scheduler", True):
        args.extend(["--scheduler", job.scheduler])
    if job.clip_skip > 0 and parameters.get("clip_skip", True):
        args.extend(["--clip-skip", str(job.clip_skip)])
    if job.guidance > 0 and parameters.get("guidance", True):
        args.extend(["--guidance", str(job.guidance)])
    if job.img_cfg_scale > 0 and parameters.get("img_cfg_scale", False):
        args.extend(["--img-cfg-scale", str(job.img_cfg_scale)])
    if job.eta > 0 and parameters.get("eta", True):
        args.extend(["--eta", str(job.eta)])
    if job.flow_shift > 0 and parameters.get("flow_shift", True):
        args.extend(["--flow-shift", str(job.flow_shift)])
    if job.high_noise_steps > 0 and parameters.get("high_noise_steps", False):
        args.extend(["--high-noise-steps", str(job.high_noise_steps)])
    if job.high_noise_cfg_scale > 0 and parameters.get("high_noise_cfg_scale", False):
        args.extend(["--high-noise-cfg-scale", str(job.high_noise_cfg_scale)])
    if job.high_noise_sampler and parameters.get("high_noise_sampler", False):
        args.extend(["--high-noise-sampling-method", SAMPLER_MAP.get(job.high_noise_sampler, job.high_noise_sampler)])
    if job.slg_scale > 0 and parameters.get("slg_scale", True):
        args.extend(["--slg-scale", str(job.slg_scale)])
        args.extend(["--skip-layer-start", str(job.skip_layer_start)])
        args.extend(["--skip-layer-end", str(job.skip_layer_end)])
    if job.rng and parameters.get("rng", True):
        args.extend(["--rng", job.rng])
    if job.sampler_rng and parameters.get("sampler_rng", True):
        args.extend(["--sampler-rng", job.sampler_rng])
    if job.prediction and parameters.get("prediction", True):
        args.extend(["--prediction", job.prediction])
    if job.weight_type and parameters.get("weight_type", True):
        args.extend(["--type", job.weight_type])
    if job.tensor_type_rules and parameters.get("tensor_type_rules", True):
        args.extend(["--tensor-type-rules", job.tensor_type_rules])
    if job.cache_mode and parameters.get("cache_mode", True):
        args.extend(["--cache-mode", job.cache_mode])
    if job.cache_option and parameters.get("cache_option", True):
        args.extend(["--cache-option", job.cache_option])
    if job.qwen_image_layers > 0 and parameters.get("qwen_image_layers", False):
        args.extend(["--qwen-image-layers", str(job.qwen_image_layers)])
    if job.hires and parameters.get("hires", False):
        args.append("--hires")
        args.extend(["--hires-scale", str(job.hires_scale)])
        if job.hires_width > 0:
            args.extend(["--hires-width", str(job.hires_width)])
        if job.hires_height > 0:
            args.extend(["--hires-height", str(job.hires_height)])
        if job.hires_steps > 0:
            args.extend(["--hires-steps", str(job.hires_steps)])
        args.extend(["--hires-denoising-strength", str(job.hires_denoising_strength)])


def _append_runtime_memory_args(args: list[str], job: JobRecord, parameters: dict) -> None:
    if job.vae_tiling and parameters.get("vae_tiling", True):
        _append_unique(args, "--vae-tiling")
        if job.vae_tile_size:
            args.extend(["--vae-tile-size", job.vae_tile_size])
        if job.vae_tile_overlap != 0.5:
            args.extend(["--vae-tile-overlap", str(job.vae_tile_overlap)])
    if job.temporal_tiling and parameters.get("temporal_tiling", False):
        _append_unique(args, "--temporal-tiling")
        tiling_args = f"temporal_tile_frames={job.temporal_tile_frames},temporal_tile_overlap={job.temporal_tile_overlap}"
        args.extend(["--extra-tiling-args", tiling_args])
    if job.max_vram != 0 and parameters.get("max_vram", True):
        args.extend(["--max-vram", str(job.max_vram)])
    if job.stream_layers and job.max_vram != 0 and parameters.get("stream_layers", True):
        _append_unique(args, "--stream-layers")
    if job.auto_fit and parameters.get("auto_fit", True):
        _append_unique(args, "--auto-fit")
    if job.clip_on_cpu and parameters.get("clip_on_cpu", True):
        _append_unique(args, "--clip-on-cpu")
    if job.offload_to_cpu and parameters.get("offload_to_cpu", True):
        _append_unique(args, "--offload-to-cpu")
    if job.backend and parameters.get("backend", True):
        _append_assignment(args, "--backend", job.backend)
    if job.params_backend and parameters.get("params_backend", True):
        _append_assignment(args, "--params-backend", job.params_backend)


def _append_unique(args: list[str], flag: str) -> None:
    if flag not in args:
        args.append(flag)


def _append_assignment(args: list[str], flag: str, value: str) -> None:
    if flag in args:
        idx = args.index(flag)
        args[idx + 1] = f"{args[idx + 1]},{value}"
        return
    args.extend([flag, value])


def _is_memory_error(message: str) -> bool:
    lower = message.lower()
    return any(marker in lower for marker in MEMORY_ERROR_MARKERS)


async def _terminate_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        process.terminate()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except asyncio.TimeoutError:
        try:
            process.kill()
        except ProcessLookupError:
            return
        await process.wait()


def init_image_path(job: JobRecord) -> Path | None:
    init_input_id = str(job.metadata.get("init_input_id") or "").strip()
    if init_input_id:
        path = input_path(job.user_key, init_input_id)
        if not path:
            raise FileNotFoundError(f"init image not found: {init_input_id}")
        return path
    init_job_id = str(job.metadata.get("init_job_id") or "").strip()
    init_filename = str(job.metadata.get("init_filename") or "").strip()
    if not init_job_id or not init_filename:
        return None
    if "/" in init_filename or "\\" in init_filename or init_filename.startswith("."):
        raise ValueError("invalid init image filename")
    path = user_dir(job.user_key) / init_job_id / init_filename
    if not path.exists():
        raise FileNotFoundError(f"init image not found: {init_job_id}/{init_filename}")
    return path


def write_mock_svg_as_png_named(job: JobRecord, output: Path) -> None:
    # Development fallback: keep API/UI behavior usable before sd.cpp is added to the image.
    svg = output.with_suffix(".svg")
    text = job.prompt[:120].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    svg.write_text(
        f"""<svg xmlns="http://www.w3.org/2000/svg" width="{job.width}" height="{job.height}" viewBox="0 0 {job.width} {job.height}">
<defs><linearGradient id="g" x2="1" y2="1"><stop stop-color="#dbeafe"/><stop offset="1" stop-color="#f8fafc"/></linearGradient></defs>
<rect width="100%" height="100%" fill="url(#g)"/>
<rect x="32" y="32" width="{job.width - 64}" height="{job.height - 64}" rx="18" fill="rgba(255,255,255,0.78)" stroke="#94a3b8"/>
<text x="56" y="88" font-family="Arial" font-size="28" font-weight="700" fill="#0f172a">Image Studio Preview</text>
<text x="56" y="132" font-family="Arial" font-size="18" fill="#334155">{text}</text>
</svg>""",
        encoding="utf-8",
    )
    output.write_bytes(svg.read_bytes())
