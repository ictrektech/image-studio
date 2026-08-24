from __future__ import annotations

import os
from pathlib import Path


class Settings:
    app_id = "com.ictrek.image-studio"
    service_name = "Image Studio"
    app_version = os.getenv("IMAGE_STUDIO_APP_VERSION", "0.0.0")
    profile = os.getenv("IMAGE_STUDIO_PROFILE", "local")
    data_dir = Path(os.getenv("IMAGE_STUDIO_DATA_DIR", "/data")).resolve()
    modelhub_root = Path(os.getenv("MODEL_HUB_SHARED_MODELS_PATH", "/modelhub")).resolve()
    model_hub_api_url = os.getenv("MODEL_HUB_API_URL", "http://model-hub-backend:5005").rstrip("/")
    sd_cpp_bin = os.getenv("SD_CPP_BIN", "sd-cli")
    sd_cpp_extra_args = os.getenv("SD_CPP_EXTRA_ARGS", "")
    default_timeout_seconds = int(os.getenv("IMAGE_STUDIO_GENERATE_TIMEOUT_SECONDS", "900"))
    max_concurrency = int(os.getenv("IMAGE_STUDIO_MAX_CONCURRENCY", "1"))
    mock_when_runtime_missing = os.getenv("IMAGE_STUDIO_MOCK_WHEN_RUNTIME_MISSING", "true").lower() == "true"

    @property
    def sessions_dir(self) -> Path:
        return self.data_dir / "sessions"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"


settings = Settings()

