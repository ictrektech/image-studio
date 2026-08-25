import { useEffect, useMemo, useRef, useState } from 'react'
import { CheckCircle2, Database, Download, DownloadCloud, AlertTriangle, ImageIcon, Loader2, Play, RefreshCw, RotateCcw, Sparkles, Square, Trash2, UserCircle2, Wand2, X } from 'lucide-react'
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

const isVideoFile = (name: string) => /\.(mp4|webm|mov)$/i.test(name)

const initialPayload: GeneratePayload = {
  prompt: 'a cozy mountain cabin at dusk, warm lights, snowy pine trees, cinematic lighting, ultra detailed',
  negative_prompt: 'blurry, low quality, watermark, text, deformed',
  model_key: 'sd15',
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
  video_frames: 33,
  fps: 24,
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

  const imageModels = useMemo(() => models.filter(model =>
    model.capabilities.includes('txt2img') || model.capabilities.includes('img2img') || model.capabilities.includes('video')), [models])
  const selectedModel = models.find(model => model.key === payload.model_key)
  const modelReady = selectedModel?.status === 'ready'
  const isVideoModel = selectedModel?.runtime?.mode === 'video'
  const modelUsable = Boolean(selectedModel?.capabilities.includes('txt2img') || selectedModel?.capabilities.includes('img2img')) || isVideoModel
  const supportsInit = !isVideoModel || Boolean(selectedModel?.runtime?.ref_flag)
  const isEditModel = selectedModel?.runtime?.ref_flag === '-r'
  const supportsStrength = !isEditModel && !isVideoModel
  const negativeIgnored = selectedModel?.runtime?.negative === false
  const hasRunning = jobs.some(job => job.status === 'queued' || job.status === 'running')
  const isImg2Img = Boolean((payload.init_job_id && payload.init_filename) || payload.init_input_id)
  const videoDuration = payload.fps > 0 && payload.video_frames > 0 ? (payload.video_frames / payload.fps).toFixed(1) : ''
  const initPreviewUrl = payload.init_input_id
    ? api.inputUrl(payload.init_input_id)
    : payload.init_job_id && payload.init_filename
      ? api.outputUrl(payload.init_job_id, payload.init_filename)
      : ''

  const modelName = (key: string) => models.find(m => m.key === key)?.name || key

  const switchModel = (key: string) => {
    const next = models.find(model => model.key === key)
    const defaults = next?.runtime?.defaults || {}
    setPayload({
      ...payload,
      model_key: key,
      width: defaults.width ?? payload.width,
      height: defaults.height ?? payload.height,
      steps: defaults.steps ?? payload.steps,
      cfg_scale: defaults.cfg_scale ?? payload.cfg_scale,
      sampler: defaults.sampler ?? payload.sampler,
      video_frames: defaults.video_frames ?? payload.video_frames,
      fps: defaults.fps ?? payload.fps,
    })
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
    if (!selectedModel || selectedModel.status === 'downloading') return
    try {
      await api.pullModel(selectedModel.key)
      onRefresh()
    } catch { /* 模型管理页有完整反馈，这里静默刷新即可 */ }
  }

  const stopModelDownload = async () => {
    if (!selectedModel || selectedModel.status !== 'downloading') return
    try {
      await api.stopModel(selectedModel.key)
      onRefresh()
    } catch { /* 同上 */ }
  }

  const modelDownloading = selectedModel?.status === 'downloading'
  const modelProgress = modelDownloading ? Math.round((selectedModel?.progress ?? 0) * 100) : 0

  const deleteJob = async (job: JobRecord) => {
    if (!window.confirm(t.confirmDelete)) return
    await api.deleteJob(job.job_id)
    await loadJobs()
  }

  const sortedJobs = useMemo(() => [...jobs].reverse(), [jobs])

  return (
    <div className="workspace-grid chat-workspace">
      {/* 左栏：模型 */}
      <section className="panel side-panel studio-panel">
        <div className="panel-heading">
          <div className="panel-title">{t.modelPanelTitle}</div>
          <button className="quiet-button" onClick={onRefresh} title={t.refreshModels}><RefreshCw size={15} /></button>
        </div>
        <select value={payload.model_key} onChange={e => switchModel(e.target.value)}>
          {imageModels.map(model => <option key={model.key} value={model.key}>{model.name}{model.params ? ` (${model.params})` : ''} · {model.family}</option>)}
        </select>
        <div className={`inline-status ${modelReady ? 'ready' : 'missing'}`}>
          <strong>{selectedModel?.name || t.noModelsConfigured}</strong>
          <span>{modelUsable ? (modelReady ? t.modelReady : t.modelMissing) : t.chooseModelHint}</span>
          <code>{selectedModel?.resolved_path || selectedModel?.access_path || '-'}</code>
        </div>
        {selectedModel && (
          <div className={`model-brief-card ${modelReady ? 'ready' : modelDownloading ? 'downloading' : 'pending'}`}>
            <div className="model-brief-meta">
              <div><span>{t.status}</span>
                <code className="model-brief-status">
                  {modelReady && <CheckCircle2 size={13} />}
                  {modelDownloading && <Loader2 size={13} className="spin" />}
                  {modelReady ? t.modelReady : modelDownloading ? `${t.modelDownloading} ${modelProgress}%` : selectedModel.status === 'failed' ? t.modelFailed : t.modelMissing}
                </code>
              </div>
              <div><span>{t.source}</span><code>{selectedModel.source}</code></div>
              <div><span>{t.family}</span><code>{selectedModel.family}</code></div>
              <div><span>{t.paramsLabel}</span><code>{selectedModel.params || '-'}</code></div>
              <div><span>{t.capabilities}</span><code>{selectedModel.capabilities.join(', ')}</code></div>
              <div><span>{t.modelId}</span><code>{selectedModel.model_id}</code></div>
              <div><span>{t.size}</span><code>{modelReady ? formatSize(selectedModel.size) : modelDownloading ? formatSize(selectedModel.downloaded_bytes ?? undefined) : '-'}</code></div>
            </div>
            {!modelReady && (
              <>
                {selectedModel.status === 'failed' && selectedModel.error && (
                  <code className="model-brief-error">⚠ {selectedModel.error}</code>
                )}
                <button
                  className="secondary-action model-brief-download"
                  disabled={modelDownloading}
                  onClick={downloadModel}
                >
                  {modelDownloading ? <Loader2 size={14} className="spin" /> : <DownloadCloud size={14} />}
                  {modelDownloading ? `${t.modelDownloading} ${modelProgress}%` : t.downloadModel}
                </button>
                {modelDownloading && (
                  <button className="secondary-action model-brief-download" onClick={stopModelDownload}>
                    <Square size={14} />{t.stopDownload}
                  </button>
                )}
                {modelDownloading && <progress className="model-brief-progress" max="100" value={modelProgress} />}
              </>
            )}
          </div>
        )}
        {(!modelReady || !modelUsable) && (
          <button className="secondary-action model-jump-action" onClick={onOpenModels}>
            <Database size={15} />{t.openModelManagement}
          </button>
        )}
      </section>

      {/* 中间：聊天主窗口 */}
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
                      <span>{modelName(job.model_key)} · {job.width}×{job.height} · {job.steps} steps · cfg {job.cfg_scale} · {job.sampler}{job.seed >= 0 ? ` · seed ${job.seed}` : ''}{job.video_frames > 1 ? ` · ${job.video_frames}f${job.fps ? `@${job.fps}` : ''}` : ''}</span>
                      {lineage && <span>↳ {lineage}</span>}
                    </div>
                    {initThumb && <img className="chat-msg-init" src={initThumb} alt="" />}
                    <p className="chat-msg-prompt">{job.prompt}</p>
                    {job.negative_prompt && <p className="chat-msg-negative">− {job.negative_prompt}</p>}
                  </div>
                </div>
                <div className="chat-msg assistant-msg">
                  <div className={`chat-bubble ${job.status === 'failed' ? 'failed' : ''}`}>
                    <div className="chat-msg-meta"><span>{modelName(job.model_key)}</span></div>
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
                      <button className="quiet-button danger-action" onClick={() => deleteJob(job)}><Trash2 size={14} />{t.deleteOutput}</button>
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
                placeholder={negativeIgnored ? t.negativeIgnoredHint : ''}
              />
            </div>
          </div>
          <div className="composer-send">
            {error && <div className="notice error">{error}</div>}
            <button className="primary-action generate-action" disabled={submitting || !modelReady || !modelUsable} onClick={submit}>
              {submitting ? <Loader2 size={16} className="spin" /> : <Sparkles size={16} />}{submitting ? t.submitting : t.submit}
            </button>
          </div>
        </div>
      </section>

      {/* 右栏：参数 */}
      <aside className="panel detail-panel studio-panel">
        <div className="panel-heading">
          <div className="panel-title">{t.paramsPanelTitle}</div>
          <button className="quiet-button" onClick={() => setPayload(initialPayload)} title={t.reset}><RotateCcw size={15} /></button>
        </div>
        <div className={`inline-status ${isImg2Img ? 'ready' : ''}`}>
          <strong>{isVideoModel ? (isImg2Img ? t.img2Video : t.text2Video) : isImg2Img ? (isEditModel ? t.imageEdit : t.imageToImage) : t.textToImage}</strong>
          <span>{isVideoModel ? t.videoModelHint : isImg2Img ? (isEditModel ? t.imageEditHint : t.sourceImageHint) : t.previewHint}</span>
          {isImg2Img && <code>{payload.init_input_id || `${payload.init_job_id}/${payload.init_filename}`}</code>}
        </div>
        <div className="control-row two">
          <div><label>{t.width}</label><input type="number" value={payload.width} onChange={e => setPayload({ ...payload, width: Number(e.target.value) })} /></div>
          <div><label>{t.height}</label><input type="number" value={payload.height} onChange={e => setPayload({ ...payload, height: Number(e.target.value) })} /></div>
        </div>
        <div className="control-row two">
          <div><label>{t.steps}</label><input type="number" value={payload.steps} onChange={e => setPayload({ ...payload, steps: Number(e.target.value) })} /></div>
          <div><label>{t.cfgScale}</label><input type="number" step="0.5" value={payload.cfg_scale} onChange={e => setPayload({ ...payload, cfg_scale: Number(e.target.value) })} /></div>
        </div>
        <div className="control-row two">
          <div><label>{t.sampler}</label><select value={payload.sampler} onChange={e => setPayload({ ...payload, sampler: e.target.value })}><option value="euler_a">Euler A</option><option value="euler">Euler</option><option value="heun">Heun</option><option value="dpm++2m">DPM++ 2M</option></select></div>
          <div><label>{t.seed}</label><input type="number" title={t.randomSeedHint} value={payload.seed} onChange={e => setPayload({ ...payload, seed: Number(e.target.value) })} /></div>
        </div>
        <div className="param-groups">
          <div className={`param-group${isVideoModel ? ' param-ignored' : ''}`}>
            <div className="param-group-title">{t.imageParamsTitle}{isVideoModel && <em className="ignored-tag">{t.paramIgnoredTag}</em>}</div>
            <label>{t.strength}{!(isImg2Img && supportsStrength) && <em className="ignored-tag">{t.paramIgnoredTag}</em>}</label>
            <input type="number" min="0" max="1" step="0.05" value={payload.strength} onChange={e => setPayload({ ...payload, strength: Number(e.target.value) })} />
            <label>{t.batch}</label>
            <input type="number" min="1" max="4" value={payload.batch_count} onChange={e => setPayload({ ...payload, batch_count: Number(e.target.value) })} />
          </div>
          <div className={`param-group${isVideoModel ? '' : ' param-ignored'}`}>
            <div className="param-group-title">{t.videoParamsTitle}{!isVideoModel && <em className="ignored-tag">{t.paramIgnoredTag}</em>}</div>
            <label>{t.videoFrames}</label>
            <input type="number" min="2" max="240" value={payload.video_frames} onChange={e => setPayload({ ...payload, video_frames: Number(e.target.value) })} />
            <label>{t.videoFps}</label>
            <input type="number" min="1" max="60" value={payload.fps} onChange={e => setPayload({ ...payload, fps: Number(e.target.value) })} />
            {videoDuration && <span className="video-duration">{t.videoDurationHint} {videoDuration} {t.videoSeconds}</span>}
          </div>
        </div>
        <p className="api-note">{t.paramsIgnoredHint}</p>
        <div className="side-divider" />
        <div className="panel-title small-title">{t.currentJob}</div>
        {jobs[0] ? (
          <>
            <div className="kv"><span>{t.jobId}</span><code>{jobs[0].job_id}</code></div>
            <div className="kv"><span>{t.progress}</span><code>{Math.round(jobs[0].progress * 100)}%</code></div>
            <progress max="1" value={jobs[0].progress} />
            <div className="kv"><span>{t.modelPath}</span><code>{jobs[0].model_path}</code></div>
          </>
        ) : <div className="empty-small">{t.noJobs}</div>}
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
  )
}
