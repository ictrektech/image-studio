from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers.api import router
from app.services.storage import ensure_storage

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


@app.get("/health")
async def health():
    return {"status": "ok", "app": settings.app_id, "version": settings.app_version}

