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
from app.services.models import model_path_for
from app.services.storage import job_dir, save_job

_semaphore = asyncio.Semaphore(settings.max_concurrency)


async def create_job(user_key: str, request: GenerateRequest) -> JobRecord:
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
        sampler=request.sampler,
        seed=request.seed,
        batch_count=request.batch_count,
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


def run_sd_cpp(job: JobRecord, output: Path) -> None:
    args = [
        settings.sd_cpp_bin,
        "-m",
        job.model_path,
        "-p",
        job.prompt,
        "-o",
        str(output),
        "--width",
        str(job.width),
        "--height",
        str(job.height),
        "--steps",
        str(job.steps),
        "--cfg-scale",
        str(job.cfg_scale),
        "--sampling-method",
        job.sampler,
    ]
    if job.negative_prompt:
        args.extend(["-n", job.negative_prompt])
    if job.seed >= 0:
        args.extend(["--seed", str(job.seed)])
    if settings.sd_cpp_extra_args:
        args.extend(shlex.split(settings.sd_cpp_extra_args))
    subprocess.run(args, check=True, timeout=settings.default_timeout_seconds)


def write_mock_svg_as_png_named(job: JobRecord, output: Path) -> None:
    # Development fallback: keep API/UI behavior usable before sd.cpp is added to the image.
    svg = output.with_suffix(".svg")
    text = job.prompt[:120].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    svg.write_text(
        f"""<svg xmlns="http://www.w3.org/2000/svg" width="{job.width}" height="{job.height}" viewBox="0 0 {job.width} {job.height}">
<defs><linearGradient id="g" x1="0" x2="1" y1="0" y2="1"><stop stop-color="#dbeafe"/><stop offset="1" stop-color="#f8fafc"/></linearGradient></defs>
<rect width="100%" height="100%" fill="url(#g)"/>
<rect x="32" y="32" width="{job.width - 64}" height="{job.height - 64}" rx="18" fill="rgba(255,255,255,0.78)" stroke="#94a3b8"/>
<text x="56" y="88" font-family="Arial" font-size="28" font-weight="700" fill="#0f172a">Image Studio Preview</text>
<text x="56" y="132" font-family="Arial" font-size="18" fill="#334155">{text}</text>
</svg>""",
        encoding="utf-8",
    )
    output.write_bytes(svg.read_bytes())

