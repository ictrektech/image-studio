import { useEffect, useMemo, useState } from 'react'
import { Download, ImageIcon, Play, RefreshCw } from 'lucide-react'
import { api, GeneratePayload, JobRecord, ModelInfo } from '../api/client'
import { messages } from '../i18n'

const initialPayload: GeneratePayload = {
  prompt: 'a cozy mountain cabin at dusk, warm lights, snowy pine trees, cinematic lighting, ultra detailed',
  negative_prompt: 'blurry, low quality, watermark, text, deformed',
  model_key: 'sd15',
  width: 768,
  height: 768,
  steps: 30,
  cfg_scale: 7,
  sampler: 'euler_a',
  seed: -1,
  batch_count: 1,
}

export default function GeneratePage({ models, onRefresh, t }: { models: ModelInfo[]; onRefresh: () => void; t: typeof messages['zh-CN'] }) {
  const [payload, setPayload] = useState<GeneratePayload>(initialPayload)
  const [jobs, setJobs] = useState<JobRecord[]>([])
  const [selectedJobId, setSelectedJobId] = useState<string>('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const selectedJob = useMemo(() => jobs.find(job => job.job_id === selectedJobId) || jobs[0], [jobs, selectedJobId])
  const selectedModel = models.find(model => model.key === payload.model_key)
  const hasRunning = jobs.some(job => job.status === 'queued' || job.status === 'running')

  const loadJobs = async () => {
    const data = await api.listJobs()
    setJobs(data)
    if (!selectedJobId && data[0]) setSelectedJobId(data[0].job_id)
  }

  useEffect(() => {
    loadJobs().catch(() => undefined)
  }, [])

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

  return (
    <div className="workspace-grid">
      <section className="panel prompt-panel">
        <div className="panel-title">{t.prompt}</div>
        <label>{t.positivePrompt}</label>
        <textarea value={payload.prompt} onChange={e => setPayload({ ...payload, prompt: e.target.value })} rows={5} />
        <label>{t.negativePrompt}</label>
        <textarea value={payload.negative_prompt} onChange={e => setPayload({ ...payload, negative_prompt: e.target.value })} rows={3} />

        <label>{t.model}</label>
        <select value={payload.model_key} onChange={e => setPayload({ ...payload, model_key: e.target.value })}>
          {models.map(model => <option key={model.key} value={model.key}>{model.name}</option>)}
        </select>
        <div className={`inline-status ${selectedModel?.status === 'ready' ? 'ready' : 'missing'}`}>
          {selectedModel?.status === 'ready' ? t.modelReady : t.modelMissing} · {selectedModel?.resolved_path || selectedModel?.access_path}
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
          <div><label>{t.sampler}</label><select value={payload.sampler} onChange={e => setPayload({ ...payload, sampler: e.target.value })}><option value="euler_a">Euler A</option><option value="euler">Euler</option><option value="dpm++2m">DPM++ 2M</option></select></div>
          <div><label>{t.seed}</label><input type="number" value={payload.seed} onChange={e => setPayload({ ...payload, seed: Number(e.target.value) })} /></div>
        </div>

        {error && <div className="notice error">{error}</div>}
        <button className="primary-action" disabled={submitting} onClick={submit}><Play size={16} />{submitting ? t.submitting : t.submit}</button>
      </section>

      <section className="panel canvas-panel">
        <div className="canvas-toolbar">
          <div>
            <div className="panel-title">{t.preview}</div>
            <p>{selectedJob ? selectedJob.prompt : t.previewHint}</p>
          </div>
          <button className="icon-button" onClick={loadJobs} title="刷新"><RefreshCw size={17} /></button>
        </div>
        <div className="preview-canvas">
          {selectedJob?.outputs[0] ? (
            <img src={api.outputUrl(selectedJob.job_id, selectedJob.outputs[0])} alt="Generated output" />
          ) : (
            <div className="empty-preview"><ImageIcon size={40} /><span>{selectedJob ? selectedJob.status : t.noOutput}</span></div>
          )}
        </div>
        <div className="thumb-strip">
          {jobs.slice(0, 6).map(job => (
            <button className={`thumb ${job.job_id === selectedJob?.job_id ? 'active' : ''}`} key={job.job_id} onClick={() => setSelectedJobId(job.job_id)}>
              {job.outputs[0] ? <img src={api.outputUrl(job.job_id, job.outputs[0])} alt="" /> : <span>{job.status}</span>}
            </button>
          ))}
        </div>
      </section>

      <aside className="panel detail-panel">
        <div className="panel-title">{t.currentJob}</div>
        {selectedJob ? (
          <>
            <div className={`job-status ${selectedJob.status}`}>{selectedJob.status}</div>
            <div className="kv"><span>Job ID</span><code>{selectedJob.job_id}</code></div>
            <progress max={1} value={selectedJob.progress} />
            <div className="kv"><span>Steps</span><code>{selectedJob.steps}</code></div>
            <div className="kv"><span>Size</span><code>{selectedJob.width} x {selectedJob.height}</code></div>
            <div className="kv"><span>Session</span><code>{selectedJob.user_key}</code></div>
            <div className="kv"><span>Model</span><code>{selectedJob.model_path}</code></div>
            {selectedJob.outputs[0] && <a className="secondary-action" href={api.outputUrl(selectedJob.job_id, selectedJob.outputs[0])} download><Download size={15} />{t.downloadOutput}</a>}
            {selectedJob.error && <div className="notice error">{selectedJob.error}</div>}
          </>
        ) : <div className="empty-small">{t.noJobs}</div>}
        <button className="secondary-action" onClick={onRefresh}><RefreshCw size={15} />{t.refreshModels}</button>
      </aside>
    </div>
  )
}
