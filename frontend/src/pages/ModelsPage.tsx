import { CheckCircle2, DownloadCloud, Loader2, RefreshCw, RotateCcw, ShieldAlert, ShieldCheck, Square } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
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

function sizeDisplay(model: ModelInfo, t: typeof messages['zh-CN']) {
  if (model.size) return sizeText(model.size)
  if (model.status === 'downloading') return bytesText(model) || sizeText(model.total_bytes ?? undefined)
  if (model.total_bytes) return sizeText(model.total_bytes)
  if (model.files?.length) return `${model.files.length} ${t.filesCountLabel}`
  return '-'
}

export default function ModelsPage({ models, onRefresh, t }: { models: ModelInfo[]; onRefresh: () => void; t: typeof messages['zh-CN'] }) {
  const [busy, setBusy] = useState('')
  const [message, setMessage] = useState('')
  const [variants, setVariants] = useState<Record<string, string>>({})
  const downloading = models.some(model => model.status === 'downloading')
  const sortedModels = useMemo(
    () => [...models].sort((a, b) => Number(Boolean(b.variants?.length)) - Number(Boolean(a.variants?.length))),
    [models],
  )

  useEffect(() => {
    if (!downloading) return
    const timer = setInterval(() => onRefresh(), 3000)
    return () => clearInterval(timer)
  }, [downloading, onRefresh])

  const selectedInfo = (model: ModelInfo) => model.variants?.find(variant => variant.id === variants[model.key]) || model

  const run = async (model: ModelInfo, action: 'pull' | 'pull-force' | 'stop' | 'sync') => {
    const variant = variants[model.key] || ''
    setBusy(`${model.key}:${variant}:${action}`)
    setMessage('')
    try {
      if (action === 'pull') await api.pullModel(model.key, false, variant)
      else if (action === 'pull-force') await api.pullModel(model.key, true, variant)
      else if (action === 'stop') await api.stopModel(model.key, variant)
      else await api.syncModel(model.key)
      setMessage(action === 'pull' ? t.pullSubmitted : action === 'pull-force' ? t.pullSubmitted : action === 'stop' ? t.stopSubmitted : t.syncSubmitted)
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
          {sortedModels.map(model => {
            const active = selectedInfo(model)
            const ready = active.status === 'ready'
            const downloading = active.status === 'downloading'
            const failed = active.status === 'failed'
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
                    {Boolean(model.variants?.length) && (
                      <select className="model-variant-select" value={variants[model.key] || ''} onChange={e => setVariants({ ...variants, [model.key]: e.target.value })}>
                        <option value="">{t.defaultModelVariant}</option>
                        {model.variants?.map(variant => <option key={variant.id} value={variant.id}>{variant.name}{variant.params ? ` (${variant.params})` : ''}</option>)}
                      </select>
                    )}
                  </div>
                  <span className={`model-status ${ready ? 'ready' : 'pending'}`}>
                    {ready && <ShieldCheck size={14} />}
                    {failed && <ShieldAlert size={14} />}
                    {downloading && <Loader2 size={14} className="spin" />}
                    {ready ? t.modelReady : failed ? t.modelFailed : downloading ? t.modelDownloading : t.modelMissing}
                  </span>
                </div>

                <div className="model-meta">
                  <div><span>{t.modelVariant}</span><code>{variants[model.key] ? active.name : t.defaultModelVariant}</code></div>
                  <div><span>{t.modelId}</span><code>{active.model_id}</code></div>
                  <div><span>{t.source}</span><code>{active.source}</code></div>
                  <div><span>{t.family}</span><code>{active.family}</code></div>
                  <div><span>{t.paramsLabel}</span><code>{active.params || '-'}</code></div>
                  <div><span>{t.capabilities}</span><code>{active.capabilities.join(', ')}</code></div>
                  <div><span>{t.loadPath}</span><code>{active.resolved_path || active.access_path}</code></div>
                  <div><span>{t.expectedFiles}</span><code>{active.expected_files.join(', ')}</code></div>
                  <div><span>{t.size}</span><code>{sizeDisplay(active, t)}</code></div>
                  <div><span>{t.status}</span><code>{active.status}</code></div>
                </div>

                <progress className="model-progress" max="100" value={percent(active)} />
                {downloading && active.current_file && (
                  <p className="model-current-file">
                    {t.downloadingFile}: {active.current_file}{bytesText(active) && ` · ${bytesText(active)}`}
                  </p>
                )}
                {failed && active.error && <p className="model-error">{active.error}</p>}

                <div className="model-actions">
                  <button
                    className="primary-action compact-action"
                    disabled={ready || downloading || Boolean(busy)}
                    onClick={() => run(model, 'pull')}
                  >
                    {ready ? <CheckCircle2 size={15} /> : <DownloadCloud size={15} />}
                    {ready ? t.downloaded : downloading ? `${t.modelDownloading} ${percent(active)}%` : t.downloadModel}
                  </button>
                  {downloading && (
                    <button
                      className="secondary-action compact-action"
                      disabled={Boolean(busy)}
                      onClick={() => run(model, 'stop')}
                    >
                      <Square size={15} />{t.stopDownload}
                    </button>
                  )}
                  {(downloading || ready || failed) && (
                    <button
                      className="secondary-action compact-action"
                      disabled={Boolean(busy)}
                      onClick={() => run(model, 'pull-force')}
                    >
                      <RotateCcw size={15} />{t.redownload}
                    </button>
                  )}
                  <button
                    className="secondary-action compact-action"
                    disabled={Boolean(busy)}
                    onClick={() => run(model, 'sync')}
                  >
                    <RefreshCw size={15} />{t.syncModel}
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
        {sortedModels.map(model => (
          <div className="path-guide" key={model.key}>
            <span>{model.name}</span>
            <code>{model.access_path}</code>
          </div>
        ))}
      </section>
    </div>
  )
}
