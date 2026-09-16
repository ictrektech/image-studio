import { CheckCircle2, Cloud, DownloadCloud, ExternalLink, RefreshCw, RotateCcw, ShieldAlert, ShieldCheck, Square, WifiOff } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty'
import { Progress } from '@/components/ui/progress'
import { Spinner } from '@/components/ui/spinner'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { Panel, PanelHeading, PanelTitle } from '@/components/app/panel'
import { StatusBadge } from '@/components/app/status-badge'
import { api, ModelInfo, VRouterStatus } from '../api/client'
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
  const vRouterSettingsUrl = `${window.location.origin}/#/app/app-drawer/com.ictrek.v-router/v-router`
  const [busy, setBusy] = useState('')
  const [message, setMessage] = useState('')
  const [selectedCapabilities, setSelectedCapabilities] = useState<string[]>([])
  const [vRouterStatus, setVRouterStatus] = useState<VRouterStatus | null>(null)
  const downloading = models.some(model => model.status === 'downloading' || model.variants?.some(variant => variant.status === 'downloading'))
  const modelEntries = useMemo(
    () => models.flatMap(model => [
      ...(model.variants || []).map(variant => ({ base: model, active: variant, variantId: variant.id || '', isVariant: true })),
      { base: model, active: model, variantId: '', isVariant: false },
    ]),
    [models],
  )
  const localEntries = useMemo(() => modelEntries.filter(entry => entry.active.source !== 'v-router'), [modelEntries])
  const remoteEntries = useMemo(() => modelEntries.filter(entry => entry.active.source === 'v-router'), [modelEntries])
  const vRouterReachable = remoteEntries.length > 0 || Boolean(vRouterStatus?.reachable)
  const vRouterModelCount = remoteEntries.length || vRouterStatus?.eligible_models || 0
  const capabilityOptions = useMemo(
    () => sortCapabilities(Array.from(new Set(localEntries.flatMap(entry => displayCapabilities(entryCapabilities(entry)))))),
    [localEntries],
  )
  const filteredEntries = useMemo(
    () => selectedCapabilities.length === 0
      ? localEntries
      : localEntries.filter(entry => {
        const caps = entryCapabilities(entry)
        return selectedCapabilities.every(capability => caps.includes(capability))
      }),
    [localEntries, selectedCapabilities],
  )

  const refreshVRouterStatus = () => api.vRouterStatus()
    .then(setVRouterStatus)
    .catch(error => setVRouterStatus({ configured: true, reachable: false, api_url: '', eligible_models: 0, error: error.message || String(error) }))

  useEffect(() => {
    refreshVRouterStatus()
  }, [])

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
    <div className="grid gap-2.5">
      <Panel className="p-3">
        <PanelHeading className="mb-3">
          <div>
            <PanelTitle className="flex items-center gap-2"><Cloud size={17} />{t.vRouterCloudModels}</PanelTitle>
            <p className="mt-0.5 text-xs text-muted-foreground">{t.vRouterCloudModelsHelp}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button asChild>
              <a
                href={vRouterSettingsUrl}
                target="_top"
              >
                <ExternalLink size={15} />{t.openVRouter}
              </a>
            </Button>
            <Button variant="outline" onClick={() => { onRefresh(); refreshVRouterStatus() }}><RefreshCw size={15} />{t.refresh}</Button>
          </div>
        </PanelHeading>
        <Alert className={vRouterReachable ? 'mb-3 border-green-300 bg-green-50 text-green-900 dark:border-green-800 dark:bg-green-950/30 dark:text-green-200' : 'mb-3'}>
          {vRouterReachable ? <ShieldCheck size={16} /> : <WifiOff size={16} />}
          <AlertDescription>
            <strong>{vRouterReachable ? t.vRouterConnected : t.vRouterUnavailable}</strong>
            {vRouterReachable
              ? ` · ${vRouterModelCount} ${t.vRouterModelCount}`
              : vRouterStatus?.error ? ` · ${vRouterStatus.error}` : ''}
          </AlertDescription>
        </Alert>
        {remoteEntries.length === 0 ? (
          <Empty className="border py-6">
            <EmptyHeader>
              <EmptyTitle>{vRouterReachable ? t.vRouterNoModels : t.vRouterUnavailable}</EmptyTitle>
              <EmptyDescription>{vRouterReachable ? t.vRouterCloudModelsHelp : (vRouterStatus?.error || t.vRouterCloudModelsHelp)}</EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <div className="grid gap-2.5 [grid-template-columns:repeat(auto-fit,minmax(300px,1fr))]">
            {remoteEntries.map(entry => (
              <article className="rounded-lg border border-blue-300 bg-card p-3 dark:border-blue-800" key={entry.base.key}>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h3 className="truncate text-[15px] font-bold">{entry.active.name}</h3>
                    <p className="mt-1 text-xs text-muted-foreground">{entry.active.description}</p>
                  </div>
                  <StatusBadge status="ready" className="shrink-0 whitespace-nowrap"><ShieldCheck size={14} />{t.modelReady}</StatusBadge>
                </div>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  <Badge>V-Router</Badge>
                  {displayCapabilities(entryCapabilities(entry)).map(capability => <Badge variant="outline" key={capability}>{capabilityLabel(capability, t)}</Badge>)}
                </div>
                <code className="mt-3 block truncate rounded border bg-secondary px-1.5 py-1.5 font-mono text-[11px]">{entry.active.model_id}</code>
              </article>
            ))}
          </div>
        )}
      </Panel>

      <Panel className="p-3">
        <PanelHeading className="mb-3">
          <div>
            <PanelTitle>{t.localModels}</PanelTitle>
            <p className="mt-0.5 text-xs text-muted-foreground">{t.localModelsHelp}</p>
          </div>
          <Button variant="outline" onClick={onRefresh}><RefreshCw size={15} />{t.refresh}</Button>
        </PanelHeading>
        {message && (
          <Alert className="mb-3 border-blue-200 bg-blue-50 text-blue-900 dark:border-blue-900/60 dark:bg-blue-950/40 dark:text-blue-200">
            <AlertDescription>{message}</AlertDescription>
          </Alert>
        )}
        {localEntries.length === 0 && (
          <Empty className="border-0 py-6">
            <EmptyHeader>
              <EmptyTitle>{t.noModelsConfigured}</EmptyTitle>
              <EmptyDescription>{t.modelManagementHelp}</EmptyDescription>
            </EmptyHeader>
          </Empty>
        )}
        {capabilityOptions.length > 0 && (
          <div className="my-3 rounded-lg bg-secondary p-3">
            <PanelHeading>
              <div>
                <strong className="block text-xs text-foreground">{t.capabilityFilter}</strong>
                <span className="mt-0.5 block text-[11px] text-muted-foreground">{t.capabilityFilterHelp}</span>
              </div>
              {selectedCapabilities.length > 0 && (
                <Button variant="ghost" size="sm" className="shrink-0" onClick={() => setSelectedCapabilities([])}>
                  {t.clearCapabilityFilters}
                </Button>
              )}
            </PanelHeading>
            <ToggleGroup
              type="multiple"
              variant="outline"
              spacing={1}
              className="mt-2.5 flex-wrap"
              value={selectedCapabilities}
              onValueChange={setSelectedCapabilities}
            >
              {capabilityOptions.map(capability => (
                <ToggleGroupItem key={capability} value={capability}>
                  {capabilityLabel(capability, t)}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          </div>
        )}
        {models.length > 0 && filteredEntries.length === 0 && (
          <Empty className="border-0 py-6">
            <EmptyHeader>
              <EmptyTitle>{t.noModelsMatchFilter}</EmptyTitle>
              <EmptyDescription>{t.capabilityFilterHelp}</EmptyDescription>
            </EmptyHeader>
          </Empty>
        )}
        <div className="grid gap-2.5 [grid-template-columns:repeat(auto-fit,minmax(420px,1fr))] max-lg:grid-cols-1">
          {filteredEntries.map(entry => {
            const model = entry.base
            const active = entry.active
            const capabilities = displayCapabilities(entryCapabilities(entry))
            const ready = active.status === 'ready'
            const downloading = active.status === 'downloading'
            const failed = active.status === 'failed'
            const metaFields: [string, string][] = [
              [t.modelVariant, entry.isVariant ? `${active.name} (${entry.variantId})` : t.defaultModelVariant],
              [t.modelId, active.model_id],
              [t.source, active.source],
              [t.family, active.family],
              [t.paramsLabel, active.params || '-'],
              [t.capabilities, capabilities.map(capability => capabilityLabel(capability, t)).join(', ')],
              [t.loadPath, active.resolved_path || active.access_path],
              [t.expectedFiles, active.expected_files.join(', ')],
              [t.size, sizeDisplay(active, t)],
              [t.status, active.status],
            ]
            return (
              <article
                className={
                  ready
                    ? 'rounded-lg border border-green-300 bg-card p-3 dark:border-green-700'
                    : 'rounded-lg border border-orange-300 bg-card p-3 dark:border-orange-700'
                }
                key={`${model.key}:${entry.variantId || 'default'}`}
              >
                <div className="flex items-start justify-between gap-3.5">
                  <div className="min-w-0">
                    <h3 className="text-[15px] font-bold">{entry.isVariant ? `${model.name} · ${active.name}` : model.name}</h3>
                    <div className="mt-1.5 mb-1 flex flex-wrap gap-1.5">
                      {entry.isVariant && <Badge className="h-[22px] rounded-full bg-accent px-2 text-[11px] font-semibold text-accent-foreground">{t.modelVariant}</Badge>}
                      {active.preferred && <Badge className="h-[22px] rounded-full bg-accent px-2 text-[11px] font-semibold text-accent-foreground">{t.preferredModel}</Badge>}
                      <Badge className="h-[22px] rounded-full bg-accent px-2 text-[11px] font-semibold text-accent-foreground">{active.family}</Badge>
                      {capabilities.map(capability => (
                        <Badge className="h-[22px] rounded-full bg-accent px-2 text-[11px] font-semibold text-accent-foreground" key={capability}>{capabilityLabel(capability, t)}</Badge>
                      ))}
                    </div>
                    <p className="mt-0.5 text-xs text-muted-foreground">{active.description}</p>
                  </div>
                  <StatusBadge status={ready ? 'ready' : downloading ? 'downloading' : failed ? 'failed' : 'pending'} className="shrink-0 whitespace-nowrap">
                    {ready && <ShieldCheck size={14} />}
                    {failed && <ShieldAlert size={14} />}
                    {downloading && <Spinner className="size-3.5" />}
                    {ready ? t.modelReady : failed ? t.modelFailed : downloading ? t.modelDownloading : t.modelMissing}
                  </StatusBadge>
                </div>

                <div className="mt-3.5 grid grid-cols-2 gap-2 gap-x-3 max-md:grid-cols-1">
                  {metaFields.map(([label, value]) => (
                    <div className="min-w-0" key={label}>
                      <span className="mb-1 block text-[11px] text-muted-foreground">{label}</span>
                      <code className="block truncate rounded border bg-secondary px-1.5 py-1.5 font-mono text-[11px]">{value}</code>
                    </div>
                  ))}
                </div>

                <Progress className="mt-3.5" max={100} value={percent(active)} />
                {downloading && active.current_file && (
                  <p className="mt-1.5 truncate text-[11px] text-muted-foreground">
                    {t.downloadingFile}: {active.current_file}{bytesText(active) && ` · ${bytesText(active)}`}
                  </p>
                )}
                {failed && active.error && <p className="mt-1.5 break-all text-[11px] text-destructive">{active.error}</p>}

                <div className="mt-3 flex flex-wrap gap-2">
                  <Button
                    className="min-w-[132px]"
                    disabled={ready || downloading || Boolean(busy)}
                    onClick={() => run(model, entry.variantId, 'pull')}
                  >
                    {ready ? <CheckCircle2 size={15} /> : <DownloadCloud size={15} />}
                    {ready ? t.downloaded : downloading ? `${t.modelDownloading} ${percent(active)}%` : t.downloadModel}
                  </Button>
                  {downloading && (
                    <Button
                      variant="outline"
                      className="min-w-[132px]"
                      disabled={Boolean(busy)}
                      onClick={() => run(model, entry.variantId, 'stop')}
                    >
                      <Square size={15} />{t.stopDownload}
                    </Button>
                  )}
                  {(downloading || ready || failed) && (
                    <Button
                      variant="outline"
                      className="min-w-[132px]"
                      disabled={Boolean(busy)}
                      onClick={() => run(model, entry.variantId, 'pull-force')}
                    >
                      <RotateCcw size={15} />{t.redownload}
                    </Button>
                  )}
                  <Button
                    variant="outline"
                    className="min-w-[132px]"
                    disabled={Boolean(busy)}
                    onClick={() => run(model, entry.variantId, 'sync')}
                  >
                    <RefreshCw size={15} />{t.syncModel}
                  </Button>
                </div>
              </article>
            )
          })}
        </div>
      </Panel>

      <Panel className="p-3">
        <PanelTitle>{t.modelHubPathGuide}</PanelTitle>
        <p className="mt-0.5 text-xs text-muted-foreground">{t.modelHubPathHelp}</p>
        {filteredEntries.map(entry => (
          <div className="grid grid-cols-[260px_minmax(0,1fr)] items-center gap-3 border-t py-2.5 text-xs first:mt-2.5 max-md:grid-cols-1" key={`${entry.base.key}:${entry.variantId || 'default'}`}>
            <span className="font-bold text-foreground">{entry.isVariant ? `${entry.base.name} · ${entry.active.name}` : entry.base.name}</span>
            <code className="truncate rounded border bg-secondary px-1.5 py-1.5 font-mono text-[11px]">{entry.active.access_path}</code>
          </div>
        ))}
      </Panel>
    </div>
  )
}
