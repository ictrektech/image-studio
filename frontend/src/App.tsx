import { useCallback, useEffect, useState } from 'react'
import { Cpu, Database, ImageIcon, Info, ListChecks, PlugZap, X } from 'lucide-react'
import { api, AboutInfo, ModelInfo } from './api/client'
import GeneratePage from './pages/GeneratePage'
import ModelsPage from './pages/ModelsPage'
import JobsPage from './pages/JobsPage'
import ApiPage from './pages/ApiPage'
import { Language, messages } from './i18n'
import appIcon from './assets/icon.png'

type Tab = 'generate' | 'models' | 'jobs' | 'api'

export default function App() {
  const [tab, setTab] = useState<Tab>('generate')
  const [models, setModels] = useState<ModelInfo[]>([])
  const [about, setAbout] = useState<AboutInfo | null>(null)
  const [error, setError] = useState('')
  const [language, setLanguage] = useState<Language>('zh-CN')
  const [aboutOpen, setAboutOpen] = useState(false)
  const t = messages[language]

  const changeLanguage = (next: Language) => {
    setLanguage(next)
    api.updateSettings({ language: next }).catch(() => undefined)
  }

  const refresh = useCallback(async () => {
    let nextError = ''
    try {
      setModels(await api.listModels())
    } catch (e: any) {
      nextError = e.message || t.serviceUnavailable
    }

    try {
      setAbout(await api.about())
    } catch (e: any) {
      nextError = nextError || e.message || t.serviceUnavailable
    }

    if (nextError) {
      setError(nextError)
    } else {
      setError('')
    }
  }, [t.serviceUnavailable])

  useEffect(() => {
    refresh()
  }, [refresh])

  useEffect(() => {
    if (!models.some(model => model.status === 'downloading')) return
    const timer = window.setInterval(() => refresh(), 2000)
    return () => window.clearInterval(timer)
  }, [models, refresh])

  useEffect(() => {
    api.settings()
      .then(settings => setLanguage(settings.language === 'en' ? 'en' : 'zh-CN'))
      .catch(() => undefined)
  }, [])

  useEffect(() => {
    if (!aboutOpen) return
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setAboutOpen(false)
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [aboutOpen])

  const visibleModels = models.flatMap(model => [...(model.variants || []), model])
  const readyCount = visibleModels.filter(model => model.status === 'ready').length

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <img className="brand-mark" src={appIcon} alt="" />
          <div>
            <h1>Image Studio</h1>
            <p>{t.appSubtitle}</p>
          </div>
        </div>
        <div className="status-strip">
          <div><Cpu size={16} /><span>{about?.profile || 'local'}</span></div>
          <div><Database size={16} /><span>{readyCount}/{visibleModels.length || 1} models</span></div>
          <div><PlugZap size={16} /><span>{about?.sd_cpp_bin || 'sd-cli'}</span></div>
          <button className="about-button" onClick={() => setAboutOpen(true)}><Info size={16} /><span>{t.about}</span></button>
          <select className="language-select" value={language} onChange={e => changeLanguage(e.target.value as Language)}>
            <option value="zh-CN">中文</option>
            <option value="en">English</option>
          </select>
        </div>
      </header>
      <nav className="tabs">
        <button className={tab === 'generate' ? 'active' : ''} onClick={() => setTab('generate')}><ImageIcon size={16} />{t.generate}</button>
        <button className={tab === 'models' ? 'active' : ''} onClick={() => setTab('models')}><Database size={16} />{t.models}</button>
        <button className={tab === 'jobs' ? 'active' : ''} onClick={() => setTab('jobs')}><ListChecks size={16} />{t.jobs}</button>
        <button className={tab === 'api' ? 'active' : ''} onClick={() => setTab('api')}><PlugZap size={16} />{t.api}</button>
      </nav>
      {aboutOpen && (
        <div className="about-modal" role="presentation" onMouseDown={() => setAboutOpen(false)}>
          <section className="about-modal-box" role="dialog" aria-modal="true" aria-labelledby="about-title" onMouseDown={event => event.stopPropagation()}>
            <div className="about-modal-heading">
              <div>
                <img src={appIcon} alt="" />
                <div><h2 id="about-title">{t.aboutTitle}</h2><p>{t.appSubtitle}</p></div>
              </div>
              <button aria-label={t.close} onClick={() => setAboutOpen(false)}><X size={18} /></button>
            </div>
            <dl className="about-versions">
              <div><dt>{t.vosAppVersion}</dt><dd>{about?.app_version || window.__APP_VERSION__ || t.unavailable}</dd></div>
              <div><dt>{t.frontendImage}</dt><dd>{window.__FRONTEND_IMAGE__ || t.unavailable}</dd></div>
              <div><dt>{t.backendImage}</dt><dd>{window.__BACKEND_IMAGE__ || t.unavailable}</dd></div>
              <div><dt>{t.deploymentProfile}</dt><dd>{about?.profile || t.unavailable}</dd></div>
            </dl>
          </section>
        </div>
      )}
      {error && <div className="notice error">{error}</div>}
      <main>
        {tab === 'generate' && <GeneratePage models={models} onRefresh={refresh} onOpenModels={() => setTab('models')} t={t} />}
        {tab === 'models' && <ModelsPage models={models} onRefresh={refresh} t={t} />}
        {tab === 'jobs' && <JobsPage t={t} />}
        {tab === 'api' && <ApiPage models={models} t={t} />}
      </main>
    </div>
  )
}
