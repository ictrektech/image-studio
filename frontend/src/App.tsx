import { lazy, Suspense, useCallback, useEffect, useState } from 'react'
import { AlertTriangle, CircleCheck, CircleOff, CircleX, Clock, Cpu, Database, ImageIcon, Info, ListChecks, LoaderCircle, Monitor, Moon, PlugZap, Sun } from 'lucide-react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Toaster } from '@/components/ui/sonner'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { api, AboutInfo, ImmichStatus, ModelInfo } from './api/client'
import GeneratePage from './pages/GeneratePage'

// 首屏只需要 GeneratePage，其余页面按需加载（实测延后约 41kB）。
// 主包 570kB 主要来自 radix + lucide，要继续压首屏得在 vite 里拆 vendor，不是靠路由懒加载。
const ModelsPage = lazy(() => import('./pages/ModelsPage'))
const JobsPage = lazy(() => import('./pages/JobsPage'))
const ApiPage = lazy(() => import('./pages/ApiPage'))
import { Language, messages } from './i18n'
import appIcon from './assets/icon.png'
import { useTheme } from './hooks/useTheme'

type Tab = 'generate' | 'models' | 'jobs' | 'api'

const tabs: { key: Tab; icon: typeof ImageIcon; labelKey: 'generate' | 'models' | 'jobs' | 'api' }[] = [
  { key: 'generate', icon: ImageIcon, labelKey: 'generate' },
  { key: 'models', icon: Database, labelKey: 'models' },
  { key: 'jobs', icon: ListChecks, labelKey: 'jobs' },
  { key: 'api', icon: PlugZap, labelKey: 'api' },
]

export default function App() {
  const [tab, setTab] = useState<Tab>('generate')
  const [models, setModels] = useState<ModelInfo[]>([])
  const [about, setAbout] = useState<AboutInfo | null>(null)
  const [error, setError] = useState('')
  const [language, setLanguage] = useState<Language>('zh-CN')
  const [aboutOpen, setAboutOpen] = useState(false)
  // AI 相册（Immich）连通性：null = 检查中；独立于 refresh()（后者被下载轮询每 2s 调一次，
  // 不能把 immich ping 也带成 2s 一次）
  const [immich, setImmich] = useState<ImmichStatus | null>(null)
  const { theme, cycleTheme } = useTheme()
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

  // 连通性状态：挂载时查一次，窗口重新聚焦时复查（首传开通后回来即可见 connected）；
  // 失败落终态而非保持 null，避免与"检查中"不可区分的永久旋转
  useEffect(() => {
    const load = () => api.immichStatus().then(setImmich)
      .catch(() => setImmich({ state: 'unreachable', detail: t.immichStatusUnavailable }))
    load()
    window.addEventListener('focus', load)
    return () => window.removeEventListener('focus', load)
  }, [t])

  const visibleModels = models.flatMap(model => [...(model.variants || []), model])

  // AI 相册状态指示：一张表查 label/颜色/形状（形状即状态：钩/钟/叉/圈，颜色作强化）；
  // 文字全在 hover Tooltip 与 aria-label
  const immichStates: Record<string, { label: string; tone: string; Icon: typeof CircleCheck }> = {
    '': { label: t.immichStateChecking, tone: 'text-muted-foreground', Icon: LoaderCircle },
    connected: { label: t.immichStateConnected, tone: 'text-green-600 dark:text-green-400', Icon: CircleCheck },
    pending: { label: t.immichStatePending, tone: 'text-orange-600 dark:text-orange-400', Icon: Clock },
    unreachable: { label: t.immichStateUnreachable, tone: 'text-red-600 dark:text-red-400', Icon: CircleX },
    error: { label: t.immichStateError, tone: 'text-red-600 dark:text-red-400', Icon: CircleX },
    disabled: { label: t.immichStateDisabled, tone: 'text-muted-foreground', Icon: CircleOff },
  }
  const immichState = immich?.state ?? ''
  const { label: immichLabel, tone: immichTone, Icon: ImmichIcon } = immichStates[immichState] ?? immichStates['']
  const immichChip = (
    <Badge
      variant="outline"
      role="img"
      aria-label={`${t.immichChipName} · ${immichLabel}`}
      tabIndex={0}
      className="h-[34px] gap-2 rounded-md px-3 text-xs font-medium text-muted-foreground"
    >
      <ImmichIcon size={16} className={`${immichTone} ${immich ? '' : 'animate-spin'}`} />
      <span>{t.immichChipName}</span>
    </Badge>
  )
  const readyCount = visibleModels.filter(model => model.status === 'ready').length

  return (
    <TooltipProvider delayDuration={200}>
    <div className="flex h-svh flex-col overflow-hidden">
      <header className="flex shrink-0 flex-wrap items-center gap-x-5 gap-y-2 border-b bg-card px-4 py-2.5 md:h-[68px] md:flex-nowrap md:px-6">
        <div className="flex min-w-0 items-center gap-3">
          <img className="block size-[42px] rounded-[10px] object-cover shadow-[0_8px_20px_rgba(8,60,80,0.14)]" src={appIcon} alt="" />
          <div>
            <h1 className="text-xl font-bold leading-tight">Image Studio</h1>
            <p className="mt-1 text-xs text-muted-foreground">{t.appSubtitle}</p>
          </div>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2.5">
          <Badge variant="outline" className="h-[34px] gap-2 rounded-md px-3 text-xs font-medium text-muted-foreground"><Cpu size={16} /><span>{about?.profile || 'local'}</span></Badge>
          <Badge variant="outline" className="h-[34px] gap-2 rounded-md px-3 text-xs font-medium text-muted-foreground"><Database size={16} /><span>{readyCount}/{visibleModels.length || 1} models</span></Badge>
          <Tooltip>
            <TooltipTrigger asChild>
              <Badge variant="outline" className="h-[34px] gap-2 rounded-md px-3 text-xs font-medium text-muted-foreground"><PlugZap size={16} /><span className="max-w-[220px] truncate">{about?.sd_cpp_bin || 'sd-cli'}</span></Badge>
            </TooltipTrigger>
            <TooltipContent className="max-w-[80vw] break-all"><p>{about?.sd_cpp_bin || 'sd-cli'}</p></TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>{immichChip}</TooltipTrigger>
            <TooltipContent className="max-w-[80vw] break-all">
              <p>{t.immichChipName} · {immichLabel}</p>
              {immich?.detail && <p className="mt-1 opacity-80">{immich.detail}</p>}
            </TooltipContent>
          </Tooltip>
          <Button variant="outline" className="h-[34px] gap-2 rounded-md px-3 text-xs font-semibold text-foreground shadow-none" onClick={() => setAboutOpen(true)}>
            <Info size={16} /><span>{t.about}</span>
          </Button>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="outline"
                size="icon"
                className="h-[34px] w-[34px] rounded-md shadow-none"
                onClick={cycleTheme}
                aria-label={theme === 'light' ? t.themeLight : theme === 'dark' ? t.themeDark : t.themeAuto}
              >
                {theme === 'light' ? <Sun size={16} /> : theme === 'dark' ? <Moon size={16} /> : <Monitor size={16} />}
              </Button>
            </TooltipTrigger>
            <TooltipContent>{theme === 'light' ? t.themeLight : theme === 'dark' ? t.themeDark : t.themeAuto}</TooltipContent>
          </Tooltip>
          <Select value={language} onValueChange={value => changeLanguage(value as Language)}>
            <SelectTrigger size="sm" className="w-[110px] bg-card text-xs text-foreground shadow-none"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="zh-CN">中文</SelectItem>
              <SelectItem value="en">English</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </header>
      <nav className="shrink-0 border-b bg-card px-4 py-2 md:px-6">
        <Tabs value={tab} onValueChange={value => setTab(value as Tab)}>
          <TabsList>
            {tabs.map(({ key, icon: Icon, labelKey }) => (
              <TabsTrigger key={key} value={key}>
                <Icon size={16} />{t[labelKey]}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </nav>
      {error && (
        <div className="shrink-0 px-4 pt-3">
          <Alert variant="destructive" className="border-red-200 bg-red-50 dark:border-red-900/60 dark:bg-red-950/40">
            <AlertTriangle />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        </div>
      )}
      <div className="min-h-0 flex-1 overflow-y-auto">
        {tab === 'generate' && <GeneratePage models={models} onRefresh={refresh} onOpenModels={() => setTab('models')} t={t} />}
        {tab !== 'generate' && (
          <div className="p-3 pb-6 md:px-3">
            <Suspense fallback={<p className="p-6 text-xs text-muted-foreground">{t.loading}</p>}>
              {tab === 'models' && <ModelsPage models={models} onRefresh={refresh} t={t} />}
              {tab === 'jobs' && <JobsPage t={t} />}
              {tab === 'api' && <ApiPage models={models} t={t} />}
            </Suspense>
          </div>
        )}
      </div>
      <Dialog open={aboutOpen} onOpenChange={setAboutOpen}>
        <DialogContent className="w-[min(520px,100%)] gap-0 rounded-xl p-5 sm:max-w-[520px]">
          <DialogHeader className="flex-row items-center gap-3">
            <img src={appIcon} alt="" className="size-11 rounded-[10px]" />
            <div className="min-w-0">
              <DialogTitle className="text-lg">{t.aboutTitle}</DialogTitle>
              <p className="mt-1 text-xs text-muted-foreground">{t.appSubtitle}</p>
            </div>
          </DialogHeader>
          <dl className="mt-5 grid gap-2.5">
            <div className="rounded-lg bg-secondary px-3 py-2.5">
              <dt className="text-[11px] font-bold text-muted-foreground">{t.vosAppVersion}</dt>
              <dd className="mt-1 break-all font-mono text-xs">{about?.app_version || window.__APP_VERSION__ || t.unavailable}</dd>
            </div>
            <div className="rounded-lg bg-secondary px-3 py-2.5">
              <dt className="text-[11px] font-bold text-muted-foreground">{t.frontendImage}</dt>
              <dd className="mt-1 break-all font-mono text-xs">{window.__FRONTEND_IMAGE__ || t.unavailable}</dd>
            </div>
            <div className="rounded-lg bg-secondary px-3 py-2.5">
              <dt className="text-[11px] font-bold text-muted-foreground">{t.backendImage}</dt>
              <dd className="mt-1 break-all font-mono text-xs">{window.__BACKEND_IMAGE__ || t.unavailable}</dd>
            </div>
            <div className="rounded-lg bg-secondary px-3 py-2.5">
              <dt className="text-[11px] font-bold text-muted-foreground">{t.deploymentProfile}</dt>
              <dd className="mt-1 break-all font-mono text-xs">{about?.profile || t.unavailable}</dd>
            </div>
          </dl>
        </DialogContent>
      </Dialog>
      <Toaster />
    </div>
    </TooltipProvider>
  )
}
