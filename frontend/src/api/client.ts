import { clearCachedVOSBearerToken, getCachedVOSBearerToken, getVOSBearerToken } from './vos-auth'

const API_BASE = import.meta.env.VITE_API_BASE || '/api/com.ictrek.image-studio'

export interface ModelSourceSpec {
  source: string
  model_id: string
  files?: string[] | null
}

export interface ModelRuntime {
  mode?: string
  model_flag?: string
  ref_flag?: string
  extra_args?: string[]
  defaults?: Partial<GeneratePayload>
  negative?: boolean
  parameters?: Record<string, boolean>
}

export interface ModelInfo {
  id?: string
  key: string
  name: string
  model_id: string
  source: string
  sources?: ModelSourceSpec[]
  files?: string[]
  family: string
  capabilities: string[]
  preferred: boolean
  description: string
  expected_files: string[]
  params?: string
  runtime?: ModelRuntime
  variants?: ModelInfo[]
  access_path: string
  resolved_path?: string
  status: 'ready' | 'missing' | 'downloading' | 'failed' | 'unknown'
  size?: number
  progress?: number | null
  current_file?: string | null
  downloaded_bytes?: number | null
  total_bytes?: number | null
  error?: string | null
  v_router?: {
    model: string
    qualified: string
    protocol: 'image_studio' | 'v_router'
    status: string
    endpoints: string[]
    capabilities: string[]
    model_kind: 'unknown'
  }
}

export interface GeneratePayload {
  prompt: string
  negative_prompt: string
  model_key: string
  model_variant: string
  init_job_id: string
  init_filename: string
  init_input_id: string
  width: number
  height: number
  steps: number
  cfg_scale: number
  strength: number
  sampler: string
  seed: number
  batch_count: number
  scheduler: string
  clip_skip: number
  guidance: number
  img_cfg_scale: number
  eta: number
  flow_shift: number
  high_noise_steps: number
  high_noise_cfg_scale: number
  high_noise_sampler: string
  slg_scale: number
  skip_layer_start: number
  skip_layer_end: number
  rng: string
  sampler_rng: string
  prediction: string
  weight_type: string
  tensor_type_rules: string
  cache_mode: string
  cache_option: string
  qwen_image_layers: number
  hires: boolean
  hires_scale: number
  hires_width: number
  hires_height: number
  hires_steps: number
  hires_denoising_strength: number
  video_frames: number
  fps: number
  vae_tiling: boolean
  vae_tile_size: string
  vae_tile_overlap: number
  temporal_tiling: boolean
  temporal_tile_frames: number
  temporal_tile_overlap: number
  max_vram: number
  stream_layers: boolean
  auto_fit: boolean
  clip_on_cpu: boolean
  offload_to_cpu: boolean
  vae_cpu_fallback: boolean
  backend: string
  params_backend: string
}

export interface JobRecord extends GeneratePayload {
  job_id: string
  user_key: string
  status: 'queued' | 'running' | 'succeeded' | 'failed'
  model_path: string
  progress: number
  outputs: string[]
  error: string
  created_at: string
  updated_at: string
  metadata?: { init_job_id?: string; init_filename?: string; init_input_id?: string }
  immich_uploads?: Record<string, ImmichUploadRecord>
}

export interface InputItem {
  input_id: string
  filename: string
  size: number
  created_at: string
  url: string
}

export interface SessionInfo {
  user_key: string
  authenticated: boolean
}

export interface TemplateInfo {
  id: string
  name: string
  description: string
  payload: Partial<GeneratePayload>
}

export interface AboutInfo {
  app_id: string
  app_version: string
  profile: string
  data_dir: string
  modelhub_root: string
  model_hub_api_url: string
  sd_cpp_bin: string
  max_concurrency: number
}

export interface UserSettings {
  language: 'zh-CN' | 'en'
}

export interface VRouterStatus {
  configured: boolean
  reachable: boolean
  api_url: string
  eligible_models: number
  error: string
}

export interface ImmichSettings {
  api_url: string
  configured: boolean
  verify_ssl: boolean
}

export interface ImmichUploadRecord {
  status: 'queued' | 'uploading' | 'uploaded' | 'duplicate' | 'failed'
  checksum: string
  asset_id?: string | null
  attempts: number
  error: string
  updated_at: string
}

async function requestOnce<T>(path: string, init?: RequestInit): Promise<Response> {
  const token = await getVOSBearerToken().catch(() => null)
  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(init?.headers || {}),
  }
  // 轮询任务/上传状态时不能拿到浏览器或网关缓存的旧响应。
  return fetch(`${API_BASE}${path}`, { cache: 'no-store', headers, ...init })
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let resp = await requestOnce<T>(path, init)
  // 401 = token 失效：清缓存并换新 token 重试一次；403 是权限问题，
  // 清缓存只会引发重复授权弹窗，不做处理。
  if (resp.status === 401) {
    clearCachedVOSBearerToken()
    resp = await requestOnce<T>(path, init)
  }
  if (!resp.ok) {
    const text = await resp.text()
    throw new Error(errorMessage(resp, text))
  }
  return resp.json()
}

function errorMessage(resp: Response, text: string): string {
  const trimmed = text.trim()
  if (trimmed.startsWith('{')) {
    try {
      const data = JSON.parse(trimmed)
      if (typeof data.detail === 'string') return data.detail
      if (typeof data.error === 'string') return data.error
    } catch {
      // Fall through to plain response handling.
    }
  }
  if (/^<!doctype html/i.test(trimmed) || /^<html[\s>]/i.test(trimmed)) {
    return `${resp.status} ${resp.statusText || '请求失败'}`
  }
  return trimmed || `${resp.status} ${resp.statusText}`
}

export const api = {
  about: () => request<AboutInfo>('/api/v1/about'),
  listTemplates: () => request<{ templates: TemplateInfo[]; default_template: string | null }>('/api/v1/templates'),
  saveTemplate: (name: string, payload: Partial<GeneratePayload>) =>
    request<TemplateInfo>('/api/v1/templates', { method: 'POST', body: JSON.stringify({ name, payload }) }),
  renameTemplate: (id: string, name: string) =>
    request<TemplateInfo>(`/api/v1/templates/${id}`, { method: 'PATCH', body: JSON.stringify({ name }) }),
  deleteTemplate: (id: string) => request<{ ok: boolean }>(`/api/v1/templates/${id}`, { method: 'DELETE' }),
  me: () => request<SessionInfo>('/api/v1/me'),
  settings: () => request<UserSettings>('/api/v1/settings'),
  updateSettings: (payload: UserSettings) => request<UserSettings>('/api/v1/settings', { method: 'PUT', body: JSON.stringify(payload) }),
  immichSettings: () => request<ImmichSettings>('/api/v1/immich'),
  updateImmichSettings: (payload: { api_url: string; api_key?: string; verify_ssl: boolean }) =>
    request<ImmichSettings>('/api/v1/immich', { method: 'PUT', body: JSON.stringify(payload) }),
  listModels: () => request<ModelInfo[]>('/api/v1/models'),
  vRouterStatus: () => request<VRouterStatus>('/api/v1/v-router/status'),
  pullModel: (key: string, force = false, variant = '') => {
    const params = new URLSearchParams()
    if (force) params.set('force', 'true')
    if (variant) params.set('variant', variant)
    const query = params.toString()
    return request(`/api/v1/models/${key}/pull${query ? `?${query}` : ''}`, { method: 'POST' })
  },
  stopModel: (key: string, variant = '') => request(`/api/v1/models/${key}/stop${variant ? `?variant=${encodeURIComponent(variant)}` : ''}`, { method: 'POST' }),
  syncModel: (key: string) => request(`/api/v1/models/${key}/sync`, { method: 'POST' }),
  generate: (payload: GeneratePayload) => request<JobRecord>('/api/v1/generate', { method: 'POST', body: JSON.stringify(payload) }),
  listJobs: () => request<JobRecord[]>('/api/v1/jobs'),
  getJob: (jobId: string) => request<JobRecord>(`/api/v1/jobs/${jobId}`),
  deleteJob: (jobId: string) => request<{ deleted: boolean; job_id: string }>(`/api/v1/jobs/${jobId}`, { method: 'DELETE' }),
  uploadJobToImmich: (jobId: string, force = false) =>
    request<JobRecord>(`/api/v1/jobs/${jobId}/immich-upload${force ? '?force=true' : ''}`, { method: 'POST' }),
  retryImmichUpload: (jobId: string) => request<JobRecord>(`/api/v1/jobs/${jobId}/immich-upload/retry`, { method: 'POST' }),
  outputUrl: (jobId: string, filename: string) => {
    const token = getCachedVOSBearerToken()
    const suffix = token ? `?access_token=${encodeURIComponent(token)}` : ''
    return `${API_BASE}/api/v1/outputs/${jobId}/${filename}${suffix}`
  },
  listInputs: () => request<InputItem[]>('/api/v1/inputs'),
  uploadInput: async (file: File) => {
    const token = await getVOSBearerToken().catch(() => null)
    const resp = await fetch(`${API_BASE}/api/v1/inputs`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      body: (() => {
        const form = new FormData()
        form.append('file', file)
        return form
      })(),
    })
    if (!resp.ok) {
      const text = await resp.text()
      throw new Error(errorMessage(resp, text))
    }
    return resp.json() as Promise<InputItem>
  },
  deleteInput: (inputId: string) => request<{ deleted: boolean }>(`/api/v1/inputs/${inputId}`, { method: 'DELETE' }),
  inputUrl: (inputId: string) => {
    const token = getCachedVOSBearerToken()
    const suffix = token ? `?access_token=${encodeURIComponent(token)}` : ''
    return `${API_BASE}/api/v1/inputs/${inputId}${suffix}`
  },
}
