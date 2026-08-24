import { useCallback, useEffect, useState } from 'react'
import { Cpu, Database, ImageIcon, ListChecks, PlugZap } from 'lucide-react'
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
  const t = messages[language]

  const changeLanguage = (next: Language) => {
    setLanguage(next)
    api.updateSettings({ language: next }).catch(() => undefined)
  }

  const refresh = useCallback(async () => {
    try {
      const [modelData, aboutData] = await Promise.all([api.listModels(), api.about()])
      setModels(modelData)
      setAbout(aboutData)
      setError('')
    } catch (e: any) {
      setError(e.message || t.serviceUnavailable)
    }
  }, [t.serviceUnavailable])

  useEffect(() => {
    refresh()
  }, [refresh])

  useEffect(() => {
    api.settings()
      .then(settings => setLanguage(settings.language === 'en' ? 'en' : 'zh-CN'))
      .catch(() => undefined)
  }, [])

  const readyCount = models.filter(model => model.status === 'ready').length

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
          <div><Database size={16} /><span>{readyCount}/{models.length || 1} models</span></div>
          <div><PlugZap size={16} /><span>{about?.sd_cpp_bin || 'sd-cli'}</span></div>
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
      {error && <div className="notice error">{error}</div>}
      <main>
        {tab === 'generate' && <GeneratePage models={models} onRefresh={refresh} t={t} />}
        {tab === 'models' && <ModelsPage models={models} onRefresh={refresh} t={t} />}
        {tab === 'jobs' && <JobsPage t={t} />}
        {tab === 'api' && <ApiPage t={t} />}
      </main>
    </div>
  )
}
