import { CheckCircle2, DownloadCloud, Loader2, RefreshCw, RotateCw, ShieldAlert, ShieldCheck } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, ModelInfo } from '../api/client'
import { messages } from '../i18n'

function percent(model: ModelInfo) {
  if (model.status === 'ready') return 100
  if (model.status === 'downloading') return Math.round((model.progress ?? 0) * 100)
  return 0
}

function sizeText(bytes?: number) {
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

function bytesText(model: ModelInfo) {
  if (!model.downloaded_bytes) return ''
  return model.total_bytes
    ? `${sizeText(model.downloaded_bytes)} / ${sizeText(model.total_bytes)}`
    : sizeText(model.downloaded_bytes)
}

export default function ModelsPage({ models, onRefresh, t }: { models: ModelInfo[]; onRefresh: () => void; t: typeof messages['zh-CN'] }) {
  const [busy, setBusy] = useState('')
  const [message, setMessage] = useState('')
  const downloading = models.some(model => model.status === 'downloading')

  useEffect(() => {
    if (!downloading) return
    const timer = setInterval(() => onRefresh(), 3000)
    return () => clearInterval(timer)
  }, [downloading, onRefresh])

  const run = async (key: string, action: 'pull' | 'sync') => {
    setBusy(`${key}:${action}`)
    setMessage('')
    try {
      if (action === 'pull') await api.pullModel(key)
      else await api.syncModel(key)
      setMessage(action === 'pull' ? t.pullSubmitted : t.syncSubmitted)
      onRefresh()
    } catch (e: any) {
      setMessage(e.message || t.modelActionFailed)
    } finally {
      setBusy('')
    }
  }

  return (
    <div className="model-page">
      <section className="panel model-zoo">
        <div className="model-header">
          <div>
            <div className="panel-title">{t.modelManagement}</div>
            <p>{t.modelManagementHelp}</p>
          </div>
          <button className="secondary-action" onClick={onRefresh}><RefreshCw size={15} />{t.refresh}</button>
        </div>
        {message && <div className="notice">{message}</div>}
        {models.length === 0 && <div className="empty-small">{t.noModelsConfigured}</div>}
        <div className="model-card-grid">
          {models.map(model => {
            const ready = model.status === 'ready'
            const downloading = model.status === 'downloading'
            const failed = model.status === 'failed'
            return (
              <article className={`managed-model-card ${ready ? 'ready' : 'pending'}`} key={model.key}>
                <div className="model-card-header">
                  <div>
                    <h3>{model.name}</h3>
                    <div className="model-badges">
                      {model.preferred && <span>{t.preferredModel}</span>}
                      <span>{model.family}</span>
                      {model.capabilities.map(capability => <span key={capability}>{capability}</span>)}
                    </div>
                    <p>{model.description}</p>
                  </div>
                  <span className={`model-status ${ready ? 'ready' : 'pending'}`}>
                    {ready && <ShieldCheck size={14} />}
                    {failed && <ShieldAlert size={14} />}
                    {downloading && <Loader2 size={14} className="spin" />}
                    {ready ? t.modelReady : failed ? t.modelFailed : downloading ? t.modelDownloading : t.modelMissing}
                  </span>
                </div>

                <div className="model-meta">
                  <div><span>{t.modelId}</span><code>{model.model_id}</code></div>
                  <div><span>{t.source}</span><code>{model.source}</code></div>
                  <div><span>{t.family}</span><code>{model.family}</code></div>
                  <div><span>{t.capabilities}</span><code>{model.capabilities.join(', ')}</code></div>
                  <div><span>{t.loadPath}</span><code>{model.resolved_path || model.access_path}</code></div>
                  <div><span>{t.expectedFiles}</span><code>{model.expected_files.join(', ')}</code></div>
                  <div><span>{t.size}</span><code>{sizeText(model.size)}</code></div>
                  <div><span>{t.status}</span><code>{model.status}</code></div>
                </div>

                <progress className="model-progress" max="100" value={percent(model)} />
                {downloading && model.current_file && (
                  <p className="model-current-file">
                    {t.downloadingFile}: {model.current_file}{bytesText(model) && ` · ${bytesText(model)}`}
                  </p>
                )}
                {failed && model.error && <p className="model-error">{model.error}</p>}

                <div className="model-actions">
                  <button
                    className="primary-action compact-action"
                    disabled={ready || downloading || Boolean(busy)}
                    onClick={() => run(model.key, 'pull')}
                  >
                    {ready ? <CheckCircle2 size={15} /> : <DownloadCloud size={15} />}
                    {ready ? t.downloaded : downloading ? `${t.modelDownloading} ${percent(model)}%` : t.downloadModel}
                  </button>
                  <button
                    className="secondary-action compact-action"
                    disabled={Boolean(busy)}
                    onClick={() => run(model.key, 'sync')}
                  >
                    <RotateCw size={15} />{t.syncModel}
                  </button>
                </div>
              </article>
            )
          })}
        </div>
      </section>

      <section className="panel model-path-panel">
        <div className="panel-title">{t.modelHubPathGuide}</div>
        <p>{t.modelHubPathHelp}</p>
        {models.map(model => (
          <div className="path-guide" key={model.key}>
            <span>{model.name}</span>
            <code>{model.access_path}</code>
          </div>
        ))}
      </section>
    </div>
  )
}
