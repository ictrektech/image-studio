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
| `GET` | `/api/v1/v-router/registration` | Registration payload for V-Router to discover Image Studio's own ready local models |
| `POST` | `/api/v1/models/{key}/pull` | Trigger Model Hub pull from ModelScope |
| `POST` | `/api/v1/models/{key}/stop` | Stop an in-flight download (resumable) |
| `POST` | `/api/v1/models/{key}/sync` | Ask Model Hub to sync local model registry |
| `GET` | `/api/v1/immich` | Read per-user Immich settings (never returns the API key) |
| `PUT` | `/api/v1/immich` | Save per-user Immich base URL / API key (key is stored server-side, never returned) |
| `POST` | `/api/v1/jobs/{job_id}/immich-upload` | Queue a succeeded job's outputs for upload to Immich (`?force=true` re-queues already completed outputs) |
| `POST` | `/api/v1/jobs/{job_id}/immich-upload/retry` | Re-queue failed outputs |

## Immich Integration

Image Studio can upload completed images and videos to a self-hosted Immich
instance. The browser never talks to Immich directly — the backend holds the
credentials and performs the upload.

- **Zero-touch mode (no API key application needed)**: users never create or
  paste an Immich API key, and there is no Immich settings form or persisted
  credential of any kind — vos-exchange is the only path. On the first upload
  the backend posts the caller's VOS access token to Immich's
  `POST /oauth/vos-exchange` endpoint, which verifies the token (issuer,
  audience and JWKS signature), resolves or creates the matching Immich user,
  and returns a dedicated key limited to `asset.upload`. The key lives only in
  the backend's process memory: the upload queue, retries and background
  workers reuse it, it never touches disk, and a backend restart simply
  exchanges a fresh key on the next upload (the user must be present with a
  valid VOS token). No Immich admin credentials are involved anywhere.
  `GET /api/v1/immich` reports a connectivity status for the UI
  (`disabled` / `pending` / `connected` / `unreachable` / `error`, plus a
  `detail` reason), probed with a live Immich `server/ping`; requests without
  a VOS token are rejected with `409`, and disabling
  `IMAGE_STUDIO_IMMICH_AUTO_PROVISION` turns the feature (and Immich uploads)
  off.
- The Immich address goes through the platform internal gateway (Traefik
  `web-internal`, plain HTTP without TLS) and is addressed by app path prefix,
  so no per-app host port has to be memorised:
  `http://172.17.0.1:1182/app/com.ictrek.ai-album/api`. It is derived from
  `VOS_HOST_GW_IP` and `VOS_API_GW_PORT_INTERNAL` (default `172.17.0.1:1182`);
  set `IMAGE_STUDIO_IMMICH_API_URL` only to point somewhere else. The VOS
  userinfo endpoints used for token verification are derived the same way.
- Keys never touch disk and are never returned by any endpoint; the settings
  files carry no Immich fields at all.
- A cached key can stop being accepted by Immich — typically after Immich is
  redeployed/reinstalled and the same VOS identity maps to a different Immich
  user. A `401`/`403` while uploading is therefore treated as a stale-credential
  signal, not a final failure: the backend drops the cached key, re-runs
  `POST /oauth/vos-exchange` once with the remembered VOS token, and retries the
  same request with the new key. Only a rejection after that re-exchange (or a
  failed re-exchange) marks the upload as failed, so a redeployed Immich does
  not require a backend restart and the user does not need to retry by hand.
  Each upload attempt re-exchanges at most once, which keeps a failing exchange
  from looping.
- HTTPS certificate verification is on by default; set
  `IMAGE_STUDIO_IMMICH_VERIFY_SSL=false` only for a self-signed HTTPS Immich
  endpoint (disabling it exposes uploads to man-in-the-middle interception —
  prefer installing the Immich CA certificate instead). The internal gateway
  address is plain HTTP, where this flag has no effect.
- A generation job must be `succeeded` before its outputs can be uploaded.
  Each output is uploaded through:
  1. `POST /assets/bulk-upload-check` (SHA-1 dedupe),
  2. `POST /assets` only when the server reports the asset is new.
- Uploads run in a single background worker with a bounded retry for transient
  errors; status is persisted on the `JobRecord` (`immich_uploads`), and
  unfinished uploads are re-queued after a restart.
- Deleting a job removes its local queued uploads but never deletes remote
  Immich assets.
- Duplicate detection has three layers:
  1. Outputs already `queued`, `uploading`, `uploaded`, or `duplicate` on the
     `JobRecord` are skipped without contacting Immich.
  2. The SHA-1 checksum is checked with `POST /assets/bulk-upload-check`, so
     byte-identical outputs from *different* jobs are only stored once.
  3. Immich itself keys assets by `(deviceId, deviceAssetId)`.
- Because layer 1 is local state, deleting an asset in Immich does not make the
  job re-uploadable by default. Pass `?force=true` (the frontend asks for
  confirmation first) to re-queue completed outputs.

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
The model management page can filter entries by supported capabilities such as
text-to-image, image-to-image, text-to-video, and image-to-video. Selecting
multiple capabilities uses AND semantics, so only model entries that support
every selected capability remain visible.

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

Quantized alternatives are exposed as model variants, not extra top-level
models: `GET /api/v1/models` still returns the 45 base model entries, and each
entry may include a `variants` list. Pass `model_variant` to generation or
`variant` to pull/stop APIs to use one of those quantized variants. Empty means
the default full-precision model. Variants can point to one or more ModelScope
repositories when a GGUF main model needs separate VAE or text-encoder files.
The frontend expands base models and variants into separate selectable entries
so quantized versions are visible and ordered independently.

When a model is ready, Image Studio resolves the largest compatible model file
under that directory (`.safetensors`, `.ckpt`, `.pt`, `.pth`, or `.gguf`) and
passes it to `sd-cli`.

## V-Router Integration

Image Studio has two separate V-Router integrations:

1. **Image Studio as a provider.** V-Router can discover or register Image
   Studio's own ready local models through `GET /api/v1/models` or
   `GET /api/v1/v-router/registration`. These models are exposed to V-Router
   with the `image-studio/` prefix and the `image_studio` protocol.
2. **Image Studio as a consumer.** Image Studio can read models already
   configured in V-Router from `IMAGE_STUDIO_V_ROUTER_API_URL`
   (default `http://v-router:8080`). Image Studio tries the `v-router` and
   `v-router-backend` aliases on `vos_default` first, then falls back to
   `IMAGE_STUDIO_V_ROUTER_HOST_API_URL` (default
   `http://host.docker.internal:22888`). It reports V-Router as unavailable
   only after every candidate fails. It adds eligible image/video
   entries to the generation picker with a `v-router/` key, calls V-Router's
   `/v1/images/generations`, `/v1/images/edits`, or `/v1/videos/generations`,
   and saves returned files into the normal Image Studio job output directory.

In the web UI, open **Models** to see a dedicated **V-Router cloud models**
section. It shows connection health and the number of eligible models, links to
V-Router for adding or editing providers through the current VOS shell route
(`/#/app/app-drawer/com.ictrek.v-router/v-router`, preserving the current
origin), and lists remote models separately
from models downloaded locally through Model Hub. The generation model picker
uses the same local/cloud grouping. A V-Router model is eligible when its model
row has an ID (`qualified` or `id`) and declares at least one of
`images/generations`, `images/edits`, `images/variations`, or
`videos/generations` in `endpoints`.

The consumer path filters out `image-studio/` rows returned by V-Router. This
prevents a routing loop where Image Studio calls V-Router, and V-Router routes
the request back into the same Image Studio instance.

`IMAGE_STUDIO_V_ROUTER_BASE_URL` is a different setting: it is the Image Studio
backend URL that V-Router should call when Image Studio is acting as a provider
(default `http://image-studio-backend:5000`). Do not set it to the V-Router API
URL.

## Video Generation

Video families (`wan21`, `wan22`, `wan21-t2v-14b`, `wan21-i2v-14b`,
`wan22-t2v-a14b`, `wan22-i2v-a14b`, `ltx-video`, `hunyuan-video`,
`hunyuan-i2v-720p`, `hunyuan-t2v-480p`, `minimax-h3`, `minimax-ref2va`,
`lingbot-video`) generate through the same job pipeline: the backend appends
`-M vid_gen`, passes the supported base parameters (`width`, `height`, `steps`,
`cfg_scale`, `sampler`, `seed`) plus `--video-frames` / `--fps`, and produces a
single browser-playable `output.webm`.
If sd-cli writes WebM-compatible VP8/VP9/AV1 frames with a Matroska container
doctype, the backend remuxes the file with ffmpeg before exposing it to the
browser; invalid AVI or non-WebM video payloads fail the job instead of being
served as `output.webm`.

Each model's `runtime.parameters` is the shared contract used by both frontend
controls and backend sd-cli argument assembly. Pure T2V models do not accept a
reference image; I2V/TI2V/Ref2VA models opt into `-i` or `-r` explicitly.
`--strength` and `batch_count` are not applied to video jobs. Families without
negative prompt support, or fixed-CFG families such as FLUX/turbo/MiniMax, have
those inputs disabled in the UI and normalized to runtime defaults on submit.
The same `runtime.parameters` contract covers advanced sd-cli controls exposed
in the UI/API: scheduler, clip skip, guidance, eta, flow shift, SLG, highres
fix, cache, RNG/prediction overrides, Qwen layered output, VAE tiling, temporal
tiling, VRAM budget, streaming, auto-fit, CPU offload, and backend assignment.
The generation workspace keeps model selection and common image controls in a
compact top toolbar, uses a wide generation canvas with a narrow task
inspector, and groups advanced and VRAM/runtime controls into expandable
sections. Video-specific controls only appear for video models.
The selected model entry and each model entry's last-used generation parameters
are stored in browser local storage. The reset action restores the current
model entry's runtime defaults without switching back to the first model.
Video jobs default to VAE tiling plus graph-split streaming with `max_vram=-2`
and retry VAE decode once on CPU when sd-cli reports CUDA/VAE allocation
failure.
Video jobs use a separate, much longer timeout
(`IMAGE_STUDIO_VIDEO_TIMEOUT_SECONDS`, default 3600).

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
| `arm`, `arm-cuda` | `tc35` | image tags `arm_YYYYMMDD` / `arm_cu128_YYYYMMDD` |
| `l4t` | `tc192` | image tag `l4t_YYYYMMDD` |
| `thor` | explicit Thor build host only | image tag `thor_YYYYMMDD` |

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
image is written to every selected ARM, L4T, Thor, and SOPHON sheet. The L4T
host check only applies when building the backend; frontend-only runs may update
the shared ARM frontend tag for L4T and Thor sheets from an ARM build host.

## VOS Package

### Profile caps

The package declares VOS 1.1+ profile caps:

- `amd`: `arch: amd64`
- `amd-cuda`: `arch: amd64`, `software: [cuda]`
- `arm`: `arch: arm64`
- `arm-cuda`: `device-type: generic`, `arch: arm64`, `software: [cuda]`
- `l4t`: `device-type` any of `l4t` or `jetson`, `arch: arm64`,
  `software: [cuda]`
- `thor`: `device-type` any of `thor-spark` or `thor`, `arch: arm64`,
  `software: [cuda]`

Hosts that should enable the dedicated Jetson/L4T or Thor profiles must expose
the matching `/etc/vos/caps/*.yaml` `device-type` value; generic ARM CUDA
hosts should use `device-type: generic`.

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
