import { Cloud, RefreshCw, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { api, ModelInfo } from '../api/client'
import { messages } from '../i18n'

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

export default function ModelsPage({ models, onRefresh, t }: { models: ModelInfo[]; onRefresh: () => void; t: typeof messages['zh-CN'] }) {
  const [busy, setBusy] = useState('')
  const [message, setMessage] = useState('')

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
    <section className="panel model-zoo">
      <div className="model-header">
        <div>
          <div className="panel-title">{t.modelManagement}</div>
          <p>{t.modelManagementHelp}</p>
        </div>
        <button className="secondary-action" onClick={onRefresh}><RefreshCw size={15} />{t.refresh}</button>
      </div>
      {message && <div className="notice">{message}</div>}
      <div className="model-table">
        <div className="model-row header">
          <span>{t.model}</span><span>{t.source}</span><span>{t.status}</span><span>{t.size}</span><span>{t.loadPath}</span><span>{t.actions}</span>
        </div>
        {models.map(model => (
          <div className="model-row" key={model.key}>
            <div>
              <strong>{model.name}</strong>
              <small>{model.model_id}</small>
            </div>
            <span className="source"><Cloud size={14} />{model.source}</span>
            <span className={`pill ${model.status}`}><ShieldCheck size={13} />{model.status}</span>
            <span>{sizeText(model.size)}</span>
            <code>{model.resolved_path || model.access_path}</code>
            <div className="row-actions">
              <button disabled={Boolean(busy)} onClick={() => run(model.key, 'pull')}>Pull</button>
              <button disabled={Boolean(busy)} onClick={() => run(model.key, 'sync')}>Sync</button>
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
