import { getVOSBearerToken } from './vos-auth'

const API_BASE = import.meta.env.VITE_API_BASE || '/api/com.ictrek.image-studio'

export interface ModelInfo {
  key: string
  name: string
  model_id: string
  source: string
  description: string
  expected_files: string[]
  access_path: string
  resolved_path?: string
  status: 'ready' | 'missing' | 'downloading' | 'failed' | 'unknown'
  size?: number
}

export interface GeneratePayload {
  prompt: string
  negative_prompt: string
  model_key: string
  width: number
  height: number
  steps: number
  cfg_scale: number
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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = await getVOSBearerToken().catch(() => null)
  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(init?.headers || {}),
  }
  const resp = await fetch(`${API_BASE}${path}`, {
    headers,
    ...init,
  })
  if (!resp.ok) {
    const text = await resp.text()
    throw new Error(text || `${resp.status} ${resp.statusText}`)
  }
  return resp.json()
}

export const api = {
  about: () => request<AboutInfo>('/api/v1/about'),
  settings: () => request<UserSettings>('/api/v1/settings'),
  updateSettings: (payload: UserSettings) => request<UserSettings>('/api/v1/settings', { method: 'PUT', body: JSON.stringify(payload) }),
  listModels: () => request<ModelInfo[]>('/api/v1/models'),
  pullModel: (key: string) => request(`/api/v1/models/${key}/pull`, { method: 'POST' }),
  syncModel: (key: string) => request(`/api/v1/models/${key}/sync`, { method: 'POST' }),
  generate: (payload: GeneratePayload) => request<JobRecord>('/api/v1/generate', { method: 'POST', body: JSON.stringify(payload) }),
  listJobs: () => request<JobRecord[]>('/api/v1/jobs'),
  getJob: (jobId: string) => request<JobRecord>(`/api/v1/jobs/${jobId}`),
  outputUrl: (jobId: string, filename: string) => `${API_BASE}/api/v1/outputs/${jobId}/${filename}`,
}
