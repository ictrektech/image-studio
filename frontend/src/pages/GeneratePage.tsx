import { useEffect, useMemo, useState } from 'react'
import { CheckCircle2, Database, Download, DownloadCloud, ImageIcon, Loader2, RefreshCw, RotateCcw, Sparkles, Trash2, UserCircle2, Wand2 } from 'lucide-react'
import { api, GeneratePayload, JobRecord, ModelInfo, SessionInfo } from '../api/client'
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

const initialPayload: GeneratePayload = {
  prompt: 'a cozy mountain cabin at dusk, warm lights, snowy pine trees, cinematic lighting, ultra detailed',
  negative_prompt: 'blurry, low quality, watermark, text, deformed',
  model_key: 'sd15',
  init_job_id: '',
  init_filename: '',
  width: 768,
  height: 768,
  steps: 30,
  cfg_scale: 7,
  strength: 0.75,
  sampler: 'euler_a',
  seed: -1,
  batch_count: 1,
}

export default function GeneratePage({ models, onRefresh, onOpenModels, t }: { models: ModelInfo[]; onRefresh: () => void; onOpenModels: () => void; t: typeof messages['zh-CN'] }) {
  const [payload, setPayload] = useState<GeneratePayload>(initialPayload)
  const [jobs, setJobs] = useState<JobRecord[]>([])
  const [selectedJobId, setSelectedJobId] = useState<string>('')
  const [session, setSession] = useState<SessionInfo | null>(null)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const selectedJob = useMemo(() => jobs.find(job => job.job_id === selectedJobId) || jobs[0], [jobs, selectedJobId])
  const imageModels = useMemo(() => models.filter(model => model.capabilities.includes('txt2img') || model.capabilities.includes('img2img')), [models])
  const selectedModel = models.find(model => model.key === payload.model_key)
  const modelReady = selectedModel?.status === 'ready'
  const modelSupportsImages = Boolean(selectedModel?.capabilities.includes('txt2img') || selectedModel?.capabilities.includes('img2img'))
  const isEditModel = selectedModel?.runtime?.ref_flag === '-r'
  const supportsStrength = !isEditModel
  const hasRunning = jobs.some(job => job.status === 'queued' || job.status === 'running')
  const selectedOutput = selectedJob?.outputs[0]
  const selectedOutputUrl = selectedJob && selectedOutput ? api.outputUrl(selectedJob.job_id, selectedOutput) : ''
  const isImg2Img = Boolean(payload.init_job_id && payload.init_filename)

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
    })
  }

  const loadJobs = async () => {
    const data = await api.listJobs()
    setJobs(data)
    if (!selectedJobId && data[0]) setSelectedJobId(data[0].job_id)
  }

  useEffect(() => {
    loadJobs().catch(() => undefined)
  }, [])

  useEffect(() => {
    api.me().then(setSession).catch(() => undefined)
  }, [])

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
      const job = await api.generate(payload)
      setSelectedJobId(job.job_id)
      await loadJobs()
    } catch (e: any) {
      setError(e.message || t.submitFailed)
    } finally {
      setSubmitting(false)
    }
  }

  const reuseSelectedOutput = () => {
    if (!selectedJob || !selectedOutput) return
    reuseOutput(selectedJob, selectedOutput)
  }

  const reuseOutput = (job: JobRecord, output: string) => {
    setPayload({
      ...payload,
      init_job_id: job.job_id,
      init_filename: output,
      width: job.width,
      height: job.height,
    })
  }

  const clearSourceImage = () => {
    setPayload({ ...payload, init_job_id: '', init_filename: '' })
  }

  const downloadModel = async () => {
    if (!selectedModel || selectedModel.status === 'ready' || selectedModel.status === 'downloading') return
    try {
      await api.pullModel(selectedModel.key)
      onRefresh()
    } catch { /* 模型管理页有完整反馈，这里静默刷新即可 */ }
  }

  const modelDownloading = selectedModel?.status === 'downloading'
  const modelProgress = modelDownloading ? Math.round((selectedModel?.progress ?? 0) * 100) : 0

  const deleteSelectedJob = async () => {
    if (!selectedJob) return
    await deleteJob(selectedJob)
  }

  const deleteJob = async (job: JobRecord) => {
    if (!window.confirm(t.confirmDelete)) return
    await api.deleteJob(job.job_id)
    if (selectedJobId === job.job_id) setSelectedJobId('')
    await loadJobs()
  }

  return (
    <div className="workspace-grid">
      <section className="panel prompt-panel studio-panel">
        <div className="panel-heading">
          <div>
            <div className="panel-title">{t.generationSettings}</div>
            <p>{selectedModel?.name || t.model}</p>
          </div>
          <button className="quiet-button" onClick={() => setPayload(initialPayload)} title={t.reset}><RotateCcw size={15} />{t.reset}</button>
        </div>
        <label>{t.positivePrompt}</label>
        <div className="textarea-wrap">
          <textarea value={payload.prompt} onChange={e => setPayload({ ...payload, prompt: e.target.value })} rows={6} />
          <span>{payload.prompt.length}/2000</span>
        </div>
        <label>{t.negativePrompt}</label>
        <div className="textarea-wrap compact">
          <textarea value={payload.negative_prompt} onChange={e => setPayload({ ...payload, negative_prompt: e.target.value })} rows={3} />
          <span>{payload.negative_prompt.length}/2000</span>
        </div>

        <label>{t.model}</label>
        <select value={payload.model_key} onChange={e => switchModel(e.target.value)}>
          {imageModels.map(model => <option key={model.key} value={model.key}>{model.name} · {model.family}</option>)}
        </select>
        <div className={`inline-status ${modelReady ? 'ready' : 'missing'}`}>
          <strong>{selectedModel?.name || t.noModelsConfigured}</strong>
          <span>{modelSupportsImages ? (modelReady ? t.modelReady : t.modelMissing) : t.chooseModelHint}</span>
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
              <div><span>{t.capabilities}</span><code>{selectedModel.capabilities.join(', ')}</code></div>
              <div><span>{t.modelId}</span><code>{selectedModel.model_id}</code></div>
              <div><span>{t.size}</span><code>{modelReady ? formatSize(selectedModel.size) : modelDownloading ? formatSize(selectedModel.downloaded_bytes ?? undefined) : '-'}</code></div>
            </div>
            {!modelReady && (
              <>
                <button
                  className="secondary-action model-brief-download"
                  disabled={modelDownloading}
                  onClick={downloadModel}
                >
                  {modelDownloading ? <Loader2 size={14} className="spin" /> : <DownloadCloud size={14} />}
                  {modelDownloading ? `${t.modelDownloading} ${modelProgress}%` : t.downloadModel}
                </button>
                {modelDownloading && <progress className="model-brief-progress" max="100" value={modelProgress} />}
              </>
            )}
          </div>
        )}
        {(!modelReady || !modelSupportsImages) && (
          <button className="secondary-action model-jump-action" onClick={onOpenModels}>
            <Database size={15} />{t.openModelManagement}
          </button>
        )}

        <div className="section-label">{t.parameters}</div>
        <div className={`inline-status ${isImg2Img ? 'ready' : ''}`}>
          <strong>{isImg2Img ? (isEditModel ? t.imageEdit : t.imageToImage) : t.textToImage}</strong>
          <span>{isImg2Img ? (isEditModel ? t.imageEditHint : t.sourceImageHint) : t.previewHint}</span>
          {isImg2Img && <code>{payload.init_job_id}/{payload.init_filename}</code>}
        </div>
        {isImg2Img && (
          <button className="quiet-button source-clear-button" onClick={clearSourceImage} type="button">
            <RotateCcw size={15} />{t.clear}
          </button>
        )}
        <div className="control-row two">
          <div><label>{t.width}</label><input type="number" value={payload.width} onChange={e => setPayload({ ...payload, width: Number(e.target.value) })} /></div>
          <div><label>{t.height}</label><input type="number" value={payload.height} onChange={e => setPayload({ ...payload, height: Number(e.target.value) })} /></div>
        </div>
        <div className="control-row two">
          <div><label>{t.steps}</label><input type="number" value={payload.steps} onChange={e => setPayload({ ...payload, steps: Number(e.target.value) })} /></div>
          <div><label>{t.cfgScale}</label><input type="number" step="0.5" value={payload.cfg_scale} onChange={e => setPayload({ ...payload, cfg_scale: Number(e.target.value) })} /></div>
        </div>
        {isImg2Img && supportsStrength && (
          <div className="control-row">
            <div><label>{t.strength}</label><input type="number" min="0" max="1" step="0.05" value={payload.strength} onChange={e => setPayload({ ...payload, strength: Number(e.target.value) })} /></div>
          </div>
        )}
        <div className="control-row two">
          <div><label>{t.sampler}</label><select value={payload.sampler} onChange={e => setPayload({ ...payload, sampler: e.target.value })}><option value="euler_a">Euler A</option><option value="euler">Euler</option><option value="heun">Heun</option><option value="dpm++2m">DPM++ 2M</option></select></div>
          <div><label>{t.seed}</label><input type="number" title={t.randomSeedHint} value={payload.seed} onChange={e => setPayload({ ...payload, seed: Number(e.target.value) })} /></div>
        </div>

        {error && <div className="notice error">{error}</div>}
        <button className="primary-action generate-action" disabled={submitting || !modelReady || !modelSupportsImages} onClick={submit}><Sparkles size={17} />{submitting ? t.submitting : t.submit}</button>
      </section>

      <section className="panel canvas-panel studio-panel">
        <div className="canvas-toolbar">
          <div>
            <div className="panel-title">{t.imagePreview}</div>
            <p>{selectedJob ? selectedJob.prompt : t.previewHint}</p>
          </div>
          <button className="icon-button" onClick={loadJobs} title="刷新"><RefreshCw size={17} /></button>
        </div>
        <div className={`preview-canvas ${selectedOutputUrl ? 'has-output' : ''}`}>
          {selectedOutputUrl ? (
            <img src={selectedOutputUrl} alt="Generated output" />
          ) : (
            <div className="empty-preview">
              <ImageIcon size={42} />
              <strong>{selectedJob ? selectedJob.status : t.noOutput}</strong>
              <span>{selectedJob ? t.waitingOutput : t.previewHint}</span>
            </div>
          )}
        </div>
        <div className="session-strip">
          <div className="session-user">
            <UserCircle2 size={18} />
            <div>
              <strong>{t.mySession}</strong>
              <code>{session ? session.user_key : '...'}</code>
              {session && !session.authenticated && <span className="tag-anonymous">{t.anonymousSession}</span>}
            </div>
          </div>
          <span className="session-count">{jobs.length} {t.imageCount} · {t.sessionIsolationHint}</span>
        </div>
        <div className="history-heading">
          <span>{t.conversation}</span>
          <small>{jobs.length} {t.imageCount}</small>
        </div>
        <div className="turn-list" aria-label={t.conversation}>
          {jobs.slice(0, 8).map(job => {
            const output = job.outputs[0]
            const outputUrl = output ? api.outputUrl(job.job_id, output) : ''
            const round = roundOf.get(job.job_id)
            const lineage = lineageOf(job)
            return (
              <article className={`turn-card ${job.job_id === selectedJob?.job_id ? 'active' : ''}`} key={job.job_id}>
                <button className="turn-thumb" onClick={() => setSelectedJobId(job.job_id)}>
                  {outputUrl ? <img src={outputUrl} alt="" /> : <span>{job.status}</span>}
                </button>
                <div className="turn-body">
                  <div className="turn-meta">
                    <strong>#{round} {job.job_id === jobs[0]?.job_id ? t.latestTurn : job.status}</strong>
                    <span>{job.width} x {job.height} · {timeOf(job.created_at)}</span>
                  </div>
                  <p>{job.prompt}</p>
                  {lineage && <span className="turn-lineage">↳ {lineage}</span>}
                  <div className="turn-actions">
                    {output && <button className="quiet-button" onClick={() => reuseOutput(job, output)}><Wand2 size={14} />{t.continueThread}</button>}
                    {outputUrl && <a className="quiet-button" href={outputUrl} download><Download size={14} />{t.downloadOutput}</a>}
                    <button className="quiet-button danger-action" onClick={() => deleteJob(job)}><Trash2 size={14} />{t.deleteOutput}</button>
                  </div>
                </div>
              </article>
            )
          })}
        </div>
      </section>

      <aside className="panel detail-panel studio-panel">
        <div className="panel-heading">
          <div className="panel-title">{t.currentJob}</div>
          {selectedJob && <span className={`job-status ${selectedJob.status}`}>{selectedJob.status}</span>}
        </div>
        {selectedJob ? (
          <>
            <div className="kv"><span>{t.jobId}</span><code>{selectedJob.job_id}</code></div>
            <div className="kv"><span>{t.progress}</span><code>{Math.round(selectedJob.progress * 100)}%</code></div>
            <progress max={1} value={selectedJob.progress} />
            <div className="kv"><span>{t.steps}</span><code>{selectedJob.steps}</code></div>
            <div className="kv"><span>{t.size}</span><code>{selectedJob.width} x {selectedJob.height}</code></div>
            <div className="kv"><span>{t.modelPath}</span><code>{selectedJob.model_path}</code></div>
            {selectedOutputUrl && (
              <div className="job-actions">
                <a className="secondary-action download-action" href={selectedOutputUrl} download><Download size={15} />{t.downloadOutput}</a>
                <button className="secondary-action" onClick={reuseSelectedOutput}><Wand2 size={15} />{t.reuseOutput}</button>
                <button className="secondary-action danger-action" onClick={deleteSelectedJob}><Trash2 size={15} />{t.deleteOutput}</button>
              </div>
            )}
            {selectedJob.error && <div className="notice error">{selectedJob.error}</div>}
          </>
        ) : <div className="empty-small">{t.noJobs}</div>}
        <div className="side-divider" />
        <div className="panel-title small-title">{t.modelInfo}</div>
        <div className="kv"><span>{t.model}</span><code>{selectedModel?.name || '-'}</code></div>
        <div className="kv"><span>{t.status}</span><code>{selectedModel?.status || '-'}</code></div>
        <div className="kv"><span>{t.loadPath}</span><code>{selectedModel?.resolved_path || selectedModel?.access_path || '-'}</code></div>
        <button className="secondary-action" onClick={onRefresh}><RefreshCw size={15} />{t.refreshModels}</button>
      </aside>
    </div>
  )
}
