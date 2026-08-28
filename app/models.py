from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    negative_prompt: str = ""
    model_key: str = "sd15"
    init_job_id: str = ""
    init_filename: str = ""
    init_input_id: str = ""
    width: int = Field(default=768, ge=256, le=2048)
    height: int = Field(default=768, ge=256, le=2048)
    steps: int = Field(default=30, ge=1, le=150)
    cfg_scale: float = Field(default=7.0, ge=1.0, le=30.0)
    strength: float = Field(default=0.75, ge=0.0, le=1.0)
    sampler: str = "euler_a"
    seed: int = -1
    batch_count: int = Field(default=1, ge=1, le=4)
    scheduler: str = ""
    clip_skip: int = Field(default=-1, ge=-1, le=24)
    guidance: float = Field(default=0.0, ge=0.0, le=30.0)
    img_cfg_scale: float = Field(default=0.0, ge=0.0, le=30.0)
    eta: float = Field(default=0.0, ge=0.0, le=10.0)
    flow_shift: float = Field(default=0.0, ge=0.0, le=20.0)
    high_noise_steps: int = Field(default=0, ge=0, le=150)
    high_noise_cfg_scale: float = Field(default=0.0, ge=0.0, le=30.0)
    high_noise_sampler: str = ""
    slg_scale: float = Field(default=0.0, ge=0.0, le=20.0)
    skip_layer_start: float = Field(default=0.01, ge=0.0, le=1.0)
    skip_layer_end: float = Field(default=0.2, ge=0.0, le=1.0)
    rng: str = ""
    sampler_rng: str = ""
    prediction: str = ""
    weight_type: str = ""
    tensor_type_rules: str = Field(default="", max_length=1000)
    cache_mode: str = ""
    cache_option: str = Field(default="", max_length=1000)
    qwen_image_layers: int = Field(default=0, ge=0, le=16)
    hires: bool = False
    hires_scale: float = Field(default=2.0, ge=1.0, le=8.0)
    hires_width: int = Field(default=0, ge=0, le=4096)
    hires_height: int = Field(default=0, ge=0, le=4096)
    hires_steps: int = Field(default=0, ge=0, le=150)
    hires_denoising_strength: float = Field(default=0.7, ge=0.0, le=1.0)
    # 视频参数：0 表示使用模型家族默认值（仅视频家族生效）
    video_frames: int = Field(default=0, ge=0, le=240)
    fps: int = Field(default=0, ge=0, le=60)
    vae_tiling: bool | None = None
    vae_tile_size: str = Field(default="", max_length=32)
    vae_tile_overlap: float = Field(default=0.5, ge=0.0, le=0.95)
    temporal_tiling: bool | None = None
    temporal_tile_frames: int = Field(default=4, ge=1, le=32)
    temporal_tile_overlap: int = Field(default=1, ge=0, le=16)
    max_vram: float = Field(default=0.0, ge=-64.0, le=128.0)
    stream_layers: bool | None = None
    auto_fit: bool | None = None
    offload_to_cpu: bool | None = None
    vae_cpu_fallback: bool | None = None
    backend: str = Field(default="", max_length=200)
    params_backend: str = Field(default="", max_length=200)


class JobRecord(BaseModel):
    job_id: str
    user_key: str
    status: Literal["queued", "running", "succeeded", "failed"]
    prompt: str
    negative_prompt: str = ""
    model_key: str
    model_path: str
    width: int
    height: int
    steps: int
    cfg_scale: float
    strength: float = 0.75
    sampler: str
    seed: int
    batch_count: int
    scheduler: str = ""
    clip_skip: int = -1
    guidance: float = 0.0
    img_cfg_scale: float = 0.0
    eta: float = 0.0
    flow_shift: float = 0.0
    high_noise_steps: int = 0
    high_noise_cfg_scale: float = 0.0
    high_noise_sampler: str = ""
    slg_scale: float = 0.0
    skip_layer_start: float = 0.01
    skip_layer_end: float = 0.2
    rng: str = ""
    sampler_rng: str = ""
    prediction: str = ""
    weight_type: str = ""
    tensor_type_rules: str = ""
    cache_mode: str = ""
    cache_option: str = ""
    qwen_image_layers: int = 0
    hires: bool = False
    hires_scale: float = 2.0
    hires_width: int = 0
    hires_height: int = 0
    hires_steps: int = 0
    hires_denoising_strength: float = 0.7
    video_frames: int = 0
    fps: int = 0
    vae_tiling: bool = False
    vae_tile_size: str = ""
    vae_tile_overlap: float = 0.5
    temporal_tiling: bool = False
    temporal_tile_frames: int = 4
    temporal_tile_overlap: int = 1
    max_vram: float = 0.0
    stream_layers: bool = False
    auto_fit: bool = False
    offload_to_cpu: bool = False
    vae_cpu_fallback: bool = False
    backend: str = ""
    params_backend: str = ""
    progress: float = 0
    outputs: list[str] = []
    error: str = ""
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelInfo(BaseModel):
    key: str
    name: str
    model_id: str
    source: str
    sources: list[dict[str, Any]] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    family: str = ""
    capabilities: list[str] = Field(default_factory=list)
    preferred: bool = False
    description: str
    expected_files: list[str]
    params: str = ""
    runtime: dict[str, Any] = Field(default_factory=dict)
    access_path: str
    resolved_path: str | None = None
    status: Literal["ready", "missing", "downloading", "failed", "unknown"] = "unknown"
    size: int | None = None
    progress: float | None = None
    current_file: str | None = None
    downloaded_bytes: int | None = None
    total_bytes: int | None = None
    error: str | None = None
    model_hub_status: dict[str, Any] | None = None
