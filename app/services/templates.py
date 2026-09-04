"""生成参数模板：templates.json 不存在时返回预设模板，首次保存时落盘，之后以文件为准。"""
from __future__ import annotations

import json
import uuid
from typing import Any

from app.config import settings

# 这些平台首次打开时应用预设默认模板（amd/thor 待实测后调整）。
_DEFAULT_TEMPLATE_PROFILES = ("nx", "amd", "thor")


def default_template_id() -> str | None:
    return "nx-recommended" if settings.profile in _DEFAULT_TEMPLATE_PROFILES else None


# 预设模板：来自 NX 实测结论（results/nx_model_report.md）。仅首次初始化时写入
# templates.json，之后以文件为准；调整预设时换新 id 即可让存量部署看到新模板。
DEFAULT_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "nx-recommended",
        "name": "极速推荐",
        "description": "SD-Turbo 512/4步/tiling，快速出图）",
        "payload": {
            "model_key": "sd-turbo", "model_variant": "",
            "width": 512, "height": 512, "steps": 4, "cfg_scale": 1.0,
            "sampler": "euler_a", "vae_tiling": True, "vae_tile_size": "128x128",
        },
    },
    {
        "id": "quality-sd21",
        "name": "质量优先",
        "description": "SD2.1 Q8 20步，速度稍慢，细节较好",
        "payload": {
            "model_key": "sd2", "model_variant": "q8_0",
            "width": 512, "height": 512, "steps": 20, "cfg_scale": 7.0,
            "sampler": "euler_a", "vae_tiling": False, "vae_tile_size": "",
        },
    },
]

# 模板可携带的参数子集（GeneratePayload 的白名单）
TEMPLATE_FIELDS = (
    "model_key", "model_variant", "width", "height", "steps", "cfg_scale",
    "sampler", "vae_tiling", "vae_tile_size", "negative_prompt",
)


def _user_templates_path():
    return settings.data_dir / "templates.json"


def _load_user_templates() -> list[dict[str, Any]]:
    try:
        data = json.loads(_user_templates_path().read_text(encoding="utf-8"))
        return data.get("templates", []) if isinstance(data, dict) else []
    except FileNotFoundError:
        return [dict(t) for t in DEFAULT_TEMPLATES]
    except (json.JSONDecodeError, OSError):
        return []


def _save_user_templates(templates: list[dict[str, Any]]) -> None:
    path = _user_templates_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"templates": templates}, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def list_templates() -> list[dict[str, Any]]:
    """文件里的全部模板，保存时间倒序（新保存的在前）。"""
    return _load_user_templates()


def save_template(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """把当前生成参数保存为模板，只保留白名单字段，同名即覆盖。"""
    name = (name or "").strip() or "未命名模板"
    entry = {
        "id": uuid.uuid4().hex[:12],
        "name": name,
        "description": "",
        "payload": {k: payload[k] for k in TEMPLATE_FIELDS if k in payload},
    }
    templates = [t for t in _load_user_templates() if t.get("name") != name]
    templates.insert(0, entry)
    _save_user_templates(templates)
    return entry


def rename_template(template_id: str, name: str) -> dict[str, Any] | None:
    templates = _load_user_templates()
    for t in templates:
        if t.get("id") == template_id:
            t["name"] = (name or "").strip() or t["name"]
            _save_user_templates(templates)
            return t
    return None


def delete_template(template_id: str) -> bool:
    templates = _load_user_templates()
    remaining = [t for t in templates if t.get("id") != template_id]
    if len(remaining) == len(templates):
        return False
    _save_user_templates(remaining)
    return True

