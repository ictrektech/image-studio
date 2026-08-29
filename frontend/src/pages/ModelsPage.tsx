import { CheckCircle2, DownloadCloud, Loader2, RefreshCw, RotateCcw, ShieldAlert, ShieldCheck, Square } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { api, ModelInfo } from '../api/client'
import { messages } from '../i18n'

type T = typeof messages['zh-CN']
type ModelEntry = { base: ModelInfo; active: ModelInfo; variantId: string; isVariant: boolean }

const CAPABILITY_ORDER = ['txt2img', 'img2img', 'edit', 'txt2video', 'img2video', 'video']

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

function entryCapabilities(entry: ModelEntry) {
  const caps = new Set(entry.active.capabilities || [])
  const runtime = entry.active.runtime
  const isVideo = runtime?.mode === 'video' || caps.has('video')
  if (isVideo) {
    caps.add('txt2video')
    if (runtime?.ref_flag || runtime?.parameters?.reference_image) caps.add('img2video')
  }
  return Array.from(caps)
}

function displayCapabilities(caps: string[]) {
  const filtered = caps.filter(capability => capability !== 'video')
  return filtered.length ? filtered : caps
}

function capabilityLabel(capability: string, t: T) {
  const key = `capability_${capability}` as keyof T
  return typeof t[key] === 'string' ? t[key] : capability
}

function sortCapabilities(caps: string[]) {
  return [...caps].sort((a, b) => {
    const ai = CAPABILITY_ORDER.indexOf(a)
    const bi = CAPABILITY_ORDER.indexOf(b)
    if (ai === -1 && bi === -1) return a.localeCompare(b)
    if (ai === -1) return 1
    if (bi === -1) return -1
    return ai - bi
  })
}

export default function ModelsPage({ models, onRefresh, t }: { models: ModelInfo[]; onRefresh: () => void; t: typeof messages['zh-CN'] }) {
  const [busy, setBusy] = useState('')
  const [message, setMessage] = useState('')
  const [selectedCapabilities, setSelectedCapabilities] = useState<string[]>([])
  const downloading = models.some(model => model.status === 'downloading' || model.variants?.some(variant => variant.status === 'downloading'))
  const modelEntries = useMemo(
    () => models.flatMap(model => [
      ...(model.variants || []).map(variant => ({ base: model, active: variant, variantId: variant.id || '', isVariant: true })),
      { base: model, active: model, variantId: '', isVariant: false },
    ]),
    [models],
  )
  const capabilityOptions = useMemo(
    () => sortCapabilities(Array.from(new Set(modelEntries.flatMap(entry => displayCapabilities(entryCapabilities(entry)))))),
    [modelEntries],
  )
  const filteredEntries = useMemo(
    () => selectedCapabilities.length === 0
      ? modelEntries
      : modelEntries.filter(entry => {
        const caps = entryCapabilities(entry)
        return selectedCapabilities.every(capability => caps.includes(capability))
      }),
    [modelEntries, selectedCapabilities],
  )

  const toggleCapability = (capability: string) => {
    setSelectedCapabilities(current =>
      current.includes(capability)
        ? current.filter(item => item !== capability)
        : [...current, capability],
    )
  }

  useEffect(() => {
    if (!downloading) return
    const timer = setInterval(() => onRefresh(), 3000)
    return () => clearInterval(timer)
  }, [downloading, onRefresh])

  const run = async (model: ModelInfo, variant: string, action: 'pull' | 'pull-force' | 'stop' | 'sync') => {
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
        {capabilityOptions.length > 0 && (
          <div className="capability-filter">
            <div className="capability-filter-heading">
              <div>
                <strong>{t.capabilityFilter}</strong>
                <span>{t.capabilityFilterHelp}</span>
              </div>
              {selectedCapabilities.length > 0 && (
                <button type="button" className="quiet-button" onClick={() => setSelectedCapabilities([])}>
                  {t.clearCapabilityFilters}
                </button>
              )}
            </div>
            <div className="capability-filter-options">
              {capabilityOptions.map(capability => (
                <label className="capability-check" key={capability}>
                  <input
                    type="checkbox"
                    checked={selectedCapabilities.includes(capability)}
                    onChange={() => toggleCapability(capability)}
                  />
                  <span>{capabilityLabel(capability, t)}</span>
                </label>
              ))}
            </div>
          </div>
        )}
        {models.length > 0 && filteredEntries.length === 0 && <div className="empty-small">{t.noModelsMatchFilter}</div>}
        <div className="model-card-grid">
          {filteredEntries.map(entry => {
            const model = entry.base
            const active = entry.active
            const capabilities = displayCapabilities(entryCapabilities(entry))
            const ready = active.status === 'ready'
            const downloading = active.status === 'downloading'
            const failed = active.status === 'failed'
            return (
              <article className={`managed-model-card ${ready ? 'ready' : 'pending'} ${entry.isVariant ? 'variant-card' : ''}`} key={`${model.key}:${entry.variantId || 'default'}`}>
                <div className="model-card-header">
                  <div>
                    <h3>{entry.isVariant ? `${model.name} · ${active.name}` : model.name}</h3>
                    <div className="model-badges">
                      {entry.isVariant && <span>{t.modelVariant}</span>}
                      {active.preferred && <span>{t.preferredModel}</span>}
                      <span>{active.family}</span>
                      {capabilities.map(capability => <span key={capability}>{capabilityLabel(capability, t)}</span>)}
                    </div>
                    <p>{active.description}</p>
                  </div>
                  <span className={`model-status ${ready ? 'ready' : 'pending'}`}>
                    {ready && <ShieldCheck size={14} />}
                    {failed && <ShieldAlert size={14} />}
                    {downloading && <Loader2 size={14} className="spin" />}
                    {ready ? t.modelReady : failed ? t.modelFailed : downloading ? t.modelDownloading : t.modelMissing}
                  </span>
                </div>

                <div className="model-meta">
                  <div><span>{t.modelVariant}</span><code>{entry.isVariant ? `${active.name} (${entry.variantId})` : t.defaultModelVariant}</code></div>
                  <div><span>{t.modelId}</span><code>{active.model_id}</code></div>
                  <div><span>{t.source}</span><code>{active.source}</code></div>
                  <div><span>{t.family}</span><code>{active.family}</code></div>
                  <div><span>{t.paramsLabel}</span><code>{active.params || '-'}</code></div>
                  <div><span>{t.capabilities}</span><code>{capabilities.map(capability => capabilityLabel(capability, t)).join(', ')}</code></div>
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
                    onClick={() => run(model, entry.variantId, 'pull')}
                  >
                    {ready ? <CheckCircle2 size={15} /> : <DownloadCloud size={15} />}
                    {ready ? t.downloaded : downloading ? `${t.modelDownloading} ${percent(active)}%` : t.downloadModel}
                  </button>
                  {downloading && (
                    <button
                      className="secondary-action compact-action"
                      disabled={Boolean(busy)}
                      onClick={() => run(model, entry.variantId, 'stop')}
                    >
                      <Square size={15} />{t.stopDownload}
                    </button>
                  )}
                  {(downloading || ready || failed) && (
                    <button
                      className="secondary-action compact-action"
                      disabled={Boolean(busy)}
                      onClick={() => run(model, entry.variantId, 'pull-force')}
                    >
                      <RotateCcw size={15} />{t.redownload}
                    </button>
                  )}
                  <button
                    className="secondary-action compact-action"
                    disabled={Boolean(busy)}
                    onClick={() => run(model, entry.variantId, 'sync')}
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
        {filteredEntries.map(entry => (
          <div className="path-guide" key={`${entry.base.key}:${entry.variantId || 'default'}`}>
            <span>{entry.isVariant ? `${entry.base.name} · ${entry.active.name}` : entry.base.name}</span>
            <code>{entry.active.access_path}</code>
          </div>
        ))}
      </section>
    </div>
  )
}
