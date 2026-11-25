from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from app.api_documentation import build_openapi

from app.config import settings
from app.routers.api import router
from app.routers.compute import placement_router, router as compute_router
from app.services.immich import start as start_immich_uploads, stop as stop_immich_uploads
from app.services.storage import ensure_storage
from app.services import scheduler
from app.services.scheduler_binding import router as scheduler_binding_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = FastAPI(title="Image Studio", version=settings.app_version, docs_url=None)
app.openapi = lambda: build_openapi(app)


@app.get("/docs", include_in_schema=False)
async def api_documentation():
    return get_swagger_ui_html(openapi_url="openapi.json", title="Image Studio API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
app.include_router(compute_router)
app.include_router(placement_router)
app.include_router(scheduler.router)
app.include_router(scheduler_binding_router)


@app.on_event("startup")
async def startup() -> None:
    ensure_storage()
    await scheduler.start()
    await start_immich_uploads()


@app.on_event("shutdown")
async def shutdown() -> None:
    stop_immich_uploads()
    await scheduler.stop()


@app.get("/health")
async def health():
    return {"status": "ok", "app": settings.app_id, "version": settings.app_version}


if os.getenv("V_SCHEDULER_BACKEND_CONFIG_B64"):
    from app.worker import deployed_worker

    worker = deployed_worker()
    if worker is not None:
        app = worker

