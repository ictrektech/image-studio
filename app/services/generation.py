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
from app.services.models import get_model_def, model_path_for, runtime_paths_for
from app.services.storage import input_path, job_dir, save_job, user_dir

_semaphore = asyncio.Semaphore(settings.max_concurrency)

# sd.cpp 旗标与 runtime 角色的对应关系
ROLE_FLAGS = {
    "vae": "--vae",
    "clip_l": "--clip_l",
    "clip_g": "--clip_g",
    "t5xxl": "--t5xxl",
    "llm": "--llm",
    "llm_vision": "--llm_vision",
    "clip_vision": "--clip_vision",
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
    if runtime.get("mode") == "video":
        raise ValueError("视频模型暂不支持网页生成，请先选择图像模型")
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
        metadata={
            "init_job_id": request.init_job_id,
            "init_filename": request.init_filename,
            "init_input_id": request.init_input_id,
        },
        created_at=now,
        updated_at=now,
    )
    save_job(job)
    asyncio.create_task(run_job(job))
    return job


async def run_job(job: JobRecord) -> None:
    async with _semaphore:
        job.status = "running"
        job.progress = 0.1
        save_job(job)
        try:
            output_dir = job_dir(job.user_key, job.job_id)
            output = output_dir / "output.png"
            if shutil.which(settings.sd_cpp_bin):
                await asyncio.to_thread(run_sd_cpp, job, output)
            elif settings.mock_when_runtime_missing:
                await asyncio.to_thread(write_mock_svg_as_png_named, job, output)
            else:
                raise RuntimeError(f"sd.cpp binary not found: {settings.sd_cpp_bin}")
            job.outputs = [output.name]
            job.progress = 1
            job.status = "succeeded"
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)
        save_job(job)


def build_sd_args(job: JobRecord, output: Path) -> list[str]:
    """按模型家族的 runtime 规格装配 sd-cli 参数。"""
    item = get_model_def(job.model_key)
    runtime = item["runtime"]
    role_paths = runtime_paths_for(job.model_key)

    args = [
        settings.sd_cpp_bin,
        runtime.get("model_flag", "-m"),
        job.model_path,
    ]
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

    init_image = init_image_path(job)
    if init_image:
        ref_flag = runtime.get("ref_flag", "-i")
        args.extend([ref_flag, str(init_image)])
        if ref_flag == "-i":
            args.extend(["--strength", str(job.strength)])

    if job.negative_prompt and runtime.get("negative", True):
        args.extend(["-n", job.negative_prompt])
    if job.seed >= 0:
        args.extend(["--seed", str(job.seed)])
    args.extend(runtime.get("extra_args") or [])
    if settings.sd_cpp_extra_args:
        args.extend(shlex.split(settings.sd_cpp_extra_args))
    return args


def run_sd_cpp(job: JobRecord, output: Path) -> None:
    args = build_sd_args(job, output)
    result = subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        timeout=settings.default_timeout_seconds,
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
