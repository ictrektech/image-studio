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
| `DELETE` | `/api/v1/jobs/{job_id}` | Stop an active runtime, then delete the job and its generated files |
| `GET` | `/api/v1/outputs` | List generated files for current user |
| `GET` | `/api/v1/outputs/{job_id}/{filename}` | Download one generated file |
| `POST` | `/api/v1/inputs` | Upload an img2img / edit reference image (png/jpg/jpeg/webp, ≤20MB), returns `input_id` |
| `GET` | `/api/v1/inputs` | List current user's uploaded reference images |
| `GET` | `/api/v1/inputs/{input_id}` | Download one uploaded reference image |
| `DELETE` | `/api/v1/inputs/{input_id}` | Delete one uploaded reference image |
| `GET` | `/api/v1/models` | List managed model definitions and state |
| `POST` | `/api/v1/models/{key}/pull` | Trigger Model Hub pull from ModelScope |
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

All built-in entries are pulled by Model Hub from dedicated ModelScope runtime
repositories under `vivibit/image-studio-*`. Each repository contains the
curated file list Image Studio needs for exactly one model key: diffusion
weights plus required VAE, text encoder, vision encoder, tokenizer/config
files, or GGUF quants where the sd.cpp runtime expects them.

ModelScope downloads use the Model Hub compatible layout, so both sides stay in
sync:

```text
<shared>/export/ms/vivibit/image-studio-<key>/current/<repo-relative files>
```

`force=true` asks Model Hub to refresh the selected runtime repository. Image
Studio reads Model Hub's registry and task list to display pull progress,
local readiness, expected total size, and the resolved shared path.

All models resolve through the same shared-root convention:
```text
/modelhub/export/ms/vivibit/image-studio-<key>/current/
```

When a model is ready, Image Studio resolves the largest compatible model file
under that directory (`.safetensors`, `.ckpt`, `.pt`, `.pth`, or `.gguf`) and
passes it to `sd-cli`.

## Video Generation

Video families (`wan21`, `wan22`, `ltx-video`, `hunyuan-video`, `minimax-h3`,
`lingbot-video`) generate through the same job pipeline: the backend appends
`-M vid_gen` plus `--video-frames` / `--fps` from the request (0 = family
default from the sd.cpp docs) and produces a single `output.mp4`. Families
whose runtime declares a reference flag (Wan 2.2 TI2V, LTX, MiniMax, LingBot)
accept a first-frame image via the same `init_input_id` / `init_job_id`
mechanism; `--strength` is not applied for video. Video jobs use a separate,
much longer timeout (`IMAGE_STUDIO_VIDEO_TIMEOUT_SECONDS`, default 3600).
Parameters that do not apply to the selected family (e.g. `batch_count` for
video, `negative_prompt` for families without uncond support) are silently
ignored when assembling the sd-cli command line.

Deleting a running generation job first terminates and waits for its `sd-cli`
process, then removes metadata and outputs. On service startup, persisted jobs
left in `queued` or `running` by an earlier process are reconciled to `failed`
with a retry message.

Notes:

- The Model Hub shared root must be mounted writable (the VOS package mounts
  it at `/modelhub` without `:ro`) so ModelScope downloads can land in
  `export/ms`.
- Multi-file families (FLUX, Qwen-Image, Wan, SeFi, Ideogram, ...) fetch only
  the Image Studio-selected runtime files; expect roughly 4-70 GB per family.

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

Backend tags remain profile-specific. The frontend is architecture-only: one
`amd_<date>` image is written to every selected AMD sheet, and one `arm_<date>`
image is written to every selected ARM, L4T, Thor, and SOPHON sheet.

## VOS Package

```bash
cd ictrek.app
./scripts/package.sh
```

The package is written to `ictrek.app/dist/image_studio_<version>_pull.tar`.
For formal releases, use `ictrek.app/scripts/update_version.sh`; GitHub Actions
is the authoritative package builder and VOS App Store publisher.

The top-right **About** dialog reports the VOS app version, frontend and backend
image references, and the active deployment profile. These values are injected
by the VOS package at container startup, so they match the installed profile.
