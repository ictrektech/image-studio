from __future__ import annotations

import asyncio
import shlex
import shutil
import subprocess
import uuid
from datetime import datetime
from pathlib import Path

from app.config import settings
from app.models import GenerateRequest, JobRecord
from app.services.models import assert_model_hub_ready, get_model_def, model_path_for, runtime_paths_for
from app.services.storage import input_path, job_dir, save_job, user_dir

_semaphore = asyncio.Semaphore(settings.max_concurrency)

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
}


async def create_job(user_key: str, request: GenerateRequest) -> JobRecord:
    runtime = get_model_def(request.model_key)["runtime"]
    video_mode = runtime.get("mode") == "video"
    defaults = runtime.get("defaults") or {}
    await assert_model_hub_ready(request.model_key)
    model_path = model_path_for(request.model_key)
    now = datetime.utcnow()
    job = JobRecord(
        job_id=f"job_{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}",
        user_key=user_key,
        status="queued",
        prompt=request.prompt,
        negative_prompt=request.negative_prompt,
        model_key=request.model_key,
        model_path=str(model_path),
        width=request.width,
        height=request.height,
        steps=request.steps,
        cfg_scale=request.cfg_scale,
        strength=request.strength,
        sampler=request.sampler,
        seed=request.seed,
        batch_count=request.batch_count,
        video_frames=request.video_frames or int(defaults.get("video_frames", 0) or 0),
        fps=request.fps or int(defaults.get("fps", 0) or 0),
        metadata={
            "init_job_id": request.init_job_id,
            "init_filename": request.init_filename,
            "init_input_id": request.init_input_id,
        },
        created_at=now,
        updated_at=now,
    )
    if video_mode and job.video_frames <= 1:
        # sd-cli 以 --video-frames > 1 区分视频生成，缺省时强制使用家族默认
        job.video_frames = int(defaults.get("video_frames", 33) or 33)
    save_job(job)
    asyncio.create_task(run_job(job))
    return job


async def run_job(job: JobRecord) -> None:
    async with _semaphore:
        job.status = "running"
        job.progress = 0.1
        save_job(job)
        try:
            video_mode = get_model_def(job.model_key)["runtime"].get("mode") == "video"
            output_dir = job_dir(job.user_key, job.job_id)
            has_bin = bool(shutil.which(settings.sd_cpp_bin))
            if not has_bin and not settings.mock_when_runtime_missing:
                raise RuntimeError(f"sd.cpp binary not found: {settings.sd_cpp_bin}")

            def run_once(output: Path, seed_offset: int = 0) -> None:
                if has_bin:
                    run_sd_cpp(job, output, seed_offset=seed_offset)
                else:
                    write_mock_svg_as_png_named(job, output)

            if video_mode:
                # 视频任务固定单输出；batch/strength 等不适用的参数已在装配时忽略
                output = output_dir / "output.mp4"
                await asyncio.to_thread(run_once, output)
                job.outputs = [output.name]
            else:
                names = (
                    ["output.png"]
                    if job.batch_count <= 1
                    else [f"output_{i:02d}.png" for i in range(1, job.batch_count + 1)]
                )
                for i, name in enumerate(names):
                    await asyncio.to_thread(run_once, output_dir / name, i)
                    job.outputs = [*job.outputs, name]
                    job.progress = 0.1 + 0.9 * (i + 1) / len(names)
                    save_job(job)
            job.progress = 1
            job.status = "succeeded"
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)
        save_job(job)


def build_sd_args(job: JobRecord, output: Path, seed_offset: int = 0) -> list[str]:
    """按模型家族的 runtime 规格装配 sd-cli 参数。"""
    item = get_model_def(job.model_key)
    runtime = item["runtime"]
    video_mode = runtime.get("mode") == "video"
    role_paths = runtime_paths_for(job.model_key)

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
    args.extend(["--cfg-scale", str(job.cfg_scale)])
    args.extend(["--sampling-method", SAMPLER_MAP.get(job.sampler, job.sampler)])
    if video_mode:
        if job.video_frames > 1:
            args.extend(["--video-frames", str(job.video_frames)])
        if job.fps > 0:
            args.extend(["--fps", str(job.fps)])

    init_image = init_image_path(job)
    if init_image:
        ref_flag = runtime.get("ref_flag", "-i")
        args.extend([ref_flag, str(init_image)])
        # 视频家族的 -i 是首帧参考，不使用 --strength
        if ref_flag == "-i" and not video_mode:
            args.extend(["--strength", str(job.strength)])

    if job.negative_prompt and runtime.get("negative", True):
        args.extend(["-n", job.negative_prompt])
    if job.seed >= 0:
        # batch 时固定 seed 逐张 +i，保持可复现的同时避免完全相同的图
        args.extend(["--seed", str(job.seed + seed_offset)])
    args.extend(runtime.get("extra_args") or [])
    if settings.sd_cpp_extra_args:
        args.extend(shlex.split(settings.sd_cpp_extra_args))
    return args


def run_sd_cpp(job: JobRecord, output: Path, seed_offset: int = 0) -> None:
    args = build_sd_args(job, output, seed_offset=seed_offset)
    video_mode = get_model_def(job.model_key)["runtime"].get("mode") == "video"
    timeout = settings.video_timeout_seconds if video_mode else settings.default_timeout_seconds
    result = subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        stderr_tail = (result.stderr or "").strip().splitlines()[-6:]
        detail = " | ".join(line.strip() for line in stderr_tail if line.strip())
        raise RuntimeError(f"sd-cli 退出码 {result.returncode}: {detail or '无错误输出'}")


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
