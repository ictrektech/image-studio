from __future__ import annotations

import os
import json
from pathlib import Path


class Settings:
    app_id = "com.ictrek.image-studio"
    service_name = "Image Studio"
    app_version = os.getenv("IMAGE_STUDIO_APP_VERSION", "0.0.0")
    profile = os.getenv("IMAGE_STUDIO_PROFILE", "local")
    data_dir = Path(os.getenv("IMAGE_STUDIO_DATA_DIR", "/data")).resolve()
    modelhub_root = Path(os.getenv("MODEL_HUB_SHARED_MODELS_PATH", "/modelhub")).resolve()
    model_hub_api_url = os.getenv("MODEL_HUB_API_URL", "http://v-scheduler-model-hub:6005").rstrip("/")
    # Base URL that V-Router should call when Image Studio registers itself.
    # VOS containers share vos_default, so the internal backend DNS is the default.
    v_router_base_url = os.getenv("IMAGE_STUDIO_V_ROUTER_BASE_URL", "http://image-studio-backend:5000").rstrip("/")
    # V-Router API endpoint consumed by Image Studio for remote image/video models.
    v_router_api_url = os.getenv("IMAGE_STUDIO_V_ROUTER_API_URL", "http://v-router:8080").rstrip("/")
    v_router_host_api_url = os.getenv(
        "IMAGE_STUDIO_V_ROUTER_HOST_API_URL", "http://host.docker.internal:22888"
    ).rstrip("/")
    vos_sso_enabled = os.getenv("IMAGE_STUDIO_VOS_SSO_ENABLED", "true").lower() in {"1", "true", "yes"}
    # 平台内部网关（Traefik web-internal，HTTP 无 TLS）：按 app 路径前缀寻址，
    # 不需要记忆各应用自己的宿主端口；端口由平台注入且可能变化，所以从环境变量读。
    vos_gateway_base_url = (
        f"http://{os.getenv('VOS_HOST_GW_IP', '172.17.0.1')}:{os.getenv('VOS_API_GW_PORT_INTERNAL', '1182')}"
    ).rstrip("/")
    # 留空（或未设置）即按内部网关推导；显式配置时以配置值为准。
    vos_userinfo_url = os.getenv("IMAGE_STUDIO_VOS_USERINFO_URL") or f"{vos_gateway_base_url}/v1000/user/check"
    vos_oidc_userinfo_url = os.getenv("IMAGE_STUDIO_VOS_OIDC_USERINFO_URL") or f"{vos_gateway_base_url}/v1000/oauth2/userinfo"
    # 零接触 Immich：上传时用当前 VOS 登录令牌向 Immich 换取专属 API Key（首次上传时
    # 自动完成）；关闭开关则整个免密互传功能停用。
    immich_default_api_url = os.getenv(
        "IMAGE_STUDIO_IMMICH_API_URL"
    ) or f"{vos_gateway_base_url}/app/com.ictrek.ai-album/api"
    immich_default_api_url = immich_default_api_url.rstrip("/")
    immich_auto_provision = os.getenv("IMAGE_STUDIO_IMMICH_AUTO_PROVISION", "true").lower() in {"1", "true", "yes"}
    # HTTPS 校验（内部网关是纯 HTTP，不受此开关影响；指向自签名 HTTPS 时才需关闭）。
    immich_verify_ssl = os.getenv("IMAGE_STUDIO_IMMICH_VERIFY_SSL", "true").lower() in {"1", "true", "yes"}
    sd_cpp_bin = os.getenv("SD_CPP_BIN", "sd-cli")
    sd_cpp_extra_args = os.getenv("SD_CPP_EXTRA_ARGS", "")
    default_timeout_seconds = int(os.getenv("IMAGE_STUDIO_GENERATE_TIMEOUT_SECONDS", "900"))
    # 视频生成远慢于出图，单独放宽超时（默认 1 小时）
    video_timeout_seconds = int(os.getenv("IMAGE_STUDIO_VIDEO_TIMEOUT_SECONDS", "3600"))
    max_concurrency = int(os.getenv("IMAGE_STUDIO_MAX_CONCURRENCY", "1"))
    mock_when_runtime_missing = os.getenv("IMAGE_STUDIO_MOCK_WHEN_RUNTIME_MISSING", "true").lower() == "true"

    # Keep service credentials in the app's private storage, outside VOS public configs.
    scheduler_config_path = Path(os.getenv("IMAGE_STUDIO_SCHEDULER_CONFIG", str(data_dir / "scheduler.json")))
    scheduler_config = json.loads(scheduler_config_path.read_text()) if scheduler_config_path.exists() else {}
    scheduler_url = (os.getenv("IMAGE_STUDIO_SCHEDULER_URL") or scheduler_config.get("url", "")).rstrip("/")
    scheduler_token = os.getenv("IMAGE_STUDIO_SCHEDULER_TOKEN") or scheduler_config.get("token", "")
    scheduler_executor_token = os.getenv("IMAGE_STUDIO_SCHEDULER_EXECUTOR_TOKEN") or scheduler_config.get("executor_token", "")
    scheduler_executor_id = os.getenv("IMAGE_STUDIO_SCHEDULER_EXECUTOR_ID") or scheduler_config.get("executor_id", "image-studio.generate")
    scheduler_required = os.getenv("IMAGE_STUDIO_SCHEDULER_REQUIRED") == "true"
    scheduler_models = scheduler_config.get("models", {})
    scheduler_model_limits = scheduler_config.get("model_limits", {})
    scheduler_model_parameters = scheduler_config.get("model_parameters", {})

    @property
    def sessions_dir(self) -> Path:
        return self.data_dir / "sessions"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"


settings = Settings()
