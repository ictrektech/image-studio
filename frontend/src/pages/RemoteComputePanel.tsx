import { useEffect, useRef, useState } from 'react'
import { Panel, PanelHeading, PanelTitle } from '@/components/app/panel'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { api, type ComputeDeployment, type ComputeOverview, type ComputeTarget, type ModelInfo } from '../api/client'
import { messages } from '../i18n'

type Text = typeof messages['zh-CN']

const targetKey = (target: ComputeTarget) => `${target.kind}:${target.node_id}`
const deploymentTarget = (row: ComputeDeployment) => `${row.target_kind}:${row.target_id}`

function imageVersion(image: string): string {
  const tag = image.split('/').pop()?.split('@')[0].split(':')[1] || ''
  const match = /^(?:amd(?:_cu128)?|arm(?:_cu128)?|l4t|thor)_(\d{4})(\d{2})(\d{2})(?:_(vos\d+))?(?:_|$)/.exec(tag)
  if (match) return [`${match[1]}-${match[2]}-${match[3]}`, match[4]].filter(Boolean).join(' · ')
  return /^v?\d+\.\d+\.\d+(?:-[a-z]+\d*)?$/i.test(tag) && tag.length <= 24 ? tag : ''
}

export default function RemoteComputePanel({ models, t }: { models: ModelInfo[]; t: Text }) {
  const [open, setOpen] = useState(false)
  const [overview, setOverview] = useState<ComputeOverview | null>(null)
  const [modelIds, setModelIds] = useState<Record<string, string>>({})
  const [error, setError] = useState('')
  const [overviewError, setOverviewError] = useState(false)
  const [busy, setBusy] = useState('')
  const [remove, setRemove] = useState<{ id: string; node: string }>()
  const deployKeys = useRef(new Map<string, string>())
  const localModels = models.filter(model => model.source !== 'v-router').flatMap(model => [
    { id: model.key, key: model.key, variant: '', name: model.name, ready: model.status === 'ready' },
    ...(model.variants || []).filter(variant => variant.id).map(variant => ({
      id: `${model.key}@${variant.id}`, key: model.key, variant: variant.id!,
      name: `${model.name} · ${variant.name}`, ready: variant.status === 'ready',
    })),
  ])
  const readyModels = localModels.filter(model => model.ready)
  const nodes = new Map<string, { name: string; profile: string; target?: ComputeTarget; deployments: ComputeDeployment[] }>()
  for (const target of overview?.targets ?? []) {
    nodes.set(targetKey(target), { name: target.name, profile: target.profile, target, deployments: [] })
  }
  for (const row of overview?.deployments ?? []) {
    if (row.state === 'removed') continue
    const key = deploymentTarget(row)
    let node = nodes.get(key)
    if (!node) {
      node = { name: row.node_name || t.remoteComputeUnknownNode, profile: row.profile, deployments: [] }
      nodes.set(key, node)
    }
    node.deployments.push(row)
  }

  async function refresh() {
    try {
      setOverview(await api.computeOverview())
      setOverviewError(false)
    } catch {
      setOverviewError(true)
    }
  }

  useEffect(() => {
    if (!open) return
    void refresh()
    const timer = window.setInterval(refresh, 4000)
    return () => window.clearInterval(timer)
  }, [open])

  async function act(key: string, action: () => Promise<unknown>) {
    setBusy(key)
    setError('')
    try {
      await action()
      await refresh()
    } catch (reason) {
      const code = reason instanceof Error ? reason.message : ''
      const errors: Record<string, string> = {
        BACKEND_TASKS_ACTIVE: t.remoteComputeTasksActive,
        COMPUTE_MODEL_PREPARATION_ACTIVE: t.remoteComputePreparationActive,
        COMPUTE_DEPLOYMENT_BUSY: t.remoteComputeBusy,
        BACKEND_BUSY: t.remoteComputeBusy,
      }
      setError(errors[code] || t.remoteComputeError)
    } finally {
      setBusy('')
    }
  }

  function control(id: string, action: 'start' | 'stop' | 'remove') {
    void act(id, async () => {
      const receipt = await api.controlCompute(id, action)
      setOverview(current => current && {
        ...current,
        deployments: current.deployments.map(row => row.id === id ? { ...row, ...receipt, last_error: null } : row),
      })
    })
  }

  function deploy(target: ComputeTarget) {
    const node = targetKey(target)
    const key = deployKeys.current.get(node) || crypto.randomUUID()
    deployKeys.current.set(node, key)
    void act(node, async () => {
      await api.deployCompute(target, key)
      deployKeys.current.delete(node)
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
        {(error || overviewError) && <Alert><AlertDescription>{error || t.remoteComputeError}</AlertDescription></Alert>}
        {overview && !nodes.size && <p className="text-sm text-muted-foreground">{t.remoteComputeNoTargets}</p>}
        {[...nodes].map(([nodeKey, { name, profile, target, deployments }]) => {
          const canDeploy = !deployments.length && target
          const candidateVersion = canDeploy ? imageVersion(target.image) : ''
          return <section key={nodeKey} className="min-w-0 rounded-lg border" aria-label={name}>
            <header className="flex flex-wrap items-center justify-between gap-3 px-3 py-2.5">
              <div className="min-w-0">
                <h3 className="break-words text-sm font-semibold">{name}</h3>
                <p className="text-xs text-muted-foreground">{profile}{candidateVersion && ` · ${t.remoteComputeImageVersion} ${candidateVersion}`}</p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {!deployments.length && <Badge variant="secondary">{t.remoteComputeNotDeployed}</Badge>}
                {target && canDeploy && <Button size="sm" disabled={!!busy} onClick={() => deploy(target)}>
                  {busy === nodeKey ? t.remoteComputeStates.pending : t.remoteComputeDeploy}
                </Button>}
              </div>
            </header>
            {deployments.map((row, index) => {
              const version = imageVersion(row.image)
              const preparations = overview?.preparations.filter(item => item.deployment_id === row.id) ?? []
              const selectedModel = readyModels.find(model => model.id === modelIds[row.id])
              const running = row.state === 'running' && !row.last_error
              const transitioning = row.state === 'stopping' || row.state === 'deleting'
              return <div key={row.id} className="grid gap-3 border-t px-3 py-2.5">
                <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
                  <span>{t.remoteComputeBackendLabel}{deployments.length > 1 && ` ${index + 1}`}{version && ` · ${t.remoteComputeImageVersion} ${version}`}</span>
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant={row.last_error ? 'destructive' : running ? 'default' : 'secondary'}>
                      {row.last_error && row.state === 'running' ? t.remoteComputeStates.failed : t.remoteComputeStates[row.state]}
                    </Badge>
                    {(row.state === 'running' || row.state === 'pending') &&
                      <Button variant="outline" size="sm" disabled={!!busy} onClick={() => control(row.id, 'stop')}>{t.remoteComputeStop}</Button>}
                    {(row.state === 'stopped' || row.state === 'failed') &&
                      <Button variant="outline" size="sm" disabled={!!busy} onClick={() => control(row.id, 'start')}>{t.remoteComputeStart}</Button>}
                    {!transitioning &&
                      <Button variant="outline" size="sm" className="text-destructive" disabled={!!busy}
                        onClick={() => setRemove({ id: row.id, node: name })}>{t.remoteComputeRemove}</Button>}
                  </div>
                </div>
                {preparations.map(item => {
                  const percentage = item.total_bytes ? Math.round(100 * item.received_bytes / item.total_bytes) : 0
                  return <div key={item.model_id} className="grid gap-1 text-sm">
                    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
                      <span className="font-medium">{localModels.find(model => model.id === item.model_id)?.name || t.remoteComputeModelLabel}</span>
                      <span className="text-xs text-muted-foreground">
                        {running && item.state === 'registered' ? t.remoteComputeModelReady : t.remoteComputeStates[item.state]}
                        {item.state === 'transferring' && ` · ${percentage}%`}
                        {item.weight_source && ` · ${item.weight_source === 'shared' ? t.remoteComputeShared : t.remoteComputeCopy}`}
                      </span>
                    </div>
                    {item.state === 'transferring' && <Progress value={percentage} aria-label={t.remoteComputeTransfer} />}
                  </div>
                })}
                {running && <div className="flex flex-wrap items-end gap-2">
                  <div className="grid gap-1">
                    <span className="text-xs font-medium">{t.remoteComputeModelLabel}</span>
                    <Select value={modelIds[row.id] || ''} onValueChange={value => setModelIds(current => ({ ...current, [row.id]: value }))}>
                      <SelectTrigger aria-label={`${t.remoteComputeModelLabel} · ${name}`}>
                        <SelectValue placeholder={t.remoteComputeModel} />
                      </SelectTrigger>
                      <SelectContent>
                        {readyModels.map(model => <SelectItem key={model.id} value={model.id}>{model.name}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                  <Button size="sm" disabled={!!busy || !selectedModel || preparations.some(item => item.model_id === selectedModel.id && (item.state === 'registered' || item.state === 'transferring'))}
                    onClick={() => selectedModel && void act(row.id, () => api.prepareComputeModel(row.id, selectedModel.key, selectedModel.variant))}>
                    {t.remoteComputeTransfer}
                  </Button>
                </div>}
              </div>
            })}
          </section>
        })}
      </div>}
      <AlertDialog open={!!remove} onOpenChange={value => { if (!value) setRemove(undefined) }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t.remoteComputeRemove} · {remove?.node}</AlertDialogTitle>
            <AlertDialogDescription>{t.remoteComputeRemoveDescription}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t.remoteComputeCancel}</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => { if (remove) control(remove.id, 'remove') }}>
              {t.remoteComputeRemove}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Panel>
  )
}
