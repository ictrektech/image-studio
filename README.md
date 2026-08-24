# Image Studio

Image Studio is a VOS app for local Stable Diffusion / `stable-diffusion.cpp`
image generation. It provides a browser workspace for text-to-image requests,
job tracking, generated-file access, and Model Hub backed model management.

## Scope

- Generate images from prompts through a local `sd-cli` compatible runtime.
- Keep VOS user sessions, language preference, and generated files separated
  under the app data path.
- Expose HTTP APIs that same-account VOS apps can call through the VOS gateway.
- Manage required diffusion model files through Model Hub paths and APIs.
- Package as a VOS pull-mode app with `amd`, `amd-cuda`, `arm`, `arm-cuda`,
  `l4t`, and `thor` profiles.

## Runtime API

The VOS gateway exposes the backend at:

```text
/api/com.ictrek.image-studio
```

Main endpoints:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Service health |
| `GET` | `/api/v1/about` | Runtime and path information |
| `GET` | `/api/v1/settings` | Current VOS user's app settings |
| `PUT` | `/api/v1/settings` | Save current VOS user's language preference |
| `POST` | `/api/v1/generate` | Create a generation job |
| `GET` | `/api/v1/jobs` | List current user's jobs |
| `GET` | `/api/v1/jobs/{job_id}` | Read one job |
| `GET` | `/api/v1/outputs` | List generated files for current user |
| `GET` | `/api/v1/outputs/{job_id}/{filename}` | Download one generated file |
| `GET` | `/api/v1/models` | List managed model definitions and state |
| `POST` | `/api/v1/models/{key}/pull` | Trigger Model Hub pull |
| `POST` | `/api/v1/models/{key}/sync` | Ask Model Hub to sync local model registry |

## Model Hub Integration

The default SD 1.5 model is expected from Model Hub:

```text
/modelhub/export/ms/vivibit/stable-diffusion-v1-5/current/v1-5-pruned-emaonly.safetensors
```

The app also checks the raw ModelScope snapshot layout:

```text
/modelhub/modelscope/vivibit/stable-diffusion-v1-5/v1-5-pruned-emaonly.safetensors
```

At install time, set `MODEL_HUB_SHARED_MODELS_PATH` to the same shared model
root used by Model Hub, usually `/data/vos_workspace/model_hub`.

## Development

Backend:

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 5000 --reload
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

## Docker Images

The Dockerfiles default to ictrek mirrored base images rather than direct
Docker Hub names. Before building on a new target, mirror the base images on
the matching host:

| Profile | Host | Base image tags |
| --- | --- | --- |
| `amd`, `amd-cuda` | `tc232` | `amd_3.12-slim`, `amd_22-alpine`, `amd_alpine` |
| `arm`, `arm-cuda`, `l4t` | `tc192` | `arm_3.12-slim`, `arm_22-alpine`, `arm_alpine`, `l4t_3.12` |
| `thor` | `tc97` | `thor_3.12`, `thor_22-alpine`, `thor_alpine` |

Build script entrypoint:

```bash
./docker/build_image.sh --sheet AMD_with_cuda
./docker/build_image.sh --sheet AMD_with_mxn100
./docker/build_image.sh --sheet ARM_with_cuda
./docker/build_image.sh --sheet ARM_without_cuda
./docker/build_image.sh --sheet l4t
./docker/build_image.sh --sheet thor_spark
```

## VOS Package

```bash
cd ictrek.app
./scripts/package.sh
```

The package is written to `ictrek.app/dist/image_studio_<version>_pull.tar`.
