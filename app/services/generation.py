from __future__ import annotations

import asyncio
import shlex
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.models import GenerateRequest, JobRecord
from app.services.models import assert_model_hub_ready, get_model_def, model_path_for, runtime_paths_for
from app.services.storage import input_path, job_dir, load_job, save_job, user_dir

_semaphore = asyncio.Semaphore(settings.max_concurrency)
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
}


async def create_job(user_key: str, request: GenerateRequest) -> JobRecord:
    runtime = get_model_def(request.model_key)["runtime"]
    video_mode = runtime.get("mode") == "video"
    defaults = runtime.get("defaults") or {}
    parameters = runtime.get("parameters") or {}
    await assert_model_hub_ready(request.model_key)
    model_path = model_path_for(request.model_key)
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
        model_path=str(model_path),
        width=request.width,
        height=request.height,
        steps=request.steps,
        cfg_scale=request.cfg_scale if parameters.get("cfg_scale", True) else float(defaults.get("cfg_scale", 1.0) or 1.0),
        strength=request.strength if parameters.get("strength", False) else 0,
        sampler=request.sampler,
        seed=request.seed,
        batch_count=request.batch_count if parameters.get("batch_count", True) else 1,
        video_frames=effective_video_frames if parameters.get("video_frames", False) else 0,
        fps=(request.fps or int(defaults.get("fps", 0) or 0)) if parameters.get("fps", False) else 0,
        metadata={
            "init_job_id": request.init_job_id if supports_reference else "",
            "init_filename": request.init_filename if supports_reference else "",
            "init_input_id": request.init_input_id if supports_reference else "",
        },
        created_at=now,
        updated_at=now,
    )
    save_job(job)
    task_key = (job.user_key, job.job_id)
    task = asyncio.create_task(run_job(job))
    _job_tasks[task_key] = task
    task.add_done_callback(lambda _: _job_tasks.pop(task_key, None))
    return job


async def cancel_job(user_key: str, job_id: str) -> bool:
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
            video_mode = get_model_def(job.model_key)["runtime"].get("mode") == "video"
            output_dir = job_dir(job.user_key, job.job_id)
            has_bin = bool(shutil.which(settings.sd_cpp_bin))
            if not has_bin and not settings.mock_when_runtime_missing:
                raise RuntimeError(f"sd.cpp binary not found: {settings.sd_cpp_bin}")

            async def run_once(output: Path, seed_offset: int = 0) -> None:
                if has_bin:
                    await run_sd_cpp(job, output, seed_offset=seed_offset)
                else:
                    await asyncio.to_thread(write_mock_svg_as_png_named, job, output)

            if video_mode:
                # 视频任务固定单输出；batch/strength 等不适用的参数已在装配时忽略
                output = output_dir / "output.mp4"
                await run_once(output)
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
                    await run_once(output_dir / name, i)
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


def build_sd_args(job: JobRecord, output: Path, seed_offset: int = 0) -> list[str]:
    """按模型家族的 runtime 规格装配 sd-cli 参数。"""
    item = get_model_def(job.model_key)
    runtime = item["runtime"]
    video_mode = runtime.get("mode") == "video"
    defaults = runtime.get("defaults") or {}
    parameters = runtime.get("parameters") or {}
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
    cfg_scale = job.cfg_scale if parameters.get("cfg_scale", True) else defaults.get("cfg_scale", 1.0)
    args.extend(["--cfg-scale", str(cfg_scale)])
    args.extend(["--sampling-method", SAMPLER_MAP.get(job.sampler, job.sampler)])
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
    if settings.sd_cpp_extra_args:
        args.extend(shlex.split(settings.sd_cpp_extra_args))
    return args


async def run_sd_cpp(job: JobRecord, output: Path, seed_offset: int = 0) -> None:
    args = build_sd_args(job, output, seed_offset=seed_offset)
    video_mode = get_model_def(job.model_key)["runtime"].get("mode") == "video"
    timeout = settings.video_timeout_seconds if video_mode else settings.default_timeout_seconds
    task_key = (job.user_key, job.job_id)
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _job_processes[task_key] = process
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.CancelledError:
        await _terminate_process(process)
        raise
    except asyncio.TimeoutError as exc:
        await _terminate_process(process)
        raise RuntimeError(f"sd-cli 超时（{timeout}s）") from exc
    finally:
        _job_processes.pop(task_key, None)
    if process.returncode != 0:
        stderr_text = stderr.decode(errors="replace")
        stderr_tail = stderr_text.strip().splitlines()[-6:]
        detail = " | ".join(line.strip() for line in stderr_tail if line.strip())
        raise RuntimeError(f"sd-cli 退出码 {process.returncode}: {detail or '无错误输出'}")


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
