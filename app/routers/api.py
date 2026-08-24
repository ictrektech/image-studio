from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from app.config import settings
from app.models import GenerateRequest
from app.services.generation import create_job
from app.services.models import get_model, list_model_defs, pull_model, sync_model_hub
from app.services.session import current_user_key
from app.services.storage import job_dir, list_jobs, load_job, load_settings, save_settings

router = APIRouter(prefix="/api/v1")


@router.get("/about")
async def about():
    return {
        "app_id": settings.app_id,
        "app_version": settings.app_version,
        "profile": settings.profile,
        "data_dir": str(settings.data_dir),
        "modelhub_root": str(settings.modelhub_root),
        "model_hub_api_url": settings.model_hub_api_url,
        "sd_cpp_bin": settings.sd_cpp_bin,
        "max_concurrency": settings.max_concurrency,
    }


@router.get("/settings")
async def settings(request: Request):
    return load_settings(await current_user_key(request))


@router.put("/settings")
async def update_settings(request: Request, payload: dict):
    return save_settings(await current_user_key(request), payload)


@router.post("/generate")
async def generate(request: Request, payload: GenerateRequest):
    user_key = await current_user_key(request)
    try:
        job = await create_job(user_key, payload)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=f"模型文件未就绪: {exc}")
    return job


@router.get("/jobs")
async def jobs(request: Request):
    return list_jobs(await current_user_key(request))


@router.get("/jobs/{job_id}")
async def job(request: Request, job_id: str):
    item = load_job(await current_user_key(request), job_id)
    if not item:
        raise HTTPException(status_code=404, detail="job not found")
    return item


@router.get("/outputs")
async def outputs(request: Request):
    user_key = await current_user_key(request)
    result = []
    for item in list_jobs(user_key):
        for name in item.outputs:
            path = job_dir(user_key, item.job_id) / name
            result.append({
                "job_id": item.job_id,
                "filename": name,
                "url": f"/api/v1/outputs/{item.job_id}/{name}",
                "size": path.stat().st_size if path.exists() else 0,
                "created_at": item.created_at,
                "prompt": item.prompt,
            })
    return result


@router.get("/outputs/{job_id}/{filename}")
async def output_file(request: Request, job_id: str, filename: str):
    path = job_dir(await current_user_key(request), job_id) / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="output not found")
    return FileResponse(path)


@router.get("/models")
async def models():
    return list_model_defs()


@router.get("/models/{key}")
async def model(key: str):
    try:
        return get_model(key)
    except KeyError:
        raise HTTPException(status_code=404, detail="model not found")


@router.post("/models/{key}/pull")
async def pull(key: str):
    try:
        return await pull_model(key)
    except KeyError:
        raise HTTPException(status_code=404, detail="model not found")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/models/{key}/sync")
async def sync(key: str):
    try:
        get_model(key)
        return await sync_model_hub()
    except KeyError:
        raise HTTPException(status_code=404, detail="model not found")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
