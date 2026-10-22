from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from app.config import settings
from app.models import ModelInfo
from app.services.v_router import fetch_v_router_generation_models, model_metadata


MODEL_FILE_PATTERNS = ("*.safetensors", "*.ckpt", "*.pt", "*.pth", "*.gguf")


def _runtime(
    mode: str = "image",
    model_flag: str = "-m",
    ref_flag: str | None = None,
    roles: dict[str, str] | None = None,
    extra_args: list[str] | None = None,
    defaults: dict[str, Any] | None = None,
    negative: bool = True,
    parameters: dict[str, bool] | None = None,
) -> dict[str, Any]:
    base_defaults = {
        "width": 1024,
        "height": 1024,
        "steps": 20,
        "cfg_scale": 7.0,
        "sampler": "euler",
        "scheduler": "",
        "clip_skip": -1,
        "guidance": 0.0,
        "img_cfg_scale": 0.0,
        "eta": 0.0,
        "flow_shift": 0.0,
        "high_noise_steps": 0,
        "high_noise_cfg_scale": 0.0,
        "high_noise_sampler": "",
        "slg_scale": 0.0,
        "skip_layer_start": 0.01,
        "skip_layer_end": 0.2,
        "rng": "",
        "sampler_rng": "",
        "prediction": "",
        "weight_type": "",
        "tensor_type_rules": "",
        "cache_mode": "",
        "cache_option": "",
        "qwen_image_layers": 0,
        "hires": False,
        "hires_scale": 2.0,
        "hires_width": 0,
        "hires_height": 0,
        "hires_steps": 0,
        "hires_denoising_strength": 0.7,
        "vae_tiling": mode == "video",
        "vae_tile_size": "",
        "vae_tile_overlap": 0.5,
        "temporal_tiling": False,
        "temporal_tile_frames": 4,
        "temporal_tile_overlap": 1,
        "max_vram": -2.0 if mode == "video" else 0.0,
        "stream_layers": mode == "video",
        "auto_fit": False,
        "clip_on_cpu": False,
        "offload_to_cpu": False,
        "vae_cpu_fallback": mode == "video",
        "backend": "",
        "params_backend": "",
    }
    base_defaults.update(defaults or {})
    effective_parameters = {
        "width": True,
        "height": True,
        "steps": True,
        "cfg_scale": True,
        "sampler": True,
        "seed": True,
        "negative_prompt": negative,
        "reference_image": False,
        "strength": False,
        "batch_count": mode != "video",
        "scheduler": True,
        "clip_skip": True,
        "guidance": True,
        "img_cfg_scale": False,
        "eta": True,
        "flow_shift": True,
        "high_noise_steps": False,
        "high_noise_cfg_scale": False,
        "high_noise_sampler": False,
        "slg_scale": True,
        "skip_layer_start": True,
        "skip_layer_end": True,
        "rng": True,
        "sampler_rng": True,
        "prediction": True,
        "weight_type": True,
        "tensor_type_rules": True,
        "cache_mode": True,
        "cache_option": True,
        "qwen_image_layers": False,
        "hires": mode != "video",
        "hires_scale": mode != "video",
        "hires_width": mode != "video",
        "hires_height": mode != "video",
        "hires_steps": mode != "video",
        "hires_denoising_strength": mode != "video",
        "video_frames": mode == "video",
        "fps": mode == "video",
        "vae_tiling": True,
        "vae_tile_size": True,
        "vae_tile_overlap": True,
        "temporal_tiling": False,
        "temporal_tile_frames": False,
        "temporal_tile_overlap": False,
        "max_vram": True,
        "stream_layers": True,
        "auto_fit": True,
        "clip_on_cpu": True,
        "offload_to_cpu": True,
        "vae_cpu_fallback": mode == "video",
        "backend": True,
        "params_backend": True,
    }
    effective_parameters.update(parameters or {})
    return {
        "mode": mode,
        "model_flag": model_flag,
        "ref_flag": ref_flag,
        "roles": roles or {},
        "extra_args": extra_args or [],
        "defaults": base_defaults,
        "negative": negative,
        "parameters": effective_parameters,
    }


# 拆分式图像家族共用的运行时参数；CPU offload 只由请求参数显式控制。
_FA_ARGS = ["--diffusion-fa"]


def _with_runtime_defaults(spec: dict[str, Any], **defaults: Any) -> dict[str, Any]:
    next_spec = dict(spec)
    merged = dict(next_spec.get("defaults") or {})
    merged.update(defaults)
    next_spec["defaults"] = merged
    return next_spec


def _with_runtime_parameters(spec: dict[str, Any], **parameters: bool) -> dict[str, Any]:
    next_spec = dict(spec)
    merged = dict(next_spec.get("parameters") or {})
    merged.update(parameters)
    next_spec["parameters"] = merged
    return next_spec


def _model(
    key: str,
    name: str,
    family: str,
    capabilities: list[str],
    description: str,
    sources: list[dict[str, Any]],
    preferred: bool = False,
) -> dict[str, Any]:
    primary = sources[0]
    if key in RUNTIME_SPECS:
        runtime = dict(RUNTIME_SPECS[key])
    elif "video" in capabilities and "txt2img" not in capabilities and "img2img" not in capabilities:
        runtime = _runtime(mode="video")
    else:
        runtime = _runtime()
    parameters = dict(runtime.get("parameters") or {})
    supports_reference = any(cap in capabilities for cap in ("img2img", "edit")) or parameters.get("reference_image", False)
    default_ref_flag = runtime.get("ref_flag") or ("-r" if "edit" in capabilities else "-i")
    parameters["reference_image"] = supports_reference
    parameters["strength"] = runtime.get("mode") != "video" and "img2img" in capabilities and default_ref_flag == "-i"
    parameters["img_cfg_scale"] = runtime.get("mode") != "video" and supports_reference
    parameters["batch_count"] = runtime.get("mode") != "video"
    parameters["video_frames"] = runtime.get("mode") == "video"
    parameters["fps"] = runtime.get("mode") == "video"
    parameters["vae_cpu_fallback"] = runtime.get("mode") == "video"
    if supports_reference and not runtime.get("ref_flag"):
        runtime["ref_flag"] = default_ref_flag
    runtime["parameters"] = parameters
    required_files: list[str] = []
    for source in sources:
        for filename in source.get("files") or []:
            if filename not in required_files:
                required_files.append(filename)
    return {
        "key": key,
        "name": name,
        "model_id": primary["model_id"],
        "source": primary["source"],
        "sources": sources,
        "files": primary.get("files") or [],
        "family": family,
        "capabilities": capabilities,
        "description": description,
        "expected_files": required_files or list(MODEL_FILE_PATTERNS),
        "preferred": preferred,
        "runtime": runtime,
        "params": "",
    }


# 各模型家族的 sd.cpp 运行时规格：主模型旗标、参考图旗标、辅助角色文件
# （仓库内相对路径）、家族级附加参数、默认采样参数、是否支持负向提示词。
# 路径均相对 export/<source>/<org>/<repo>/current 解析。
RUNTIME_SPECS: dict[str, dict[str, Any]] = {
    "sd15": _runtime(defaults={"width": 512, "height": 512, "steps": 20, "cfg_scale": 7.0, "sampler": "euler_a"}),
    "sd2": _runtime(defaults={"width": 512, "height": 512, "steps": 20, "cfg_scale": 7.0, "sampler": "euler_a"}),
    "sd-turbo": _runtime(
        extra_args=[*_FA_ARGS],
        defaults={
            "width": 512,
            "height": 512,
            "steps": 4,
            "cfg_scale": 1.0,
            "sampler": "euler_a",
            "vae_tiling": True,
            "vae_tile_size": "128x128",
            "weight_type": "f16",
        },
        parameters={"cfg_scale": False},
    ),
    "sdxl": _runtime(defaults={"steps": 30, "cfg_scale": 7.0, "sampler": "euler_a"}),
    "sdxl-turbo": _runtime(defaults={"steps": 4, "cfg_scale": 1.0, "sampler": "euler_a"}, parameters={"cfg_scale": False}),
    "sd3": _runtime(
        defaults={"steps": 28, "cfg_scale": 4.5, "sampler": "euler", "vae_tiling": True, "clip_on_cpu": True},
    ),
    "sd35": _runtime(
        roles={
            "clip_l": "text_encoders/clip_l.safetensors",
            "clip_g": "text_encoders/clip_g.safetensors",
            "t5xxl": "text_encoders/t5xxl_fp16.safetensors",
        },
        defaults={"steps": 28, "cfg_scale": 4.5, "sampler": "euler", "vae_tiling": True, "clip_on_cpu": True},
    ),
    "flux-schnell": _runtime(
        model_flag="--diffusion-model",
        roles={"vae": "ae.safetensors", "clip_l": "clip_l.safetensors", "t5xxl": "t5xxl_fp16.safetensors"},
        extra_args=list(_FA_ARGS),
        defaults={"steps": 4, "cfg_scale": 1.0, "sampler": "euler"},
        negative=False,
        parameters={"cfg_scale": False},
    ),
    "flux-dev": _runtime(
        model_flag="--diffusion-model",
        roles={"vae": "ae.safetensors", "clip_l": "clip_l.safetensors", "t5xxl": "t5xxl_fp16.safetensors"},
        extra_args=list(_FA_ARGS),
        defaults={"steps": 20, "cfg_scale": 1.0, "sampler": "euler"},
        negative=False,
        parameters={"cfg_scale": False},
    ),
    "flux-kontext": _runtime(
        model_flag="--diffusion-model",
        ref_flag="-r",
        roles={"vae": "ae.safetensors", "clip_l": "clip_l.safetensors", "t5xxl": "t5xxl_fp16.safetensors"},
        extra_args=list(_FA_ARGS),
        defaults={"steps": 20, "cfg_scale": 1.0, "sampler": "euler"},
        negative=False,
        parameters={"cfg_scale": False},
    ),
    "flux2": _runtime(
        model_flag="--diffusion-model",
        roles={
            "vae": "vae/flux2-vae.safetensors",
            "llm": "Mistral-Small-3.2-24B-Instruct-2506-Q4_K_M.gguf",
        },
        extra_args=list(_FA_ARGS),
        defaults={"steps": 20, "cfg_scale": 1.0, "sampler": "euler"},
        negative=False,
        parameters={"cfg_scale": False},
    ),
    "qwen-image": _runtime(
        model_flag="--diffusion-model",
        roles={"vae": "split_files/vae/qwen_image_vae.safetensors", "llm": "split_files/text_encoders/qwen_2.5_vl_7b.safetensors"},
        extra_args=list(_FA_ARGS),
        defaults={"steps": 20, "cfg_scale": 2.5, "sampler": "euler", "flow_shift": 3.0},
        parameters={"qwen_image_layers": True},
    ),
    "qwen-image-edit": _runtime(
        model_flag="--diffusion-model",
        ref_flag="-r",
        roles={"vae": "split_files/vae/qwen_image_vae.safetensors", "llm": "split_files/text_encoders/qwen_2.5_vl_7b.safetensors"},
        extra_args=list(_FA_ARGS),
        defaults={"steps": 20, "cfg_scale": 2.5, "sampler": "euler", "flow_shift": 3.0},
        parameters={"qwen_image_layers": True},
    ),
    "longcat-image": _runtime(
        model_flag="--diffusion-model",
        roles={"vae": "ae.safetensors", "llm": "Qwen2.5-VL-7B-Instruct-Q8_0.gguf"},
        extra_args=list(_FA_ARGS),
        defaults={"steps": 20, "cfg_scale": 5.0, "sampler": "euler", "flow_shift": 3.0},
    ),
    "longcat-image-edit": _runtime(
        model_flag="--diffusion-model",
        ref_flag="-r",
        roles={"vae": "ae.safetensors", "llm": "Qwen2.5-VL-7B-Instruct-Q8_0.gguf"},
        extra_args=list(_FA_ARGS),
        defaults={"steps": 20, "cfg_scale": 5.0, "sampler": "euler", "flow_shift": 3.0},
    ),
    "z-image": _runtime(
        model_flag="--diffusion-model",
        roles={"vae": "split_files/vae/ae.safetensors", "llm": "split_files/text_encoders/qwen_3_4b.safetensors"},
        extra_args=list(_FA_ARGS),
        defaults={"steps": 20, "cfg_scale": 5.0, "sampler": "euler"},
    ),
    "chroma": _runtime(
        model_flag="--diffusion-model",
        roles={"vae": "ae.safetensors", "t5xxl": "t5xxl_fp16.safetensors"},
        extra_args=["--model-args", "chroma_use_dit_mask=false"],
        defaults={"steps": 20, "cfg_scale": 4.0, "sampler": "euler", "clip_on_cpu": True},
    ),
    "chroma-radiance": _runtime(
        model_flag="--diffusion-model",
        roles={"t5xxl": "t5xxl_fp16.safetensors"},
        defaults={"steps": 20, "cfg_scale": 4.0, "sampler": "euler", "clip_on_cpu": True},
    ),
    "ovis-image": _runtime(
        model_flag="--diffusion-model",
        roles={"vae": "ae.safetensors", "llm": "split_files/text_encoders/ovis_2.5.safetensors"},
        extra_args=list(_FA_ARGS),
        defaults={"steps": 20, "cfg_scale": 5.0, "sampler": "euler"},
    ),
    "anima": _runtime(
        model_flag="--diffusion-model",
        roles={
            "vae": "split_files/vae/qwen_image_vae.safetensors",
            "llm": "split_files/text_encoders/qwen_3_06b_base.safetensors",
        },
        extra_args=list(_FA_ARGS),
        defaults={"steps": 20, "cfg_scale": 6.0, "sampler": "euler"},
    ),
    "ernie-image": _runtime(
        model_flag="--diffusion-model",
        roles={
            "vae": "vae/flux2-vae.safetensors",
            "llm": "text_encoders/ministral-3-3b.safetensors",
        },
        extra_args=list(_FA_ARGS),
        defaults={"steps": 8, "cfg_scale": 1.0, "sampler": "euler"},
        parameters={"cfg_scale": False},
    ),
    "boogu-image": _runtime(
        model_flag="--diffusion-model",
        roles={
            "vae": "vae/flux1_vae_bf16.safetensors",
            "llm": "Qwen3-VL-8B-Instruct-Q4_K_M.gguf",
        },
        extra_args=list(_FA_ARGS),
        defaults={"steps": 20, "cfg_scale": 5.0, "sampler": "euler"},
    ),
    "boogu-image-edit": _runtime(
        model_flag="--diffusion-model",
        ref_flag="-r",
        roles={
            "vae": "vae/flux1_vae_bf16.safetensors",
            "llm": "Qwen3-VL-8B-Instruct-Q4_K_M.gguf",
        },
        extra_args=list(_FA_ARGS),
        defaults={"steps": 20, "cfg_scale": 5.0, "sampler": "euler"},
    ),
    "krea2": _runtime(
        model_flag="--diffusion-model",
        roles={
            "vae": "split_files/vae/wan_2.1_vae.safetensors",
            "llm": "Qwen3VL-4B-Instruct-Q4_K_M.gguf",
        },
        extra_args=list(_FA_ARGS),
        defaults={"steps": 20, "cfg_scale": 5.0, "sampler": "euler"},
    ),
    "mage-flow": _runtime(
        model_flag="--diffusion-model",
        roles={"vae": "vae/diffusion_pytorch_model.safetensors", "llm": "Qwen3VL-4B-Instruct-Q4_K_M.gguf"},
        extra_args=list(_FA_ARGS),
        defaults={"steps": 4, "cfg_scale": 1.0, "sampler": "euler"},
        parameters={"cfg_scale": False},
    ),
    "mage-flow-edit": _runtime(
        model_flag="--diffusion-model",
        ref_flag="-r",
        roles={"vae": "vae/diffusion_pytorch_model.safetensors", "llm": "Qwen3VL-4B-Instruct-Q4_K_M.gguf"},
        extra_args=list(_FA_ARGS),
        defaults={"steps": 4, "cfg_scale": 1.0, "sampler": "euler"},
        parameters={"cfg_scale": False},
    ),
    "hidream-o1": _runtime(defaults={"steps": 20, "cfg_scale": 1.0, "sampler": "euler"}, parameters={"cfg_scale": False}),
    "ideogram4": _runtime(
        model_flag="--diffusion-model",
        roles={
            "uncond": "unconditional_transformer/diffusion_pytorch_model.safetensors",
            "llm": "text_encoder/model.safetensors",
            "vae": "vae/diffusion_pytorch_model.safetensors",
        },
        extra_args=list(_FA_ARGS),
        defaults={"steps": 20, "cfg_scale": 5.0, "sampler": "euler"},
    ),
    "lens": _runtime(
        model_flag="--diffusion-model",
        roles={"vae": "vae/flux2-vae.safetensors", "llm": "gpt-oss-20b-UD-Q8_K_XL.gguf"},
        extra_args=list(_FA_ARGS),
        defaults={"steps": 20, "cfg_scale": 5.0, "sampler": "euler"},
    ),
    "minit2i": _runtime(
        model_flag="--diffusion-model",
        roles={"t5xxl": "model.safetensors"},
        defaults={"width": 512, "height": 512, "steps": 50, "cfg_scale": 6.0, "sampler": "euler"},
    ),
    "sefi-image": _runtime(defaults={"steps": 50, "cfg_scale": 4.0, "sampler": "euler"}),
    # 视频家族：sd-cli 需要 -M vid_gen（generation.py 统一附加），角色路径为仓库内相对路径。
    # 默认参数来自 sd.cpp docs/{wan,ltx2,hunyuan_video,minimax_h3,lingbot_video}.md 的示例。
    "wan21": _runtime(
        mode="video",
        model_flag="--diffusion-model",
        roles={
            "vae": "split_files/vae/wan_2.1_vae.safetensors",
            "t5xxl": "split_files/text_encoders/umt5_xxl_fp16.safetensors",
        },
        extra_args=[*_FA_ARGS, "-v"],
        defaults={"width": 832, "height": 480, "steps": 20, "cfg_scale": 6.0, "sampler": "euler", "flow_shift": 3.0, "video_frames": 33, "fps": 24},
    ),
    "wan22": _runtime(  # TI2V 5B 支持 -i 首帧参考（不加 --strength）
        mode="video",
        model_flag="--diffusion-model",
        ref_flag="-i",
        roles={
            "vae": "split_files/vae/wan2.2_vae.safetensors",
            "t5xxl": "split_files/text_encoders/umt5_xxl_fp16.safetensors",
        },
        extra_args=[*_FA_ARGS, "-v"],
        defaults={"width": 480, "height": 832, "steps": 20, "cfg_scale": 6.0, "sampler": "euler", "flow_shift": 3.0, "video_frames": 33, "fps": 24},
        parameters={"reference_image": True},
    ),
    "ltx-video": _runtime(
        mode="video",
        model_flag="--diffusion-model",
        ref_flag="-i",
        roles={
            "vae": "vae/ltx-2.3-22b-dev_video_vae.safetensors",
            "audio_vae": "vae/ltx-2.3-22b-dev_audio_vae.safetensors",
            "llm": "gemma-3-12b-it-UD-Q4_K_XL.gguf",
            "embeddings_connectors": "text_encoders/ltx-2.3-22b-dev_embeddings_connectors.safetensors",
        },
        extra_args=[*_FA_ARGS, "-v"],
        defaults={"width": 1280, "height": 720, "steps": 20, "cfg_scale": 6.0, "sampler": "euler", "video_frames": 33, "fps": 24},
        parameters={"reference_image": True, "temporal_tiling": True, "temporal_tile_frames": True, "temporal_tile_overlap": True},
    ),
    "hunyuan-video": _runtime(
        mode="video",
        model_flag="--diffusion-model",
        roles={
            "vae": "split_files/vae/hunyuanvideo15_vae_fp16.safetensors",
            "llm": "split_files/text_encoders/qwen_2.5_vl_7b.safetensors",
            "t5xxl": "split_files/text_encoders/byt5_small_glyphxl_fp16.safetensors",
        },
        extra_args=["--diffusion-fa", "-v"],
        defaults={"width": 1280, "height": 720, "steps": 20, "cfg_scale": 6.0, "sampler": "euler", "video_frames": 33, "fps": 24},
        negative=False,
    ),
    "minimax-h3": _runtime(
        mode="video",
        model_flag="--diffusion-model",
        ref_flag="-i",
        roles={
            "vae": "vae/minimax_h3_video_vae_fp16.safetensors",
            "audio_vae": "vae/minimax_h3_audio_vae_fp32.safetensors",
            "llm": "qwen3vl_32b_minimax_h3-Q4_K_M.gguf",
        },
        extra_args=["--diffusion-fa", "-v"],
        defaults={"width": 864, "height": 480, "steps": 20, "cfg_scale": 1.0, "sampler": "euler", "video_frames": 56, "fps": 24, "rng": "cpu"},
        negative=False,
        parameters={"cfg_scale": False, "reference_image": True},
    ),
    "lingbot-video": _runtime(
        mode="video",
        model_flag="--diffusion-model",
        ref_flag="-i",
        roles={
            "vae": "split_files/vae/wan_2.1_vae.safetensors",
            "llm": "Qwen3VL-4B-Instruct-Q4_K_M.gguf",
        },
        extra_args=[*_FA_ARGS, "-v"],
        defaults={"width": 832, "height": 480, "steps": 20, "cfg_scale": 3.0, "sampler": "euler", "video_frames": 33, "fps": 24},
        parameters={"reference_image": True},
    ),
    "wan21-t2v-14b": _runtime(
        mode="video",
        model_flag="--diffusion-model",
        roles={
            "vae": "split_files/vae/wan_2.1_vae.safetensors",
            "t5xxl": "split_files/text_encoders/umt5_xxl_fp16.safetensors",
        },
        extra_args=[*_FA_ARGS, "-v"],
        defaults={"width": 832, "height": 480, "steps": 20, "cfg_scale": 6.0, "sampler": "euler", "flow_shift": 3.0, "video_frames": 33, "fps": 24},
    ),
    "wan21-i2v-14b": _runtime(
        mode="video",
        model_flag="--diffusion-model",
        ref_flag="-i",
        roles={
            "vae": "split_files/vae/wan_2.1_vae.safetensors",
            "t5xxl": "split_files/text_encoders/umt5_xxl_fp16.safetensors",
            "clip_vision": "split_files/clip_vision/clip_vision_h.safetensors",
        },
        extra_args=[*_FA_ARGS, "-v"],
        defaults={"width": 480, "height": 832, "steps": 20, "cfg_scale": 6.0, "sampler": "euler", "flow_shift": 3.0, "video_frames": 33, "fps": 24},
        parameters={"reference_image": True},
    ),
    "wan22-t2v-a14b": _runtime(
        mode="video",
        model_flag="--diffusion-model",
        roles={
            "high_noise": "split_files/diffusion_models/wan2.2_t2v_high_noise_14B_fp16.safetensors",
            "vae": "split_files/vae/wan2.2_vae.safetensors",
            "t5xxl": "split_files/text_encoders/umt5_xxl_fp16.safetensors",
        },
        extra_args=[*_FA_ARGS, "-v"],
        defaults={
            "width": 832, "height": 480, "steps": 10, "cfg_scale": 3.5, "sampler": "euler", "flow_shift": 3.0,
            "high_noise_steps": 8, "high_noise_cfg_scale": 3.5, "high_noise_sampler": "euler", "video_frames": 33, "fps": 24,
        },
        parameters={"high_noise_steps": True, "high_noise_cfg_scale": True, "high_noise_sampler": True},
    ),
    "wan22-i2v-a14b": _runtime(
        mode="video",
        model_flag="--diffusion-model",
        ref_flag="-i",
        roles={
            "high_noise": "split_files/diffusion_models/wan2.2_i2v_high_noise_14B_fp16.safetensors",
            "vae": "split_files/vae/wan2.2_vae.safetensors",
            "t5xxl": "split_files/text_encoders/umt5_xxl_fp16.safetensors",
        },
        extra_args=[*_FA_ARGS, "-v"],
        defaults={
            "width": 832, "height": 480, "steps": 10, "cfg_scale": 3.5, "sampler": "euler", "flow_shift": 3.0,
            "high_noise_steps": 8, "high_noise_cfg_scale": 3.5, "high_noise_sampler": "euler", "video_frames": 33, "fps": 24,
        },
        parameters={"reference_image": True, "high_noise_steps": True, "high_noise_cfg_scale": True, "high_noise_sampler": True},
    ),
    "hunyuan-i2v-720p": _runtime(
        mode="video",
        model_flag="--diffusion-model",
        ref_flag="-i",
        roles={
            "vae": "split_files/vae/hunyuanvideo15_vae_fp16.safetensors",
            "llm": "split_files/text_encoders/qwen_2.5_vl_7b.safetensors",
            "t5xxl": "split_files/text_encoders/byt5_small_glyphxl_fp16.safetensors",
        },
        extra_args=["--diffusion-fa", "-v"],
        defaults={"width": 1280, "height": 720, "steps": 20, "cfg_scale": 6.0, "sampler": "euler", "video_frames": 33, "fps": 24},
        negative=False,
        parameters={"reference_image": True},
    ),
    "hunyuan-t2v-480p": _runtime(
        mode="video",
        model_flag="--diffusion-model",
        roles={
            "vae": "split_files/vae/hunyuanvideo15_vae_fp16.safetensors",
            "llm": "split_files/text_encoders/qwen_2.5_vl_7b.safetensors",
            "t5xxl": "split_files/text_encoders/byt5_small_glyphxl_fp16.safetensors",
        },
        extra_args=["--diffusion-fa", "-v"],
        defaults={"width": 960, "height": 480, "steps": 20, "cfg_scale": 6.0, "sampler": "euler", "video_frames": 33, "fps": 24},
        negative=False,
    ),
    "minimax-ref2va": _runtime(
        mode="video",
        model_flag="--diffusion-model",
        ref_flag="-r",
        roles={
            "vae": "vae/minimax_h3_video_vae_fp16.safetensors",
            "audio_vae": "vae/minimax_h3_audio_vae_fp32.safetensors",
            "llm": "qwen3vl_32b_minimax_h3-Q4_K_M.gguf",
        },
        extra_args=["--diffusion-fa", "-v"],
        defaults={"width": 864, "height": 480, "steps": 20, "cfg_scale": 1.0, "sampler": "euler", "video_frames": 56, "fps": 24, "rng": "cpu"},
        negative=False,
        parameters={"cfg_scale": False, "reference_image": True},
    ),
}


# 参数量（官方标注或可从文件体积推得；不确定的留空，不编造）
MODEL_PARAMS: dict[str, str] = {
    "sd15": "860M", "sd2": "865M", "sd-turbo": "860M",
    "sdxl": "3.5B", "sdxl-turbo": "3.5B",
    "sd3": "2B", "sd35": "8.1B", "sd35-medium": "2.5B",
    "flux-schnell": "12B", "flux-dev": "12B", "flux-kontext": "12B", "flux2": "32B",
    "qwen-image": "20B", "qwen-image-edit": "20B",
    "wan21": "1.3B", "wan21-t2v-14b": "14B", "wan21-i2v-14b": "14B",
    "wan22": "5B", "wan22-t2v-a14b": "14B×2", "wan22-i2v-a14b": "14B×2",
    "ltx-video": "22B",
    "hunyuan-video": "8.3B", "hunyuan-i2v-720p": "8.3B", "hunyuan-t2v-480p": "8.3B",
    "lingbot-video": "1.3B",
    "chroma": "6B", "chroma-radiance": "6B", "z-image": "6B",
}

MODEL_SCOPE_FILES: dict[str, list[str]] = {
    "sd15": ["v1-5-pruned-emaonly.safetensors", "v1-inference.yaml"],
    "sd2": ["v2-1_512-ema-pruned.safetensors"],
    "sd-turbo": ["sd_turbo.safetensors"],
    "sdxl": ["sd_xl_base_1.0.safetensors"],
    "sdxl-turbo": ["sd_xl_turbo_1.0_fp16.safetensors"],
    "sd3": ["sd3_medium_incl_clips_t5xxlfp8.safetensors"],
    "sd35": [
        "sd3.5_large_fp8_scaled.safetensors",
        "text_encoders/clip_l.safetensors",
        "text_encoders/clip_g.safetensors",
        "text_encoders/t5xxl_fp16.safetensors",
    ],
    "sd35-medium": ["sd3.5_medium_incl_clips_t5xxlfp8scaled.safetensors"],
    "flux-schnell": ["flux1-schnell-q8_0.gguf", "ae.safetensors", "clip_l.safetensors", "t5xxl_fp16.safetensors"],
    "flux-dev": ["flux1-dev-q8_0.gguf", "ae.safetensors", "clip_l.safetensors", "t5xxl_fp16.safetensors"],
    "flux-kontext": ["flux1-kontext-dev-Q8_0.gguf", "ae.safetensors", "clip_l.safetensors", "t5xxl_fp16.safetensors"],
    "flux2": ["flux2-dev-Q4_K_S.gguf", "vae/flux2-vae.safetensors", "Mistral-Small-3.2-24B-Instruct-2506-Q4_K_M.gguf"],
    "qwen-image": [
        "split_files/diffusion_models/qwen_image_fp8_e4m3fn.safetensors",
        "split_files/vae/qwen_image_vae.safetensors",
        "split_files/text_encoders/qwen_2.5_vl_7b.safetensors",
    ],
    "qwen-image-edit": [
        "split_files/diffusion_models/qwen_image_edit_2509_fp8_e4m3fn.safetensors",
        "split_files/vae/qwen_image_vae.safetensors",
        "split_files/text_encoders/qwen_2.5_vl_7b.safetensors",
    ],
    "wan21": [
        "split_files/diffusion_models/wan2.1_t2v_1.3B_fp16.safetensors",
        "split_files/text_encoders/umt5_xxl_fp16.safetensors",
        "split_files/vae/wan_2.1_vae.safetensors",
    ],
    "wan22": [
        "split_files/diffusion_models/wan2.2_ti2v_5B_fp16.safetensors",
        "split_files/text_encoders/umt5_xxl_fp16.safetensors",
        "split_files/vae/wan2.2_vae.safetensors",
    ],
    "wan21-t2v-14b": [
        "split_files/diffusion_models/wan2.1_t2v_14B_fp16.safetensors",
        "split_files/text_encoders/umt5_xxl_fp16.safetensors",
        "split_files/vae/wan_2.1_vae.safetensors",
    ],
    "wan21-i2v-14b": [
        "split_files/diffusion_models/wan2.1_i2v_480p_14B_fp16.safetensors",
        "split_files/text_encoders/umt5_xxl_fp16.safetensors",
        "split_files/vae/wan_2.1_vae.safetensors",
        "split_files/clip_vision/clip_vision_h.safetensors",
    ],
    "wan22-t2v-a14b": [
        "split_files/diffusion_models/wan2.2_t2v_low_noise_14B_fp16.safetensors",
        "split_files/diffusion_models/wan2.2_t2v_high_noise_14B_fp16.safetensors",
        "split_files/text_encoders/umt5_xxl_fp16.safetensors",
        "split_files/vae/wan2.2_vae.safetensors",
    ],
    "wan22-i2v-a14b": [
        "split_files/diffusion_models/wan2.2_i2v_low_noise_14B_fp16.safetensors",
        "split_files/diffusion_models/wan2.2_i2v_high_noise_14B_fp16.safetensors",
        "split_files/text_encoders/umt5_xxl_fp16.safetensors",
        "split_files/vae/wan2.2_vae.safetensors",
    ],
    "ltx-video": [
        "ltx-2.3-22b-dev-UD-Q4_K_M.gguf",
        "text_encoders/ltx-2.3-22b-dev_embeddings_connectors.safetensors",
        "vae/ltx-2.3-22b-dev_video_vae.safetensors",
        "vae/ltx-2.3-22b-dev_audio_vae.safetensors",
        "gemma-3-12b-it-UD-Q4_K_XL.gguf",
    ],
    "hunyuan-video": [
        "split_files/diffusion_models/hunyuanvideo1.5_720p_t2v_fp16.safetensors",
        "split_files/vae/hunyuanvideo15_vae_fp16.safetensors",
        "split_files/text_encoders/qwen_2.5_vl_7b.safetensors",
        "split_files/text_encoders/byt5_small_glyphxl_fp16.safetensors",
    ],
    "hunyuan-i2v-720p": [
        "split_files/diffusion_models/hunyuanvideo1.5_720p_i2v_fp16.safetensors",
        "split_files/vae/hunyuanvideo15_vae_fp16.safetensors",
        "split_files/text_encoders/qwen_2.5_vl_7b.safetensors",
        "split_files/text_encoders/byt5_small_glyphxl_fp16.safetensors",
    ],
    "hunyuan-t2v-480p": [
        "split_files/diffusion_models/hunyuanvideo1.5_480p_t2v_fp16.safetensors",
        "split_files/vae/hunyuanvideo15_vae_fp16.safetensors",
        "split_files/text_encoders/qwen_2.5_vl_7b.safetensors",
        "split_files/text_encoders/byt5_small_glyphxl_fp16.safetensors",
    ],
    "minimax-h3": [
        "minimax_h3_fl2va-Q4_K_M.gguf",
        "qwen3vl_32b_minimax_h3-Q4_K_M.gguf",
        "vae/minimax_h3_video_vae_fp16.safetensors",
        "vae/minimax_h3_audio_vae_fp32.safetensors",
    ],
    "minimax-ref2va": [
        "minimax_h3_ref2va_pruned-Q4_K_M.gguf",
        "qwen3vl_32b_minimax_h3-Q4_K_M.gguf",
        "vae/minimax_h3_video_vae_fp16.safetensors",
        "vae/minimax_h3_audio_vae_fp32.safetensors",
    ],
    "lingbot-video": [
        "transformer/diffusion_pytorch_model.safetensors",
        "split_files/vae/wan_2.1_vae.safetensors",
        "Qwen3VL-4B-Instruct-Q4_K_M.gguf",
        "mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf",
    ],
    "lens": ["diffusion_models/lens_bf16.safetensors", "vae/flux2-vae.safetensors", "gpt-oss-20b-UD-Q8_K_XL.gguf"],
    "chroma": ["chroma-unlocked-v40/chroma-unlocked-v40-Q8_0.gguf", "ae.safetensors", "t5xxl_fp16.safetensors"],
    "chroma-radiance": ["Chroma1-Radiance-v0.4/Chroma1-Radiance-v0.4-Q8_0.gguf", "t5xxl_fp16.safetensors"],
    "longcat-image": ["comfy/LongCat-Image-Q4_K_M.gguf", "ae.safetensors", "Qwen2.5-VL-7B-Instruct-Q8_0.gguf"],
    "longcat-image-edit": ["LongCat-Image-Edit-Q4_K_M.gguf", "ae.safetensors", "Qwen2.5-VL-7B-Instruct-Q8_0.gguf"],
    "z-image": [
        "split_files/diffusion_models/z_image_bf16.safetensors",
        "split_files/text_encoders/qwen_3_4b.safetensors",
        "split_files/vae/ae.safetensors",
    ],
    "minit2i": ["minit2i-b-16/transformer/diffusion_pytorch_model.safetensors", "model.safetensors"],
    "ovis-image": ["ovis_image-Q4_0.gguf", "split_files/text_encoders/ovis_2.5.safetensors", "ae.safetensors"],
    "anima": [
        "split_files/diffusion_models/anima-preview.safetensors",
        "split_files/vae/qwen_image_vae.safetensors",
        "split_files/text_encoders/qwen_3_06b_base.safetensors",
    ],
    "ernie-image": ["diffusion_models/ernie-image-turbo.safetensors", "vae/flux2-vae.safetensors", "text_encoders/ministral-3-3b.safetensors"],
    "boogu-image": [
        "diffusion_models/boogu_image_base_bf16.safetensors",
        "vae/flux1_vae_bf16.safetensors",
        "Qwen3-VL-8B-Instruct-Q4_K_M.gguf",
        "mmproj-F16.gguf",
    ],
    "boogu-image-edit": [
        "diffusion_models/boogu_image_edit_bf16.safetensors",
        "vae/flux1_vae_bf16.safetensors",
        "Qwen3-VL-8B-Instruct-Q4_K_M.gguf",
        "mmproj-F16.gguf",
    ],
    "krea2": [
        "BASE/Krea-2-Base-Q8_0.gguf",
        "split_files/vae/wan_2.1_vae.safetensors",
        "Qwen3VL-4B-Instruct-Q4_K_M.gguf",
        "mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf",
    ],
    "mage-flow": [
        "transformer/diffusion_pytorch_model.safetensors",
        "vae/diffusion_pytorch_model.safetensors",
        "Qwen3VL-4B-Instruct-Q4_K_M.gguf",
        "mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf",
        "model_index.json",
        "scheduler/scheduler_config.json",
        "transformer/config.json",
        "vae/config.json",
    ],
    "mage-flow-edit": [
        "transformer/diffusion_pytorch_model.safetensors",
        "vae/diffusion_pytorch_model.safetensors",
        "Qwen3VL-4B-Instruct-Q4_K_M.gguf",
        "mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf",
        "model_index.json",
        "scheduler/scheduler_config.json",
        "transformer/config.json",
        "vae/config.json",
    ],
    "sefi-image": [
        "transformer/diffusion_pytorch_model-00001-of-00006.safetensors",
        "transformer/diffusion_pytorch_model-00002-of-00006.safetensors",
        "transformer/diffusion_pytorch_model-00003-of-00006.safetensors",
        "transformer/diffusion_pytorch_model-00004-of-00006.safetensors",
        "transformer/diffusion_pytorch_model-00005-of-00006.safetensors",
        "transformer/diffusion_pytorch_model-00006-of-00006.safetensors",
        "transformer/diffusion_pytorch_model.safetensors.index.json",
        "vae/diffusion_pytorch_model.safetensors",
        "Qwen3-VL-4B-Instruct/model-00001-of-00002.safetensors",
        "Qwen3-VL-4B-Instruct/model-00002-of-00002.safetensors",
        "Qwen3-VL-4B-Instruct/model.safetensors.index.json",
        "model_index.json",
        "scheduler/scheduler_config.json",
        "sefi_config.yaml",
        "transformer/config.json",
        "vae/config.json",
        "Qwen3-VL-4B-Instruct/config.json",
        "Qwen3-VL-4B-Instruct/generation_config.json",
        "Qwen3-VL-4B-Instruct/merges.txt",
        "Qwen3-VL-4B-Instruct/preprocessor_config.json",
        "Qwen3-VL-4B-Instruct/tokenizer.json",
        "Qwen3-VL-4B-Instruct/tokenizer_config.json",
        "Qwen3-VL-4B-Instruct/video_preprocessor_config.json",
        "Qwen3-VL-4B-Instruct/vocab.json",
    ],
    "hidream-o1": ["checkpoints/hidream_o1_image_dev_bf16.safetensors"],
    "ideogram4": [
        "transformer/diffusion_pytorch_model.safetensors",
        "unconditional_transformer/diffusion_pytorch_model.safetensors",
        "text_encoder/model.safetensors",
        "vae/diffusion_pytorch_model.safetensors",
    ],
}

MODEL_SIZES: dict[str, int] = {
    "sd15": 4265148177, "sd2": 5214604494, "sd-turbo": 5214561328,
    "sdxl": 6938078334, "sdxl-turbo": 6938081905,
    "sd3": 10867168284, "sd35": 26358290218, "sd35-medium": 11638004202,
    "flux-schnell": 23171010812, "flux-dev": 23211930108, "flux-kontext": 23083741820, "flux2": 33969264692,
    "qwen-image": 37268856958, "qwen-image-edit": 37268920246,
    "wan21": 14458518263, "wan22": 22775459193,
    "wan21-t2v-14b": 40197975879, "wan21-i2v-14b": 45675811603,
    "wan22-t2v-a14b": 69929991529, "wan22-i2v-a14b": 69931629929,
    "ltx-video": 28067922278,
    "hunyuan-video": 36197719646, "hunyuan-i2v-720p": 36197719646, "hunyuan-t2v-480p": 36197719646,
    "minimax-h3": 42810976776, "minimax-ref2va": 35451792232,
    "lingbot-video": 5997038614, "lens": 21740251708,
    "chroma": 19858555236, "chroma-radiance": 20174442976,
    "longcat-image": 12095697828, "longcat-image-edit": 12300981284,
    "z-image": 20690152836, "minit2i": 4165203276,
    "ovis-image": 9676436964, "anima": 5628159702,
    "ernie-image": 24120876547,
    "boogu-image": 26939709486, "boogu-image-edit": 26939709454,
    "krea2": 16911005334,
    "mage-flow": 11527847271, "mage-flow-edit": 11527847271,
    "sefi-image": 19000701745,
    "hidream-o1": 16365209824, "ideogram4": 27526985054,
}


def _ms_source(key: str) -> dict[str, Any]:
    return {"source": "ms", "model_id": f"vivibit/image-studio-{key}", "files": MODEL_SCOPE_FILES[key]}


def _ms_repo_source(model_id: str, files: list[str]) -> dict[str, Any]:
    return {"source": "ms", "model_id": model_id, "files": files}


def _variant(
    variant_id: str,
    name: str,
    sources: list[dict[str, Any]],
    description: str,
    runtime: dict[str, Any] | None = None,
    params: str = "",
    size: int | None = None,
) -> dict[str, Any]:
    return {
        "id": variant_id,
        "name": name,
        "sources": sources,
        "description": description,
        "runtime": runtime or {},
        "params": params,
        "size": size,
    }


MODEL_VARIANTS: dict[str, list[dict[str, Any]]] = {
    "sd15": [
        # q8_0 优先：NX 实测 q8 速度/显存/质量均优于 q4，q4 仅作显存极紧时的备选
        _variant("q8_0", "Q8_0", [_ms_repo_source("gpustack/stable-diffusion-v1-5-GGUF", ["stable-diffusion-v1-5-Q8_0.gguf"])], "ModelScope GGUF Q8_0 checkpoint for sd.cpp.", params="860M"),
        _variant("q4_0", "Q4_0", [_ms_repo_source("gpustack/stable-diffusion-v1-5-GGUF", ["stable-diffusion-v1-5-Q4_0.gguf"])], "ModelScope GGUF Q4_0 checkpoint for sd.cpp.", params="860M"),
    ],
    "sd2": [
        _variant("q8_0", "Q8_0", [_ms_repo_source("gpustack/stable-diffusion-v2-1-GGUF", ["stable-diffusion-v2-1-Q8_0.gguf"])], "ModelScope GGUF Q8_0 checkpoint for sd.cpp.", params="865M"),
        _variant("q4_0", "Q4_0", [_ms_repo_source("gpustack/stable-diffusion-v2-1-GGUF", ["stable-diffusion-v2-1-Q4_0.gguf"])], "ModelScope GGUF Q4_0 checkpoint for sd.cpp.", params="865M"),
    ],
    "sdxl": [
        _variant("q4_0", "Q4_0", [_ms_repo_source("gpustack/stable-diffusion-xl-base-1.0-GGUF", ["stable-diffusion-xl-base-1.0-Q4_0.gguf"])], "ModelScope SDXL GGUF Q4_0 checkpoint for sd.cpp.", params="3.5B"),
        _variant("q8_0", "Q8_0", [_ms_repo_source("gpustack/stable-diffusion-xl-base-1.0-GGUF", ["stable-diffusion-xl-base-1.0-Q8_0.gguf"])], "ModelScope SDXL GGUF Q8_0 checkpoint for sd.cpp.", params="3.5B"),
    ],
    "sd3": [
        _variant("q4_0", "Q4_0", [_ms_repo_source("gpustack/stable-diffusion-v3-medium-GGUF", ["stable-diffusion-v3-medium-Q4_0.gguf"])], "ModelScope SD3 Medium GGUF Q4_0 checkpoint for sd.cpp.", params="2B"),
        _variant("q8_0", "Q8_0", [_ms_repo_source("gpustack/stable-diffusion-v3-medium-GGUF", ["stable-diffusion-v3-medium-Q8_0.gguf"])], "ModelScope SD3 Medium GGUF Q8_0 checkpoint for sd.cpp.", params="2B"),
    ],
    "sd35": [
        _variant("q4_0", "Q4_0", [_ms_repo_source("gpustack/stable-diffusion-v3-5-large-GGUF", ["stable-diffusion-v3-5-large-Q4_0.gguf"])], "ModelScope SD3.5 Large GGUF Q4_0 checkpoint for sd.cpp.", runtime={"roles": {}}, params="8.1B"),
        _variant("q8_0", "Q8_0", [_ms_repo_source("gpustack/stable-diffusion-v3-5-large-GGUF", ["stable-diffusion-v3-5-large-Q8_0.gguf"])], "ModelScope SD3.5 Large GGUF Q8_0 checkpoint for sd.cpp.", runtime={"roles": {}}, params="8.1B"),
    ],
    "sd35-medium": [
        _variant("q4_0", "Q4_0", [_ms_repo_source("gpustack/stable-diffusion-v3-5-medium-GGUF", ["stable-diffusion-v3-5-medium-Q4_0.gguf"])], "ModelScope SD3.5 Medium GGUF Q4_0 checkpoint for sd.cpp.", params="2.5B"),
        _variant("q8_0", "Q8_0", [_ms_repo_source("gpustack/stable-diffusion-v3-5-medium-GGUF", ["stable-diffusion-v3-5-medium-Q8_0.gguf"])], "ModelScope SD3.5 Medium GGUF Q8_0 checkpoint for sd.cpp.", params="2.5B"),
    ],
    "flux-schnell": [
        _variant("q4_k_s", "Q4_K_S", [_ms_repo_source("vivibit/image-studio-flux-schnell-q4ks", ["flux1-schnell-Q4_K_S.gguf", "ae.safetensors", "clip_l.safetensors", "t5xxl_fp16.safetensors"])], "Dedicated vivibit ModelScope repo mirrored from HF city96/FLUX.1-schnell-gguf plus required sd.cpp auxiliary files.", params="12B"),
    ],
    "flux-dev": [
        _variant("q4_0", "Q4_0", [_ms_repo_source("gpustack/FLUX.1-dev-GGUF", ["FLUX.1-dev-Q4_0.gguf"]), _ms_source("flux-dev")], "ModelScope FLUX.1 Dev GGUF Q4_0 main model with existing vivibit auxiliary files.", params="12B"),
        _variant("q8_0", "Q8_0", [_ms_repo_source("gpustack/FLUX.1-dev-GGUF", ["FLUX.1-dev-Q8_0.gguf"]), _ms_source("flux-dev")], "ModelScope FLUX.1 Dev GGUF Q8_0 main model with existing vivibit auxiliary files.", params="12B"),
    ],
    "qwen-image": [
        _variant("q4_k_m", "Q4_K_M", [_ms_repo_source("city96/Qwen-Image-gguf", ["qwen-image-Q4_K_M.gguf"]), _ms_source("qwen-image")], "ModelScope Qwen Image GGUF Q4_K_M main model with existing vivibit VAE/text encoder files.", params="20B"),
        _variant("q8_0", "Q8_0", [_ms_repo_source("city96/Qwen-Image-gguf", ["qwen-image-Q8_0.gguf"]), _ms_source("qwen-image")], "ModelScope Qwen Image GGUF Q8_0 main model with existing vivibit VAE/text encoder files.", params="20B"),
    ],
    "qwen-image-edit": [
        _variant("q4_k_m", "Q4_K_M", [_ms_repo_source("QuantStack/Qwen-Image-Edit-2509-GGUF", ["Qwen-Image-Edit-2509-Q4_K_M.gguf"]), _ms_source("qwen-image-edit")], "ModelScope Qwen Image Edit 2509 GGUF Q4_K_M main model with existing vivibit VAE/text encoder files.", params="20B"),
        _variant("q8_0", "Q8_0", [_ms_repo_source("QuantStack/Qwen-Image-Edit-2509-GGUF", ["Qwen-Image-Edit-2509-Q8_0.gguf"]), _ms_source("qwen-image-edit")], "ModelScope Qwen Image Edit 2509 GGUF Q8_0 main model with existing vivibit VAE/text encoder files.", params="20B"),
    ],
    "wan21": [
        _variant("q4_k_m", "Q4_K_M", [_ms_repo_source("calcuis/wan-1.3b-gguf", ["wan2.1_t2v_1.3b-q4_k_m.gguf", "umt5-xxl-encoder-q4_k_m.gguf", "pig_wan_vae_fp32-f16.gguf"])], "ModelScope Wan 2.1 T2V 1.3B GGUF Q4_K_M package with matching T5/VAE files.", runtime={"roles": {"vae": "pig_wan_vae_fp32-f16.gguf", "t5xxl": "umt5-xxl-encoder-q4_k_m.gguf"}}, params="1.3B"),
        _variant("q8_0", "Q8_0", [_ms_repo_source("calcuis/wan-1.3b-gguf", ["wan2.1_t2v_1.3b-q8_0.gguf", "umt5-xxl-encoder-q4_k_m.gguf", "pig_wan_vae_fp32-f16.gguf"])], "ModelScope Wan 2.1 T2V 1.3B GGUF Q8_0 main model with Q4_K_M T5 and matching VAE.", runtime={"roles": {"vae": "pig_wan_vae_fp32-f16.gguf", "t5xxl": "umt5-xxl-encoder-q4_k_m.gguf"}}, params="1.3B"),
    ],
    "wan22": [
        _variant("q4_k_m", "Q4_K_M", [_ms_repo_source("QuantStack/Wan2.2-TI2V-5B-GGUF", ["Wan2.2-TI2V-5B-Q4_K_M.gguf", "VAE/Wan2.2_VAE.safetensors"]), _ms_repo_source("city96/umt5-xxl-encoder-gguf", ["umt5-xxl-encoder-Q4_K_M.gguf"])], "ModelScope Wan 2.2 TI2V 5B GGUF Q4_K_M main model with quantized umT5 encoder.", runtime={"roles": {"vae": "VAE/Wan2.2_VAE.safetensors", "t5xxl": "umt5-xxl-encoder-Q4_K_M.gguf"}}, params="5B"),
        _variant("q8_0", "Q8_0", [_ms_repo_source("QuantStack/Wan2.2-TI2V-5B-GGUF", ["Wan2.2-TI2V-5B-Q8_0.gguf", "VAE/Wan2.2_VAE.safetensors"]), _ms_repo_source("city96/umt5-xxl-encoder-gguf", ["umt5-xxl-encoder-Q8_0.gguf"])], "ModelScope Wan 2.2 TI2V 5B GGUF Q8_0 main model with quantized umT5 encoder.", runtime={"roles": {"vae": "VAE/Wan2.2_VAE.safetensors", "t5xxl": "umt5-xxl-encoder-Q8_0.gguf"}}, params="5B"),
    ],
    "wan21-t2v-14b": [
        _variant("q4_k_m", "Q4_K_M", [_ms_repo_source("city96/Wan2.1-T2V-14B-gguf", ["wan2.1-t2v-14b-Q4_K_M.gguf"]), _ms_repo_source("city96/umt5-xxl-encoder-gguf", ["umt5-xxl-encoder-Q4_K_M.gguf"]), _ms_source("wan21-t2v-14b")], "ModelScope Wan 2.1 T2V 14B GGUF Q4_K_M main model with quantized umT5 encoder.", runtime={"roles": {"vae": "split_files/vae/wan_2.1_vae.safetensors", "t5xxl": "umt5-xxl-encoder-Q4_K_M.gguf"}}, params="14B"),
        _variant("q8_0", "Q8_0", [_ms_repo_source("city96/Wan2.1-T2V-14B-gguf", ["wan2.1-t2v-14b-Q8_0.gguf"]), _ms_repo_source("city96/umt5-xxl-encoder-gguf", ["umt5-xxl-encoder-Q8_0.gguf"]), _ms_source("wan21-t2v-14b")], "ModelScope Wan 2.1 T2V 14B GGUF Q8_0 main model with quantized umT5 encoder.", runtime={"roles": {"vae": "split_files/vae/wan_2.1_vae.safetensors", "t5xxl": "umt5-xxl-encoder-Q8_0.gguf"}}, params="14B"),
    ],
    "wan21-i2v-14b": [
        _variant("q4_k_m", "Q4_K_M", [_ms_repo_source("city96/Wan2.1-I2V-14B-480P-gguf", ["wan2.1-i2v-14b-480p-Q4_K_M.gguf"]), _ms_repo_source("city96/umt5-xxl-encoder-gguf", ["umt5-xxl-encoder-Q4_K_M.gguf"]), _ms_source("wan21-i2v-14b")], "ModelScope Wan 2.1 I2V 14B 480P GGUF Q4_K_M main model with quantized umT5 encoder.", runtime={"roles": {"vae": "split_files/vae/wan_2.1_vae.safetensors", "t5xxl": "umt5-xxl-encoder-Q4_K_M.gguf", "clip_vision": "split_files/clip_vision/clip_vision_h.safetensors"}}, params="14B"),
        _variant("q8_0", "Q8_0", [_ms_repo_source("city96/Wan2.1-I2V-14B-480P-gguf", ["wan2.1-i2v-14b-480p-Q8_0.gguf"]), _ms_repo_source("city96/umt5-xxl-encoder-gguf", ["umt5-xxl-encoder-Q8_0.gguf"]), _ms_source("wan21-i2v-14b")], "ModelScope Wan 2.1 I2V 14B 480P GGUF Q8_0 main model with quantized umT5 encoder.", runtime={"roles": {"vae": "split_files/vae/wan_2.1_vae.safetensors", "t5xxl": "umt5-xxl-encoder-Q8_0.gguf", "clip_vision": "split_files/clip_vision/clip_vision_h.safetensors"}}, params="14B"),
    ],
    "wan22-t2v-a14b": [
        _variant("q4_k_m", "Q4_K_M", [_ms_repo_source("QuantStack/Wan2.2-T2V-A14B-GGUF", ["LowNoise/Wan2.2-T2V-A14B-LowNoise-Q4_K_M.gguf", "HighNoise/Wan2.2-T2V-A14B-HighNoise-Q4_K_M.gguf", "VAE/Wan2.1_VAE.safetensors"]), _ms_repo_source("city96/umt5-xxl-encoder-gguf", ["umt5-xxl-encoder-Q4_K_M.gguf"])], "ModelScope Wan 2.2 T2V A14B GGUF Q4_K_M low/high-noise pair with quantized umT5 encoder.", runtime={"roles": {"high_noise": "HighNoise/Wan2.2-T2V-A14B-HighNoise-Q4_K_M.gguf", "vae": "VAE/Wan2.1_VAE.safetensors", "t5xxl": "umt5-xxl-encoder-Q4_K_M.gguf"}}, params="14B×2"),
        _variant("q8_0", "Q8_0", [_ms_repo_source("QuantStack/Wan2.2-T2V-A14B-GGUF", ["LowNoise/Wan2.2-T2V-A14B-LowNoise-Q8_0.gguf", "HighNoise/Wan2.2-T2V-A14B-HighNoise-Q8_0.gguf", "VAE/Wan2.1_VAE.safetensors"]), _ms_repo_source("city96/umt5-xxl-encoder-gguf", ["umt5-xxl-encoder-Q8_0.gguf"])], "ModelScope Wan 2.2 T2V A14B GGUF Q8_0 low/high-noise pair with quantized umT5 encoder.", runtime={"roles": {"high_noise": "HighNoise/Wan2.2-T2V-A14B-HighNoise-Q8_0.gguf", "vae": "VAE/Wan2.1_VAE.safetensors", "t5xxl": "umt5-xxl-encoder-Q8_0.gguf"}}, params="14B×2"),
    ],
    "wan22-i2v-a14b": [
        _variant("q4_k_m", "Q4_K_M", [_ms_repo_source("QuantStack/Wan2.2-I2V-A14B-GGUF", ["LowNoise/Wan2.2-I2V-A14B-LowNoise-Q4_K_M.gguf", "HighNoise/Wan2.2-I2V-A14B-HighNoise-Q4_K_M.gguf", "VAE/Wan2.1_VAE.safetensors"]), _ms_repo_source("city96/umt5-xxl-encoder-gguf", ["umt5-xxl-encoder-Q4_K_M.gguf"])], "ModelScope Wan 2.2 I2V A14B GGUF Q4_K_M low/high-noise pair with quantized umT5 encoder.", runtime={"roles": {"high_noise": "HighNoise/Wan2.2-I2V-A14B-HighNoise-Q4_K_M.gguf", "vae": "VAE/Wan2.1_VAE.safetensors", "t5xxl": "umt5-xxl-encoder-Q4_K_M.gguf"}}, params="14B×2"),
        _variant("q8_0", "Q8_0", [_ms_repo_source("QuantStack/Wan2.2-I2V-A14B-GGUF", ["LowNoise/Wan2.2-I2V-A14B-LowNoise-Q8_0.gguf", "HighNoise/Wan2.2-I2V-A14B-HighNoise-Q8_0.gguf", "VAE/Wan2.1_VAE.safetensors"]), _ms_repo_source("city96/umt5-xxl-encoder-gguf", ["umt5-xxl-encoder-Q8_0.gguf"])], "ModelScope Wan 2.2 I2V A14B GGUF Q8_0 low/high-noise pair with quantized umT5 encoder.", runtime={"roles": {"high_noise": "HighNoise/Wan2.2-I2V-A14B-HighNoise-Q8_0.gguf", "vae": "VAE/Wan2.1_VAE.safetensors", "t5xxl": "umt5-xxl-encoder-Q8_0.gguf"}}, params="14B×2"),
    ],
    "lens": [
        _variant("turbo_q4_0", "Turbo Q4_0", [_ms_repo_source("gguf-org/lens-gguf", ["lens_turbo-q4_0.gguf", "pig_flux2_vae_fp32-f16.gguf"]), _ms_source("lens")], "ModelScope Lens Turbo GGUF Q4_0 main model; kept as an explicit non-default variant until smoke-tested.", runtime={"roles": {"vae": "pig_flux2_vae_fp32-f16.gguf", "llm": "gpt-oss-20b-UD-Q8_K_XL.gguf"}}, params=""),
    ],
    "z-image": [
        _variant("q4_k", "Q4_K", [_ms_repo_source("hf/leejet-Z-Image-Turbo-GGUF", ["z_image_turbo-Q4_K.gguf"]), _ms_source("z-image")], "ModelScope Z-Image Turbo GGUF Q4_K main model with existing vivibit VAE/text encoder files.", params="6B"),
        _variant("q8_0", "Q8_0", [_ms_repo_source("hf/leejet-Z-Image-Turbo-GGUF", ["z_image_turbo-Q8_0.gguf"]), _ms_source("z-image")], "ModelScope Z-Image Turbo GGUF Q8_0 main model with existing vivibit VAE/text encoder files.", params="6B"),
    ],
}

MODEL_DEFS = [
    _model(
        'sd15',
        'Stable Diffusion v1.5 EMA',
        'SD 1.x',
        ['txt2img', 'img2img'],
        'SD 1.5 ema-only safetensors prepared for stable-diffusion.cpp.',
        [_ms_source('sd15')],
        True,
    ),
    _model(
        'sd2',
        'Stable Diffusion 2.1',
        'SD 2.x',
        ['txt2img', 'img2img'],
        'Stable Diffusion 2.1-base 512 checkpoint supported by sd.cpp.',
        [_ms_source('sd2')],
    ),
    _model(
        'sd-turbo',
        'SD Turbo',
        'SD Turbo',
        ['txt2img', 'img2img'],
        'Fast SD Turbo image generation family supported by sd.cpp.',
        [_ms_source('sd-turbo')],
    ),
    _model(
        'sdxl',
        'Stable Diffusion XL Base',
        'SDXL',
        ['txt2img', 'img2img'],
        'SDXL base image generation family supported by sd.cpp.',
        [_ms_source('sdxl')],
        True,
    ),
    _model(
        'sdxl-turbo',
        'SDXL Turbo',
        'SDXL Turbo',
        ['txt2img', 'img2img'],
        'Fast SDXL Turbo generation family supported by sd.cpp.',
        [_ms_source('sdxl-turbo')],
    ),
    _model(
        'sd3',
        'Stable Diffusion 3',
        'SD3',
        ['txt2img'],
        'Stable Diffusion 3 Medium all-in-one checkpoint (incl. clips + t5xxl fp8) supported by sd.cpp.',
        [_ms_source('sd3')],
    ),
    _model(
        'sd35',
        'Stable Diffusion 3.5 Large',
        'SD3.5',
        ['txt2img'],
        'Stable Diffusion 3.5 Large fp8 checkpoint with clip_l/clip_g/t5xxl encoders supported by sd.cpp.',
        [_ms_source('sd35')],
    ),
    _model(
        'sd35-medium',
        'Stable Diffusion 3.5 Medium',
        'SD3.5',
        ['txt2img'],
        'Stable Diffusion 3.5 Medium fp8 checkpoint with built-in clip/t5xxl encoders supported by sd.cpp.',
        [_ms_source('sd35-medium')],
    ),
    _model(
        'flux-schnell',
        'FLUX.1 Schnell',
        'FLUX',
        ['txt2img'],
        'FLUX.1 Schnell q8_0 GGUF with flux VAE and clip_l/t5xxl encoders supported by sd.cpp.',
        [_ms_source('flux-schnell')],
    ),
    _model(
        'flux-dev',
        'FLUX.1 Dev',
        'FLUX',
        ['txt2img'],
        'FLUX.1 Dev q8_0 GGUF with flux VAE and clip_l/t5xxl encoders supported by sd.cpp.',
        [_ms_source('flux-dev')],
    ),
    _model(
        'flux-kontext',
        'FLUX.1 Kontext Dev',
        'FLUX Edit',
        ['img2img', 'edit'],
        'FLUX.1 Kontext Dev q8_0 GGUF image editing family supported by sd.cpp.',
        [_ms_source('flux-kontext')],
    ),
    _model(
        'flux2',
        'FLUX.2',
        'FLUX',
        ['txt2img'],
        'FLUX.2 dev Q4_K_S GGUF with flux2 VAE and Mistral-Small-24B text encoder supported by sd.cpp.',
        [_ms_source('flux2')],
    ),
    _model(
        'qwen-image',
        'Qwen Image',
        'Qwen',
        ['txt2img'],
        'Qwen Image fp8 diffusion with qwen VAE and Qwen2.5-VL-7B text encoder supported by sd.cpp.',
        [_ms_source('qwen-image')],
    ),
    _model(
        'qwen-image-edit',
        'Qwen Image Edit',
        'Qwen Edit',
        ['img2img', 'edit'],
        'Qwen Image Edit 2509 fp8 diffusion with qwen VAE and Qwen2.5-VL-7B text encoder supported by sd.cpp.',
        [_ms_source('qwen-image-edit')],
    ),
    _model(
        'wan21',
        'Wan 2.1 T2V 1.3B',
        'Wan Video',
        ['video'],
        'Wan 2.1 T2V 1.3B fp16 with umt5-xxl text encoder and wan 2.1 VAE supported by sd.cpp.',
        [_ms_source('wan21')],
    ),
    _model(
        'wan22',
        'Wan 2.2 TI2V 5B',
        'Wan Video',
        ['video'],
        'Wan 2.2 TI2V 5B fp16 with umt5-xxl text encoder and wan 2.2 VAE supported by sd.cpp.',
        [_ms_source('wan22')],
    ),
    _model(
        'wan21-t2v-14b',
        'Wan 2.1 T2V 14B',
        'Wan Video',
        ['video'],
        'Wan 2.1 T2V 14B fp16 with umt5-xxl text encoder and wan 2.1 VAE supported by sd.cpp.',
        [_ms_source('wan21-t2v-14b')],
    ),
    _model(
        'wan21-i2v-14b',
        'Wan 2.1 I2V 14B 480P',
        'Wan Video',
        ['video'],
        'Wan 2.1 I2V 14B 480p fp16 (first-frame image-to-video) with umt5-xxl, clip_vision_h and wan 2.1 VAE supported by sd.cpp.',
        [_ms_source('wan21-i2v-14b')],
    ),
    _model(
        'wan22-t2v-a14b',
        'Wan 2.2 T2V A14B',
        'Wan Video',
        ['video'],
        'Wan 2.2 T2V A14B dual low/high-noise 14B fp16 with umt5-xxl and wan 2.2 VAE supported by sd.cpp.',
        [_ms_source('wan22-t2v-a14b')],
    ),
    _model(
        'wan22-i2v-a14b',
        'Wan 2.2 I2V A14B',
        'Wan Video',
        ['video'],
        'Wan 2.2 I2V A14B dual low/high-noise 14B fp16 (first-frame image-to-video) with umt5-xxl and wan 2.2 VAE supported by sd.cpp.',
        [_ms_source('wan22-i2v-a14b')],
    ),
    _model(
        'ltx-video',
        'LTX Video',
        'Video',
        ['video'],
        'LTX-2.3 22B dev UD-Q4_K_M GGUF with gemma-3-12b text encoder, connectors and video/audio VAE supported by sd.cpp.',
        [_ms_source('ltx-video')],
    ),
    _model(
        'hunyuan-video',
        'HunyuanVideo 1.5 T2V 720P',
        'Video',
        ['video'],
        'HunyuanVideo 1.5 720p T2V fp16 with qwen VAE, Qwen2.5-VL-7B and byt5 glyph encoder supported by sd.cpp.',
        [_ms_source('hunyuan-video')],
    ),
    _model(
        'hunyuan-i2v-720p',
        'HunyuanVideo 1.5 I2V 720P',
        'Video',
        ['video'],
        'HunyuanVideo 1.5 720p I2V fp16 (first-frame image-to-video) with qwen VAE, Qwen2.5-VL-7B and byt5 glyph encoder supported by sd.cpp.',
        [_ms_source('hunyuan-i2v-720p')],
    ),
    _model(
        'hunyuan-t2v-480p',
        'HunyuanVideo 1.5 T2V 480P',
        'Video',
        ['video'],
        'HunyuanVideo 1.5 480p T2V fp16, the lighter text-to-video entry, with qwen VAE, Qwen2.5-VL-7B and byt5 glyph encoder supported by sd.cpp.',
        [_ms_source('hunyuan-t2v-480p')],
    ),
    _model(
        'minimax-h3',
        'MiniMax-H3',
        'Video',
        ['video'],
        'MiniMax-H3 fl2va Q4_K_M GGUF with qwen3vl-32b text encoder and video/audio VAE supported by sd.cpp.',
        [_ms_source('minimax-h3')],
    ),
    _model(
        'minimax-ref2va',
        'MiniMax-H3 Ref2VA',
        'Video',
        ['video'],
        'MiniMax-H3 Ref2VA pruned Q4_K_M GGUF (reference-image-to-video) with qwen3vl-32b text encoder and video/audio VAE supported by sd.cpp.',
        [_ms_source('minimax-ref2va')],
    ),
    _model(
        'lingbot-video',
        'LingBot Video',
        'Video',
        ['video'],
        'LingBot Video dense 1.3B with wan 2.1 VAE and Qwen3-VL-4B text encoder supported by sd.cpp.',
        [_ms_source('lingbot-video')],
    ),
    _model(
        'lens',
        'Lens',
        'Image',
        ['txt2img'],
        'Lens bf16 diffusion with flux2 VAE and gpt-oss-20b text encoder supported by sd.cpp.',
        [_ms_source('lens')],
    ),
    _model(
        'chroma',
        'Chroma',
        'Image',
        ['txt2img'],
        'Chroma unlocked v40 Q8_0 GGUF with flux VAE and t5xxl text encoder supported by sd.cpp.',
        [_ms_source('chroma')],
    ),
    _model(
        'chroma-radiance',
        'Chroma1 Radiance',
        'Image',
        ['txt2img'],
        'Chroma1 Radiance v0.4 Q8_0 GGUF with t5xxl text encoder supported by sd.cpp.',
        [_ms_source('chroma-radiance')],
    ),
    _model(
        'longcat-image',
        'LongCat Image',
        'Image',
        ['txt2img'],
        'LongCat Image Q4_K_M GGUF with flux VAE and Qwen2.5-VL-7B text encoder supported by sd.cpp.',
        [_ms_source('longcat-image')],
    ),
    _model(
        'longcat-image-edit',
        'LongCat Image Edit',
        'Image Edit',
        ['img2img', 'edit'],
        'LongCat Image Edit Q4_K_M GGUF with flux VAE and Qwen2.5-VL-7B text encoder supported by sd.cpp.',
        [_ms_source('longcat-image-edit')],
    ),
    _model(
        'z-image',
        'Z-Image',
        'Image',
        ['txt2img'],
        'Z-Image base bf16 diffusion with flux VAE and Qwen3-4B text encoder supported by sd.cpp.',
        [_ms_source('z-image')],
    ),
    _model(
        'minit2i',
        'MiniT2I',
        'Image',
        ['txt2img'],
        'MiniT2I B-16 diffusion with flan-t5-large text encoder supported by sd.cpp.',
        [_ms_source('minit2i')],
    ),
    _model(
        'ovis-image',
        'Ovis-Image',
        'Image',
        ['txt2img'],
        'Ovis-Image-7B Q4_0 GGUF with ovis-2.5 text encoder and flux VAE supported by sd.cpp.',
        [_ms_source('ovis-image')],
    ),
    _model(
        'anima',
        'Anima',
        'Image',
        ['txt2img'],
        'Anima preview diffusion with qwen VAE and Qwen3-0.6B base text encoder supported by sd.cpp.',
        [_ms_source('anima')],
    ),
    _model(
        'ernie-image',
        'ERNIE-Image',
        'Image',
        ['txt2img'],
        'ERNIE-Image Turbo diffusion with flux2 VAE and ministral-3b text encoder supported by sd.cpp.',
        [_ms_source('ernie-image')],
    ),
    _model(
        'boogu-image',
        'Boogu Image',
        'Image',
        ['txt2img'],
        'Boogu Image base bf16 diffusion with flux VAE and Qwen3-VL-8B text encoder supported by sd.cpp.',
        [_ms_source('boogu-image')],
    ),
    _model(
        'boogu-image-edit',
        'Boogu Image Edit',
        'Image Edit',
        ['img2img', 'edit'],
        'Boogu Image Edit bf16 diffusion with flux VAE and Qwen3-VL-8B text encoder supported by sd.cpp.',
        [_ms_source('boogu-image-edit')],
    ),
    _model(
        'krea2',
        'Krea2',
        'Image',
        ['txt2img'],
        'Krea-2 Base Q8_0 GGUF with wan 2.1 VAE and Qwen3-VL-4B text encoder supported by sd.cpp.',
        [_ms_source('krea2')],
    ),
    _model(
        'mage-flow',
        'Mage-Flow',
        'Image',
        ['txt2img'],
        'Mage-Flow Turbo transformer and VAE with Qwen3-VL-4B text encoder in a dedicated ModelScope runtime repo.',
        [_ms_source('mage-flow')],
    ),
    _model(
        'mage-flow-edit',
        'Mage-Flow Edit',
        'Image Edit',
        ['img2img', 'edit'],
        'Mage-Flow Edit Turbo transformer and VAE with Qwen3-VL-4B text encoder in a dedicated ModelScope runtime repo.',
        [_ms_source('mage-flow-edit')],
    ),
    _model(
        'sefi-image',
        'SeFi-Image',
        'Image',
        ['txt2img'],
        'SeFi-Image 5B turbo with its required transformer, VAE and Qwen3-VL files in a dedicated ModelScope runtime repo.',
        [_ms_source('sefi-image')],
    ),
    _model(
        'hidream-o1',
        'HiDream-O1-Image',
        'Image',
        ['txt2img'],
        'HiDream-O1-Image dev bf16 all-in-one checkpoint supported by sd.cpp.',
        [_ms_source('hidream-o1')],
    ),
    _model(
        'ideogram4',
        'Ideogram4',
        'Image',
        ['txt2img'],
        'Ideogram 4 fp8 transformer with unconditional transformer, text encoder and VAE supported by sd.cpp.',
        [_ms_source('ideogram4')],
    ),
]
for _item in MODEL_DEFS:
    _item["params"] = MODEL_PARAMS.get(_item["key"], "")


def list_model_defs() -> list[ModelInfo]:
    return [model_info(item) for item in MODEL_DEFS]


def get_model(key: str) -> ModelInfo:
    for item in MODEL_DEFS:
        if item["key"] == key:
            return model_info(item)
    raise KeyError(key)


def get_model_def(key: str, variant_id: str = "") -> dict[str, Any]:
    for item in MODEL_DEFS:
        if item["key"] == key:
            return _effective_model_item(item, variant_id)
    raise KeyError(key)


def _effective_model_item(item: dict[str, Any], variant_id: str = "") -> dict[str, Any]:
    # Orin 的统一内存使用本机实测的低内存边界，保留原始共享权重。
    if item["key"] == "sd-turbo" and settings.profile == "l4t":
        item = {**item, "runtime": _with_runtime_defaults(item["runtime"], weight_type="q4_0", max_vram=2.0, vae_tile_size="")}
    variant_id = (variant_id or "").strip()
    if not variant_id:
        return item
    for variant in MODEL_VARIANTS.get(item["key"], []):
        if variant["id"] != variant_id:
            continue
        effective = dict(item)
        sources = variant["sources"]
        runtime = dict(item["runtime"])
        variant_runtime = variant.get("runtime") or {}
        for key, value in variant_runtime.items():
            if key == "roles":
                runtime[key] = dict(value)
            elif isinstance(value, dict) and isinstance(runtime.get(key), dict):
                merged = dict(runtime[key])
                merged.update(value)
                runtime[key] = merged
            else:
                runtime[key] = value
        required_files: list[str] = []
        for source in sources:
            for filename in source.get("files") or []:
                if filename not in required_files:
                    required_files.append(filename)
        effective.update(
            {
                "variant": variant,
                "variant_id": variant_id,
                "model_id": sources[0]["model_id"],
                "source": sources[0]["source"],
                "sources": sources,
                "files": sources[0].get("files") or [],
                "expected_files": required_files,
                "runtime": runtime,
                "description": variant.get("description") or item["description"],
                "params": variant.get("params") or item.get("params", ""),
            }
        )
        if variant.get("size"):
            effective["expected_size"] = variant["size"]
        return effective
    raise ValueError(f"unknown model variant: {variant_id}")


def _relative_candidates(item: dict[str, Any]) -> list[str]:
    candidates = []
    for spec in item["sources"]:
        rel = f"export/{spec['source']}/{spec['model_id']}/current"
        if rel not in candidates:
            candidates.append(rel)
    return candidates


def model_info(item: dict[str, Any]) -> ModelInfo:
    effective = _effective_model_item(item) if not item.get("variant_id") else item
    return ModelInfo(**_model_payload(effective, include_variants=True))


def _model_payload(item: dict[str, Any], include_variants: bool = False) -> dict[str, Any]:
    resolved = None
    size = None
    expected_size = item.get("expected_size") or MODEL_SIZES.get(item["key"])
    registered_files = list(item.get("files") or [])
    for rel in _relative_candidates(item):
        candidate = settings.modelhub_root / rel
        found = _resolve_model_file(candidate, registered_files[0] if registered_files else None)
        if found:
            resolved = found
            size = expected_size or found.stat().st_size
            break

    fallback = settings.modelhub_root / _relative_candidates(item)[0]
    dirty_partial = _has_incomplete_markers(item)
    info = {
        "key": item["key"],
        "name": item["name"],
        "model_id": item["model_id"],
        "source": item["source"],
        "sources": item["sources"],
        "files": item["files"],
        "family": item["family"],
        "capabilities": item["capabilities"],
        "preferred": item["preferred"],
        "params": item.get("params", ""),
        "runtime": item["runtime"],
        "description": item["description"],
        "expected_files": item["expected_files"],
        "variants": _variant_payloads(item) if include_variants else [],
        "access_path": str(fallback),
        "resolved_path": str(resolved) if resolved else None,
        "status": "ready" if resolved else ("failed" if dirty_partial else "missing"),
        "size": size,
        "total_bytes": expected_size,
    }
    info["v_router"] = model_metadata(item["key"], item["capabilities"], variant_id=item.get("variant_id", ""), status=info["status"])
    if dirty_partial and not resolved:
        info["error"] = "发现上次未完成下载残留，请重新下载以清理后重新拉取"
    return info


def _variant_payloads(item: dict[str, Any]) -> list[dict[str, Any]]:
    variants = []
    for variant in MODEL_VARIANTS.get(item["key"], []):
        effective = _effective_model_item(item, variant["id"])
        payload = _model_payload(effective)
        payload.update(
            {
                "id": variant["id"],
                "name": variant["name"],
                "description": variant["description"],
            }
        )
        variants.append(payload)
    return variants


def _has_incomplete_markers(item: dict[str, Any]) -> bool:
    for spec in item["sources"]:
        repo_root = settings.modelhub_root / "export" / spec["source"] / spec["model_id"]
        if not repo_root.exists():
            continue
        for path in repo_root.rglob("*"):
            if path.is_file() and path.name.endswith((".incomplete", ".tmp")):
                return True
    return False


def runtime_paths_for(key: str, variant_id: str = "") -> dict[str, Path]:
    """按 runtime 角色解析辅助文件（VAE / 文本编码器等）的实际路径。

    角色值是仓库内相对路径。优先在各来源的 current 目录下查找；若未命中
    （current 只指向某一 revision 的 snapshot，而历史下载可能把部分文件
    下到了 main/其他 revision 目录），回退扫描该仓库所有 snapshot 目录，
    命中即用，避免"同仓库多文件分散到不同 snapshot 导致辅助文件缺失"。
    """
    item = get_model_def(key, variant_id)
    roles: dict[str, Path] = {}
    missing: list[str] = []
    for role, rel in (item["runtime"].get("roles") or {}).items():
        found = None
        for spec in item["sources"]:
            repo_root = settings.modelhub_root / "export" / spec["source"] / spec["model_id"]
            # 1) 优先 current
            candidate = repo_root / "current" / rel
            if candidate.exists():
                found = candidate
                break
            # 2) 回退：扫描所有 snapshot 目录（current 可能只指向部分文件所在 revision）
            snapshots_dir = repo_root / "snapshots"
            if snapshots_dir.is_dir():
                for snap in sorted(snapshots_dir.iterdir(), reverse=True):
                    candidate = snap / rel
                    if candidate.exists():
                        found = candidate
                        break
                if found:
                    break
        if found:
            roles[role] = found
        else:
            missing.append(f"{role}({rel})")
    if missing:
        raise FileNotFoundError(f"模型辅助文件缺失: {', '.join(missing)}")
    return roles


def _resolve_model_file(path: Path, preferred_rel: str | None = None) -> Path | None:
    # 多文件仓库（diffusion + 文本编码器同仓）必须用注册清单里的主模型文件，
    # 不能按体积猜——umt5/qwen3vl 等编码器常比小尺寸 diffusion 模型更大。
    if preferred_rel:
        preferred = path / preferred_rel
        if preferred.is_file() and _is_model_file(preferred):
            return preferred
    if path.is_file() and _is_model_file(path):
        return path
    if not path.is_dir():
        return None
    for pattern in MODEL_FILE_PATTERNS:
        matches = sorted((p for p in path.rglob(pattern) if p.is_file()), key=lambda p: p.stat().st_size, reverse=True)
        if matches:
            return matches[0]
    return None


def _is_model_file(path: Path) -> bool:
    return path.suffix.lower() in {".safetensors", ".ckpt", ".pt", ".pth", ".gguf"}


async def pull_model(key: str, force: bool = False, variant_id: str = "") -> dict[str, Any]:
    item = get_model_def(key, variant_id)
    submitted = []
    async with httpx.AsyncClient(timeout=30) as client:
        for spec in item["sources"]:
            payload = {
                "source": spec["source"],
                "model_id": spec["model_id"],
                "name": item["name"],
                "force": force,
                "files": spec.get("files"),
            }
            resp = await client.post(f"{settings.model_hub_api_url}/api/v1/models/pull", json=payload)
            if resp.status_code == 409:
                submitted.append({"status": "active", "model_id": spec["model_id"], "detail": resp.json().get("detail", "")})
                continue
            resp.raise_for_status()
            submitted.append({"status": "submitted", "model_id": spec["model_id"], "task": resp.json()})
    return {
        "status": "submitted",
        "model_id": item["model_id"],
        "variant": item.get("variant_id", ""),
        "sources": submitted,
    }


async def stop_model(key: str, variant_id: str = "") -> dict[str, Any]:
    item = get_model_def(key, variant_id)
    model_ids = {spec["model_id"] for spec in item["sources"]}
    cancelled = []
    async with httpx.AsyncClient(timeout=30) as client:
        tasks_resp = await client.get(f"{settings.model_hub_api_url}/api/v1/tasks")
        tasks_resp.raise_for_status()
        for task in tasks_resp.json():
            task_model_id = str(task.get("model_id", "")).replace("ms://", "").replace("hf://", "")
            phase = task.get("phase")
            if task_model_id in model_ids and phase in {"PENDING", "DOWNLOADING", "VERIFYING"}:
                task_id = str(task.get("task_id", ""))
                if not task_id:
                    continue
                cancel_resp = await client.post(f"{settings.model_hub_api_url}/api/v1/tasks/{quote(task_id, safe='')}/cancel")
                cancel_resp.raise_for_status()
                cancelled.append({"model_id": task_model_id, "task": cancel_resp.json()})
    if cancelled:
        return {"status": "cancelled", "model_id": item["model_id"], "variant": item.get("variant_id", ""), "tasks": cancelled}
    return {"status": "not_running", "model_id": item["model_id"], "variant": item.get("variant_id", "")}


async def sync_model_hub() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(f"{settings.model_hub_api_url}/api/v1/models/sync")
        resp.raise_for_status()
        return resp.json()


async def fetch_model_hub_states() -> dict[str, dict[str, Any]]:
    """读取 Model Hub 的模型注册表与任务列表，用于回显 ms 源模型的下载状态。"""
    states: dict[str, dict[str, Any]] = {}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            models_resp = await client.get(f"{settings.model_hub_api_url}/api/v1/models", params={"status": "all"})
            models_resp.raise_for_status()
            for entry in models_resp.json():
                model_id = str(entry.get("model_id", "")).replace("ms://", "").replace("hf://", "")
                states[model_id] = {
                    "status": entry.get("status"),
                    "size": entry.get("size"),
                    "path": entry.get("path"),
                    "access_path": entry.get("access_path"),
                    "progress": entry.get("progress"),
                    "downloaded_bytes": entry.get("downloaded_bytes"),
                    "total_bytes": entry.get("total_bytes"),
                    "current_file": entry.get("current_file"),
                }
            tasks_resp = await client.get(f"{settings.model_hub_api_url}/api/v1/tasks")
            if tasks_resp.status_code == 200:
                for task in tasks_resp.json():
                    model_id = str(task.get("model_id", "")).replace("ms://", "").replace("hf://", "")
                    state = states.setdefault(model_id, {})
                    phase = task.get("phase")
                    if phase == "DOWNLOADING":
                        if state.get("status") in ("ready", "READY"):
                            continue
                        state["status"] = "pulling"
                        state["progress"] = task.get("progress")
                        state["downloaded_bytes"] = task.get("downloaded_bytes")
                        state["total_bytes"] = task.get("total_bytes")
                        state["current_file"] = task.get("current_file")
                    elif phase == "FAILED" and state.get("status") in (None, "pulling", "failed"):
                        state["status"] = "failed"
                        state["error"] = task.get("error_msg")
    except Exception:
        return {}
    return states


def merge_model_hub_state(hub_state: dict[str, Any] | None, info: dict[str, Any]) -> None:
    """把 Model Hub 侧状态合并进模型信息。

    ready 判定不能只看主模型文件是否已落盘。多文件模型下载时，主模型
    可能先完成，但 VAE / 文本编码器仍在拉取；只要 Model Hub 仍标记
    pulling，就先视作 downloading，避免提交必然失败的生成任务。
    """
    if not hub_state:
        return
    if info["status"] == "downloading":
        return
    hub_size = hub_state.get("size")
    if isinstance(hub_size, int) and hub_size > 0:
        info["total_bytes"] = hub_size
        if info.get("status") == "ready" and not info.get("size"):
            info["size"] = hub_size
    access_path = hub_state.get("access_path") or hub_state.get("path")
    if isinstance(access_path, str) and access_path:
        info["access_path"] = access_path
    status = hub_state.get("status")
    if status in ("pulling", "PULLING"):
        info["status"] = "downloading"
        progress = hub_state.get("progress")
        info["progress"] = float(progress) if isinstance(progress, (int, float)) else None
        for field in ("downloaded_bytes", "total_bytes", "current_file"):
            value = hub_state.get(field)
            if value is not None:
                info[field] = value
    elif status in ("failed", "FAILED") and info["status"] != "ready":
        info["status"] = "failed"
        info["error"] = hub_state.get("error") or ""


def merge_item_hub_states(item: dict[str, Any], hub_states: dict[str, dict[str, Any]], info: dict[str, Any]) -> None:
    for index, spec in enumerate(item["sources"]):
        before_status = info.get("status")
        before_access = info.get("access_path")
        merge_model_hub_state(hub_states.get(spec["model_id"]), info)
        if index > 0 and before_access:
            info["access_path"] = before_access
        if before_status == "ready" and info.get("status") not in ("downloading", "failed"):
            info["status"] = "ready"


async def list_model_defs_with_hub_state(access_token: str = "") -> list[ModelInfo]:
    """列出模型并合并双端下载状态：本应用 HF 任务 + Model Hub 拉取任务。"""
    hub_states = await fetch_model_hub_states()
    result = []
    for item in MODEL_DEFS:
        info = model_info(item)
        payload = info.model_dump()
        merge_item_hub_states(item, hub_states, payload)
        for variant in payload.get("variants", []):
            variant_item = get_model_def(item["key"], variant.get("id", ""))
            merge_item_hub_states(variant_item, hub_states, variant)
        info = ModelInfo(**payload)
        result.append(info)
    try:
        for item in await fetch_v_router_generation_models(access_token):
            result.append(ModelInfo(**item))
    except Exception:
        # V-Router is optional for Image Studio. Local models must remain usable
        # when V-Router is not installed, not reachable, or rejects this token.
        pass
    return result


async def assert_model_hub_ready(key: str, variant_id: str = "") -> None:
    item = get_model_def(key, variant_id)
    hub_states = await fetch_model_hub_states()
    for spec in item["sources"]:
        state = hub_states.get(spec["model_id"])
        if not state:
            continue
        status = state.get("status")
        if status in ("pulling", "PULLING"):
            raise FileNotFoundError(f"Model Hub 仍在下载: {spec['model_id']}")
    model_path_for(key, variant_id)
    runtime_paths_for(key, variant_id)


def model_path_for(key: str, variant_id: str = "") -> Path:
    item = get_model_def(key, variant_id)
    info = ModelInfo(**_model_payload(item))
    if not info.resolved_path:
        raise FileNotFoundError(info.access_path)
    return Path(info.resolved_path)
