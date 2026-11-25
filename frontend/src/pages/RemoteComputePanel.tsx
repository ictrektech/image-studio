import { useEffect, useRef, useState } from 'react'
import { Panel, PanelHeading, PanelTitle } from '@/components/app/panel'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { api, type ComputeOverview, type ComputeTarget, type ModelInfo } from '../api/client'
import { messages } from '../i18n'

type Text = typeof messages['zh-CN']

const targetKey = (target: ComputeTarget) => `${target.kind}:${target.node_id}`

export default function RemoteComputePanel({ models, t }: { models: ModelInfo[]; t: Text }) {
  const [open, setOpen] = useState(false)
  const [overview, setOverview] = useState<ComputeOverview | null>(null)
  const [targetId, setTargetId] = useState('')
  const [deploymentId, setDeploymentId] = useState('')
  const [modelId, setModelId] = useState('')
  const [error, setError] = useState('')
  const [overviewError, setOverviewError] = useState('')
  const [busy, setBusy] = useState(false)
  const deployKeys = useRef(new Map<string, string>())
  const target = overview?.targets.find(row => targetKey(row) === targetId)
  const readyModels = models.filter(model => model.source !== 'v-router').flatMap(model => [
    { id: model.key, key: model.key, variant: '', name: model.name, ready: model.status === 'ready' },
    ...(model.variants || []).filter(variant => variant.id).map(variant => ({
      id: `${model.key}@${variant.id}`, key: model.key, variant: variant.id!,
      name: `${model.name} · ${variant.name}`, ready: variant.status === 'ready',
    })),
  ]).filter(model => model.ready)
  const selectedModel = readyModels.find(model => model.id === modelId)
  const deployments = overview?.deployments.filter(row => row.state !== 'removed') ?? []
  const running = deployments.filter(row => row.state === 'running' && !row.last_error)

  const refresh = () => api.computeOverview().then(value => {
    setOverview(value)
    setOverviewError('')
  }).catch((reason: Error) => setOverviewError(reason.message))

  useEffect(() => {
    if (!open) return
    void refresh()
    const timer = window.setInterval(refresh, 4000)
    return () => window.clearInterval(timer)
  }, [open])

  async function act(action: () => Promise<unknown>) {
    setBusy(true)
    setError('')
    try {
      await action()
      await refresh()
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setBusy(false)
    }
  }

  function deploy() {
    if (!target) return
    const key = deployKeys.current.get(targetId) || crypto.randomUUID()
    deployKeys.current.set(targetId, key)
    void act(async () => {
      await api.deployCompute(target, key)
      deployKeys.current.delete(targetId)
    })
  }

  return (
    <Panel className="p-3">
      <PanelHeading>
        <PanelTitle>{t.remoteCompute}</PanelTitle>
        <Button variant="outline" onClick={() => setOpen(value => !value)} aria-expanded={open}>
          {open ? t.remoteComputeClose : t.remoteComputeManage}
        </Button>
      </PanelHeading>
      {open && <div className="mt-3 grid gap-3">
        {(error || overviewError) && <Alert><AlertDescription>{t.remoteComputeError} <code>{error || overviewError}</code></AlertDescription></Alert>}
        {overview && <>
          <div className="flex flex-wrap items-center gap-2">
            <Select value={targetId} onValueChange={setTargetId}>
              <SelectTrigger aria-label={t.remoteComputeTarget}><SelectValue placeholder={t.remoteComputeTarget} /></SelectTrigger>
              <SelectContent>
                {overview.targets.map(row => <SelectItem key={targetKey(row)} value={targetKey(row)}>{row.name} · {row.profile}</SelectItem>)}
              </SelectContent>
            </Select>
            <Button disabled={busy || !target} onClick={deploy}>{t.remoteComputeDeploy}</Button>
          </div>
          {!overview.targets.length && <p className="text-xs text-muted-foreground">{t.remoteComputeNoTargets}</p>}
          {target && <code className="break-all text-xs text-muted-foreground">{target.image}</code>}
          {deployments.map(row => <div key={row.id} className="rounded-md border px-3 py-2 text-sm">
            <div className="flex flex-wrap justify-between gap-2">
              <span>{row.target_id} · {row.profile}</span>
              <span>{t.remoteComputeStates[row.state]}</span>
            </div>
            {row.last_error && <code className="text-xs text-muted-foreground">{row.last_error}</code>}
          </div>)}
          {running.length > 0 && <div className="flex flex-wrap items-center gap-2">
            <Select value={deploymentId} onValueChange={setDeploymentId}>
              <SelectTrigger aria-label={t.remoteComputeBackend}><SelectValue placeholder={t.remoteComputeBackend} /></SelectTrigger>
              <SelectContent>
                {running.map(row => <SelectItem key={row.id} value={row.id}>{row.target_id} · {row.id.slice(0, 8)}</SelectItem>)}
              </SelectContent>
            </Select>
            <Select value={modelId} onValueChange={setModelId}>
              <SelectTrigger aria-label={t.remoteComputeModel}><SelectValue placeholder={t.remoteComputeModel} /></SelectTrigger>
              <SelectContent>
                {readyModels.map(model => <SelectItem key={model.id} value={model.id}>{model.name}</SelectItem>)}
              </SelectContent>
            </Select>
            <Button disabled={busy || !selectedModel || !running.some(row => row.id === deploymentId)}
              onClick={() => selectedModel && void act(() => api.prepareComputeModel(deploymentId, selectedModel.key, selectedModel.variant))}>
              {t.remoteComputeTransfer}
            </Button>
          </div>}
          {overview.preparations.map(row => {
            const percentage = row.total_bytes ? Math.round(100 * row.received_bytes / row.total_bytes) : 0
            return <div key={`${row.deployment_id}:${row.model_id}`} className="grid gap-1 rounded-md border px-3 py-2">
              <div className="flex flex-wrap justify-between gap-2 text-sm">
                <span>{row.model_id} · {row.deployment_id.slice(0, 8)}</span>
                <span>
                  {t.remoteComputeStates[row.state]}{row.state === 'transferring' ? ` · ${percentage}%` : ''}
                  {row.weight_source && ` · ${row.weight_source === 'shared' ? t.remoteComputeShared : t.remoteComputeCopy}`}
                </span>
              </div>
              {row.state === 'transferring' && <Progress value={percentage} aria-label={t.remoteComputeTransfer} />}
              {row.error && <code className="text-xs text-muted-foreground">{row.error}</code>}
            </div>
          })}
        </>}
      </div>}
    </Panel>
  )
}
