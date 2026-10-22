from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from app.config import settings as app_settings
from app.models import GenerateRequest, ImmichStatusResponse
from app.services.generation import cancel_job, create_job
from app.services.immich import (
    ExchangeError,
    ImmichUploadError,
    cached_api_key,
    cancel_job_uploads,
    check_reachable,
    enqueue_job as enqueue_immich_job,
    ensure_api_key,
    last_error,
    retry_job as retry_immich_job,
    zero_touch_available,
)
from app.services.models import get_model, get_model_def, list_model_defs_with_hub_state, model_info, pull_model, stop_model, sync_model_hub
from app.services.v_router import registration_payload, v_router_connection_status
from app.services.templates import delete_template, default_template_id, list_templates, rename_template, save_template
from app.services.session import bearer_token, current_user_key
from app.services.storage import (
    delete_input,
    delete_job,
    input_path,
    job_dir,
    list_inputs,
    list_jobs,
    load_job,
    load_settings,
    save_input,
    save_settings,
)

router = APIRouter(prefix="/api/v1")


@router.get("/about")
async def about():
    return {
        "app_id": app_settings.app_id,
        "app_version": app_settings.app_version,
        "profile": app_settings.profile,
        "data_dir": str(app_settings.data_dir),
        "modelhub_root": str(app_settings.modelhub_root),
        "model_hub_api_url": app_settings.model_hub_api_url,
        "sd_cpp_bin": app_settings.sd_cpp_bin,
        "max_concurrency": app_settings.max_concurrency,
    }


@router.get("/templates")
async def templates_list():
    return {"templates": list_templates(), "default_template": default_template_id()}


@router.post("/templates")
async def templates_create(payload: dict):
    name = str(payload.get("name") or "")
    body = payload.get("payload")
    if not isinstance(body, dict) or not body:
        raise HTTPException(status_code=422, detail="payload 不能为空")
    return save_template(name, body)


@router.patch("/templates/{template_id}")
async def templates_rename(template_id: str, payload: dict):
    renamed = rename_template(template_id, str(payload.get("name") or ""))
    if not renamed:
        raise HTTPException(status_code=404, detail="模板不存在")
    return renamed


@router.delete("/templates/{template_id}")
async def templates_delete(template_id: str):
    if not delete_template(template_id):
        raise HTTPException(status_code=404, detail="模板不存在")
    return {"ok": True}


@router.get("/me")
async def me(request: Request):
    user_key = await current_user_key(request)
    return {"user_key": user_key, "authenticated": bool(bearer_token(request))}


@router.get("/settings")
async def settings(request: Request):
    return load_settings(await current_user_key(request))


@router.put("/settings")
async def update_settings(request: Request, payload: dict):
    return save_settings(await current_user_key(request), payload)


@router.get("/immich", response_model=ImmichStatusResponse)
async def immich_status(request: Request):
    """Immich 连通性状态（五态见 ImmichStatusResponse，不返回任何凭据）。"""
    if not zero_touch_available():
        return ImmichStatusResponse(state="disabled")
    reason = await check_reachable()
    if reason:
        return ImmichStatusResponse(state="unreachable", detail=reason)
    user_key = await current_user_key(request)
    if error := last_error(user_key):
        return ImmichStatusResponse(state="error", detail=error)
    if cached_api_key(user_key):
        return ImmichStatusResponse(state="connected")
    return ImmichStatusResponse(state="pending")


@router.post("/generate")
async def generate(request: Request, payload: GenerateRequest):
    user_key = await current_user_key(request)
    try:
        job = await create_job(user_key, payload, bearer_token(request))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=f"模型文件未就绪: {exc}")
    except KeyError:
        raise HTTPException(status_code=404, detail="model not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return job


@router.get("/jobs")
async def jobs(request: Request):
    return list_jobs(await current_user_key(request))


@router.post("/jobs/{job_id}/immich-upload", status_code=202)
async def upload_job_to_immich(request: Request, job_id: str, force: bool = False):
    user_key = await current_user_key(request)
    await _ensure_key(request, user_key)
    try:
        return await enqueue_immich_job(user_key, job_id, force=force)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ImmichUploadError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/jobs/{job_id}/immich-upload/retry", status_code=202)
async def retry_job_immich_upload(request: Request, job_id: str):
    user_key = await current_user_key(request)
    await _ensure_key(request, user_key)
    try:
        return await retry_immich_job(user_key, job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


async def _ensure_key(request: Request, user_key: str) -> None:
    """零接触：上传前用当前 VOS 令牌换取（或复用本进程缓存的）Immich Key。

    Key 只存在进程内存：首次上传或后端重启后需要用户在场（持有效令牌），
    失败即时反馈；成功后队列、重试、后台上传都直接用缓存。
    """
    if not zero_touch_available():
        raise HTTPException(status_code=409, detail="零接触免密互传未启用，无法上传到 Immich")
    try:
        await ensure_api_key(user_key, bearer_token(request))
    except ExchangeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/jobs/{job_id}")
async def job(request: Request, job_id: str):
    item = load_job(await current_user_key(request), job_id)
    if not item:
        raise HTTPException(status_code=404, detail="job not found")
    return item


@router.delete("/jobs/{job_id}")
async def delete_generation_job(request: Request, job_id: str):
    user_key = await current_user_key(request)
    await cancel_job(user_key, job_id)
    await cancel_job_uploads(user_key, job_id)
    deleted = delete_job(user_key, job_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="job not found")
    return {"deleted": True, "job_id": job_id}


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


@router.post("/jobs/{job_id}/photocraft")
async def photocraft_handoff(request: Request, job_id: str, payload: dict):
    from app.services.photocraft import issue
    # Use the same account/session ownership as generation and downloading;
    # reinterpreting the source token under another audience loses that owner.
    return issue(await current_user_key(request), job_id, str(payload.get("filename") or ""))


@router.get("/photocraft/handoffs/{ticket}/{filename}")
async def photocraft_output(ticket: str, filename: str):
    from app.services.photocraft import resolve
    return FileResponse(resolve(ticket, filename), headers={"Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer"})


@router.post("/inputs")
async def upload_input(request: Request, file: UploadFile = File(...)):
    """上传 img2img / edit 参考图（png/jpg/jpeg/webp，≤20MB），返回可引用的 input_id。"""
    user_key = await current_user_key(request)
    data = await file.read()
    try:
        return save_input(user_key, file.filename or "upload.png", data)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/inputs")
async def inputs(request: Request):
    return list_inputs(await current_user_key(request))


@router.get("/inputs/{input_id}")
async def input_file(request: Request, input_id: str):
    path = input_path(await current_user_key(request), input_id)
    if not path or not path.exists():
        raise HTTPException(status_code=404, detail="input not found")
    return FileResponse(path)


@router.delete("/inputs/{input_id}")
async def remove_input(request: Request, input_id: str):
    if not delete_input(await current_user_key(request), input_id):
        raise HTTPException(status_code=404, detail="input not found")
    return {"deleted": True, "input_id": input_id}


@router.get("/models")
async def models(request: Request):
    return await list_model_defs_with_hub_state(bearer_token(request))


@router.get("/v-router/registration")
async def v_router_registration(ready_only: bool = True):
    rows = [item.model_dump() for item in await list_model_defs_with_hub_state()]
    return registration_payload(rows, ready_only=ready_only)


@router.get("/v-router/status")
async def v_router_status(request: Request):
    return await v_router_connection_status(bearer_token(request))


@router.get("/models/{key}")
async def model(key: str, variant: str = ""):
    try:
        if variant:
            return model_info(get_model_def(key, variant))
        return get_model(key)
    except KeyError:
        raise HTTPException(status_code=404, detail="model not found")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/models/{key}/pull")
async def pull(key: str, force: bool = False, variant: str = ""):
    try:
        return await pull_model(key, force=force, variant_id=variant)
    except KeyError:
        raise HTTPException(status_code=404, detail="model not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/models/{key}/stop")
async def stop(key: str, variant: str = ""):
    try:
        return await stop_model(key, variant_id=variant)
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
