# Image Studio API reference

Source reference for the next application release. In the app, open **API → Complete API and request/response fields**, or download OpenAPI JSON. The installed version's `/openapi.json` is authoritative; this source documentation update does not upgrade installed Image Studio instances.

## Endpoints and identity

VOS base URL: `https://<VOS-HOST>:1180/api/com.ictrek.image-studio`; same Docker network: `http://image-studio-backend:5000`. Append `/api/v1/...` below. VOS HTTPS port can differ. The native backend port must remain in a trusted network.

Use the same valid VOS Bearer token for generation, polling and files. Business APIs use verified VOS identity when available, then legacy trusted headers/token/IP attribution; token presence alone is not proof of verification. `/me.authenticated` reports token presence. Do not expose these fallbacks as a public authentication boundary. Settings and generated files use the derived user context; generation templates are shared application configuration. V-Scheduler inference keys apply to its unified model APIs, not Image Studio management. Vendor keys belong in provider settings. Scheduler binding requires the verified **V-Scheduler application identity**; execution callbacks require the separate executor token, not an ordinary user's key.

## Complete workflow

### Remote compute API

The overview, deployment and model preparation routes require a verified VOS system administrator Bearer token. The application backend uses its own Scheduler service identity for deployment, transfer and registration. Listing placements and submitting remote jobs require a verified VOS user. Use the VOS or container base URL above and send `application/json` for POST bodies.

| Request | Input and response |
| --- | --- |
| `GET /api/v1/compute` | No parameters. 200 returns `targets`, `deployments` and `preparations` arrays. An empty array means there are no matching records. |
| `POST /api/v1/compute/deployments` | Required `kind` (`ssh` or `cluster`), `node_id` and `request_key` (1–96 ASCII letters, digits, periods, underscores or hyphens). Replay the same key and parameters to recover an ambiguous result. 200 returns `id` and `state`. |
| `POST /api/v1/compute/deployments/{deployment_id}/models` | The path ID is 32 lowercase hex characters. `model_key` is required. `model_variant` defaults to the empty string. Each accepts up to 96 lowercase letters, digits, periods, underscores or hyphens. 202 returns a preparation record. Submitting the same deployment and model returns the active operation or resumes from confirmed offsets. |
| `GET /api/v1/compute/placements` | No parameters. 200 returns an array of placements with `deployment_id`, `model_id` (`key` or `key@variant`), `profile` (Image Studio runtime Profile), `runtime_parameters` (calibrated fields and approved values), and `has_reference` (whether a reference image is required). |
| `POST /api/v1/generate` | Optional `compute_deployment_id` selects the registered deployment. Omit it or send an empty string to use the main node. A nonempty ID is 32 lowercase hex characters. Match the model and variant and use the target's calibrated runtime values. Explicit runtime parameters must match the approved values. The response remains a `JobRecord`. |

Targets contain `kind`, `node_id`, `name`, `profile` (fixed hardware Profile), `runtime_profile` (Image Studio runtime Profile) and full `image`. Deployments contain `id`, `target_kind`, `target_id`, `profile`, `image`, `state` and nullable `last_error`. Deployment states are `pending`, `running`, `failed`, `stopping`, `deleting`, `stopped`, `removed` and `cleanup_failed`. Preparation records contain `deployment_id`, `model_id`, `state`, `received_bytes`, `total_bytes` and nullable `executor_id`, `node_id` and `error`. Counts are nonnegative bytes. Preparation states are `transferring`, `interrupted`, `registered` and `failed`. `total_bytes` can be 0 before transfer starts.

The preparation record's `weight_source` is `shared` for read-only NFS, `copy` for a node copy, or `null` while the source is pending. Image Studio tries to verify shared weights first. Copying is used when the mount is unavailable or shared files do not match the source revision. With shared weights, `received_bytes` counts verified bytes.

Grant the target and repository, deploy, and poll for `running`. Submit model preparation and poll for `registered`. Generate against that deployment, then use `GET /api/v1/jobs/{job_id}` and `GET /api/v1/outputs/{job_id}/{filename}` for results. For 401, sign in again. For 403, check the administrator role or deployment grant. For 404, check the deployment ID. For 409, check runtime and model readiness. For 422, correct the request or choose a model with the matching calibration. For 503, check the node, identity service and Scheduler. If preparation fails, inspect the record's `error`, resolve it and retry the same model.

### Main-node generation

```sh
export IMAGE_API='https://<VOS-HOST>:1180/api/com.ictrek.image-studio'
curl --fail-with-body -H "Authorization: Bearer $VOS_TOKEN" "$IMAGE_API/api/v1/models"
# Choose a ready model key and variant from that response; do not use a model from another machine/profile.
curl --fail-with-body -X POST "$IMAGE_API/api/v1/generate" \
  -H "Authorization: Bearer $VOS_TOKEN" -H 'Content-Type: application/json' \
  -d '{"prompt":"A small red house","model_key":"<ready-key>","model_variant":"<variant-or-empty>","width":512,"height":512,"steps":4,"batch_count":1,"scheduling":{"priority":"interactive"}}'
# Save top-level job_id, not data.job_id. Poll until succeeded or failed.
curl --fail-with-body -H "Authorization: Bearer $VOS_TOKEN" "$IMAGE_API/api/v1/jobs/$JOB_ID"
# After succeeded, copy one filename from outputs; inspect Content-Type before saving.
curl --fail-with-body -H "Authorization: Bearer $VOS_TOKEN" \
  -o output.png "$IMAGE_API/api/v1/outputs/$JOB_ID/$FILENAME"
```

The example is a template, not a measured hardware preset; use the selected model's supported dimensions/steps. `ready` means weights are ready, not that Scheduler capacity is granted. Native JSON has no `{code,data}` envelope. HTTP200 accepting a job does not prove generation completed: inspect `status`, `progress`, `outputs`, `error` and metadata, then check the artifact. Poll with bounded deadlines/backoff; a client timeout does not cancel computation. The API has no universal inference idempotency key: do not blindly repeat a timed-out POST.

For img2img, upload `file` with `POST /api/v1/inputs` (multipart, png/jpg/jpeg/webp, at most20MiB), then set `init_input_id` in GenerateRequest. Alternatively use your own successful `init_job_id` and `init_filename`. `POST /models/{key}/stop` cancels **weight downloads**, not running generation. `DELETE /jobs/{job_id}` first cancels execution/uploads, then deletes that job and its outputs; it is not a nondestructive stop endpoint. PhotoCraft handoffs return a URL for one owned output and fractional Unix `expires_at`; tickets live in memory for300seconds and also expire on process restart. A missing/expired handoff returns404. Immich upload returns202 with JobRecord; inspect its per-file `immich_uploads` state for actual upload completion.

## Configuration, errors and scheduling

GenerateRequest exposes model/variant, reference inputs, image/video controls, runtime memory settings and request-level `scheduling` (priority, preemptible, allow_preemption, force_admission as supported by SchedulingOptions). Scheduler task acceptance, actual computation and confirmed stop remain separate. Model registration/binding and fresh heartbeats do not grant a resource budget. Binding revisions, execution settings and per-model approvals must match; do not hand-edit the private callback URL, tokens or hardware profile to bypass checks. `/scheduler/binding` configured=true indicates a valid saved binding, not current available resources.

Inspect status and Content-Type before parsing. FastAPI errors use `detail` (message or validation list); unhandled server/gateway errors may be text. Correct422 fields, reconcile404 model/job references, resolve409 missing weights/binding revision conflicts, and respect429/503 resource/dependency failures. A job can fail after a successful HTTP submission. Files are binary, not JSON. Use full current OpenAPI fields below instead of copying a schema from another release. Swagger assets can be unreachable on networks in mainland China; OpenAPI JSON remains available through the local gateway.


## Operations and responses

### GET /api/v1/about

Identity: public operation / boundary described above

Response 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `app_id` | string | Required |  |
| `app_version` | string | Required |  |
| `profile` | string | Required |  |
| `data_dir` | string | Required |  |
| `modelhub_root` | string | Required |  |
| `model_hub_api_url` | string | Required |  |
| `sd_cpp_bin` | string | Required |  |
| `max_concurrency` | integer | Required |  |

Response default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Required | FastAPI error message or structured validation details. |

`text/plain`

`string`

### GET /api/v1/templates

Identity: public operation / boundary described above

Response 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `templates` | array<TemplateRecord> | Required |  |
| `default_template` | string  /  null | Required |  |

Response default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Required | FastAPI error message or structured validation details. |

`text/plain`

`string`

### POST /api/v1/templates

Identity: public operation / boundary described above

Request body: application/json

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `name` | string | Optional |  |
| `payload` | object | Required | Allowed keys: model_key, model_variant, width, height, steps, cfg_scale, sampler, vae_tiling, vae_tile_size, negative_prompt. |

Response 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`TemplateRecord`

Response 422 — Validation Error

`application/json`

`HTTPValidationError`

Response default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Required | FastAPI error message or structured validation details. |

`text/plain`

`string`

### PATCH /api/v1/templates/{template_id}

Identity: public operation / boundary described above

- `path: template_id` · string · Required · 

Request body: application/json

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `name` | string | Optional |  |

Response 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`TemplateRecord`

Response 422 — Validation Error

`application/json`

`HTTPValidationError`

Response default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Required | FastAPI error message or structured validation details. |

`text/plain`

`string`

### DELETE /api/v1/templates/{template_id}

Identity: public operation / boundary described above

- `path: template_id` · string · Required · 

Response 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `ok` | boolean | Required |  |

Response 422 — Validation Error

`application/json`

`HTTPValidationError`

Response default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Required | FastAPI error message or structured validation details. |

`text/plain`

`string`

### GET /api/v1/me

Identity: VOSBearer / trusted-network compatibility mode

Response 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `user_key` | string | Required |  |
| `authenticated` | boolean | Required | Indicates token presence, not proof that the token was verified. |

Response default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Required | FastAPI error message or structured validation details. |

`text/plain`

`string`

### GET /api/v1/settings

Identity: VOSBearer / trusted-network compatibility mode

Response 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `language` | string | Required |  · enum=["auto", "zh-CN", "zh-TW", "en"] |

Response default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Required | FastAPI error message or structured validation details. |

`text/plain`

`string`

### PUT /api/v1/settings

Identity: VOSBearer / trusted-network compatibility mode

Request body: application/json

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `language` | string | Optional |  · enum=["auto", "zh-CN", "zh-TW", "en"] |

Response 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `language` | string | Required |  · enum=["auto", "zh-CN", "zh-TW", "en"] |

Response 422 — Validation Error

`application/json`

`HTTPValidationError`

Response default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Required | FastAPI error message or structured validation details. |

`text/plain`

`string`

### GET /api/v1/immich

Identity: public operation / boundary described above

Immich connection status; no credentials are returned. See the five states in ImmichStatusResponse.

Response 200 — Successful Response

`application/json`

`ImmichStatusResponse`

Response default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Required | FastAPI error message or structured validation details. |

`text/plain`

`string`

### POST /api/v1/generate

Identity: VOSBearer / trusted-network compatibility mode

Request body: application/json

`GenerateRequest`

Response 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`JobRecord`

Response 422 — Validation Error

`application/json`

`HTTPValidationError`

Response default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Required | FastAPI error message or structured validation details. |

`text/plain`

`string`

### GET /api/v1/jobs

Identity: VOSBearer / trusted-network compatibility mode

Response 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`array<JobRecord>`

Response default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Required | FastAPI error message or structured validation details. |

`text/plain`

`string`

### POST /api/v1/jobs/{job_id}/immich-upload

Identity: VOSBearer / trusted-network compatibility mode

- `path: job_id` · string · Required · 

- `query: force` · boolean · Optional · 

Response 202 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`JobRecord`

Response 422 — Validation Error

`application/json`

`HTTPValidationError`

Response default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Required | FastAPI error message or structured validation details. |

`text/plain`

`string`

### POST /api/v1/jobs/{job_id}/immich-upload/retry

Identity: VOSBearer / trusted-network compatibility mode

- `path: job_id` · string · Required · 

Response 202 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`JobRecord`

Response 422 — Validation Error

`application/json`

`HTTPValidationError`

Response default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Required | FastAPI error message or structured validation details. |

`text/plain`

`string`

### GET /api/v1/jobs/{job_id}

Identity: VOSBearer / trusted-network compatibility mode

- `path: job_id` · string · Required · 

Response 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`JobRecord`

Response 422 — Validation Error

`application/json`

`HTTPValidationError`

Response default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Required | FastAPI error message or structured validation details. |

`text/plain`

`string`

### DELETE /api/v1/jobs/{job_id}

Identity: VOSBearer / trusted-network compatibility mode

- `path: job_id` · string · Required · 

Response 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `deleted` | boolean | Required |  |
| `job_id` | string | Required |  |

Response 422 — Validation Error

`application/json`

`HTTPValidationError`

Response default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Required | FastAPI error message or structured validation details. |

`text/plain`

`string`

### GET /api/v1/outputs

Identity: VOSBearer / trusted-network compatibility mode

Response 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`array<GeneratedOutput>`

Response default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Required | FastAPI error message or structured validation details. |

`text/plain`

`string`

### GET /api/v1/outputs/{job_id}/{filename}

Identity: VOSBearer / trusted-network compatibility mode

- `path: job_id` · string · Required · 

- `path: filename` · string · Required · 

Response 200 — Binary file. Inspect Content-Type; errors remain JSON. PhotoCraft handoffs require the expiring ticket in the URL.

`*/*`

`string`

Response 422 — Validation Error

`application/json`

`HTTPValidationError`

Response default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Required | FastAPI error message or structured validation details. |

`text/plain`

`string`

### POST /api/v1/jobs/{job_id}/photocraft

Identity: VOSBearer / trusted-network compatibility mode

- `path: job_id` · string · Required · 

Request body: application/json

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `filename` | string | Required |  |

Response 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `url` | string | Required |  |
| `expires_at` | number | Required | Unix seconds; fractional seconds are retained. The ticket expires after 300 seconds. |

Response 422 — Validation Error

`application/json`

`HTTPValidationError`

Response default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Required | FastAPI error message or structured validation details. |

`text/plain`

`string`

### GET /api/v1/photocraft/handoffs/{ticket}/{filename}

Identity: public operation / boundary described above

- `path: ticket` · string · Required · 

- `path: filename` · string · Required · 

Response 200 — Binary file. Inspect Content-Type; errors remain JSON. PhotoCraft handoffs require the expiring ticket in the URL.

`*/*`

`string`

Response 422 — Validation Error

`application/json`

`HTTPValidationError`

Response default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Required | FastAPI error message or structured validation details. |

`text/plain`

`string`

### GET /api/v1/inputs

Identity: VOSBearer / trusted-network compatibility mode

Response 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`array<InputFile>`

Response default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Required | FastAPI error message or structured validation details. |

`text/plain`

`string`

### POST /api/v1/inputs

Identity: VOSBearer / trusted-network compatibility mode

Upload an img2img/edit reference (png/jpg/jpeg/webp, at most 20 MiB); returns an input_id for generation.

Request body: multipart/form-data

`Body_upload_input_api_v1_inputs_post`

Response 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`InputFile`

Response 422 — Validation Error

`application/json`

`HTTPValidationError`

Response default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Required | FastAPI error message or structured validation details. |

`text/plain`

`string`

### GET /api/v1/inputs/{input_id}

Identity: VOSBearer / trusted-network compatibility mode

- `path: input_id` · string · Required · 

Response 200 — Binary file. Inspect Content-Type; errors remain JSON. PhotoCraft handoffs require the expiring ticket in the URL.

`*/*`

`string`

Response 422 — Validation Error

`application/json`

`HTTPValidationError`

Response default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Required | FastAPI error message or structured validation details. |

`text/plain`

`string`

### DELETE /api/v1/inputs/{input_id}

Identity: VOSBearer / trusted-network compatibility mode

- `path: input_id` · string · Required · 

Response 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `deleted` | boolean | Required |  |
| `input_id` | string | Required |  |

Response 422 — Validation Error

`application/json`

`HTTPValidationError`

Response default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Required | FastAPI error message or structured validation details. |

`text/plain`

`string`

### GET /api/v1/models

Identity: public operation / boundary described above

Response 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`array<ModelInfo>`

Response default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Required | FastAPI error message or structured validation details. |

`text/plain`

`string`

### GET /api/v1/v-router/registration

Identity: public operation / boundary described above

- `query: ready_only` · boolean · Optional · 

Response 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `service_id` | string | Required |  |
| `name` | string | Required |  |
| `visibility` | string | Required |  |
| `protocol` | string | Required |  |
| `base_url` | string | Required |  |
| `model_kind` | string | Required |  |
| `models` | array<object> | Required |  |
| `ttl_seconds` | integer | Required |  |
| `scheduler` | object | Required |  |
| `scheduler.protocol_version` | integer | Required |  |
| `scheduler.lifecycle_protocol_version` | integer | Required |  |
| `scheduler.preemption_modes` | array<string> | Required |  |
| `scheduler.app_id` | string | Required |  |
| `scheduler.binding_endpoint` | string | Required |  |
| `scheduler.executor_base_url` | string | Required |  |
| `scheduler.upstream_url` | string | Required |  |
| `scheduler.async_models` | array<object> | Required |  |
| `scheduler.execution_settings` | object | Required |  |
| `scheduler.binding` | SchedulerBindingStatus | Required |  |

Response 422 — Validation Error

`application/json`

`HTTPValidationError`

Response default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Required | FastAPI error message or structured validation details. |

`text/plain`

`string`

### GET /api/v1/v-router/status

Identity: public operation / boundary described above

Response 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `configured` | boolean | Required |  |
| `reachable` | boolean | Required |  |
| `api_url` | string | Required |  |
| `eligible_models` | integer | Required |  |
| `error` | string | Required |  |

Response default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Required | FastAPI error message or structured validation details. |

`text/plain`

`string`

### GET /api/v1/models/{key}

Identity: public operation / boundary described above

- `path: key` · string · Required · 

- `query: variant` · string · Optional · 

Response 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`ModelInfo`

Response 422 — Validation Error

`application/json`

`HTTPValidationError`

Response default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Required | FastAPI error message or structured validation details. |

`text/plain`

`string`

### POST /api/v1/models/{key}/pull

Identity: public operation / boundary described above

- `path: key` · string · Required · 

- `query: force` · boolean · Optional · 

- `query: variant` · string · Optional · 

Response 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `status` | string | Required |  |
| `model_id` | string | Required |  |
| `variant` | string | Required |  |
| `sources` | array<DownloadSourceSubmission> | Required |  |

Response 422 — Validation Error

`application/json`

`HTTPValidationError`

Response default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Required | FastAPI error message or structured validation details. |

`text/plain`

`string`

### POST /api/v1/models/{key}/stop

Identity: public operation / boundary described above

- `path: key` · string · Required · 

- `query: variant` · string · Optional · 

Response 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `status` | string | Required |  |
| `model_id` | string | Required |  |
| `variant` | string | Required |  |
| `tasks` | array<JSON> | Optional |  |

Response 422 — Validation Error

`application/json`

`HTTPValidationError`

Response default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Required | FastAPI error message or structured validation details. |

`text/plain`

`string`

### POST /api/v1/models/{key}/sync

Identity: public operation / boundary described above

- `path: key` · string · Required · 

Response 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `synced` | integer | Required |  |
| `hf_added` | integer | Required |  |
| `ms_added` | integer | Required |  |
| `ollama_added` | integer | Required |  |
| `message` | string | Required |  |

Response 422 — Validation Error

`application/json`

`HTTPValidationError`

Response default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Required | FastAPI error message or structured validation details. |

`text/plain`

`string`

### POST /api/v1/scheduler/executions/{attempt}/start

Identity: ExecutorBearer

- `path: attempt` · string · Required · 

Request body: application/json

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `fence` | integer | Required |  |
| `parameters` | object | Required |  |
| `parameters.user_key` | string | Required |  |
| `parameters.job_id` | string | Required |  |
| `lease_seconds` | integer | Optional |  |
| `preempted` | boolean | Optional |  |

Response 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`ExecutionStatus`

Response 422 — Validation Error

`application/json`

`HTTPValidationError`

Response default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Required | FastAPI error message or structured validation details. |

`text/plain`

`string`

### POST /api/v1/scheduler/executions/{attempt}/inspect

Identity: ExecutorBearer

- `path: attempt` · string · Required · 

Request body: application/json

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `fence` | integer | Required |  |

Response 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`ExecutionStatus`

Response 422 — Validation Error

`application/json`

`HTTPValidationError`

Response default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Required | FastAPI error message or structured validation details. |

`text/plain`

`string`

### POST /api/v1/scheduler/executions/{attempt}/cancel

Identity: ExecutorBearer

- `path: attempt` · string · Required · 

Request body: application/json

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `fence` | integer | Required |  |
| `parameters` | object | Required |  |
| `parameters.user_key` | string | Required |  |
| `parameters.job_id` | string | Required |  |
| `preempted` | boolean | Optional |  |

Response 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`ExecutionStatus`

Response 422 — Validation Error

`application/json`

`HTTPValidationError`

Response default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Required | FastAPI error message or structured validation details. |

`text/plain`

`string`

### GET /api/v1/scheduler/binding

Identity: public operation / boundary described above

Response 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`SchedulerBindingStatus`

Response default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Required | FastAPI error message or structured validation details. |

`text/plain`

`string`

### POST /api/v1/scheduler/binding

Identity: SchedulerApplication

Request body: application/json

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `protocol_version` | integer | Required |  · const=1 |
| `binding_revision` | integer | Required |  · minimum=1 |
| `app_id` | string | Required |  · const="com.ictrek.image-studio" |
| `url` | string | Required | Application binding snapshot; this legacy alias is not a caller-selected provider address. · const="http://v-router:8080/scheduler/api/v1" |
| `upstream_url` | string | Required |  · const="http://image-studio-backend:5000" |
| `token` | string | Required | Provisioned Scheduler service identity, never an upstream vendor key. · minLength=32 · maxLength=4096 |
| `executor_token` | string | Required |  · minLength=32 · maxLength=4096 |
| `models` | object | Required |  |
| `gateway_executors` | object | Optional |  |
| `model_limits` | object | Required |  |
| `model_limits.{key}.width` | integer | Required |  · minimum=0 |
| `model_limits.{key}.height` | integer | Required |  · minimum=0 |
| `model_limits.{key}.steps` | integer | Required |  · minimum=0 |
| `model_limits.{key}.batch_count` | integer | Required |  · minimum=0 |
| `model_limits.{key}.video_frames` | integer | Required |  · minimum=0 |
| `model_limits.{key}.prompt_characters` | integer | Required |  · minimum=0 |
| `model_limits.{key}.negative_prompt_characters` | integer | Required |  · minimum=0 |
| `model_parameters` | object | Required |  |
| `model_parameters.{key}.weight_type` | string | Required |  · default="" |
| `model_parameters.{key}.tensor_type_rules` | string | Required |  · default="" |
| `model_parameters.{key}.cache_mode` | string | Required |  · default="" |
| `model_parameters.{key}.cache_option` | string | Required |  · default="" |
| `model_parameters.{key}.qwen_image_layers` | integer | Required |  · default=0 |
| `model_parameters.{key}.vae_tiling` | boolean | Required |  · default=false |
| `model_parameters.{key}.vae_tile_size` | string | Required |  · default="" |
| `model_parameters.{key}.vae_tile_overlap` | number | Required |  · default=0.5 |
| `model_parameters.{key}.temporal_tiling` | boolean | Required |  · default=false |
| `model_parameters.{key}.temporal_tile_frames` | integer | Required |  · default=4 |
| `model_parameters.{key}.temporal_tile_overlap` | integer | Required |  · default=1 |
| `model_parameters.{key}.max_vram` | number | Required |  · default=0.0 |
| `model_parameters.{key}.stream_layers` | boolean | Required |  · default=false |
| `model_parameters.{key}.auto_fit` | boolean | Required |  · default=false |
| `model_parameters.{key}.clip_on_cpu` | boolean | Required |  · default=false |
| `model_parameters.{key}.offload_to_cpu` | boolean | Required |  · default=false |
| `model_parameters.{key}.vae_cpu_fallback` | boolean | Required |  · default=false |
| `model_parameters.{key}.backend` | string | Required |  · default="" |
| `model_parameters.{key}.params_backend` | string | Required |  · default="" |
| `model_parameters.{key}.has_reference` | boolean | Required |  |
| `execution_settings` | object | Required |  |
| `execution_settings.profile` | string | Required |  |
| `execution_settings.runtime` | string | Required |  |
| `execution_settings.logical_cpu_count` | integer  /  null | Required |  |
| `execution_settings.max_concurrency` | integer | Required |  |
| `execution_settings.sd_cpp_extra_args_sha256` | string | Required |  |

Response 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `configured` | boolean | Required |  |
| `binding_revision` | integer | Required |  |

Response default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Required | FastAPI error message or structured validation details. |

`text/plain`

`string`

### GET /health

Identity: public operation / boundary described above

Response 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `status` | string | Required |  |
| `app` | string | Required |  |
| `version` | string | Required |  |

Response default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | JSON | Required | FastAPI error message or structured validation details. |

`text/plain`

`string`

## Shared data types

Field names retain their API spelling. Interpret extension metadata according to its owning service.

### Body_upload_input_api_v1_inputs_post

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `file` | string | Required |  |

### GenerateRequest

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `scheduling` | SchedulingOptions  /  null | Optional |  |
| `prompt` | string | Required |  · minLength=1 · maxLength=4000 |
| `negative_prompt` | string | Optional |  · default="" |
| `model_key` | string | Optional |  · default="sd15" |
| `model_variant` | string | Optional |  · default="" |
| `init_job_id` | string | Optional |  · default="" |
| `init_filename` | string | Optional |  · default="" |
| `init_input_id` | string | Optional |  · default="" |
| `width` | integer | Optional |  · default=768 · minimum=256.0 · maximum=2048.0 |
| `height` | integer | Optional |  · default=768 · minimum=256.0 · maximum=2048.0 |
| `steps` | integer | Optional |  · default=30 · minimum=1.0 · maximum=150.0 |
| `cfg_scale` | number | Optional |  · default=7.0 · minimum=1.0 · maximum=30.0 |
| `strength` | number | Optional |  · default=0.75 · minimum=0.0 · maximum=1.0 |
| `sampler` | string | Optional |  · default="euler_a" |
| `seed` | integer | Optional |  · default=-1 |
| `batch_count` | integer | Optional |  · default=1 · minimum=1.0 · maximum=4.0 |
| `scheduler` | string | Optional |  · default="" |
| `clip_skip` | integer | Optional |  · default=-1 · minimum=-1.0 · maximum=24.0 |
| `guidance` | number | Optional |  · default=0.0 · minimum=0.0 · maximum=30.0 |
| `img_cfg_scale` | number | Optional |  · default=0.0 · minimum=0.0 · maximum=30.0 |
| `eta` | number | Optional |  · default=0.0 · minimum=0.0 · maximum=10.0 |
| `flow_shift` | number | Optional |  · default=0.0 · minimum=0.0 · maximum=20.0 |
| `high_noise_steps` | integer | Optional |  · default=0 · minimum=0.0 · maximum=150.0 |
| `high_noise_cfg_scale` | number | Optional |  · default=0.0 · minimum=0.0 · maximum=30.0 |
| `high_noise_sampler` | string | Optional |  · default="" |
| `slg_scale` | number | Optional |  · default=0.0 · minimum=0.0 · maximum=20.0 |
| `skip_layer_start` | number | Optional |  · default=0.01 · minimum=0.0 · maximum=1.0 |
| `skip_layer_end` | number | Optional |  · default=0.2 · minimum=0.0 · maximum=1.0 |
| `rng` | string | Optional |  · default="" |
| `sampler_rng` | string | Optional |  · default="" |
| `prediction` | string | Optional |  · default="" |
| `weight_type` | string | Optional |  · default="" |
| `tensor_type_rules` | string | Optional |  · default="" · maxLength=1000 |
| `cache_mode` | string | Optional |  · default="" |
| `cache_option` | string | Optional |  · default="" · maxLength=1000 |
| `qwen_image_layers` | integer | Optional |  · default=0 · minimum=0.0 · maximum=16.0 |
| `hires` | boolean | Optional |  · default=false |
| `hires_scale` | number | Optional |  · default=2.0 · minimum=1.0 · maximum=8.0 |
| `hires_width` | integer | Optional |  · default=0 · minimum=0.0 · maximum=4096.0 |
| `hires_height` | integer | Optional |  · default=0 · minimum=0.0 · maximum=4096.0 |
| `hires_steps` | integer | Optional |  · default=0 · minimum=0.0 · maximum=150.0 |
| `hires_denoising_strength` | number | Optional |  · default=0.7 · minimum=0.0 · maximum=1.0 |
| `video_frames` | integer | Optional |  · default=0 · minimum=0.0 · maximum=240.0 |
| `fps` | integer | Optional |  · default=0 · minimum=0.0 · maximum=60.0 |
| `vae_tiling` | boolean  /  null | Optional |  |
| `vae_tile_size` | string | Optional |  · default="" · maxLength=32 |
| `vae_tile_overlap` | number | Optional |  · default=0.5 · minimum=0.0 · maximum=0.95 |
| `temporal_tiling` | boolean  /  null | Optional |  |
| `temporal_tile_frames` | integer | Optional |  · default=4 · minimum=1.0 · maximum=32.0 |
| `temporal_tile_overlap` | integer | Optional |  · default=1 · minimum=0.0 · maximum=16.0 |
| `max_vram` | number | Optional |  · default=0.0 · minimum=-64.0 · maximum=128.0 |
| `stream_layers` | boolean  /  null | Optional |  |
| `auto_fit` | boolean  /  null | Optional |  |
| `clip_on_cpu` | boolean  /  null | Optional |  |
| `offload_to_cpu` | boolean  /  null | Optional |  |
| `vae_cpu_fallback` | boolean  /  null | Optional |  |
| `backend` | string | Optional |  · default="" · maxLength=200 |
| `params_backend` | string | Optional |  · default="" · maxLength=200 |

### HTTPValidationError

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `detail` | array<ValidationError> | Optional |  |

### ImmichStatusResponse

Immich connectivity state without credentials.

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `state` | string | Required |  · enum=["disabled", "pending", "connected", "unreachable", "error"] |
| `detail` | string | Optional |  · default="" |

### SchedulingOptions

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `priority` | string | Optional |  · default="background" · enum=["background", "interactive", "high"] |
| `preemptible` | boolean | Optional |  · default=false |
| `allow_preemption` | boolean | Optional |  · default=false |
| `force_admission` | boolean | Optional |  · default=false |

### ValidationError

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `loc` | array<string  /  integer> | Required |  |
| `msg` | string | Required |  |
| `type` | string | Required |  |
| `input` | JSON | Optional |  |
| `ctx` | object | Optional |  |

### ImmichUploadRecord

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `status` | string | Required |  · enum=["queued", "uploading", "uploaded", "duplicate", "failed"] |
| `checksum` | string | Optional |  · default="" |
| `asset_id` | string  /  null | Optional |  · default=null |
| `attempts` | integer | Optional |  · default=0 |
| `error` | string | Optional |  · default="" |
| `updated_at` | string | Required |  · format="date-time" |

### JobRecord

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `job_id` | string | Required |  |
| `user_key` | string | Required |  |
| `status` | string | Required |  · enum=["queued", "running", "succeeded", "failed"] |
| `prompt` | string | Required |  |
| `negative_prompt` | string | Optional |  · default="" |
| `model_key` | string | Required |  |
| `model_variant` | string | Optional |  · default="" |
| `model_path` | string | Required |  |
| `width` | integer | Required |  |
| `height` | integer | Required |  |
| `steps` | integer | Required |  |
| `cfg_scale` | number | Required |  |
| `strength` | number | Optional |  · default=0.75 |
| `sampler` | string | Required |  |
| `seed` | integer | Required |  |
| `batch_count` | integer | Required |  |
| `scheduler` | string | Optional |  · default="" |
| `clip_skip` | integer | Optional |  · default=-1 |
| `guidance` | number | Optional |  · default=0.0 |
| `img_cfg_scale` | number | Optional |  · default=0.0 |
| `eta` | number | Optional |  · default=0.0 |
| `flow_shift` | number | Optional |  · default=0.0 |
| `high_noise_steps` | integer | Optional |  · default=0 |
| `high_noise_cfg_scale` | number | Optional |  · default=0.0 |
| `high_noise_sampler` | string | Optional |  · default="" |
| `slg_scale` | number | Optional |  · default=0.0 |
| `skip_layer_start` | number | Optional |  · default=0.01 |
| `skip_layer_end` | number | Optional |  · default=0.2 |
| `rng` | string | Optional |  · default="" |
| `sampler_rng` | string | Optional |  · default="" |
| `prediction` | string | Optional |  · default="" |
| `weight_type` | string | Optional |  · default="" |
| `tensor_type_rules` | string | Optional |  · default="" |
| `cache_mode` | string | Optional |  · default="" |
| `cache_option` | string | Optional |  · default="" |
| `qwen_image_layers` | integer | Optional |  · default=0 |
| `hires` | boolean | Optional |  · default=false |
| `hires_scale` | number | Optional |  · default=2.0 |
| `hires_width` | integer | Optional |  · default=0 |
| `hires_height` | integer | Optional |  · default=0 |
| `hires_steps` | integer | Optional |  · default=0 |
| `hires_denoising_strength` | number | Optional |  · default=0.7 |
| `video_frames` | integer | Optional |  · default=0 |
| `fps` | integer | Optional |  · default=0 |
| `vae_tiling` | boolean | Optional |  · default=false |
| `vae_tile_size` | string | Optional |  · default="" |
| `vae_tile_overlap` | number | Optional |  · default=0.5 |
| `temporal_tiling` | boolean | Optional |  · default=false |
| `temporal_tile_frames` | integer | Optional |  · default=4 |
| `temporal_tile_overlap` | integer | Optional |  · default=1 |
| `max_vram` | number | Optional |  · default=0.0 |
| `stream_layers` | boolean | Optional |  · default=false |
| `auto_fit` | boolean | Optional |  · default=false |
| `clip_on_cpu` | boolean | Optional |  · default=false |
| `offload_to_cpu` | boolean | Optional |  · default=false |
| `vae_cpu_fallback` | boolean | Optional |  · default=false |
| `backend` | string | Optional |  · default="" |
| `params_backend` | string | Optional |  · default="" |
| `progress` | number | Optional |  · default=0 |
| `outputs` | array<string> | Optional |  · default=[] |
| `error` | string | Optional |  · default="" |
| `created_at` | string | Required |  · format="date-time" |
| `updated_at` | string | Required |  · format="date-time" |
| `metadata` | object | Optional |  |
| `immich_uploads` | object | Optional |  |

### ModelInfo

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `key` | string | Required |  |
| `name` | string | Required |  |
| `model_id` | string | Required |  |
| `source` | string | Required |  |
| `sources` | array<object> | Optional |  |
| `files` | array<string> | Optional |  |
| `family` | string | Optional |  · default="" |
| `capabilities` | array<string> | Optional |  |
| `preferred` | boolean | Optional |  · default=false |
| `description` | string | Required |  |
| `expected_files` | array<string> | Required |  |
| `params` | string | Optional |  · default="" |
| `runtime` | object | Optional |  |
| `variants` | array<object> | Optional |  |
| `access_path` | string | Required |  |
| `resolved_path` | string  /  null | Optional |  · default=null |
| `status` | string | Optional |  · default="unknown" · enum=["ready", "missing", "downloading", "failed", "unknown"] |
| `size` | integer  /  null | Optional |  · default=null |
| `progress` | number  /  null | Optional |  · default=null |
| `current_file` | string  /  null | Optional |  · default=null |
| `downloaded_bytes` | integer  /  null | Optional |  · default=null |
| `total_bytes` | integer  /  null | Optional |  · default=null |
| `error` | string  /  null | Optional |  · default=null |
| `model_hub_status` | object  /  null | Optional |  · default=null |
| `v_router` | object | Optional |  |

### TemplateRecord

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `id` | string | Required |  |
| `name` | string | Required |  |
| `description` | string | Required |  |
| `payload` | object | Required |  |
| `payload.model_key` | string | Optional |  · default="sd15" |
| `payload.model_variant` | string | Optional |  · default="" |
| `payload.width` | integer | Optional |  · default=768 · minimum=256.0 · maximum=2048.0 |
| `payload.height` | integer | Optional |  · default=768 · minimum=256.0 · maximum=2048.0 |
| `payload.steps` | integer | Optional |  · default=30 · minimum=1.0 · maximum=150.0 |
| `payload.cfg_scale` | number | Optional |  · default=7.0 · minimum=1.0 · maximum=30.0 |
| `payload.sampler` | string | Optional |  · default="euler_a" |
| `payload.vae_tiling` | boolean  /  null | Optional |  |
| `payload.vae_tile_size` | string | Optional |  · default="" · maxLength=32 |
| `payload.negative_prompt` | string | Optional |  · default="" |

### InputFile

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `input_id` | string | Required |  |
| `filename` | string | Required |  |
| `size` | integer | Required |  |
| `created_at` | string | Required |  |
| `url` | string | Required |  |

### GeneratedOutput

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `job_id` | string | Required |  |
| `filename` | string | Required |  |
| `url` | string | Required |  |
| `size` | integer | Required |  |
| `created_at` | string | Required |  · format="date-time" |
| `prompt` | string | Required |  |

### ExecutionStatus

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `status` | string | Required |  |
| `stopped` | boolean | Required |  |
| `progress` | object | Optional |  |
| `progress.percent` | number | Optional |  · minimum=0 · maximum=1 |
| `result` | object | Optional | Native execution result, including output references or a retryable failure. |

### SchedulerBindingStatus

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `protocol_version` | integer | Required |  |
| `configured` | boolean | Required |  |
| `binding_revision` | integer | Optional |  |
| `approved_model_count` | integer | Optional |  |

### DownloadSourceSubmission

| Field | Type | Requirement | Description |
| --- | --- | --- | --- |
| `status` | string | Required |  |
| `model_id` | string | Required |  |
| `detail` | string | Optional |  |
| `task` | object | Optional | Original weight-management task submission; poll the returned task through V-Scheduler. |
| `task.task_id` | string | Optional |  |
