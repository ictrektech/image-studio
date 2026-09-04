from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers.api import router
from app.services.immich import start as start_immich_uploads, stop as stop_immich_uploads
from app.services.storage import ensure_storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = FastAPI(title="Image Studio", version=settings.app_version)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.on_event("startup")
async def startup() -> None:
    ensure_storage()
    await start_immich_uploads()


@app.on_event("shutdown")
async def shutdown() -> None:
    stop_immich_uploads()


@app.get("/health")
async def health():
    return {"status": "ok", "app": settings.app_id, "version": settings.app_version}

