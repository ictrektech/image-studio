from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from app.config import settings
from app.models import ModelInfo
from app.services import hf_downloader


MODEL_FILE_PATTERNS = ("*.safetensors", "*.ckpt", "*.pt", "*.pth", "*.gguf")

# 各模型家族通用的辅助仓库（sd.cpp 文档指定的 VAE / 文本编码器来源）
_FLUX_VAE = {"source": "hf", "model_id": "black-forest-labs/FLUX.1-schnell", "files": ["ae.safetensors"]}
_FLUX_TEXT = {
    "source": "hf",
    "model_id": "comfyanonymous/flux_text_encoders",
    "files": ["clip_l.safetensors", "t5xxl_fp16.safetensors"],
}
_WAN21_VAE = {
    "source": "hf",
    "model_id": "Comfy-Org/Wan_2.1_ComfyUI_repackaged",
    "files": ["split_files/vae/wan_2.1_vae.safetensors"],
}
_QWEN25VL_7B_GGUF = {
    "source": "hf",
    "model_id": "mradermacher/Qwen2.5-VL-7B-Instruct-GGUF",
    "files": ["Qwen2.5-VL-7B-Instruct-Q8_0.gguf"],
}
_QWEN3VL_4B_GGUF = {
    "source": "hf",
    "model_id": "Qwen/Qwen3-VL-4B-Instruct-GGUF",
    "files": ["Qwen3VL-4B-Instruct-Q4_K_M.gguf", "mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf"],
}
_QWEN3VL_8B_GGUF = {
    "source": "hf",
    "model_id": "unsloth/Qwen3-VL-8B-Instruct-GGUF",
    "files": ["Qwen3-VL-8B-Instruct-Q4_K_M.gguf", "mmproj-F16.gguf"],
}


def _runtime(
    mode: str = "image",
    model_flag: str = "-m",
    ref_flag: str = "-i",
    roles: dict[str, str] | None = None,
    extra_args: list[str] | None = None,
    defaults: dict[str, Any] | None = None,
    negative: bool = True,
) -> dict[str, Any]:
    base_defaults = {"width": 1024, "height": 1024, "steps": 20, "cfg_scale": 7.0, "sampler": "euler"}
    base_defaults.update(defaults or {})
    return {
        "mode": mode,
        "model_flag": model_flag,
        "ref_flag": ref_flag,
        "roles": roles or {},
        "extra_args": extra_args or [],
        "defaults": base_defaults,
        "negative": negative,
    }


# 拆分式图像家族共用的运行时参数（FLUX / Qwen / Wan 等文本编码器在 CPU 更稳）
_FA_ARGS = ["--diffusion-fa", "--offload-to-cpu"]


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
        runtime = RUNTIME_SPECS[key]
    elif "video" in capabilities and "txt2img" not in capabilities and "img2img" not in capabilities:
        runtime = _runtime(mode="video")
    else:
        runtime = _runtime()
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
        "expected_files": list(MODEL_FILE_PATTERNS),
        "preferred": preferred,
        "runtime": runtime,
        "params": "",
    }


# 各模型家族的 sd.cpp 运行时规格：主模型旗标、参考图旗标、辅助角色文件
# （仓库内相对路径）、家族级附加参数、默认采样参数、是否支持负向提示词。
# 路径均相对 export/<source>/<org>/<repo>/current 解析。
RUNTIME_SPECS: dict[str, dict[str, Any]] = {
    "sd15": _runtime(defaults={"width": 512, "height": 512, "steps": 30, "cfg_scale": 7.0, "sampler": "euler_a"}),
    "sd2": _runtime(defaults={"width": 512, "height": 512, "steps": 30, "cfg_scale": 7.0, "sampler": "euler_a"}),
    "sd-turbo": _runtime(defaults={"steps": 4, "cfg_scale": 1.0, "sampler": "euler_a"}),
    "sdxl": _runtime(defaults={"steps": 30, "cfg_scale": 7.0, "sampler": "euler_a"}),
    "sdxl-turbo": _runtime(defaults={"steps": 4, "cfg_scale": 1.0, "sampler": "euler_a"}),
    "sd3": _runtime(
        extra_args=["--clip-on-cpu", "--vae-tiling"],
        defaults={"steps": 28, "cfg_scale": 4.5, "sampler": "euler"},
    ),
    "sd35": _runtime(
        roles={
            "clip_l": "text_encoders/clip_l.safetensors",
            "clip_g": "text_encoders/clip_g.safetensors",
            "t5xxl": "text_encoders/t5xxl_fp16.safetensors",
        },
        extra_args=["--clip-on-cpu", "--vae-tiling"],
        defaults={"steps": 28, "cfg_scale": 4.5, "sampler": "euler"},
    ),
    "flux-schnell": _runtime(
        model_flag="--diffusion-model",
        roles={"vae": "ae.safetensors", "clip_l": "clip_l.safetensors", "t5xxl": "t5xxl_fp16.safetensors"},
        extra_args=list(_FA_ARGS),
        defaults={"steps": 4, "cfg_scale": 1.0, "sampler": "euler"},
        negative=False,
    ),
    "flux-dev": _runtime(
        model_flag="--diffusion-model",
        roles={"vae": "ae.safetensors", "clip_l": "clip_l.safetensors", "t5xxl": "t5xxl_fp16.safetensors"},
        extra_args=list(_FA_ARGS),
        defaults={"steps": 20, "cfg_scale": 1.0, "sampler": "euler"},
        negative=False,
    ),
    "flux-kontext": _runtime(
        model_flag="--diffusion-model",
        ref_flag="-r",
        roles={"vae": "ae.safetensors", "clip_l": "clip_l.safetensors", "t5xxl": "t5xxl_fp16.safetensors"},
        extra_args=list(_FA_ARGS),
        defaults={"steps": 20, "cfg_scale": 1.0, "sampler": "euler"},
        negative=False,
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
    ),
    "qwen-image": _runtime(
        model_flag="--diffusion-model",
        roles={"vae": "split_files/vae/qwen_image_vae.safetensors", "llm": "split_files/text_encoders/qwen_2.5_vl_7b.safetensors"},
        extra_args=[*_FA_ARGS, "--flow-shift", "3"],
        defaults={"steps": 20, "cfg_scale": 2.5, "sampler": "euler"},
    ),
    "qwen-image-edit": _runtime(
        model_flag="--diffusion-model",
        ref_flag="-r",
        roles={"vae": "split_files/vae/qwen_image_vae.safetensors", "llm": "split_files/text_encoders/qwen_2.5_vl_7b.safetensors"},
        extra_args=[*_FA_ARGS, "--flow-shift", "3"],
        defaults={"steps": 20, "cfg_scale": 2.5, "sampler": "euler"},
    ),
    "longcat-image": _runtime(
        model_flag="--diffusion-model",
        roles={"vae": "ae.safetensors", "llm": "Qwen2.5-VL-7B-Instruct-Q8_0.gguf"},
        extra_args=[*_FA_ARGS, "--flow-shift", "3"],
        defaults={"steps": 20, "cfg_scale": 5.0, "sampler": "euler"},
    ),
    "longcat-image-edit": _runtime(
        model_flag="--diffusion-model",
        ref_flag="-r",
        roles={"vae": "ae.safetensors", "llm": "Qwen2.5-VL-7B-Instruct-Q8_0.gguf"},
        extra_args=[*_FA_ARGS, "--flow-shift", "3"],
        defaults={"steps": 20, "cfg_scale": 5.0, "sampler": "euler"},
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
        extra_args=["--clip-on-cpu", "--model-args", "chroma_use_dit_mask=false"],
        defaults={"steps": 20, "cfg_scale": 4.0, "sampler": "euler"},
    ),
    "chroma-radiance": _runtime(
        model_flag="--diffusion-model",
        roles={"t5xxl": "t5xxl_fp16.safetensors"},
        extra_args=["--clip-on-cpu"],
        defaults={"steps": 20, "cfg_scale": 4.0, "sampler": "euler"},
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
    ),
    "mage-flow-edit": _runtime(
        model_flag="--diffusion-model",
        ref_flag="-r",
        roles={"vae": "vae/diffusion_pytorch_model.safetensors", "llm": "Qwen3VL-4B-Instruct-Q4_K_M.gguf"},
        extra_args=list(_FA_ARGS),
        defaults={"steps": 4, "cfg_scale": 1.0, "sampler": "euler"},
    ),
    "hidream-o1": _runtime(defaults={"steps": 20, "cfg_scale": 1.0, "sampler": "euler"}),
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
        extra_args=[*_FA_ARGS, "--flow-shift", "3.0", "-v"],
        defaults={"width": 832, "height": 480, "steps": 20, "cfg_scale": 6.0, "sampler": "euler", "video_frames": 33, "fps": 24},
    ),
    "wan22": _runtime(  # TI2V 5B 支持 -i 首帧参考（不加 --strength）
        mode="video",
        model_flag="--diffusion-model",
        ref_flag="-i",
        roles={
            "vae": "split_files/vae/wan2.2_vae.safetensors",
            "t5xxl": "split_files/text_encoders/umt5_xxl_fp16.safetensors",
        },
        extra_args=[*_FA_ARGS, "--flow-shift", "3.0", "-v"],
        defaults={"width": 480, "height": 832, "steps": 20, "cfg_scale": 6.0, "sampler": "euler", "video_frames": 33, "fps": 24},
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
    ),
    "hunyuan-video": _runtime(
        mode="video",
        model_flag="--diffusion-model",
        roles={
            "vae": "split_files/vae/hunyuanvideo15_vae_fp16.safetensors",
            "llm": "split_files/text_encoders/qwen_2.5_vl_7b.safetensors",
            "t5xxl": "split_files/text_encoders/byt5_small_glyphxl_fp16.safetensors",
        },
        extra_args=["--diffusion-fa", "--offload-to-cpu", "--vae-tiling", "-v"],
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
        extra_args=["--diffusion-fa", "--offload-to-cpu", "--rng", "cpu", "-v"],
        defaults={"width": 864, "height": 480, "steps": 20, "cfg_scale": 1.0, "sampler": "euler", "video_frames": 56, "fps": 24},
        negative=False,
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
    ),
    "wan21-t2v-14b": _runtime(
        mode="video",
        model_flag="--diffusion-model",
        roles={
            "vae": "split_files/vae/wan_2.1_vae.safetensors",
            "t5xxl": "split_files/text_encoders/umt5_xxl_fp16.safetensors",
        },
        extra_args=[*_FA_ARGS, "--flow-shift", "3.0", "-v"],
        defaults={"width": 832, "height": 480, "steps": 20, "cfg_scale": 6.0, "sampler": "euler", "video_frames": 33, "fps": 24},
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
        extra_args=[*_FA_ARGS, "--flow-shift", "3.0", "-v"],
        defaults={"width": 480, "height": 832, "steps": 20, "cfg_scale": 6.0, "sampler": "euler", "video_frames": 33, "fps": 24},
    ),
    "wan22-t2v-a14b": _runtime(
        mode="video",
        model_flag="--diffusion-model",
        roles={
            "high_noise": "split_files/diffusion_models/wan2.2_t2v_high_noise_14B_fp16.safetensors",
            "vae": "split_files/vae/wan2.2_vae.safetensors",
            "t5xxl": "split_files/text_encoders/umt5_xxl_fp16.safetensors",
        },
        extra_args=[*_FA_ARGS, "--flow-shift", "3.0",
                    "--high-noise-cfg-scale", "3.5", "--high-noise-sampling-method", "euler", "--high-noise-steps", "8", "-v"],
        defaults={"width": 832, "height": 480, "steps": 10, "cfg_scale": 3.5, "sampler": "euler", "video_frames": 33, "fps": 24},
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
        extra_args=[*_FA_ARGS, "--flow-shift", "3.0",
                    "--high-noise-cfg-scale", "3.5", "--high-noise-sampling-method", "euler", "--high-noise-steps", "8", "-v"],
        defaults={"width": 832, "height": 480, "steps": 10, "cfg_scale": 3.5, "sampler": "euler", "video_frames": 33, "fps": 24},
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
        extra_args=["--diffusion-fa", "--offload-to-cpu", "--vae-tiling", "-v"],
        defaults={"width": 1280, "height": 720, "steps": 20, "cfg_scale": 6.0, "sampler": "euler", "video_frames": 33, "fps": 24},
        negative=False,
    ),
    "hunyuan-t2v-480p": _runtime(
        mode="video",
        model_flag="--diffusion-model",
        roles={
            "vae": "split_files/vae/hunyuanvideo15_vae_fp16.safetensors",
            "llm": "split_files/text_encoders/qwen_2.5_vl_7b.safetensors",
            "t5xxl": "split_files/text_encoders/byt5_small_glyphxl_fp16.safetensors",
        },
        extra_args=["--diffusion-fa", "--offload-to-cpu", "--vae-tiling", "-v"],
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
        extra_args=["--diffusion-fa", "--offload-to-cpu", "--rng", "cpu", "-v"],
        defaults={"width": 864, "height": 480, "steps": 20, "cfg_scale": 1.0, "sampler": "euler", "video_frames": 56, "fps": 24},
        negative=False,
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

MODEL_DEFS = [
    _model(
        "sd15",
        "Stable Diffusion v1.5 EMA",
        "SD 1.x",
        ["txt2img", "img2img"],
        "SD 1.5 ema-only safetensors prepared for stable-diffusion.cpp.",
        [
            {
                "source": "ms",
                "model_id": "vivibit/stable-diffusion-v1-5",
                "files": ["v1-5-pruned-emaonly.safetensors", "v1-inference.yaml"],
            }
        ],
        True,
    ),
    _model(
        "sd2",
        "Stable Diffusion 2.1",
        "SD 2.x",
        ["txt2img", "img2img"],
        "Stable Diffusion 2.1-base 512 checkpoint supported by sd.cpp.",
        [{"source": "hf", "model_id": "Manojb/stable-diffusion-2-1-base", "files": ["v2-1_512-ema-pruned.safetensors"]}],
    ),
    _model(
        "sd-turbo",
        "SD Turbo",
        "SD Turbo",
        ["txt2img", "img2img"],
        "Fast SD Turbo image generation family supported by sd.cpp.",
        [{"source": "hf", "model_id": "stabilityai/sd-turbo", "files": ["sd_turbo.safetensors"]}],
    ),
    _model(
        "sdxl",
        "Stable Diffusion XL Base",
        "SDXL",
        ["txt2img", "img2img"],
        "SDXL base image generation family supported by sd.cpp.",
        [{"source": "hf", "model_id": "stabilityai/stable-diffusion-xl-base-1.0", "files": ["sd_xl_base_1.0.safetensors"]}],
        True,
    ),
    _model(
        "sdxl-turbo",
        "SDXL Turbo",
        "SDXL Turbo",
        ["txt2img", "img2img"],
        "Fast SDXL Turbo generation family supported by sd.cpp.",
        [{"source": "hf", "model_id": "stabilityai/sdxl-turbo", "files": ["sd_xl_turbo_1.0_fp16.safetensors"]}],
    ),
    _model(
        "sd3",
        "Stable Diffusion 3",
        "SD3",
        ["txt2img"],
        "Stable Diffusion 3 Medium all-in-one checkpoint (incl. clips + t5xxl fp8) supported by sd.cpp.",
        [
            {
                "source": "hf",
                "model_id": "adamo1139/stable-diffusion-3-medium-ungated",
                "files": ["sd3_medium_incl_clips_t5xxlfp8.safetensors"],
            }
        ],
    ),
    _model(
        "sd35",
        "Stable Diffusion 3.5 Large",
        "SD3.5",
        ["txt2img"],
        "Stable Diffusion 3.5 Large fp8 checkpoint with clip_l/clip_g/t5xxl encoders supported by sd.cpp.",
        [
            {
                "source": "hf",
                "model_id": "Comfy-Org/stable-diffusion-3.5-fp8",
                "files": [
                    "sd3.5_large_fp8_scaled.safetensors",
                    "text_encoders/clip_l.safetensors",
                    "text_encoders/clip_g.safetensors",
                    "text_encoders/t5xxl_fp16.safetensors",
                ],
            }
        ],
    ),
    _model(
        "sd35-medium",
        "Stable Diffusion 3.5 Medium",
        "SD3.5",
        ["txt2img"],
        "Stable Diffusion 3.5 Medium fp8 checkpoint with built-in clip/t5xxl encoders supported by sd.cpp.",
        [
            {
                "source": "hf",
                "model_id": "Comfy-Org/stable-diffusion-3.5-fp8",
                "files": ["sd3.5_medium_incl_clips_t5xxlfp8scaled.safetensors"],
            }
        ],
    ),
    _model(
        "flux-schnell",
        "FLUX.1 Schnell",
        "FLUX",
        ["txt2img"],
        "FLUX.1 Schnell q8_0 GGUF with flux VAE and clip_l/t5xxl encoders supported by sd.cpp.",
        [
            {"source": "hf", "model_id": "leejet/FLUX.1-schnell-gguf", "files": ["flux1-schnell-q8_0.gguf"]},
            dict(_FLUX_VAE),
            dict(_FLUX_TEXT),
        ],
    ),
    _model(
        "flux-dev",
        "FLUX.1 Dev",
        "FLUX",
        ["txt2img"],
        "FLUX.1 Dev q8_0 GGUF with flux VAE and clip_l/t5xxl encoders supported by sd.cpp.",
        [
            {"source": "hf", "model_id": "leejet/FLUX.1-dev-gguf", "files": ["flux1-dev-q8_0.gguf"]},
            dict(_FLUX_VAE),
            dict(_FLUX_TEXT),
        ],
    ),
    _model(
        "flux-kontext",
        "FLUX.1 Kontext Dev",
        "FLUX Edit",
        ["img2img", "edit"],
        "FLUX.1 Kontext Dev q8_0 GGUF image editing family supported by sd.cpp.",
        [
            {"source": "hf", "model_id": "QuantStack/FLUX.1-Kontext-dev-GGUF", "files": ["flux1-kontext-dev-Q8_0.gguf"]},
            dict(_FLUX_VAE),
            dict(_FLUX_TEXT),
        ],
    ),
    _model(
        "flux2",
        "FLUX.2",
        "FLUX",
        ["txt2img"],
        "FLUX.2 dev Q4_K_S GGUF with flux2 VAE and Mistral-Small-24B text encoder supported by sd.cpp.",
        [
            {"source": "hf", "model_id": "city96/FLUX.2-dev-gguf", "files": ["flux2-dev-Q4_K_S.gguf"]},
            {"source": "hf", "model_id": "Comfy-Org/ERNIE-Image", "files": ["vae/flux2-vae.safetensors"]},
            {
                "source": "hf",
                "model_id": "unsloth/Mistral-Small-3.2-24B-Instruct-2506-GGUF",
                "files": ["Mistral-Small-3.2-24B-Instruct-2506-Q4_K_M.gguf"],
            },
        ],
    ),
    _model(
        "qwen-image",
        "Qwen Image",
        "Qwen",
        ["txt2img"],
        "Qwen Image fp8 diffusion with qwen VAE and Qwen2.5-VL-7B text encoder supported by sd.cpp.",
        [
            {
                "source": "hf",
                "model_id": "Comfy-Org/Qwen-Image_ComfyUI",
                "files": [
                    "split_files/diffusion_models/qwen_image_fp8_e4m3fn.safetensors",
                    "split_files/vae/qwen_image_vae.safetensors",
                    "split_files/text_encoders/qwen_2.5_vl_7b.safetensors",
                ],
            }
        ],
    ),
    _model(
        "qwen-image-edit",
        "Qwen Image Edit",
        "Qwen Edit",
        ["img2img", "edit"],
        "Qwen Image Edit 2509 fp8 diffusion with qwen VAE and Qwen2.5-VL-7B text encoder supported by sd.cpp.",
        [
            {
                "source": "hf",
                "model_id": "Comfy-Org/Qwen-Image-Edit_ComfyUI",
                "files": ["split_files/diffusion_models/qwen_image_edit_2509_fp8_e4m3fn.safetensors"],
            },
            {
                "source": "hf",
                "model_id": "Comfy-Org/Qwen-Image_ComfyUI",
                "files": [
                    "split_files/vae/qwen_image_vae.safetensors",
                    "split_files/text_encoders/qwen_2.5_vl_7b.safetensors",
                ],
            },
        ],
    ),
    _model(
        "wan21",
        "Wan 2.1 T2V 1.3B",
        "Wan Video",
        ["video"],
        "Wan 2.1 T2V 1.3B fp16 with umt5-xxl text encoder and wan 2.1 VAE supported by sd.cpp.",
        [
            {
                "source": "hf",
                "model_id": "Comfy-Org/Wan_2.1_ComfyUI_repackaged",
                "files": [
                    "split_files/diffusion_models/wan2.1_t2v_1.3B_fp16.safetensors",
                    "split_files/text_encoders/umt5_xxl_fp16.safetensors",
                    "split_files/vae/wan_2.1_vae.safetensors",
                ],
            }
        ],
    ),
    _model(
        "wan22",
        "Wan 2.2 TI2V 5B",
        "Wan Video",
        ["video"],
        "Wan 2.2 TI2V 5B fp16 with umt5-xxl text encoder and wan 2.2 VAE supported by sd.cpp.",
        [
            {
                "source": "hf",
                "model_id": "Comfy-Org/Wan_2.2_ComfyUI_Repackaged",
                "files": [
                    "split_files/diffusion_models/wan2.2_ti2v_5B_fp16.safetensors",
                    "split_files/text_encoders/umt5_xxl_fp16.safetensors",
                    "split_files/vae/wan2.2_vae.safetensors",
                ],
            }
        ],
    ),
    _model(
        "wan21-t2v-14b",
        "Wan 2.1 T2V 14B",
        "Wan Video",
        ["video"],
        "Wan 2.1 T2V 14B fp16 with umt5-xxl text encoder and wan 2.1 VAE supported by sd.cpp.",
        [
            {
                "source": "hf",
                "model_id": "Comfy-Org/Wan_2.1_ComfyUI_repackaged",
                "files": [
                    "split_files/diffusion_models/wan2.1_t2v_14B_fp16.safetensors",
                    "split_files/text_encoders/umt5_xxl_fp16.safetensors",
                    "split_files/vae/wan_2.1_vae.safetensors",
                ],
            }
        ],
    ),
    _model(
        "wan21-i2v-14b",
        "Wan 2.1 I2V 14B 480P",
        "Wan Video",
        ["video"],
        "Wan 2.1 I2V 14B 480p fp16 (first-frame image-to-video) with umt5-xxl, clip_vision_h and wan 2.1 VAE supported by sd.cpp.",
        [
            {
                "source": "hf",
                "model_id": "Comfy-Org/Wan_2.1_ComfyUI_repackaged",
                "files": [
                    "split_files/diffusion_models/wan2.1_i2v_480p_14B_fp16.safetensors",
                    "split_files/text_encoders/umt5_xxl_fp16.safetensors",
                    "split_files/vae/wan_2.1_vae.safetensors",
                    "split_files/clip_vision/clip_vision_h.safetensors",
                ],
            }
        ],
    ),
    _model(
        "wan22-t2v-a14b",
        "Wan 2.2 T2V A14B",
        "Wan Video",
        ["video"],
        "Wan 2.2 T2V A14B dual low/high-noise 14B fp16 with umt5-xxl and wan 2.2 VAE supported by sd.cpp.",
        [
            {
                "source": "hf",
                "model_id": "Comfy-Org/Wan_2.2_ComfyUI_Repackaged",
                "files": [
                    "split_files/diffusion_models/wan2.2_t2v_low_noise_14B_fp16.safetensors",
                    "split_files/diffusion_models/wan2.2_t2v_high_noise_14B_fp16.safetensors",
                    "split_files/text_encoders/umt5_xxl_fp16.safetensors",
                    "split_files/vae/wan2.2_vae.safetensors",
                ],
            }
        ],
    ),
    _model(
        "wan22-i2v-a14b",
        "Wan 2.2 I2V A14B",
        "Wan Video",
        ["video"],
        "Wan 2.2 I2V A14B dual low/high-noise 14B fp16 (first-frame image-to-video) with umt5-xxl and wan 2.2 VAE supported by sd.cpp.",
        [
            {
                "source": "hf",
                "model_id": "Comfy-Org/Wan_2.2_ComfyUI_Repackaged",
                "files": [
                    "split_files/diffusion_models/wan2.2_i2v_low_noise_14B_fp16.safetensors",
                    "split_files/diffusion_models/wan2.2_i2v_high_noise_14B_fp16.safetensors",
                    "split_files/text_encoders/umt5_xxl_fp16.safetensors",
                    "split_files/vae/wan2.2_vae.safetensors",
                ],
            }
        ],
    ),
    _model(
        "ltx-video",
        "LTX Video",
        "Video",
        ["video"],
        "LTX-2.3 22B dev UD-Q4_K_M GGUF with gemma-3-12b text encoder, connectors and video/audio VAE supported by sd.cpp.",
        [
            {
                "source": "hf",
                "model_id": "unsloth/LTX-2.3-GGUF",
                "files": [
                    "ltx-2.3-22b-dev-UD-Q4_K_M.gguf",
                    "text_encoders/ltx-2.3-22b-dev_embeddings_connectors.safetensors",
                    "vae/ltx-2.3-22b-dev_video_vae.safetensors",
                    "vae/ltx-2.3-22b-dev_audio_vae.safetensors",
                ],
            },
            {"source": "hf", "model_id": "unsloth/gemma-3-12b-it-GGUF", "files": ["gemma-3-12b-it-UD-Q4_K_XL.gguf"]},
        ],
    ),
    _model(
        "hunyuan-video",
        "HunyuanVideo 1.5 T2V 720P",
        "Video",
        ["video"],
        "HunyuanVideo 1.5 720p T2V fp16 with qwen VAE, Qwen2.5-VL-7B and byt5 glyph encoder supported by sd.cpp.",
        [
            {
                "source": "hf",
                "model_id": "Comfy-Org/HunyuanVideo_1.5_repackaged",
                "files": [
                    "split_files/diffusion_models/hunyuanvideo1.5_720p_t2v_fp16.safetensors",
                    "split_files/vae/hunyuanvideo15_vae_fp16.safetensors",
                    "split_files/text_encoders/qwen_2.5_vl_7b.safetensors",
                    "split_files/text_encoders/byt5_small_glyphxl_fp16.safetensors",
                ],
            }
        ],
    ),
    _model(
        "hunyuan-i2v-720p",
        "HunyuanVideo 1.5 I2V 720P",
        "Video",
        ["video"],
        "HunyuanVideo 1.5 720p I2V fp16 (first-frame image-to-video) with qwen VAE, Qwen2.5-VL-7B and byt5 glyph encoder supported by sd.cpp.",
        [
            {
                "source": "hf",
                "model_id": "Comfy-Org/HunyuanVideo_1.5_repackaged",
                "files": [
                    "split_files/diffusion_models/hunyuanvideo1.5_720p_i2v_fp16.safetensors",
                    "split_files/vae/hunyuanvideo15_vae_fp16.safetensors",
                    "split_files/text_encoders/qwen_2.5_vl_7b.safetensors",
                    "split_files/text_encoders/byt5_small_glyphxl_fp16.safetensors",
                ],
            }
        ],
    ),
    _model(
        "hunyuan-t2v-480p",
        "HunyuanVideo 1.5 T2V 480P",
        "Video",
        ["video"],
        "HunyuanVideo 1.5 480p T2V fp16, the lighter text-to-video entry, with qwen VAE, Qwen2.5-VL-7B and byt5 glyph encoder supported by sd.cpp.",
        [
            {
                "source": "hf",
                "model_id": "Comfy-Org/HunyuanVideo_1.5_repackaged",
                "files": [
                    "split_files/diffusion_models/hunyuanvideo1.5_480p_t2v_fp16.safetensors",
                    "split_files/vae/hunyuanvideo15_vae_fp16.safetensors",
                    "split_files/text_encoders/qwen_2.5_vl_7b.safetensors",
                    "split_files/text_encoders/byt5_small_glyphxl_fp16.safetensors",
                ],
            }
        ],
    ),
    _model(
        "minimax-h3",
        "MiniMax-H3",
        "Video",
        ["video"],
        "MiniMax-H3 fl2va Q4_K_M GGUF with qwen3vl-32b text encoder and video/audio VAE supported by sd.cpp.",
        [
            {
                "source": "hf",
                "model_id": "leejet/MiniMax-H3-GGUF",
                "files": ["minimax_h3_fl2va-Q4_K_M.gguf", "qwen3vl_32b_minimax_h3-Q4_K_M.gguf"],
            },
            {
                "source": "hf",
                "model_id": "Comfy-Org/MiniMax-H3",
                "files": ["vae/minimax_h3_video_vae_fp16.safetensors", "vae/minimax_h3_audio_vae_fp32.safetensors"],
            },
        ],
    ),
    _model(
        "minimax-ref2va",
        "MiniMax-H3 Ref2VA",
        "Video",
        ["video"],
        "MiniMax-H3 Ref2VA pruned Q4_K_M GGUF (reference-image-to-video) with qwen3vl-32b text encoder and video/audio VAE supported by sd.cpp.",
        [
            {
                "source": "hf",
                "model_id": "leejet/MiniMax-H3-GGUF",
                "files": ["minimax_h3_ref2va_pruned-Q4_K_M.gguf", "qwen3vl_32b_minimax_h3-Q4_K_M.gguf"],
            },
            {
                "source": "hf",
                "model_id": "Comfy-Org/MiniMax-H3",
                "files": ["vae/minimax_h3_video_vae_fp16.safetensors", "vae/minimax_h3_audio_vae_fp32.safetensors"],
            },
        ],
    ),
    _model(
        "lingbot-video",
        "LingBot Video",
        "Video",
        ["video"],
        "LingBot Video dense 1.3B with wan 2.1 VAE and Qwen3-VL-4B text encoder supported by sd.cpp.",
        [
            {"source": "hf", "model_id": "robbyant/lingbot-video-dense-1.3b", "files": ["transformer/diffusion_pytorch_model.safetensors"]},
            dict(_WAN21_VAE),
            dict(_QWEN3VL_4B_GGUF),
        ],
    ),
    _model(
        "lens",
        "Lens",
        "Image",
        ["txt2img"],
        "Lens bf16 diffusion with flux2 VAE and gpt-oss-20b text encoder supported by sd.cpp.",
        [
            {
                "source": "hf",
                "model_id": "Comfy-Org/Lens",
                "files": ["diffusion_models/lens_bf16.safetensors", "vae/flux2-vae.safetensors"],
            },
            {"source": "hf", "model_id": "unsloth/gpt-oss-20b-GGUF", "files": ["gpt-oss-20b-UD-Q8_K_XL.gguf"]},
        ],
    ),
    _model(
        "chroma",
        "Chroma",
        "Image",
        ["txt2img"],
        "Chroma unlocked v40 Q8_0 GGUF with flux VAE and t5xxl text encoder supported by sd.cpp.",
        [
            {
                "source": "hf",
                "model_id": "silveroxides/Chroma-GGUF",
                "files": ["chroma-unlocked-v40/chroma-unlocked-v40-Q8_0.gguf"],
            },
            dict(_FLUX_VAE),
            {"source": "hf", "model_id": "comfyanonymous/flux_text_encoders", "files": ["t5xxl_fp16.safetensors"]},
        ],
    ),
    _model(
        "chroma-radiance",
        "Chroma1 Radiance",
        "Image",
        ["txt2img"],
        "Chroma1 Radiance v0.4 Q8_0 GGUF with t5xxl text encoder supported by sd.cpp.",
        [
            {
                "source": "hf",
                "model_id": "silveroxides/Chroma1-Radiance-GGUF",
                "files": ["Chroma1-Radiance-v0.4/Chroma1-Radiance-v0.4-Q8_0.gguf"],
            },
            {"source": "hf", "model_id": "comfyanonymous/flux_text_encoders", "files": ["t5xxl_fp16.safetensors"]},
        ],
    ),
    _model(
        "longcat-image",
        "LongCat Image",
        "Image",
        ["txt2img"],
        "LongCat Image Q4_K_M GGUF with flux VAE and Qwen2.5-VL-7B text encoder supported by sd.cpp.",
        [
            {"source": "hf", "model_id": "vantagewithai/LongCat-Image-GGUF", "files": ["comfy/LongCat-Image-Q4_K_M.gguf"]},
            dict(_FLUX_VAE),
            dict(_QWEN25VL_7B_GGUF),
        ],
    ),
    _model(
        "longcat-image-edit",
        "LongCat Image Edit",
        "Image Edit",
        ["img2img", "edit"],
        "LongCat Image Edit Q4_K_M GGUF with flux VAE and Qwen2.5-VL-7B text encoder supported by sd.cpp.",
        [
            {"source": "hf", "model_id": "vantagewithai/LongCat-Image-Edit-GGUF", "files": ["LongCat-Image-Edit-Q4_K_M.gguf"]},
            dict(_FLUX_VAE),
            dict(_QWEN25VL_7B_GGUF),
        ],
    ),
    _model(
        "z-image",
        "Z-Image",
        "Image",
        ["txt2img"],
        "Z-Image base bf16 diffusion with flux VAE and Qwen3-4B text encoder supported by sd.cpp.",
        [
            {
                "source": "hf",
                "model_id": "Comfy-Org/z_image",
                "files": [
                    "split_files/diffusion_models/z_image_bf16.safetensors",
                    "split_files/text_encoders/qwen_3_4b.safetensors",
                    "split_files/vae/ae.safetensors",
                ],
            }
        ],
    ),
    _model(
        "minit2i",
        "MiniT2I",
        "Image",
        ["txt2img"],
        "MiniT2I B-16 diffusion with flan-t5-large text encoder supported by sd.cpp.",
        [
            {"source": "hf", "model_id": "MiniT2I/MiniT2I", "files": ["minit2i-b-16/transformer/diffusion_pytorch_model.safetensors"]},
            {"source": "hf", "model_id": "google/flan-t5-large", "files": ["model.safetensors"]},
        ],
    ),
    _model(
        "ovis-image",
        "Ovis-Image",
        "Image",
        ["txt2img"],
        "Ovis-Image-7B Q4_0 GGUF with ovis-2.5 text encoder and flux VAE supported by sd.cpp.",
        [
            {"source": "hf", "model_id": "leejet/Ovis-Image-7B-GGUF", "files": ["ovis_image-Q4_0.gguf"]},
            {"source": "hf", "model_id": "Comfy-Org/Ovis-Image", "files": ["split_files/text_encoders/ovis_2.5.safetensors"]},
            dict(_FLUX_VAE),
        ],
    ),
    _model(
        "anima",
        "Anima",
        "Image",
        ["txt2img"],
        "Anima preview diffusion with qwen VAE and Qwen3-0.6B base text encoder supported by sd.cpp.",
        [
            {
                "source": "hf",
                "model_id": "circlestone-labs/Anima",
                "files": [
                    "split_files/diffusion_models/anima-preview.safetensors",
                    "split_files/vae/qwen_image_vae.safetensors",
                    "split_files/text_encoders/qwen_3_06b_base.safetensors",
                ],
            }
        ],
    ),
    _model(
        "ernie-image",
        "ERNIE-Image",
        "Image",
        ["txt2img"],
        "ERNIE-Image Turbo diffusion with flux2 VAE and ministral-3b text encoder supported by sd.cpp.",
        [
            {
                "source": "hf",
                "model_id": "Comfy-Org/ERNIE-Image",
                "files": [
                    "diffusion_models/ernie-image-turbo.safetensors",
                    "vae/flux2-vae.safetensors",
                    "text_encoders/ministral-3-3b.safetensors",
                ],
            }
        ],
    ),
    _model(
        "boogu-image",
        "Boogu Image",
        "Image",
        ["txt2img"],
        "Boogu Image base bf16 diffusion with flux VAE and Qwen3-VL-8B text encoder supported by sd.cpp.",
        [
            {
                "source": "hf",
                "model_id": "Comfy-Org/Boogu-Image",
                "files": ["diffusion_models/boogu_image_base_bf16.safetensors", "vae/flux1_vae_bf16.safetensors"],
            },
            dict(_QWEN3VL_8B_GGUF),
        ],
    ),
    _model(
        "boogu-image-edit",
        "Boogu Image Edit",
        "Image Edit",
        ["img2img", "edit"],
        "Boogu Image Edit bf16 diffusion with flux VAE and Qwen3-VL-8B text encoder supported by sd.cpp.",
        [
            {
                "source": "hf",
                "model_id": "Comfy-Org/Boogu-Image",
                "files": ["diffusion_models/boogu_image_edit_bf16.safetensors", "vae/flux1_vae_bf16.safetensors"],
            },
            dict(_QWEN3VL_8B_GGUF),
        ],
    ),
    _model(
        "krea2",
        "Krea2",
        "Image",
        ["txt2img"],
        "Krea-2 Base Q8_0 GGUF with wan 2.1 VAE and Qwen3-VL-4B text encoder supported by sd.cpp.",
        [
            {"source": "hf", "model_id": "realrebelai/KREA-2_GGUFs", "files": ["BASE/Krea-2-Base-Q8_0.gguf"]},
            dict(_WAN21_VAE),
            dict(_QWEN3VL_4B_GGUF),
        ],
    ),
    _model(
        "mage-flow",
        "Mage-Flow",
        "Image",
        ["txt2img"],
        "Mage-Flow Turbo transformer and VAE pulled through Model Hub (HF repo is gated), pair with Qwen3-VL-4B text encoder.",
        [
            {"source": "ms", "model_id": "microsoft/Mage-Flow-Turbo", "files": None},
            dict(_QWEN3VL_4B_GGUF),
        ],
    ),
    _model(
        "mage-flow-edit",
        "Mage-Flow Edit",
        "Image Edit",
        ["img2img", "edit"],
        "Mage-Flow Edit Turbo transformer and VAE pulled through Model Hub (HF repo is gated), pair with Qwen3-VL-4B text encoder.",
        [
            {"source": "ms", "model_id": "microsoft/Mage-Flow-Edit-Turbo", "files": None},
            dict(_QWEN3VL_4B_GGUF),
        ],
    ),
    _model(
        "sefi-image",
        "SeFi-Image",
        "Image",
        ["txt2img"],
        "SeFi-Image 5B turbo (HF gated repo; requires HF_TOKEN and sd.cpp conversion script before use).",
        [{"source": "hf", "model_id": "SeFi-Image/SeFi-Image-5B-turbo", "files": None}],
    ),
    _model(
        "hidream-o1",
        "HiDream-O1-Image",
        "Image",
        ["txt2img"],
        "HiDream-O1-Image dev bf16 all-in-one checkpoint supported by sd.cpp.",
        [
            {"source": "hf", "model_id": "Comfy-Org/HiDream-O1-Image", "files": ["checkpoints/hidream_o1_image_dev_bf16.safetensors"]}
        ],
    ),
    _model(
        "ideogram4",
        "Ideogram4",
        "Image",
        ["txt2img"],
        "Ideogram 4 fp8 transformer with unconditional transformer, text encoder and VAE supported by sd.cpp.",
        [
            {
                "source": "hf",
                "model_id": "ideogram-ai/ideogram-4-fp8",
                "files": [
                    "transformer/diffusion_pytorch_model.safetensors",
                    "unconditional_transformer/diffusion_pytorch_model.safetensors",
                    "text_encoder/model.safetensors",
                    "vae/diffusion_pytorch_model.safetensors",
                ],
            }
        ],
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


def get_model_def(key: str) -> dict[str, Any]:
    for item in MODEL_DEFS:
        if item["key"] == key:
            return item
    raise KeyError(key)


def _relative_candidates(item: dict[str, Any]) -> list[str]:
    if item["key"] == "sd15":
        slug = item["model_id"]
        return [
            f"export/ms/{slug}/current/v1-5-pruned-emaonly.safetensors",
            f"modelscope/vivibit/stable-diffusion-v1-5/v1-5-pruned-emaonly.safetensors",
            f"vivibit/stable-diffusion-v1-5/v1-5-pruned-emaonly.safetensors",
            f"export/ms/{slug}/current",
        ]
    candidates = []
    for spec in item["sources"]:
        rel = f"export/{spec['source']}/{spec['model_id']}/current"
        if rel not in candidates:
            candidates.append(rel)
    return candidates


def model_info(item: dict[str, Any]) -> ModelInfo:
    resolved = None
    size = None
    registered_files = list(item.get("files") or [])
    for rel in _relative_candidates(item):
        candidate = settings.modelhub_root / rel
        found = _resolve_model_file(candidate, registered_files[0] if registered_files else None)
        if found:
            resolved = found
            size = found.stat().st_size
            break

    fallback = settings.modelhub_root / _relative_candidates(item)[0]
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
        "access_path": str(fallback),
        "resolved_path": str(resolved) if resolved else None,
        "status": "ready" if resolved else "missing",
        "size": size,
    }
    hf_downloader.merge_state(item["key"], info)
    return ModelInfo(**info)


def runtime_paths_for(key: str) -> dict[str, Path]:
    """按 runtime 角色解析辅助文件（VAE / 文本编码器等）的实际路径。

    角色值是仓库内相对路径。优先在各来源的 current 目录下查找；若未命中
    （current 只指向某一 revision 的 snapshot，而历史下载可能把部分文件
    下到了 main/其他 revision 目录），回退扫描该仓库所有 snapshot 目录，
    命中即用，避免"同仓库多文件分散到不同 snapshot 导致辅助文件缺失"。
    """
    item = get_model_def(key)
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


async def pull_model(key: str, force: bool = False) -> dict[str, Any]:
    item = get_model_def(key)
    primary = item["sources"][0]
    if primary["source"] == "ms":
        payload = {"source": "ms", "model_id": primary["model_id"], "name": item["name"], "force": force}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{settings.model_hub_api_url}/api/v1/models/pull", json=payload)
            if resp.status_code == 409:
                return {"status": "active", "model_id": primary["model_id"], "detail": resp.json().get("detail", "")}
            resp.raise_for_status()
            return {"status": "submitted", "model_id": primary["model_id"], "task": resp.json()}
    file_entries = [name for spec in item["sources"] if spec["source"] == "hf" for name in (spec.get("files") or [])]
    if not file_entries:
        raise ValueError("该模型未配置下载文件清单（gated 仓库需要先在 HuggingFace 接受协议并配置 HF_TOKEN）")
    started = await hf_downloader.start_download(key, item["sources"], force=force)
    return {
        "status": "started" if started else "active",
        "model_id": primary["model_id"],
        "files": [f"{spec['model_id']}/{name}" for spec in item["sources"] if spec["source"] == "hf" for name in (spec.get("files") or [])],
    }


async def stop_model(key: str) -> dict[str, Any]:
    get_model_def(key)
    stopped = hf_downloader.request_cancel(key)
    return {"status": "cancelled" if stopped else "not_running", "model_id": get_model_def(key)["model_id"]}


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
                }
            tasks_resp = await client.get(f"{settings.model_hub_api_url}/api/v1/tasks")
            if tasks_resp.status_code == 200:
                for task in tasks_resp.json():
                    model_id = str(task.get("model_id", "")).replace("ms://", "").replace("hf://", "")
                    state = states.setdefault(model_id, {})
                    phase = task.get("phase")
                    if phase == "DOWNLOADING":
                        state["status"] = "pulling"
                        state["progress"] = task.get("progress")
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
    status = hub_state.get("status")
    if status in ("pulling", "PULLING"):
        info["status"] = "downloading"
        progress = hub_state.get("progress")
        info["progress"] = float(progress) if isinstance(progress, (int, float)) else None
    elif status in ("failed", "FAILED") and info["status"] != "ready":
        info["status"] = "failed"
        info["error"] = hub_state.get("error") or ""


async def list_model_defs_with_hub_state() -> list[ModelInfo]:
    """列出模型并合并双端下载状态：本应用 HF 任务 + Model Hub 拉取任务。"""
    hub_states = await fetch_model_hub_states()
    result = []
    for item in MODEL_DEFS:
        info = model_info(item)
        payload = info.model_dump()
        merge_model_hub_state(hub_states.get(info.model_id), payload)
        info = ModelInfo(**payload)
        result.append(info)
    return result


async def assert_model_hub_ready(key: str) -> None:
    item = get_model_def(key)
    hub_states = await fetch_model_hub_states()
    for spec in item["sources"]:
        state = hub_states.get(spec["model_id"])
        if not state:
            continue
        status = state.get("status")
        if status in ("pulling", "PULLING"):
            raise FileNotFoundError(f"Model Hub 仍在下载: {spec['model_id']}")


def model_path_for(key: str) -> Path:
    info = get_model(key)
    if not info.resolved_path:
        raise FileNotFoundError(info.access_path)
    return Path(info.resolved_path)
