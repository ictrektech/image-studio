# Image Studio

Image Studio is a VOS app for local Stable Diffusion / `stable-diffusion.cpp`
image generation. It provides a browser workspace for text-to-image requests,
job tracking, generated-file access, and Model Hub backed model management.

## Scope

- Generate images from prompts and continue from previously generated images
  through a local `sd-cli` compatible runtime.
- Keep VOS user sessions, language preference, and generated files separated
  under the app data path.
- Use VOS OIDC Fastpath when available, then verify tokens through VOS
  `/v1000/oauth2/userinfo`; legacy token probing is only a compatibility path.
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
| `GET` | `/api/v1/me` | Current session user key (who the token belongs to) |
| `GET` | `/api/v1/settings` | Current VOS user's app settings |
| `PUT` | `/api/v1/settings` | Save current VOS user's language preference |
| `POST` | `/api/v1/generate` | Create a generation job (non-blocking, returns job record) |
| `GET` | `/api/v1/jobs` | List current user's jobs |
| `GET` | `/api/v1/jobs/{job_id}` | Read one job |
| `DELETE` | `/api/v1/jobs/{job_id}` | Delete one job and its generated files |
| `GET` | `/api/v1/outputs` | List generated files for current user |
| `GET` | `/api/v1/outputs/{job_id}/{filename}` | Download one generated file |
| `POST` | `/api/v1/inputs` | Upload an img2img / edit reference image (png/jpg/jpeg/webp, ≤20MB), returns `input_id` |
| `GET` | `/api/v1/inputs` | List current user's uploaded reference images |
| `GET` | `/api/v1/inputs/{input_id}` | Download one uploaded reference image |
| `DELETE` | `/api/v1/inputs/{input_id}` | Delete one uploaded reference image |
| `GET` | `/api/v1/models` | List managed model definitions and state |
| `POST` | `/api/v1/models/{key}/pull` | Trigger Model Hub pull or HF direct download |
| `POST` | `/api/v1/models/{key}/stop` | Stop an in-flight download (resumable) |
| `POST` | `/api/v1/models/{key}/sync` | Ask Model Hub to sync local model registry |

### Authentication and user isolation

Every request is resolved to a VOS user and all jobs, outputs, and settings
are stored under that user's key:

- **Inside VOS (recommended):** same-account apps call through the VOS
  gateway with the logged-in user's `Authorization: Bearer <token>`. The
  backend verifies the token through VOS OIDC/userinfo and attributes the
  data to that account automatically.
- **Outside VOS:** obtain an access token for the target VOS account, then
  call `https://<vos-host>/api/com.ictrek.image-studio/...` with the same
  `Authorization` header. The token's account owns whatever it creates.
  Output files also accept `?access_token=` for browser/image-tag usage.
- **No token:** the request falls into an anonymous bucket derived from the
  origin fingerprint; data is tied to no account and should only be used
  for quick tests.

## Model Sources And Model Hub Integration

`stable-diffusion.cpp` is not limited to SD 1.5. Image Studio's backend model
registry exposes the sd.cpp-supported image, image-edit, and video model
families. The UI shows every managed entry with its family, capabilities,
shared path, and download/sync actions.

Two download paths coexist:

- **SD 1.5** keeps coming from Model Hub (`vivibit/stable-diffusion-v1-5` on
  ModelScope). Pulling it delegates to the Model Hub API, so the task and its
  progress appear natively in the Model Hub UI.
- **Every other family** downloads straight from HuggingFace inside the
  Image Studio backend, using the curated file list from the sd.cpp docs
  (diffusion model + required VAE / text encoders, GGUF quants where the docs
  recommend them). `HF_ENDPOINT` defaults to `https://hf-mirror.com` for
  mirror acceleration; override it (or `IMAGE_STUDIO_HF_ENDPOINT` in the VOS
  package) to download directly.

HF downloads are written in the Model Hub compatible layout, so both sides
stay in sync:

```text
<shared>/export/hf/<org>/<repo>/snapshots/<commit>/<repo-relative files>
```

After a download finishes, Image Studio calls `POST /api/v1/models/sync` on
Model Hub, which registers the repo, refreshes the `current` symlink, and
makes the model visible in the Model Hub UI. In the other direction,
Image Studio reads Model Hub's registry and task list to display pull
progress for Model Hub-managed models (SD 1.5, Mage-Flow).

All models resolve through the same shared-root convention:

```text
/modelhub/export/<ms|hf>/<org>/<repo>/current/
```

When a model is ready, Image Studio resolves the largest compatible model file
under that directory (`.safetensors`, `.ckpt`, `.pt`, `.pth`, or `.gguf`) and
passes it to `sd-cli`.

Notes:

- The Model Hub shared root must be mounted writable (the VOS package mounts
  it at `/modelhub` without `:ro`) so HF downloads can land in `export/hf`.
- Mage-Flow families pull through Model Hub from the official
  `microsoft/*` ModelScope mirrors because the HuggingFace repos are gated.
- SeFi-Image is registered but gated on HuggingFace: downloading requires an
  `HF_TOKEN` for an account that accepted the license, plus the sd.cpp
  conversion script before use.
- Multi-file families (FLUX, Qwen-Image, Wan, …) fetch only the doc-selected
  variants; expect roughly 5-40 GB per family.

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
| `amd`, `amd-cuda` | `tc232` | image tags `amd_YYYYMMDD` / `amd_cu128_YYYYMMDD` |
| `arm`, `arm-cuda`, `l4t` | `tc192` | image tags `arm_YYYYMMDD` / `arm_cu128_YYYYMMDD` / `l4t_YYYYMMDD` |
| `thor` | `tc97` | image tag `thor_YYYYMMDD` |

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
For formal releases, use `ictrek.app/scripts/update_version.sh`; GitHub Actions
is the authoritative package builder and VOS App Store publisher.
