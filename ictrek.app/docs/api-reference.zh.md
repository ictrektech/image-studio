# Image Studio API 详细参考

本页为下一次应用发版的源码参考。应用内从「API → 完整接口与请求/响应字段」打开交互文档，也可下载 OpenAPI JSON；以已安装版本的 `/openapi.json` 为准。本轮文档源码更新不会升级已安装的 Image Studio。

## 地址与身份

VOS 根地址：`https://<VOS-HOST>:1180/api/com.ictrek.image-studio`；容器网络：`http://image-studio-backend:5000`。后接 `/api/v1/...`。HTTPS 端口按设备实际配置；原生后端端口只适合可信网络。

生成、轮询、文件下载使用同一有效 VOS Bearer token。业务接口优先使用已核验的 VOS 身份，再兼容可信内网身份头/token/IP 归属；`/me.authenticated` 仅表示携带了 token，不等于已核验。不能把这些兼容回退当作公网账号鉴权边界。设置、任务和文件按派生用户上下文隔离；生成参数模板是应用共享配置。V-Scheduler 推理 Key 用于统一模型接口，不能当作 Image Studio 管理凭据；厂商 Key 配在上游。绑定回调只接受经过 VOS 核验的 **V-Scheduler 应用身份**；执行回调使用另行下发的 executor token。

## 完整调用流程

### 远端计算 API

部署和模型准备接口要求验证通过的 VOS 系统管理员 Bearer token。应用后端使用自身的 Scheduler 服务身份发起部署、传输和注册。可用位置与远端生成要求有效 VOS 用户身份。地址沿用上文 VOS 或容器基址。POST 请求体为 `application/json`。

| 请求 | 输入与响应 |
| --- | --- |
| `GET /api/v1/compute` | 无参数。200 返回 `targets`、`deployments` 和 `preparations` 数组，空数组表示暂无对应记录。 |
| `POST /api/v1/compute/deployments` | 必填 `kind`（`ssh` 或 `cluster`）、`node_id` 和 `request_key`（1–96 位 ASCII 字母、数字、点、下划线或连字符）。相同键和参数用于安全重试。200 返回 `id` 和 `state`。 |
| `POST /api/v1/compute/deployments/{deployment_id}/models` | 路径 ID 为 32 位小写十六进制；必填 `model_key`，`model_variant` 默认为空字符串。两者最多 96 位小写字母、数字、点、下划线或连字符。202 返回一条模型准备记录。相同部署和模型重复提交会返回进行中的记录或从已确认的偏移续传。 |
| `GET /api/v1/compute/placements` | 无参数。200 返回位置数组，字段为 `deployment_id`、`model_id`（`key` 或 `key@variant`）、`profile`（应用运行配置）、`runtime_parameters`（逐模型校准字段及批准值）、`has_reference`（是否要求参考图）。 |
| `POST /api/v1/generate` | 新增可选 `compute_deployment_id`。空字符串或省略时使用主节点，非空时为 32 位小写十六进制部署 ID。匹配模型与变体后使用该部署的校准配置。若显式传运行参数，值须与批准值相同。提交和结果格式仍为 `JobRecord`。 |

`targets` 每项含 `kind`、`node_id`、`name`、`profile`（固定硬件 Profile）、`runtime_profile`（Image Studio 运行 Profile）及完整 `image`。部署记录包含 `id`、`target_kind`、`target_id`、`profile`、`image`、`state` 及可空的 `last_error`。部署状态为 `pending`、`running`、`failed`、`stopping`、`deleting`、`stopped`、`removed`、`cleanup_failed`。准备记录包含 `deployment_id`、`model_id`、`state`、`received_bytes`、`total_bytes`，以及可空的 `executor_id`、`node_id`、`error`。字节数为非负整数，准备状态为 `transferring`、`interrupted`、`registered`、`failed`。开始传输前 `total_bytes` 可为 0。

准备记录的 `weight_source` 为 `shared`（只读 NFS）、`copy`（节点副本）或 `null`（来源尚未确定）。共享可用时先校验共享文件，无法挂载或文件与主节点版本不匹配时再复制。共享模式的 `received_bytes` 表示确认的权重字节数。

依次授权目标和镜像仓库、发起部署、轮询到 `running`、提交模型准备、轮询到 `registered`。随后以相同模型和部署提交生成，使用 `GET /api/v1/jobs/{job_id}` 和 `GET /api/v1/outputs/{job_id}/{filename}` 获取结果。401 重新登录，403 检查管理员角色或部署授权，404 核对实例，409 检查运行状态和模型注册，422 修正请求或选择匹配参考图模式和运行参数的校准，503 检查节点、身份服务和 Scheduler。准备失败时在记录中读取 `error`，修复后重试同一模型。

### 本地生成

```sh
export IMAGE_API='https://<VOS-HOST>:1180/api/com.ictrek.image-studio'
curl --fail-with-body -H "Authorization: Bearer $VOS_TOKEN" "$IMAGE_API/api/v1/models"
# 从返回值选择当前机器上 ready 的模型 key 和 variant
curl --fail-with-body -X POST "$IMAGE_API/api/v1/generate" \
  -H "Authorization: Bearer $VOS_TOKEN" -H 'Content-Type: application/json' \
  -d '{"prompt":"A small red house","model_key":"<ready-key>","model_variant":"<variant-or-empty>","width":512,"height":512,"steps":4,"batch_count":1,"scheduling":{"priority":"interactive"}}'
# 保存顶层 job_id，不是 data.job_id；轮询到 succeeded 或 failed
curl --fail-with-body -H "Authorization: Bearer $VOS_TOKEN" "$IMAGE_API/api/v1/jobs/$JOB_ID"
# succeeded 后从 outputs 复制文件名，下载时检查 Content-Type
curl --fail-with-body -H "Authorization: Bearer $VOS_TOKEN" \
  -o output.png "$IMAGE_API/api/v1/outputs/$JOB_ID/$FILENAME"
```

示例是接口模板，不是所有模型的实测硬件预设；尺寸/步数按所选模型支持范围调整。模型 ready 只表示权重就绪，不表示已取得资源许可。成功 JSON 没有统一 `{code,data}` 信封。HTTP200 受理任务不等于生成完成：读取 status、progress、outputs、error 与 metadata，并验证实际产物。设置轮询总期限与退避；客户端超时不会自动取消计算。生成接口没有统一幂等键，超时后不要直接重复提交。

图生图先通过 `POST /api/v1/inputs` 的 multipart `file` 上传参考图（png/jpg/jpeg/webp，最多20MiB），然后在 GenerateRequest 填 init_input_id；也可以引用自己的成功 init_job_id 与 init_filename。`POST /models/{key}/stop` 停的是**权重下载**，不是生成计算。`DELETE /jobs/{job_id}` 先取消计算/上传，再删除任务与输出文件，不是无损停止接口。PhotoCraft 交接只授权当前用户一个输出文件，返回 URL 和带小数的 Unix expires_at；票据保存在内存，300秒或进程重启后失效，失效返回404。Immich 上传返回202与 JobRecord，实际完成情况要读取每个文件的 immich_uploads。

## 配置、错误与调度

GenerateRequest 包含模型/变体、参考图、图片/视频参数、运行时内存选项和请求级 scheduling（SchedulingOptions 中支持的 priority、preemptible、allow_preemption、force_admission）。任务受理、真正计算、原生停止确认是不同阶段。注册/绑定成功及心跳新鲜不等于获得预算；绑定版本、运行设置与逐模型批准必须匹配，不要手改私有绑定地址/token/profile 绕过校验。`/scheduler/binding` configured=true 只表示已保存的绑定有效，不表示当前资源充足。

先检查 HTTP 状态与 Content-Type。FastAPI 错误使用 detail（消息或校验列表），未处理的服务/网关错误可能为纯文本。422 修正字段，404 核对模型/任务，409 处理权重缺失或绑定版本冲突，429/503 按资源或依赖错误处理；任务提交 HTTP 成功后仍可能执行失败。文件按二进制读取。以下给出本源码全部接口与数据结构，不要照搬其他版本的字段。大陆网络可能无法加载 Swagger 的外部资源，此时仍可通过本机网关下载 OpenAPI JSON。


## 完整接口与返回

### GET /api/v1/about

身份：公开接口 / 按文中调用边界

响应 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `app_id` | string | 必填 |  |
| `app_version` | string | 必填 |  |
| `profile` | string | 必填 |  |
| `data_dir` | string | 必填 |  |
| `modelhub_root` | string | 必填 |  |
| `model_hub_api_url` | string | 必填 |  |
| `sd_cpp_bin` | string | 必填 |  |
| `max_concurrency` | integer | 必填 |  |

响应 default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 必填 | FastAPI error message or structured validation details. |

`text/plain`

`string`

### GET /api/v1/templates

身份：公开接口 / 按文中调用边界

响应 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `templates` | array<TemplateRecord> | 必填 |  |
| `default_template` | string  /  null | 必填 |  |

响应 default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 必填 | FastAPI error message or structured validation details. |

`text/plain`

`string`

### POST /api/v1/templates

身份：公开接口 / 按文中调用边界

请求体：application/json

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `name` | string | 可选 |  |
| `payload` | object | 必填 | Allowed keys: model_key, model_variant, width, height, steps, cfg_scale, sampler, vae_tiling, vae_tile_size, negative_prompt. |

响应 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`TemplateRecord`

响应 422 — Validation Error

`application/json`

`HTTPValidationError`

响应 default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 必填 | FastAPI error message or structured validation details. |

`text/plain`

`string`

### PATCH /api/v1/templates/{template_id}

身份：公开接口 / 按文中调用边界

- `path: template_id` · string · 必填 · 

请求体：application/json

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `name` | string | 可选 |  |

响应 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`TemplateRecord`

响应 422 — Validation Error

`application/json`

`HTTPValidationError`

响应 default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 必填 | FastAPI error message or structured validation details. |

`text/plain`

`string`

### DELETE /api/v1/templates/{template_id}

身份：公开接口 / 按文中调用边界

- `path: template_id` · string · 必填 · 

响应 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `ok` | boolean | 必填 |  |

响应 422 — Validation Error

`application/json`

`HTTPValidationError`

响应 default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 必填 | FastAPI error message or structured validation details. |

`text/plain`

`string`

### GET /api/v1/me

身份：VOSBearer / 可信内网兼容模式

响应 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `user_key` | string | 必填 |  |
| `authenticated` | boolean | 必填 | Indicates token presence, not proof that the token was verified. |

响应 default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 必填 | FastAPI error message or structured validation details. |

`text/plain`

`string`

### GET /api/v1/settings

身份：VOSBearer / 可信内网兼容模式

响应 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `language` | string | 必填 |  · enum=["auto", "zh-CN", "zh-TW", "en"] |

响应 default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 必填 | FastAPI error message or structured validation details. |

`text/plain`

`string`

### PUT /api/v1/settings

身份：VOSBearer / 可信内网兼容模式

请求体：application/json

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `language` | string | 可选 |  · enum=["auto", "zh-CN", "zh-TW", "en"] |

响应 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `language` | string | 必填 |  · enum=["auto", "zh-CN", "zh-TW", "en"] |

响应 422 — Validation Error

`application/json`

`HTTPValidationError`

响应 default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 必填 | FastAPI error message or structured validation details. |

`text/plain`

`string`

### GET /api/v1/immich

身份：公开接口 / 按文中调用边界

Immich connection status; no credentials are returned. See the five states in ImmichStatusResponse.

响应 200 — Successful Response

`application/json`

`ImmichStatusResponse`

响应 default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 必填 | FastAPI error message or structured validation details. |

`text/plain`

`string`

### POST /api/v1/generate

身份：VOSBearer / 可信内网兼容模式

请求体：application/json

`GenerateRequest`

响应 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`JobRecord`

响应 422 — Validation Error

`application/json`

`HTTPValidationError`

响应 default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 必填 | FastAPI error message or structured validation details. |

`text/plain`

`string`

### GET /api/v1/jobs

身份：VOSBearer / 可信内网兼容模式

响应 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`array<JobRecord>`

响应 default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 必填 | FastAPI error message or structured validation details. |

`text/plain`

`string`

### POST /api/v1/jobs/{job_id}/immich-upload

身份：VOSBearer / 可信内网兼容模式

- `path: job_id` · string · 必填 · 

- `query: force` · boolean · 可选 · 

响应 202 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`JobRecord`

响应 422 — Validation Error

`application/json`

`HTTPValidationError`

响应 default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 必填 | FastAPI error message or structured validation details. |

`text/plain`

`string`

### POST /api/v1/jobs/{job_id}/immich-upload/retry

身份：VOSBearer / 可信内网兼容模式

- `path: job_id` · string · 必填 · 

响应 202 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`JobRecord`

响应 422 — Validation Error

`application/json`

`HTTPValidationError`

响应 default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 必填 | FastAPI error message or structured validation details. |

`text/plain`

`string`

### GET /api/v1/jobs/{job_id}

身份：VOSBearer / 可信内网兼容模式

- `path: job_id` · string · 必填 · 

响应 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`JobRecord`

响应 422 — Validation Error

`application/json`

`HTTPValidationError`

响应 default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 必填 | FastAPI error message or structured validation details. |

`text/plain`

`string`

### DELETE /api/v1/jobs/{job_id}

身份：VOSBearer / 可信内网兼容模式

- `path: job_id` · string · 必填 · 

响应 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `deleted` | boolean | 必填 |  |
| `job_id` | string | 必填 |  |

响应 422 — Validation Error

`application/json`

`HTTPValidationError`

响应 default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 必填 | FastAPI error message or structured validation details. |

`text/plain`

`string`

### GET /api/v1/outputs

身份：VOSBearer / 可信内网兼容模式

响应 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`array<GeneratedOutput>`

响应 default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 必填 | FastAPI error message or structured validation details. |

`text/plain`

`string`

### GET /api/v1/outputs/{job_id}/{filename}

身份：VOSBearer / 可信内网兼容模式

- `path: job_id` · string · 必填 · 

- `path: filename` · string · 必填 · 

响应 200 — Binary file. Inspect Content-Type; errors remain JSON. PhotoCraft handoffs require the expiring ticket in the URL.

`*/*`

`string`

响应 422 — Validation Error

`application/json`

`HTTPValidationError`

响应 default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 必填 | FastAPI error message or structured validation details. |

`text/plain`

`string`

### POST /api/v1/jobs/{job_id}/photocraft

身份：VOSBearer / 可信内网兼容模式

- `path: job_id` · string · 必填 · 

请求体：application/json

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `filename` | string | 必填 |  |

响应 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `url` | string | 必填 |  |
| `expires_at` | number | 必填 | Unix seconds; fractional seconds are retained. The ticket expires after 300 seconds. |

响应 422 — Validation Error

`application/json`

`HTTPValidationError`

响应 default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 必填 | FastAPI error message or structured validation details. |

`text/plain`

`string`

### GET /api/v1/photocraft/handoffs/{ticket}/{filename}

身份：公开接口 / 按文中调用边界

- `path: ticket` · string · 必填 · 

- `path: filename` · string · 必填 · 

响应 200 — Binary file. Inspect Content-Type; errors remain JSON. PhotoCraft handoffs require the expiring ticket in the URL.

`*/*`

`string`

响应 422 — Validation Error

`application/json`

`HTTPValidationError`

响应 default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 必填 | FastAPI error message or structured validation details. |

`text/plain`

`string`

### GET /api/v1/inputs

身份：VOSBearer / 可信内网兼容模式

响应 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`array<InputFile>`

响应 default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 必填 | FastAPI error message or structured validation details. |

`text/plain`

`string`

### POST /api/v1/inputs

身份：VOSBearer / 可信内网兼容模式

Upload an img2img/edit reference (png/jpg/jpeg/webp, at most 20 MiB); returns an input_id for generation.

请求体：multipart/form-data

`Body_upload_input_api_v1_inputs_post`

响应 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`InputFile`

响应 422 — Validation Error

`application/json`

`HTTPValidationError`

响应 default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 必填 | FastAPI error message or structured validation details. |

`text/plain`

`string`

### GET /api/v1/inputs/{input_id}

身份：VOSBearer / 可信内网兼容模式

- `path: input_id` · string · 必填 · 

响应 200 — Binary file. Inspect Content-Type; errors remain JSON. PhotoCraft handoffs require the expiring ticket in the URL.

`*/*`

`string`

响应 422 — Validation Error

`application/json`

`HTTPValidationError`

响应 default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 必填 | FastAPI error message or structured validation details. |

`text/plain`

`string`

### DELETE /api/v1/inputs/{input_id}

身份：VOSBearer / 可信内网兼容模式

- `path: input_id` · string · 必填 · 

响应 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `deleted` | boolean | 必填 |  |
| `input_id` | string | 必填 |  |

响应 422 — Validation Error

`application/json`

`HTTPValidationError`

响应 default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 必填 | FastAPI error message or structured validation details. |

`text/plain`

`string`

### GET /api/v1/models

身份：公开接口 / 按文中调用边界

响应 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`array<ModelInfo>`

响应 default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 必填 | FastAPI error message or structured validation details. |

`text/plain`

`string`

### GET /api/v1/v-router/registration

身份：公开接口 / 按文中调用边界

- `query: ready_only` · boolean · 可选 · 

响应 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `service_id` | string | 必填 |  |
| `name` | string | 必填 |  |
| `visibility` | string | 必填 |  |
| `protocol` | string | 必填 |  |
| `base_url` | string | 必填 |  |
| `model_kind` | string | 必填 |  |
| `models` | array<object> | 必填 |  |
| `ttl_seconds` | integer | 必填 |  |
| `scheduler` | object | 必填 |  |
| `scheduler.protocol_version` | integer | 必填 |  |
| `scheduler.lifecycle_protocol_version` | integer | 必填 |  |
| `scheduler.preemption_modes` | array<string> | 必填 |  |
| `scheduler.app_id` | string | 必填 |  |
| `scheduler.binding_endpoint` | string | 必填 |  |
| `scheduler.executor_base_url` | string | 必填 |  |
| `scheduler.upstream_url` | string | 必填 |  |
| `scheduler.async_models` | array<object> | 必填 |  |
| `scheduler.execution_settings` | object | 必填 |  |
| `scheduler.binding` | SchedulerBindingStatus | 必填 |  |

响应 422 — Validation Error

`application/json`

`HTTPValidationError`

响应 default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 必填 | FastAPI error message or structured validation details. |

`text/plain`

`string`

### GET /api/v1/v-router/status

身份：公开接口 / 按文中调用边界

响应 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `configured` | boolean | 必填 |  |
| `reachable` | boolean | 必填 |  |
| `api_url` | string | 必填 |  |
| `eligible_models` | integer | 必填 |  |
| `error` | string | 必填 |  |

响应 default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 必填 | FastAPI error message or structured validation details. |

`text/plain`

`string`

### GET /api/v1/models/{key}

身份：公开接口 / 按文中调用边界

- `path: key` · string · 必填 · 

- `query: variant` · string · 可选 · 

响应 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`ModelInfo`

响应 422 — Validation Error

`application/json`

`HTTPValidationError`

响应 default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 必填 | FastAPI error message or structured validation details. |

`text/plain`

`string`

### POST /api/v1/models/{key}/pull

身份：公开接口 / 按文中调用边界

- `path: key` · string · 必填 · 

- `query: force` · boolean · 可选 · 

- `query: variant` · string · 可选 · 

响应 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `status` | string | 必填 |  |
| `model_id` | string | 必填 |  |
| `variant` | string | 必填 |  |
| `sources` | array<DownloadSourceSubmission> | 必填 |  |

响应 422 — Validation Error

`application/json`

`HTTPValidationError`

响应 default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 必填 | FastAPI error message or structured validation details. |

`text/plain`

`string`

### POST /api/v1/models/{key}/stop

身份：公开接口 / 按文中调用边界

- `path: key` · string · 必填 · 

- `query: variant` · string · 可选 · 

响应 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `status` | string | 必填 |  |
| `model_id` | string | 必填 |  |
| `variant` | string | 必填 |  |
| `tasks` | array<JSON> | 可选 |  |

响应 422 — Validation Error

`application/json`

`HTTPValidationError`

响应 default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 必填 | FastAPI error message or structured validation details. |

`text/plain`

`string`

### POST /api/v1/models/{key}/sync

身份：公开接口 / 按文中调用边界

- `path: key` · string · 必填 · 

响应 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `synced` | integer | 必填 |  |
| `hf_added` | integer | 必填 |  |
| `ms_added` | integer | 必填 |  |
| `ollama_added` | integer | 必填 |  |
| `message` | string | 必填 |  |

响应 422 — Validation Error

`application/json`

`HTTPValidationError`

响应 default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 必填 | FastAPI error message or structured validation details. |

`text/plain`

`string`

### POST /api/v1/scheduler/executions/{attempt}/start

身份：ExecutorBearer

- `path: attempt` · string · 必填 · 

请求体：application/json

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `fence` | integer | 必填 |  |
| `parameters` | object | 必填 |  |
| `parameters.user_key` | string | 必填 |  |
| `parameters.job_id` | string | 必填 |  |
| `lease_seconds` | integer | 可选 |  |
| `preempted` | boolean | 可选 |  |

响应 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`ExecutionStatus`

响应 422 — Validation Error

`application/json`

`HTTPValidationError`

响应 default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 必填 | FastAPI error message or structured validation details. |

`text/plain`

`string`

### POST /api/v1/scheduler/executions/{attempt}/inspect

身份：ExecutorBearer

- `path: attempt` · string · 必填 · 

请求体：application/json

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `fence` | integer | 必填 |  |

响应 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`ExecutionStatus`

响应 422 — Validation Error

`application/json`

`HTTPValidationError`

响应 default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 必填 | FastAPI error message or structured validation details. |

`text/plain`

`string`

### POST /api/v1/scheduler/executions/{attempt}/cancel

身份：ExecutorBearer

- `path: attempt` · string · 必填 · 

请求体：application/json

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `fence` | integer | 必填 |  |
| `parameters` | object | 必填 |  |
| `parameters.user_key` | string | 必填 |  |
| `parameters.job_id` | string | 必填 |  |
| `preempted` | boolean | 可选 |  |

响应 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`ExecutionStatus`

响应 422 — Validation Error

`application/json`

`HTTPValidationError`

响应 default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 必填 | FastAPI error message or structured validation details. |

`text/plain`

`string`

### GET /api/v1/scheduler/binding

身份：公开接口 / 按文中调用边界

响应 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`SchedulerBindingStatus`

响应 default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 必填 | FastAPI error message or structured validation details. |

`text/plain`

`string`

### POST /api/v1/scheduler/binding

身份：SchedulerApplication

请求体：application/json

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `protocol_version` | integer | 必填 |  · const=1 |
| `binding_revision` | integer | 必填 |  · minimum=1 |
| `app_id` | string | 必填 |  · const="com.ictrek.image-studio" |
| `url` | string | 必填 | Application binding snapshot; this legacy alias is not a caller-selected provider address. · const="http://v-router:8080/scheduler/api/v1" |
| `upstream_url` | string | 必填 |  · const="http://image-studio-backend:5000" |
| `token` | string | 必填 | Provisioned Scheduler service identity, never an upstream vendor key. · minLength=32 · maxLength=4096 |
| `executor_token` | string | 必填 |  · minLength=32 · maxLength=4096 |
| `models` | object | 必填 |  |
| `gateway_executors` | object | 可选 |  |
| `model_limits` | object | 必填 |  |
| `model_limits.{key}.width` | integer | 必填 |  · minimum=0 |
| `model_limits.{key}.height` | integer | 必填 |  · minimum=0 |
| `model_limits.{key}.steps` | integer | 必填 |  · minimum=0 |
| `model_limits.{key}.batch_count` | integer | 必填 |  · minimum=0 |
| `model_limits.{key}.video_frames` | integer | 必填 |  · minimum=0 |
| `model_limits.{key}.prompt_characters` | integer | 必填 |  · minimum=0 |
| `model_limits.{key}.negative_prompt_characters` | integer | 必填 |  · minimum=0 |
| `model_parameters` | object | 必填 |  |
| `model_parameters.{key}.weight_type` | string | 必填 |  · default="" |
| `model_parameters.{key}.tensor_type_rules` | string | 必填 |  · default="" |
| `model_parameters.{key}.cache_mode` | string | 必填 |  · default="" |
| `model_parameters.{key}.cache_option` | string | 必填 |  · default="" |
| `model_parameters.{key}.qwen_image_layers` | integer | 必填 |  · default=0 |
| `model_parameters.{key}.vae_tiling` | boolean | 必填 |  · default=false |
| `model_parameters.{key}.vae_tile_size` | string | 必填 |  · default="" |
| `model_parameters.{key}.vae_tile_overlap` | number | 必填 |  · default=0.5 |
| `model_parameters.{key}.temporal_tiling` | boolean | 必填 |  · default=false |
| `model_parameters.{key}.temporal_tile_frames` | integer | 必填 |  · default=4 |
| `model_parameters.{key}.temporal_tile_overlap` | integer | 必填 |  · default=1 |
| `model_parameters.{key}.max_vram` | number | 必填 |  · default=0.0 |
| `model_parameters.{key}.stream_layers` | boolean | 必填 |  · default=false |
| `model_parameters.{key}.auto_fit` | boolean | 必填 |  · default=false |
| `model_parameters.{key}.clip_on_cpu` | boolean | 必填 |  · default=false |
| `model_parameters.{key}.offload_to_cpu` | boolean | 必填 |  · default=false |
| `model_parameters.{key}.vae_cpu_fallback` | boolean | 必填 |  · default=false |
| `model_parameters.{key}.backend` | string | 必填 |  · default="" |
| `model_parameters.{key}.params_backend` | string | 必填 |  · default="" |
| `model_parameters.{key}.has_reference` | boolean | 必填 |  |
| `execution_settings` | object | 必填 |  |
| `execution_settings.profile` | string | 必填 |  |
| `execution_settings.runtime` | string | 必填 |  |
| `execution_settings.logical_cpu_count` | integer  /  null | 必填 |  |
| `execution_settings.max_concurrency` | integer | 必填 |  |
| `execution_settings.sd_cpp_extra_args_sha256` | string | 必填 |  |

响应 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `configured` | boolean | 必填 |  |
| `binding_revision` | integer | 必填 |  |

响应 default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 必填 | FastAPI error message or structured validation details. |

`text/plain`

`string`

### GET /health

身份：公开接口 / 按文中调用边界

响应 200 — Successful application JSON response; not wrapped in a Scheduler envelope.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `status` | string | 必填 |  |
| `app` | string | 必填 |  |
| `version` | string | 必填 |  |

响应 default — Application HTTP errors use detail (message or validation errors). Unexpected server/gateway failures can be plain text. Check status and Content-Type before decoding.

`application/json`

`object`

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | JSON | 必填 | FastAPI error message or structured validation details. |

`text/plain`

`string`

## 共享数据结构

字段保持 API 的原始拼写；JSON 任意扩展字段按其所属服务说明解释。

### Body_upload_input_api_v1_inputs_post

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `file` | string | 必填 |  |

### GenerateRequest

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `scheduling` | SchedulingOptions  /  null | 可选 |  |
| `prompt` | string | 必填 |  · minLength=1 · maxLength=4000 |
| `negative_prompt` | string | 可选 |  · default="" |
| `model_key` | string | 可选 |  · default="sd15" |
| `model_variant` | string | 可选 |  · default="" |
| `init_job_id` | string | 可选 |  · default="" |
| `init_filename` | string | 可选 |  · default="" |
| `init_input_id` | string | 可选 |  · default="" |
| `width` | integer | 可选 |  · default=768 · minimum=256.0 · maximum=2048.0 |
| `height` | integer | 可选 |  · default=768 · minimum=256.0 · maximum=2048.0 |
| `steps` | integer | 可选 |  · default=30 · minimum=1.0 · maximum=150.0 |
| `cfg_scale` | number | 可选 |  · default=7.0 · minimum=1.0 · maximum=30.0 |
| `strength` | number | 可选 |  · default=0.75 · minimum=0.0 · maximum=1.0 |
| `sampler` | string | 可选 |  · default="euler_a" |
| `seed` | integer | 可选 |  · default=-1 |
| `batch_count` | integer | 可选 |  · default=1 · minimum=1.0 · maximum=4.0 |
| `scheduler` | string | 可选 |  · default="" |
| `clip_skip` | integer | 可选 |  · default=-1 · minimum=-1.0 · maximum=24.0 |
| `guidance` | number | 可选 |  · default=0.0 · minimum=0.0 · maximum=30.0 |
| `img_cfg_scale` | number | 可选 |  · default=0.0 · minimum=0.0 · maximum=30.0 |
| `eta` | number | 可选 |  · default=0.0 · minimum=0.0 · maximum=10.0 |
| `flow_shift` | number | 可选 |  · default=0.0 · minimum=0.0 · maximum=20.0 |
| `high_noise_steps` | integer | 可选 |  · default=0 · minimum=0.0 · maximum=150.0 |
| `high_noise_cfg_scale` | number | 可选 |  · default=0.0 · minimum=0.0 · maximum=30.0 |
| `high_noise_sampler` | string | 可选 |  · default="" |
| `slg_scale` | number | 可选 |  · default=0.0 · minimum=0.0 · maximum=20.0 |
| `skip_layer_start` | number | 可选 |  · default=0.01 · minimum=0.0 · maximum=1.0 |
| `skip_layer_end` | number | 可选 |  · default=0.2 · minimum=0.0 · maximum=1.0 |
| `rng` | string | 可选 |  · default="" |
| `sampler_rng` | string | 可选 |  · default="" |
| `prediction` | string | 可选 |  · default="" |
| `weight_type` | string | 可选 |  · default="" |
| `tensor_type_rules` | string | 可选 |  · default="" · maxLength=1000 |
| `cache_mode` | string | 可选 |  · default="" |
| `cache_option` | string | 可选 |  · default="" · maxLength=1000 |
| `qwen_image_layers` | integer | 可选 |  · default=0 · minimum=0.0 · maximum=16.0 |
| `hires` | boolean | 可选 |  · default=false |
| `hires_scale` | number | 可选 |  · default=2.0 · minimum=1.0 · maximum=8.0 |
| `hires_width` | integer | 可选 |  · default=0 · minimum=0.0 · maximum=4096.0 |
| `hires_height` | integer | 可选 |  · default=0 · minimum=0.0 · maximum=4096.0 |
| `hires_steps` | integer | 可选 |  · default=0 · minimum=0.0 · maximum=150.0 |
| `hires_denoising_strength` | number | 可选 |  · default=0.7 · minimum=0.0 · maximum=1.0 |
| `video_frames` | integer | 可选 |  · default=0 · minimum=0.0 · maximum=240.0 |
| `fps` | integer | 可选 |  · default=0 · minimum=0.0 · maximum=60.0 |
| `vae_tiling` | boolean  /  null | 可选 |  |
| `vae_tile_size` | string | 可选 |  · default="" · maxLength=32 |
| `vae_tile_overlap` | number | 可选 |  · default=0.5 · minimum=0.0 · maximum=0.95 |
| `temporal_tiling` | boolean  /  null | 可选 |  |
| `temporal_tile_frames` | integer | 可选 |  · default=4 · minimum=1.0 · maximum=32.0 |
| `temporal_tile_overlap` | integer | 可选 |  · default=1 · minimum=0.0 · maximum=16.0 |
| `max_vram` | number | 可选 |  · default=0.0 · minimum=-64.0 · maximum=128.0 |
| `stream_layers` | boolean  /  null | 可选 |  |
| `auto_fit` | boolean  /  null | 可选 |  |
| `clip_on_cpu` | boolean  /  null | 可选 |  |
| `offload_to_cpu` | boolean  /  null | 可选 |  |
| `vae_cpu_fallback` | boolean  /  null | 可选 |  |
| `backend` | string | 可选 |  · default="" · maxLength=200 |
| `params_backend` | string | 可选 |  · default="" · maxLength=200 |

### HTTPValidationError

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `detail` | array<ValidationError> | 可选 |  |

### ImmichStatusResponse

Immich connectivity state without credentials.

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `state` | string | 必填 |  · enum=["disabled", "pending", "connected", "unreachable", "error"] |
| `detail` | string | 可选 |  · default="" |

### SchedulingOptions

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `priority` | string | 可选 |  · default="background" · enum=["background", "interactive", "high"] |
| `preemptible` | boolean | 可选 |  · default=false |
| `allow_preemption` | boolean | 可选 |  · default=false |
| `force_admission` | boolean | 可选 |  · default=false |

### ValidationError

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `loc` | array<string  /  integer> | 必填 |  |
| `msg` | string | 必填 |  |
| `type` | string | 必填 |  |
| `input` | JSON | 可选 |  |
| `ctx` | object | 可选 |  |

### ImmichUploadRecord

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `status` | string | 必填 |  · enum=["queued", "uploading", "uploaded", "duplicate", "failed"] |
| `checksum` | string | 可选 |  · default="" |
| `asset_id` | string  /  null | 可选 |  · default=null |
| `attempts` | integer | 可选 |  · default=0 |
| `error` | string | 可选 |  · default="" |
| `updated_at` | string | 必填 |  · format="date-time" |

### JobRecord

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `job_id` | string | 必填 |  |
| `user_key` | string | 必填 |  |
| `status` | string | 必填 |  · enum=["queued", "running", "succeeded", "failed"] |
| `prompt` | string | 必填 |  |
| `negative_prompt` | string | 可选 |  · default="" |
| `model_key` | string | 必填 |  |
| `model_variant` | string | 可选 |  · default="" |
| `model_path` | string | 必填 |  |
| `width` | integer | 必填 |  |
| `height` | integer | 必填 |  |
| `steps` | integer | 必填 |  |
| `cfg_scale` | number | 必填 |  |
| `strength` | number | 可选 |  · default=0.75 |
| `sampler` | string | 必填 |  |
| `seed` | integer | 必填 |  |
| `batch_count` | integer | 必填 |  |
| `scheduler` | string | 可选 |  · default="" |
| `clip_skip` | integer | 可选 |  · default=-1 |
| `guidance` | number | 可选 |  · default=0.0 |
| `img_cfg_scale` | number | 可选 |  · default=0.0 |
| `eta` | number | 可选 |  · default=0.0 |
| `flow_shift` | number | 可选 |  · default=0.0 |
| `high_noise_steps` | integer | 可选 |  · default=0 |
| `high_noise_cfg_scale` | number | 可选 |  · default=0.0 |
| `high_noise_sampler` | string | 可选 |  · default="" |
| `slg_scale` | number | 可选 |  · default=0.0 |
| `skip_layer_start` | number | 可选 |  · default=0.01 |
| `skip_layer_end` | number | 可选 |  · default=0.2 |
| `rng` | string | 可选 |  · default="" |
| `sampler_rng` | string | 可选 |  · default="" |
| `prediction` | string | 可选 |  · default="" |
| `weight_type` | string | 可选 |  · default="" |
| `tensor_type_rules` | string | 可选 |  · default="" |
| `cache_mode` | string | 可选 |  · default="" |
| `cache_option` | string | 可选 |  · default="" |
| `qwen_image_layers` | integer | 可选 |  · default=0 |
| `hires` | boolean | 可选 |  · default=false |
| `hires_scale` | number | 可选 |  · default=2.0 |
| `hires_width` | integer | 可选 |  · default=0 |
| `hires_height` | integer | 可选 |  · default=0 |
| `hires_steps` | integer | 可选 |  · default=0 |
| `hires_denoising_strength` | number | 可选 |  · default=0.7 |
| `video_frames` | integer | 可选 |  · default=0 |
| `fps` | integer | 可选 |  · default=0 |
| `vae_tiling` | boolean | 可选 |  · default=false |
| `vae_tile_size` | string | 可选 |  · default="" |
| `vae_tile_overlap` | number | 可选 |  · default=0.5 |
| `temporal_tiling` | boolean | 可选 |  · default=false |
| `temporal_tile_frames` | integer | 可选 |  · default=4 |
| `temporal_tile_overlap` | integer | 可选 |  · default=1 |
| `max_vram` | number | 可选 |  · default=0.0 |
| `stream_layers` | boolean | 可选 |  · default=false |
| `auto_fit` | boolean | 可选 |  · default=false |
| `clip_on_cpu` | boolean | 可选 |  · default=false |
| `offload_to_cpu` | boolean | 可选 |  · default=false |
| `vae_cpu_fallback` | boolean | 可选 |  · default=false |
| `backend` | string | 可选 |  · default="" |
| `params_backend` | string | 可选 |  · default="" |
| `progress` | number | 可选 |  · default=0 |
| `outputs` | array<string> | 可选 |  · default=[] |
| `error` | string | 可选 |  · default="" |
| `created_at` | string | 必填 |  · format="date-time" |
| `updated_at` | string | 必填 |  · format="date-time" |
| `metadata` | object | 可选 |  |
| `immich_uploads` | object | 可选 |  |

### ModelInfo

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `key` | string | 必填 |  |
| `name` | string | 必填 |  |
| `model_id` | string | 必填 |  |
| `source` | string | 必填 |  |
| `sources` | array<object> | 可选 |  |
| `files` | array<string> | 可选 |  |
| `family` | string | 可选 |  · default="" |
| `capabilities` | array<string> | 可选 |  |
| `preferred` | boolean | 可选 |  · default=false |
| `description` | string | 必填 |  |
| `expected_files` | array<string> | 必填 |  |
| `params` | string | 可选 |  · default="" |
| `runtime` | object | 可选 |  |
| `variants` | array<object> | 可选 |  |
| `access_path` | string | 必填 |  |
| `resolved_path` | string  /  null | 可选 |  · default=null |
| `status` | string | 可选 |  · default="unknown" · enum=["ready", "missing", "downloading", "failed", "unknown"] |
| `size` | integer  /  null | 可选 |  · default=null |
| `progress` | number  /  null | 可选 |  · default=null |
| `current_file` | string  /  null | 可选 |  · default=null |
| `downloaded_bytes` | integer  /  null | 可选 |  · default=null |
| `total_bytes` | integer  /  null | 可选 |  · default=null |
| `error` | string  /  null | 可选 |  · default=null |
| `model_hub_status` | object  /  null | 可选 |  · default=null |
| `v_router` | object | 可选 |  |

### TemplateRecord

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `id` | string | 必填 |  |
| `name` | string | 必填 |  |
| `description` | string | 必填 |  |
| `payload` | object | 必填 |  |
| `payload.model_key` | string | 可选 |  · default="sd15" |
| `payload.model_variant` | string | 可选 |  · default="" |
| `payload.width` | integer | 可选 |  · default=768 · minimum=256.0 · maximum=2048.0 |
| `payload.height` | integer | 可选 |  · default=768 · minimum=256.0 · maximum=2048.0 |
| `payload.steps` | integer | 可选 |  · default=30 · minimum=1.0 · maximum=150.0 |
| `payload.cfg_scale` | number | 可选 |  · default=7.0 · minimum=1.0 · maximum=30.0 |
| `payload.sampler` | string | 可选 |  · default="euler_a" |
| `payload.vae_tiling` | boolean  /  null | 可选 |  |
| `payload.vae_tile_size` | string | 可选 |  · default="" · maxLength=32 |
| `payload.negative_prompt` | string | 可选 |  · default="" |

### InputFile

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `input_id` | string | 必填 |  |
| `filename` | string | 必填 |  |
| `size` | integer | 必填 |  |
| `created_at` | string | 必填 |  |
| `url` | string | 必填 |  |

### GeneratedOutput

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `job_id` | string | 必填 |  |
| `filename` | string | 必填 |  |
| `url` | string | 必填 |  |
| `size` | integer | 必填 |  |
| `created_at` | string | 必填 |  · format="date-time" |
| `prompt` | string | 必填 |  |

### ExecutionStatus

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `status` | string | 必填 |  |
| `stopped` | boolean | 必填 |  |
| `progress` | object | 可选 |  |
| `progress.percent` | number | 可选 |  · minimum=0 · maximum=1 |
| `result` | object | 可选 | Native execution result, including output references or a retryable failure. |

### SchedulerBindingStatus

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `protocol_version` | integer | 必填 |  |
| `configured` | boolean | 必填 |  |
| `binding_revision` | integer | 可选 |  |
| `approved_model_count` | integer | 可选 |  |

### DownloadSourceSubmission

| 字段 | 类型 | 要求 | 说明 |
| --- | --- | --- | --- |
| `status` | string | 必填 |  |
| `model_id` | string | 必填 |  |
| `detail` | string | 可选 |  |
| `task` | object | 可选 | Original weight-management task submission; poll the returned task through V-Scheduler. |
| `task.task_id` | string | 可选 |  |
