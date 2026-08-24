from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    negative_prompt: str = ""
    model_key: str = "sd15"
    width: int = Field(default=768, ge=256, le=2048)
    height: int = Field(default=768, ge=256, le=2048)
    steps: int = Field(default=30, ge=1, le=150)
    cfg_scale: float = Field(default=7.0, ge=1.0, le=30.0)
    sampler: str = "euler_a"
    seed: int = -1
    batch_count: int = Field(default=1, ge=1, le=4)


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
    sampler: str
    seed: int
    batch_count: int
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
    description: str
    expected_files: list[str]
    access_path: str
    resolved_path: str | None = None
    status: Literal["ready", "missing", "downloading", "failed", "unknown"] = "unknown"
    size: int | None = None
    model_hub_status: dict[str, Any] | None = None

