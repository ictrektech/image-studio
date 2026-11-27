"""Private compute worker launched by a V-Scheduler backend deployment."""

from __future__ import annotations

import base64
import json
import os
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI

from app.config import settings
from app.services.models import get_model_def
from app.services.scheduler_binding import execution_settings
from app.services.weight_transfers import WeightTransfers, require_worker_channel, transfer_routes
from app.services.worker_execution import worker_execution_routes
from app.services.scheduler import stop

WORKER_MODE = "image-studio-worker-v1"
WORKER_PROFILES = {"amd", "amd-cuda", "arm", "arm-cuda", "l4t", "thor"}
SHARED_MODELS = Path("/modelhub-shared")


@asynccontextmanager
async def worker_lifespan(_app: FastAPI):
    try:
        yield
    finally:
        await stop()


def deployed_worker() -> FastAPI | None:
    encoded = os.environ.get("V_SCHEDULER_BACKEND_CONFIG_B64")
    if not encoded:
        return None
    config = json.loads(base64.b64decode(encoded, validate=True))
    if config.get("mode") != WORKER_MODE:
        return None
    profile = config.get("profile")
    if not isinstance(profile, str) or profile not in WORKER_PROFILES:
        raise ValueError("Invalid Image Studio worker profile")
    settings.profile = profile
    settings.sd_cpp_extra_args = "--threads 4"
    settings.mock_when_runtime_missing = False
    settings.scheduler_required = False
    settings.scheduler_executor_token = os.environ.get("V_SCHEDULER_BACKEND_CHANNEL_TOKEN", "")
    worker = FastAPI(
        title="Image Studio compute worker", docs_url=None, redoc_url=None, openapi_url=None,
        lifespan=worker_lifespan,
    )
    transfers = WeightTransfers(settings.data_dir / "weight-transfers", SHARED_MODELS)
    worker.include_router(transfer_routes(transfers))
    worker.include_router(worker_execution_routes(transfers))

    @worker.get("/scheduler/model-hub", dependencies=[Depends(require_worker_channel)])
    def model_hub():
        return {"state": "ready" if transfers.shared_available() else "unavailable"}

    @worker.get("/scheduler/capabilities", dependencies=[Depends(require_worker_channel)])
    def capabilities():
        models = []
        if shutil.which(settings.sd_cpp_bin):
            for model_id in transfers.verified_models():
                key, _, variant = model_id.partition("@")
                mode = get_model_def(key, variant)["runtime"].get("mode")
                models.append({"id": model_id, "task_type": "video.generate" if mode == "video" else "image.generate"})
        return {
            "protocol_version": 1,
            "weight_model_delete": True,
            "execution_settings": execution_settings(),
            "async_models": models,
            "preemption_modes": [],
        }

    @worker.get("/health")
    def health():
        return {"status": "ok", "mode": WORKER_MODE, "profile": profile}

    return worker
