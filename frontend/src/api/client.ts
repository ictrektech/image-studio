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
}

export interface ModelInfo {
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
  runtime?: ModelRuntime
  access_path: string
  resolved_path?: string
  status: 'ready' | 'missing' | 'downloading' | 'failed' | 'unknown'
  size?: number
  progress?: number | null
  current_file?: string | null
  downloaded_bytes?: number | null
  total_bytes?: number | null
  error?: string | null
}

export interface GeneratePayload {
  prompt: string
  negative_prompt: string
  model_key: string
  init_job_id: string
  init_filename: string
  width: number
  height: number
  steps: number
  cfg_scale: number
  strength: number
  sampler: string
  seed: number
  batch_count: number
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
  metadata?: { init_job_id?: string; init_filename?: string }
}

export interface SessionInfo {
  user_key: string
  authenticated: boolean
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

async function requestOnce<T>(path: string, init?: RequestInit): Promise<Response> {
  const token = await getVOSBearerToken().catch(() => null)
  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(init?.headers || {}),
  }
  return fetch(`${API_BASE}${path}`, { headers, ...init })
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
    throw new Error(text || `${resp.status} ${resp.statusText}`)
  }
  return resp.json()
}

export const api = {
  about: () => request<AboutInfo>('/api/v1/about'),
  me: () => request<SessionInfo>('/api/v1/me'),
  settings: () => request<UserSettings>('/api/v1/settings'),
  updateSettings: (payload: UserSettings) => request<UserSettings>('/api/v1/settings', { method: 'PUT', body: JSON.stringify(payload) }),
  listModels: () => request<ModelInfo[]>('/api/v1/models'),
  pullModel: (key: string, force = false) => request(`/api/v1/models/${key}/pull${force ? '?force=true' : ''}`, { method: 'POST' }),
  stopModel: (key: string) => request(`/api/v1/models/${key}/stop`, { method: 'POST' }),
  syncModel: (key: string) => request(`/api/v1/models/${key}/sync`, { method: 'POST' }),
  generate: (payload: GeneratePayload) => request<JobRecord>('/api/v1/generate', { method: 'POST', body: JSON.stringify(payload) }),
  listJobs: () => request<JobRecord[]>('/api/v1/jobs'),
  getJob: (jobId: string) => request<JobRecord>(`/api/v1/jobs/${jobId}`),
  deleteJob: (jobId: string) => request<{ deleted: boolean; job_id: string }>(`/api/v1/jobs/${jobId}`, { method: 'DELETE' }),
  outputUrl: (jobId: string, filename: string) => {
    const token = getCachedVOSBearerToken()
    const suffix = token ? `?access_token=${encodeURIComponent(token)}` : ''
    return `${API_BASE}/api/v1/outputs/${jobId}/${filename}${suffix}`
  },
}
