import { useEffect, useMemo, useRef, useState } from 'react'
import { ChevronDown, Database, Download, DownloadCloud, AlertTriangle, ImageIcon, Loader2, Play, RefreshCw, RotateCcw, Sparkles, Square, Trash2, UserCircle2, Wand2, X } from 'lucide-react'
import { api, GeneratePayload, InputItem, JobRecord, ModelInfo, SessionInfo } from '../api/client'
import { messages } from '../i18n'

function formatSize(bytes?: number) {
  if (!bytes) return '-'
  const units = ['B', 'KB', 'MB', 'GB']
  let value = bytes
  let idx = 0
  while (value >= 1024 && idx < units.length - 1) {
    value /= 1024
    idx += 1
  }
  return `${value.toFixed(idx === 0 ? 0 : 2)} ${units[idx]}`
}

function modelSize(model?: ModelInfo) {
  if (!model) return undefined
  return model.size || model.total_bytes || model.downloaded_bytes || undefined
}

const isVideoFile = (name: string) => /\.(mp4|webm|mov)$/i.test(name)
const samplerOptions = ['euler_a', 'euler', 'heun', 'dpm2', 'dpm++2s_a', 'dpm++2m', 'dpm++2mv2', 'ipndm', 'ipndm_v', 'lcm', 'ddim_trailing', 'tcd', 'res_multistep', 'res_2s', 'er_sde', 'euler_cfg_pp', 'euler_a_cfg_pp', 'euler_ge', 'dpm++2m_sde', 'dpm++2m_sde_bt', 'lms']
const schedulerOptions = ['', 'discrete', 'karras', 'exponential', 'ays', 'gits', 'sgm_uniform', 'simple', 'smoothstep', 'kl_optimal', 'lcm', 'bong_tangent', 'ltx2', 'logit_normal', 'flux2', 'flux', 'beta']
const rngOptions = ['', 'cuda', 'cpu', 'std_default']
const predictionOptions = ['', 'eps', 'v', 'edm_v', 'sd3_flow', 'flux_flow', 'sefi_flow']
const weightTypeOptions = ['', 'f32', 'f16', 'q4_0', 'q4_1', 'q5_0', 'q5_1', 'q8_0', 'q2_K', 'q3_K', 'q4_K']
const cacheOptions = ['', 'easycache', 'ucache', 'dbcache', 'taylorseer', 'cache-dit', 'spectrum']

const initialPayload: GeneratePayload = {
  prompt: 'a cozy mountain cabin at dusk, warm lights, snowy pine trees, cinematic lighting, ultra detailed',
  negative_prompt: 'blurry, low quality, watermark, text, deformed',
  model_key: 'sd15',
  model_variant: '',
  init_job_id: '',
  init_filename: '',
  init_input_id: '',
  width: 768,
  height: 768,
  steps: 30,
  cfg_scale: 7,
  strength: 0.75,
  sampler: 'euler_a',
  seed: -1,
  batch_count: 1,
  scheduler: '',
  clip_skip: -1,
  guidance: 0,
  img_cfg_scale: 0,
  eta: 0,
  flow_shift: 0,
  high_noise_steps: 0,
  high_noise_cfg_scale: 0,
  high_noise_sampler: '',
  slg_scale: 0,
  skip_layer_start: 0.01,
  skip_layer_end: 0.2,
  rng: '',
  sampler_rng: '',
  prediction: '',
  weight_type: '',
  tensor_type_rules: '',
  cache_mode: '',
  cache_option: '',
  qwen_image_layers: 0,
  hires: false,
  hires_scale: 2,
  hires_width: 0,
  hires_height: 0,
  hires_steps: 0,
  hires_denoising_strength: 0.7,
  video_frames: 33,
  fps: 24,
  vae_tiling: false,
  vae_tile_size: '',
  vae_tile_overlap: 0.5,
  temporal_tiling: true,
  temporal_tile_frames: 4,
  temporal_tile_overlap: 1,
  max_vram: -2,
  stream_layers: false,
  auto_fit: false,
  offload_to_cpu: false,
  vae_cpu_fallback: true,
  backend: '',
  params_backend: '',
}

export default function GeneratePage({ models, onRefresh, onOpenModels, t }: { models: ModelInfo[]; onRefresh: () => void; onOpenModels: () => void; t: typeof messages['zh-CN'] }) {
  const [payload, setPayload] = useState<GeneratePayload>(initialPayload)
  const [jobs, setJobs] = useState<JobRecord[]>([])
  const [inputs, setInputs] = useState<InputItem[]>([])
  const [session, setSession] = useState<SessionInfo | null>(null)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [playingUrl, setPlayingUrl] = useState('')
  const messagesRef = useRef<HTMLDivElement | null>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const imageModels = useMemo(() => models
    .filter(model => model.capabilities.includes('txt2img') || model.capabilities.includes('img2img') || model.capabilities.includes('video'))
    .sort((a, b) => Number(Boolean(b.variants?.length)) - Number(Boolean(a.variants?.length))), [models])
  const selectedModel = models.find(model => model.key === payload.model_key)
  const selectedVariant = selectedModel?.variants?.find(variant => variant.id === payload.model_variant)
  const activeModel = selectedVariant || selectedModel
  const modelReady = activeModel?.status === 'ready'
  const isVideoModel = activeModel?.runtime?.mode === 'video'
  const supportedParams = activeModel?.runtime?.parameters || {}
  const supportsParam = (name: string, fallback = true) => supportedParams[name] ?? fallback
  const modelUsable = Boolean(activeModel?.capabilities.includes('txt2img') || activeModel?.capabilities.includes('img2img')) || isVideoModel
  const supportsInit = supportsParam('reference_image', !isVideoModel)
  const isEditModel = activeModel?.runtime?.ref_flag === '-r'
  const supportsStrength = supportsParam('strength', !isEditModel && !isVideoModel)
  const negativeIgnored = !supportsParam('negative_prompt', activeModel?.runtime?.negative !== false)
  const hasRunning = jobs.some(job => job.status === 'queued' || job.status === 'running')
  const isImg2Img = Boolean((payload.init_job_id && payload.init_filename) || payload.init_input_id)
  const videoDuration = payload.fps > 0 && payload.video_frames > 0 ? (payload.video_frames / payload.fps).toFixed(1) : ''
  const initPreviewUrl = payload.init_input_id
    ? api.inputUrl(payload.init_input_id)
    : payload.init_job_id && payload.init_filename
      ? api.outputUrl(payload.init_job_id, payload.init_filename)
      : ''

  const modelName = (key: string) => models.find(m => m.key === key)?.name || key
  const modelVariantName = (key: string, variantId?: string) => {
    const model = models.find(m => m.key === key)
    if (!variantId) return model?.name || key
    const variant = model?.variants?.find(item => item.id === variantId)
    return variant ? `${model?.name || key} · ${variant.name}` : model?.name || key
  }

  const applyRuntimeDefaults = (base: GeneratePayload, model: ModelInfo | undefined, nextVideoModel: boolean): GeneratePayload => {
    const defaults = model?.runtime?.defaults || {}
    return {
      ...base,
      width: defaults.width ?? base.width,
      height: defaults.height ?? base.height,
      steps: defaults.steps ?? base.steps,
      cfg_scale: defaults.cfg_scale ?? base.cfg_scale,
      sampler: defaults.sampler ?? base.sampler,
      scheduler: defaults.scheduler ?? '',
      clip_skip: defaults.clip_skip ?? -1,
      guidance: defaults.guidance ?? 0,
      img_cfg_scale: defaults.img_cfg_scale ?? 0,
      eta: defaults.eta ?? 0,
      flow_shift: defaults.flow_shift ?? 0,
      high_noise_steps: defaults.high_noise_steps ?? 0,
      high_noise_cfg_scale: defaults.high_noise_cfg_scale ?? 0,
      high_noise_sampler: defaults.high_noise_sampler ?? '',
      slg_scale: defaults.slg_scale ?? 0,
      skip_layer_start: defaults.skip_layer_start ?? 0.01,
      skip_layer_end: defaults.skip_layer_end ?? 0.2,
      rng: defaults.rng ?? '',
      sampler_rng: defaults.sampler_rng ?? '',
      prediction: defaults.prediction ?? '',
      weight_type: defaults.weight_type ?? '',
      tensor_type_rules: defaults.tensor_type_rules ?? '',
      cache_mode: defaults.cache_mode ?? '',
      cache_option: defaults.cache_option ?? '',
      qwen_image_layers: defaults.qwen_image_layers ?? 0,
      hires: defaults.hires ?? false,
      hires_scale: defaults.hires_scale ?? 2,
      hires_width: defaults.hires_width ?? 0,
      hires_height: defaults.hires_height ?? 0,
      hires_steps: defaults.hires_steps ?? 0,
      hires_denoising_strength: defaults.hires_denoising_strength ?? 0.7,
      video_frames: defaults.video_frames ?? base.video_frames,
      fps: defaults.fps ?? base.fps,
      vae_tiling: defaults.vae_tiling ?? nextVideoModel,
      vae_tile_size: defaults.vae_tile_size ?? '',
      vae_tile_overlap: defaults.vae_tile_overlap ?? 0.5,
      temporal_tiling: defaults.temporal_tiling ?? model?.runtime?.parameters?.temporal_tiling ?? false,
      temporal_tile_frames: defaults.temporal_tile_frames ?? 4,
      temporal_tile_overlap: defaults.temporal_tile_overlap ?? 1,
      max_vram: defaults.max_vram ?? (nextVideoModel ? -2 : 0),
      stream_layers: defaults.stream_layers ?? nextVideoModel,
      auto_fit: defaults.auto_fit ?? false,
      offload_to_cpu: defaults.offload_to_cpu ?? false,
      vae_cpu_fallback: defaults.vae_cpu_fallback ?? nextVideoModel,
      backend: defaults.backend ?? '',
      params_backend: defaults.params_backend ?? '',
      batch_count: nextVideoModel ? 1 : base.batch_count,
    }
  }

  const switchModel = (key: string) => {
    const next = models.find(model => model.key === key)
    const nextVideoModel = next?.runtime?.mode === 'video'
    setPayload(applyRuntimeDefaults({
      ...payload,
      model_key: key,
      model_variant: '',
    }, next, Boolean(nextVideoModel)))
  }

  const switchVariant = (variantId: string) => {
    const next = variantId ? selectedModel?.variants?.find(variant => variant.id === variantId) : selectedModel
    const nextVideoModel = next?.runtime?.mode === 'video'
    setPayload(applyRuntimeDefaults({ ...payload, model_variant: variantId }, next, Boolean(nextVideoModel)))
  }

  const loadJobs = async () => {
    const data = await api.listJobs()
    setJobs(data)
  }

  const loadInputs = () => api.listInputs().then(setInputs).catch(() => undefined)

  useEffect(() => {
    loadJobs().catch(() => undefined)
    loadInputs()
  }, [])

  useEffect(() => {
    api.me().then(setSession).catch(() => undefined)
  }, [])

  // 新消息到达时贴底
  useEffect(() => {
    const el = messagesRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [jobs])

  const roundOf = useMemo(() => {
    const map = new Map<string, number>()
    jobs.forEach((job, index) => map.set(job.job_id, jobs.length - index))
    return map
  }, [jobs])

  const timeOf = (iso: string) => {
    try {
      return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    } catch {
      return ''
    }
  }

  const lineageOf = (job: JobRecord) => {
    if (job.metadata?.init_input_id) return t.uploadedImage
    const parent = job.metadata?.init_job_id
    if (!parent || !roundOf.has(parent)) return ''
    return `${t.basedOnRound} ${roundOf.get(parent)} ${t.turnWord}`
  }

  useEffect(() => {
    if (!hasRunning) return
    const timer = window.setInterval(() => loadJobs().catch(() => undefined), 2500)
    return () => window.clearInterval(timer)
  }, [hasRunning])

  const submit = async () => {
    setSubmitting(true)
    setError('')
    try {
      await api.generate(payload)
      await loadJobs()
    } catch (e: any) {
      setError(e.message || t.submitFailed)
    } finally {
      setSubmitting(false)
    }
  }

  const reuseOutput = (job: JobRecord, output: string) => {
    setPayload({
      ...payload,
      init_job_id: job.job_id,
      init_filename: output,
      init_input_id: '',
      width: job.width,
      height: job.height,
    })
    setPickerOpen(false)
  }

  const reuseInput = (inputId: string) => {
    setPayload({ ...payload, init_job_id: '', init_filename: '', init_input_id: inputId })
    setPickerOpen(false)
  }

  const clearSourceImage = () => {
    setPayload({ ...payload, init_job_id: '', init_filename: '', init_input_id: '' })
  }

  const uploadFile = async (file: File) => {
    setUploading(true)
    setError('')
    try {
      const item = await api.uploadInput(file)
      setPayload({ ...payload, init_job_id: '', init_filename: '', init_input_id: item.input_id })
      await loadInputs()
      setPickerOpen(false)
    } catch (e: any) {
      setError(e.message || t.uploadFailed)
    } finally {
      setUploading(false)
    }
  }

  const downloadModel = async () => {
    if (!selectedModel || activeModel?.status === 'downloading') return
    try {
      await api.pullModel(selectedModel.key, false, payload.model_variant)
      onRefresh()
    } catch { /* 模型管理页有完整反馈，这里静默刷新即可 */ }
  }

  const stopModelDownload = async () => {
    if (!selectedModel || activeModel?.status !== 'downloading') return
    try {
      await api.stopModel(selectedModel.key, payload.model_variant)
      onRefresh()
    } catch { /* 同上 */ }
  }

  const modelDownloading = activeModel?.status === 'downloading'
  const modelProgress = modelDownloading ? Math.round((activeModel?.progress ?? 0) * 100) : 0

  const deleteJob = async (job: JobRecord) => {
    const hasVideoOutput = job.outputs.some(isVideoFile)
    if (!window.confirm(hasVideoOutput ? t.confirmDeleteVideo : t.confirmDelete)) return
    await api.deleteJob(job.job_id)
    await loadJobs()
  }

  const sortedJobs = useMemo(() => [...jobs].reverse(), [jobs])

  return (
    <div className="page-stack">
      <section className="panel quick-settings-panel">
        <div className="quick-settings-grid">
          <div className="quick-field quick-model-field">
            <label>{t.modelPanelTitle}</label>
            <div className="quick-model-selectors">
              <select value={payload.model_key} onChange={e => switchModel(e.target.value)}>
                {imageModels.map(model => <option key={model.key} value={model.key}>{model.name}{model.params ? ` (${model.params})` : ''} · {model.family}</option>)}
              </select>
              {selectedModel && Boolean(selectedModel.variants?.length) && (
                <select value={payload.model_variant} onChange={e => switchVariant(e.target.value)}>
                  <option value="">{t.defaultModelVariant}</option>
                  {selectedModel.variants?.map(variant => <option key={variant.id} value={variant.id}>{variant.name}{variant.params ? ` (${variant.params})` : ''}</option>)}
                </select>
              )}
            </div>
          </div>
          <div className="quick-field"><label>{t.width}</label><input type="number" value={payload.width} onChange={e => setPayload({ ...payload, width: Number(e.target.value) })} /></div>
          <div className="quick-field"><label>{t.height}</label><input type="number" value={payload.height} onChange={e => setPayload({ ...payload, height: Number(e.target.value) })} /></div>
          <div className="quick-field"><label>{t.steps}</label><input type="number" value={payload.steps} onChange={e => setPayload({ ...payload, steps: Number(e.target.value) })} /></div>
          <div className="quick-field"><label>{t.cfgScale}{!supportsParam('cfg_scale') && <em className="ignored-tag">{t.paramIgnoredTag}</em>}</label><input type="number" step="0.5" value={payload.cfg_scale} disabled={!supportsParam('cfg_scale')} onChange={e => setPayload({ ...payload, cfg_scale: Number(e.target.value) })} /></div>
          <div className="quick-field"><label>{t.sampler}</label><select value={payload.sampler} onChange={e => setPayload({ ...payload, sampler: e.target.value })}>{samplerOptions.map(v => <option value={v} key={v}>{v}</option>)}</select></div>
          <div className="quick-field"><label>{t.seed}</label><input type="number" title={t.randomSeedHint} value={payload.seed} onChange={e => setPayload({ ...payload, seed: Number(e.target.value) })} /></div>
          <div className="quick-actions">
            <button className="icon-button" onClick={onRefresh} title={t.refreshModels}><RefreshCw size={16} /></button>
            <button className="icon-button" onClick={() => setPayload(initialPayload)} title={t.reset}><RotateCcw size={16} /></button>
          </div>
        </div>
        <div className={`quick-model-status ${modelReady ? 'ready' : modelDownloading ? 'downloading' : 'missing'}`}>
          <span className="quick-status-dot" />
          <strong>{activeModel?.name || selectedModel?.name || t.noModelsConfigured}</strong>
          <span>{modelReady ? t.modelReady : modelDownloading ? `${t.modelDownloading} ${modelProgress}%` : modelUsable ? t.modelMissing : t.chooseModelHint}</span>
          {activeModel && <code>{activeModel.source} · {activeModel.family} · {formatSize(modelSize(activeModel))}</code>}
          {!modelReady && activeModel && (
            <button className="quiet-button" disabled={modelDownloading} onClick={downloadModel}>
              {modelDownloading ? <Loader2 size={13} className="spin" /> : <DownloadCloud size={13} />}
              {modelDownloading ? `${modelProgress}%` : t.downloadModel}
            </button>
          )}
          {modelDownloading && <button className="quiet-button" onClick={stopModelDownload}><Square size={13} />{t.stopDownload}</button>}
          {(!modelReady || !modelUsable) && <button className="quiet-button" onClick={onOpenModels}><Database size={13} />{t.openModelManagement}</button>}
        </div>
      </section>
      {jobs[0] && (
        <div className="current-job-bar">
          <span className="current-job-label">{t.currentJob}</span>
          <span className={`job-status ${jobs[0].status}`}>{jobs[0].status}</span>
          <code>{jobs[0].job_id}</code>
          <progress max="1" value={jobs[0].progress} />
          <span className="current-job-pct">{Math.round(jobs[0].progress * 100)}%</span>
          <span className="current-job-prompt">{jobs[0].prompt.slice(0, 60)}{jobs[0].prompt.length > 60 ? '…' : ''}</span>
        </div>
      )}
      <div className="workspace-grid chat-workspace">
      {/* 左栏：聊天主窗口 */}
      <section className="panel chat-panel studio-panel">
        <div className="chat-toolbar">
          <div className="panel-title">{t.chatTitle}</div>
          <div className="session-user">
            <UserCircle2 size={18} />
            <div>
              <strong>{t.mySession}</strong>
              <code>{session ? session.user_key : '...'}</code>
              {session && !session.authenticated && <span className="tag-anonymous">{t.anonymousSession}</span>}
            </div>
          </div>
          <span className="session-count">{jobs.length} {t.imageCount} · {t.sessionIsolationHint}</span>
          <button className="icon-button" onClick={() => { loadJobs().catch(() => undefined); loadInputs() }} title={t.refreshModels}><RefreshCw size={16} /></button>
        </div>

        <div className="chat-messages" ref={messagesRef}>
          {sortedJobs.length === 0 && (
            <div className="chat-empty">
              <ImageIcon size={40} />
              <strong>{t.chatTitle}</strong>
              <span>{t.chatEmptyHint}</span>
            </div>
          )}
          {sortedJobs.map(job => {
            const round = roundOf.get(job.job_id)
            const lineage = lineageOf(job)
            const initThumb = job.metadata?.init_input_id
              ? api.inputUrl(job.metadata.init_input_id)
              : job.metadata?.init_job_id && job.metadata?.init_filename
                ? api.outputUrl(job.metadata.init_job_id, job.metadata.init_filename)
                : ''
            return (
              <div className="chat-turn" key={job.job_id}>
                <div className="chat-msg user-msg">
                  <div className="chat-bubble">
                    <div className="chat-msg-meta">
                      <span>#{round} {t.meLabel} · {timeOf(job.created_at)}</span>
                      <span>{modelVariantName(job.model_key, job.model_variant)} · {job.width}×{job.height} · {job.steps} steps · cfg {job.cfg_scale} · {job.sampler}{job.seed >= 0 ? ` · seed ${job.seed}` : ''}{job.video_frames > 1 ? ` · ${job.video_frames}f${job.fps ? `@${job.fps}` : ''}` : ''}</span>
                      {lineage && <span>↳ {lineage}</span>}
                    </div>
                    {initThumb && <img className="chat-msg-init" src={initThumb} alt="" />}
                    <p className="chat-msg-prompt">{job.prompt}</p>
                    {job.negative_prompt && <p className="chat-msg-negative">− {job.negative_prompt}</p>}
                  </div>
                </div>
                <div className="chat-msg assistant-msg">
                  <div className={`chat-bubble ${job.status === 'failed' ? 'failed' : ''}`}>
                    <div className="chat-msg-meta"><span>{modelVariantName(job.model_key, job.model_variant)}</span></div>
                    {job.status === 'succeeded' && job.outputs.map(output => {
                      const url = api.outputUrl(job.job_id, output)
                      if (isVideoFile(output)) {
                        return (
                          <div className="chat-msg-video" key={output} onClick={() => setPlayingUrl(url)} title={t.videoPlayHint}>
                            <video src={url} preload="metadata" muted />
                            <span className="chat-msg-video-play"><Play size={22} /></span>
                            <span className="chat-msg-video-tag">{t.videoBadge}</span>
                          </div>
                        )
                      }
                      return <img className="chat-msg-image" key={output} src={url} alt={job.prompt} onClick={() => reuseOutput(job, output)} title={t.continueThread} />
                    })}
                    {(job.status === 'queued' || job.status === 'running') && (
                      <div className="chat-msg-running">
                        <Loader2 size={16} className="spin" />
                        <span>{job.status} · {Math.round(job.progress * 100)}%</span>
                        <progress max="1" value={job.progress} />
                      </div>
                    )}
                    {job.status === 'failed' && (
                      <div className="chat-msg-error">
                        <AlertTriangle size={16} />
                        <code>{job.error || t.generationFailed}</code>
                      </div>
                    )}
                    <div className="chat-msg-actions">
                      {job.outputs[0] && !isVideoFile(job.outputs[0]) && <button className="quiet-button" onClick={() => reuseOutput(job, job.outputs[0])}><Wand2 size={14} />{t.continueThread}</button>}
                      {job.outputs[0] && <a className="quiet-button" href={api.outputUrl(job.job_id, job.outputs[0])} download><Download size={14} />{t.downloadOutput}</a>}
                      <button className="quiet-button danger-action" onClick={() => deleteJob(job)}><Trash2 size={14} />{job.outputs.some(isVideoFile) ? t.deleteVideoOutput : t.deleteOutput}</button>
                    </div>
                  </div>
                </div>
              </div>
            )
          })}
        </div>

        {pickerOpen && (
          <div className="img-picker">
            <div className="img-picker-head">
              <strong>{t.pickSourceTitle}</strong>
              <button className="quiet-button" onClick={() => setPickerOpen(false)}><X size={14} />{t.closePicker}</button>
            </div>
            <div className="img-picker-section">{t.recentOutputs}</div>
            <div className="img-picker-grid">
              {jobs.slice(0, 10).flatMap(job => job.outputs.filter(o => !isVideoFile(o)).map(output => (
                <button key={job.job_id + output} className="img-picker-item" onClick={() => reuseOutput(job, output)}>
                  <img src={api.outputUrl(job.job_id, output)} alt="" />
                  <span>#{roundOf.get(job.job_id)}</span>
                </button>
              )))}
            </div>
            <div className="img-picker-section">{t.uploadedImages}</div>
            <div className="img-picker-grid">
              {inputs.map(item => (
                <button key={item.input_id} className="img-picker-item" onClick={() => reuseInput(item.input_id)}>
                  <img src={api.inputUrl(item.input_id)} alt="" />
                  <span>{formatSize(item.size)}</span>
                </button>
              ))}
              <button className="img-picker-item upload" onClick={() => fileInputRef.current?.click()} disabled={uploading}>
                {uploading ? <Loader2 size={18} className="spin" /> : <DownloadCloud size={18} className="flip" />}
                <span>{t.uploadImage}</span>
              </button>
            </div>
          </div>
        )}

        <div className="chat-composer">
          {supportsInit && (
          <div className="composer-image">
            {initPreviewUrl ? (
              <div className="img-slot filled">
                <img src={initPreviewUrl} alt="" />
                <button className="img-slot-clear" onClick={clearSourceImage} title={t.clearImage}><X size={13} /></button>
                <span className="img-slot-tag">{payload.init_input_id ? t.uploadedImage : `${t.basedOnRound} ${roundOf.get(payload.init_job_id) ?? ''} ${t.turnWord}`}</span>
              </div>
            ) : (
              <div className="img-slot empty">
                <ImageIcon size={18} />
                <button className="quiet-button" onClick={() => fileInputRef.current?.click()} disabled={uploading}>
                  {uploading ? <Loader2 size={13} className="spin" /> : <DownloadCloud size={13} className="flip" />}{t.uploadImage}
                </button>
                <button className="quiet-button" onClick={() => setPickerOpen(v => !v)}><Wand2 size={13} />{t.pickFromHistory}</button>
              </div>
            )}
            <input
              ref={fileInputRef}
              type="file"
              accept=".png,.jpg,.jpeg,.webp"
              hidden
              onChange={e => {
                const file = e.target.files?.[0]
                if (file) uploadFile(file)
                e.target.value = ''
              }}
            />
          </div>
          )}
          {isVideoModel && !supportsInit && (
            <div className="composer-video-hint">{t.videoNoRefHint}</div>
          )}
          <div className="composer-columns">
            <div className="composer-col">
              <label>{t.positivePrompt}</label>
              <textarea
                value={payload.prompt}
                onChange={e => setPayload({ ...payload, prompt: e.target.value })}
                onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submit() }}
                rows={4}
              />
            </div>
            <div className="composer-col">
              <label>{t.negativePrompt}{negativeIgnored && <em className="ignored-tag">{t.paramIgnoredTag}</em>}</label>
              <textarea
                value={payload.negative_prompt}
                onChange={e => setPayload({ ...payload, negative_prompt: e.target.value })}
                rows={4}
                disabled={negativeIgnored}
                placeholder={negativeIgnored ? t.negativeIgnoredHint : ''}
              />
            </div>
          </div>
          <div className="composer-send">
            {error && <div className="notice error">{error}</div>}
            <button className="primary-action generate-action" disabled={submitting || !modelReady || !modelUsable} onClick={submit}>
              {submitting ? <Loader2 size={16} className="spin" /> : <Sparkles size={16} />}{submitting ? t.submitting : isVideoModel ? t.submitVideo : t.submit}
            </button>
          </div>
        </div>
      </section>

      {/* 右栏：任务参数检查器 */}
      <aside className="panel detail-panel studio-panel">
        <div className="panel-heading">
          <div className="panel-title">{isVideoModel ? t.baseParamsTitle : t.imageParamsTitle}</div>
        </div>
        <div className={`inline-status ${isImg2Img ? 'ready' : ''}`}>
          <strong>{isVideoModel ? (isImg2Img ? t.img2Video : t.text2Video) : isImg2Img ? (isEditModel ? t.imageEdit : t.imageToImage) : t.textToImage}</strong>
          <span>{isVideoModel ? t.videoModelHint : isImg2Img ? (isEditModel ? t.imageEditHint : t.sourceImageHint) : t.previewHint}</span>
          {isImg2Img && <code>{payload.init_input_id || `${payload.init_job_id}/${payload.init_filename}`}</code>}
        </div>
        <div className="side-param-block">
          <div className="control-row two">
            <div>
              <label>{t.strength}{!(isImg2Img && supportsStrength) && <em className="ignored-tag">{t.paramIgnoredTag}</em>}</label>
              <input type="number" min="0" max="1" step="0.05" value={payload.strength} disabled={!(isImg2Img && supportsStrength)} onChange={e => setPayload({ ...payload, strength: Number(e.target.value) })} />
            </div>
            <div>
              <label>{t.batch}{isVideoModel && <em className="ignored-tag">{t.paramIgnoredTag}</em>}</label>
              <input type="number" min="1" max="4" value={payload.batch_count} disabled={!supportsParam('batch_count')} onChange={e => setPayload({ ...payload, batch_count: Number(e.target.value) })} />
            </div>
          </div>
        </div>
        {isVideoModel && (
          <details className="parameter-section">
            <summary><span>{t.videoParamsTitle}</span><ChevronDown size={16} aria-hidden="true" /></summary>
            <div className="parameter-section-body">
              <div className="control-row two">
                <div><label>{t.videoFrames}</label><input type="number" min="2" max="240" value={payload.video_frames} disabled={!supportsParam('video_frames', isVideoModel)} onChange={e => setPayload({ ...payload, video_frames: Number(e.target.value) })} /></div>
                <div><label>{t.videoFps}</label><input type="number" min="1" max="60" value={payload.fps} disabled={!supportsParam('fps', isVideoModel)} onChange={e => setPayload({ ...payload, fps: Number(e.target.value) })} /></div>
              </div>
              <div className="control-row two">
                <div><label>{t.highNoiseSteps}{!supportsParam('high_noise_steps', false) && <em className="ignored-tag">{t.paramIgnoredTag}</em>}</label><input type="number" min="0" max="150" value={payload.high_noise_steps} disabled={!supportsParam('high_noise_steps', false)} onChange={e => setPayload({ ...payload, high_noise_steps: Number(e.target.value) })} /></div>
                <div><label>{t.highNoiseCfg}{!supportsParam('high_noise_cfg_scale', false) && <em className="ignored-tag">{t.paramIgnoredTag}</em>}</label><input type="number" min="0" max="30" step="0.5" value={payload.high_noise_cfg_scale} disabled={!supportsParam('high_noise_cfg_scale', false)} onChange={e => setPayload({ ...payload, high_noise_cfg_scale: Number(e.target.value) })} /></div>
              </div>
              <div className="control-row">
                <div><label>{t.highNoiseSampler}{!supportsParam('high_noise_sampler', false) && <em className="ignored-tag">{t.paramIgnoredTag}</em>}</label><select value={payload.high_noise_sampler} disabled={!supportsParam('high_noise_sampler', false)} onChange={e => setPayload({ ...payload, high_noise_sampler: e.target.value })}><option value="">{t.modelDefault}</option>{samplerOptions.map(v => <option value={v} key={v}>{v}</option>)}</select></div>
              </div>
              {videoDuration && <span className="video-duration">{t.videoDurationHint} {videoDuration} {t.videoSeconds}</span>}
            </div>
          </details>
        )}
        <details className="parameter-section">
          <summary><span>{t.imageAdvancedParamsTitle}</span><ChevronDown size={16} aria-hidden="true" /></summary>
          <div className="parameter-section-body">
          <div className="control-row two">
            <div><label>{t.scheduler}</label><select value={payload.scheduler} disabled={!supportsParam('scheduler')} onChange={e => setPayload({ ...payload, scheduler: e.target.value })}>{schedulerOptions.map(v => <option value={v} key={v}>{v || t.modelDefault}</option>)}</select></div>
            <div><label>{t.clipSkip}</label><input type="number" min="-1" max="24" value={payload.clip_skip} disabled={!supportsParam('clip_skip')} onChange={e => setPayload({ ...payload, clip_skip: Number(e.target.value) })} /></div>
          </div>
          <div className="control-row two">
            <div><label>{t.guidance}</label><input type="number" min="0" max="30" step="0.5" value={payload.guidance} disabled={!supportsParam('guidance')} onChange={e => setPayload({ ...payload, guidance: Number(e.target.value) })} /></div>
            <div><label>{t.imgCfgScale}{!supportsParam('img_cfg_scale', false) && <em className="ignored-tag">{t.paramIgnoredTag}</em>}</label><input type="number" min="0" max="30" step="0.5" value={payload.img_cfg_scale} disabled={!supportsParam('img_cfg_scale', false)} onChange={e => setPayload({ ...payload, img_cfg_scale: Number(e.target.value) })} /></div>
          </div>
          <div className="control-row two">
            <div><label>{t.eta}</label><input type="number" min="0" max="10" step="0.05" value={payload.eta} disabled={!supportsParam('eta')} onChange={e => setPayload({ ...payload, eta: Number(e.target.value) })} /></div>
            <div><label>{t.flowShift}</label><input type="number" min="0" max="20" step="0.1" value={payload.flow_shift} disabled={!supportsParam('flow_shift')} onChange={e => setPayload({ ...payload, flow_shift: Number(e.target.value) })} /></div>
          </div>
          <div className="control-row two">
            <div><label>{t.slgScale}</label><input type="number" min="0" max="20" step="0.1" value={payload.slg_scale} disabled={!supportsParam('slg_scale')} onChange={e => setPayload({ ...payload, slg_scale: Number(e.target.value) })} /></div>
            <div><label>{t.skipLayerRange}</label><input type="text" value={`${payload.skip_layer_start}-${payload.skip_layer_end}`} disabled={!supportsParam('slg_scale')} onChange={e => {
              const [start, end] = e.target.value.split('-').map(Number)
              setPayload({ ...payload, skip_layer_start: Number.isFinite(start) ? start : payload.skip_layer_start, skip_layer_end: Number.isFinite(end) ? end : payload.skip_layer_end })
            }} /></div>
          </div>
          <div className="control-row two">
            <div><label>{t.rng}</label><select value={payload.rng} disabled={!supportsParam('rng')} onChange={e => setPayload({ ...payload, rng: e.target.value })}>{rngOptions.map(v => <option value={v} key={v}>{v || t.modelDefault}</option>)}</select></div>
            <div><label>{t.samplerRng}</label><select value={payload.sampler_rng} disabled={!supportsParam('sampler_rng')} onChange={e => setPayload({ ...payload, sampler_rng: e.target.value })}>{rngOptions.map(v => <option value={v} key={v}>{v || t.sameAsRng}</option>)}</select></div>
          </div>
          <div className="control-row two">
            <div><label>{t.prediction}</label><select value={payload.prediction} disabled={!supportsParam('prediction')} onChange={e => setPayload({ ...payload, prediction: e.target.value })}>{predictionOptions.map(v => <option value={v} key={v}>{v || t.modelDefault}</option>)}</select></div>
            <div><label>{t.qwenImageLayers}{!supportsParam('qwen_image_layers', false) && <em className="ignored-tag">{t.paramIgnoredTag}</em>}</label><input type="number" min="0" max="16" value={payload.qwen_image_layers} disabled={!supportsParam('qwen_image_layers', false)} onChange={e => setPayload({ ...payload, qwen_image_layers: Number(e.target.value) })} /></div>
          </div>
          <div className="control-row two">
            <div><label>{t.weightType}</label><select value={payload.weight_type} disabled={!supportsParam('weight_type')} onChange={e => setPayload({ ...payload, weight_type: e.target.value })}>{weightTypeOptions.map(v => <option value={v} key={v}>{v || t.modelDefault}</option>)}</select></div>
            <div><label>{t.tensorTypeRules}</label><input value={payload.tensor_type_rules} disabled={!supportsParam('tensor_type_rules')} onChange={e => setPayload({ ...payload, tensor_type_rules: e.target.value })} placeholder="^vae.=f16,model.=q8_0" /></div>
          </div>
          <div className="control-row two">
            <label className="check-row"><input type="checkbox" checked={payload.hires} disabled={!supportsParam('hires', !isVideoModel)} onChange={e => setPayload({ ...payload, hires: e.target.checked })} />{t.hires}</label>
            <div><label>{t.hiresScale}</label><input type="number" min="1" max="8" step="0.1" value={payload.hires_scale} disabled={!payload.hires || !supportsParam('hires_scale', !isVideoModel)} onChange={e => setPayload({ ...payload, hires_scale: Number(e.target.value) })} /></div>
          </div>
          <div className="control-row two">
            <div><label>{t.hiresSize}</label><input type="text" value={`${payload.hires_width || 0}x${payload.hires_height || 0}`} disabled={!payload.hires || !supportsParam('hires_width', !isVideoModel)} onChange={e => {
              const [width, height] = e.target.value.toLowerCase().split('x').map(Number)
              setPayload({ ...payload, hires_width: Number.isFinite(width) ? width : 0, hires_height: Number.isFinite(height) ? height : 0 })
            }} /></div>
            <div><label>{t.hiresSteps}</label><input type="number" min="0" max="150" value={payload.hires_steps} disabled={!payload.hires || !supportsParam('hires_steps', !isVideoModel)} onChange={e => setPayload({ ...payload, hires_steps: Number(e.target.value) })} /></div>
          </div>
          <div className="control-row two">
            <div><label>{t.hiresDenoise}</label><input type="number" min="0" max="1" step="0.05" value={payload.hires_denoising_strength} disabled={!payload.hires || !supportsParam('hires_denoising_strength', !isVideoModel)} onChange={e => setPayload({ ...payload, hires_denoising_strength: Number(e.target.value) })} /></div>
            <div><label>{t.cacheMode}</label><select value={payload.cache_mode} disabled={!supportsParam('cache_mode')} onChange={e => setPayload({ ...payload, cache_mode: e.target.value })}>{cacheOptions.map(v => <option value={v} key={v}>{v || t.disabled}</option>)}</select></div>
          </div>
          <div className="control-row">
            <div><label>{t.cacheOption}</label><input value={payload.cache_option} disabled={!supportsParam('cache_option')} onChange={e => setPayload({ ...payload, cache_option: e.target.value })} placeholder="threshold=0.25,start=0.1,end=0.8" /></div>
          </div>
          </div>
        </details>
        <details className="parameter-section">
          <summary><span>{t.memoryParamsTitle}</span><ChevronDown size={16} aria-hidden="true" /></summary>
          <div className="parameter-section-body">
          <div className="control-row two">
            <label className="check-row"><input type="checkbox" checked={payload.vae_tiling} disabled={!supportsParam('vae_tiling')} onChange={e => setPayload({ ...payload, vae_tiling: e.target.checked })} />{t.vaeTiling}</label>
            <label className="check-row"><input type="checkbox" checked={payload.stream_layers} disabled={!supportsParam('stream_layers')} onChange={e => setPayload({ ...payload, stream_layers: e.target.checked })} />{t.streamLayers}</label>
          </div>
          <div className="control-row two">
            <div><label>{t.maxVram}</label><input type="number" min="-64" max="128" step="0.5" value={payload.max_vram} disabled={!supportsParam('max_vram')} onChange={e => setPayload({ ...payload, max_vram: Number(e.target.value) })} /></div>
            <div><label>{t.vaeTileSize}</label><input value={payload.vae_tile_size} disabled={!payload.vae_tiling || !supportsParam('vae_tile_size')} onChange={e => setPayload({ ...payload, vae_tile_size: e.target.value })} placeholder="32x32" /></div>
          </div>
          <div className="control-row two">
            <div><label>{t.vaeTileOverlap}</label><input type="number" min="0" max="0.95" step="0.05" value={payload.vae_tile_overlap} disabled={!payload.vae_tiling || !supportsParam('vae_tile_overlap')} onChange={e => setPayload({ ...payload, vae_tile_overlap: Number(e.target.value) })} /></div>
            <label className="check-row"><input type="checkbox" checked={payload.auto_fit} disabled={!supportsParam('auto_fit')} onChange={e => setPayload({ ...payload, auto_fit: e.target.checked })} />{t.autoFit}</label>
          </div>
          <div className="control-row two">
            <label className="check-row"><input type="checkbox" checked={payload.offload_to_cpu} disabled={!supportsParam('offload_to_cpu')} onChange={e => setPayload({ ...payload, offload_to_cpu: e.target.checked })} />{t.offloadToCpu}</label>
            <label className="check-row"><input type="checkbox" checked={payload.vae_cpu_fallback} disabled={!supportsParam('vae_cpu_fallback', isVideoModel)} onChange={e => setPayload({ ...payload, vae_cpu_fallback: e.target.checked })} />{t.vaeCpuFallback}</label>
          </div>
          <div className="control-row two">
            <label className="check-row"><input type="checkbox" checked={payload.temporal_tiling} disabled={!supportsParam('temporal_tiling', false)} onChange={e => setPayload({ ...payload, temporal_tiling: e.target.checked })} />{t.temporalTiling}</label>
            <div><label>{t.temporalTileFrames}</label><input type="number" min="1" max="32" value={payload.temporal_tile_frames} disabled={!payload.temporal_tiling || !supportsParam('temporal_tile_frames', false)} onChange={e => setPayload({ ...payload, temporal_tile_frames: Number(e.target.value) })} /></div>
          </div>
          <div className="control-row two">
            <div><label>{t.temporalTileOverlap}</label><input type="number" min="0" max="16" value={payload.temporal_tile_overlap} disabled={!payload.temporal_tiling || !supportsParam('temporal_tile_overlap', false)} onChange={e => setPayload({ ...payload, temporal_tile_overlap: Number(e.target.value) })} /></div>
            <div><label>{t.paramsBackend}</label><input value={payload.params_backend} disabled={!supportsParam('params_backend')} onChange={e => setPayload({ ...payload, params_backend: e.target.value })} placeholder="cpu / disk" /></div>
          </div>
          <div className="control-row">
            <div><label>{t.backendAssign}</label><input value={payload.backend} disabled={!supportsParam('backend')} onChange={e => setPayload({ ...payload, backend: e.target.value })} placeholder="clip=cpu,vae=cuda0,diffusion=cuda0" /></div>
          </div>
          </div>
        </details>
        <p className="api-note">{t.paramsIgnoredHint}</p>
      </aside>

      {playingUrl && (
        <div className="video-modal" role="presentation" onClick={() => setPlayingUrl('')}>
          <div className="video-modal-box" role="dialog" aria-modal="true" onClick={e => e.stopPropagation()}>
            <button className="video-modal-close" onClick={() => setPlayingUrl('')} title={t.closeVideo}><X size={18} /></button>
            <video src={playingUrl} controls autoPlay playsInline />
          </div>
        </div>
      )}
    </div>
    </div>
  )
}
