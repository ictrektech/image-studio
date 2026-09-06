import { useEffect, useState } from 'react'
import { CloudUpload, Download, RefreshCw, RotateCcw, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Empty, EmptyHeader, EmptyTitle } from '@/components/ui/empty'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { Panel, PanelTitle } from '@/components/app/panel'
import { StatusBadge } from '@/components/app/status-badge'
import { useConfirm } from '@/components/app/confirm'
import { api, JobRecord } from '../api/client'
import { messages } from '../i18n'
import { hasFailedUpload, hasPendingUpload, hasPendingUploads, ImmichUploadStatus, useImmichUploads } from '../immichUploads'

export default function JobsPage({ t }: { t: typeof messages['zh-CN'] }) {
  const [jobs, setJobs] = useState<JobRecord[]>([])

  const load = async () => setJobs(await api.listJobs())
  const { confirm, confirmElement } = useConfirm(t)
  const { upload, retry, busy } = useImmichUploads(t, load, confirm)

  const remove = async (jobId: string) => {
    if (!(await confirm(t.confirmDelete))) return
    await api.deleteJob(jobId)
    await load()
  }

  useEffect(() => {
    load().catch(() => undefined)
  }, [])

  // 依赖布尔值而不是 jobs 数组：否则每次刷新都会重建定时器，间隔被拉长。
  const pendingUploads = hasPendingUploads(jobs)

  useEffect(() => {
    if (!pendingUploads) return
    const timer = window.setInterval(() => load().catch(() => undefined), 2000)
    return () => window.clearInterval(timer)
  }, [pendingUploads])

  return (
    <Panel className="p-3">
      {confirmElement}
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <PanelTitle>{t.jobs}</PanelTitle>
          <p className="mt-0.5 text-xs text-muted-foreground">{t.jobsHelp}</p>
        </div>
        <Button variant="outline" onClick={load}><RefreshCw size={15} />{t.refresh}</Button>
      </div>
      <div className="grid gap-2">
        {jobs.map(job => {
          const output = job.outputs[0]
          const isVideo = output ? /\.(mp4|webm|mov)$/i.test(output) : false
          const pending = hasPendingUpload(job)
          const failed = hasFailedUpload(job)
          return (
            <div
              className="grid items-center gap-2.5 rounded-lg border p-2.5 text-xs max-md:grid-cols-1 md:grid-cols-[74px_92px_minmax(180px,0.75fr)_92px_82px_minmax(220px,1fr)_78px]"
              key={job.job_id}
            >
              <div className="grid size-16 place-items-center overflow-hidden rounded-md border bg-secondary text-[11px] text-muted-foreground">
                {output && isVideo ? (
                  <video className="size-full object-cover" src={api.outputUrl(job.job_id, output)} preload="metadata" muted />
                ) : output ? (
                  <img className="size-full object-cover" src={api.outputUrl(job.job_id, output)} alt="" />
                ) : (
                  <span>{job.status}</span>
                )}
              </div>
              <StatusBadge status={job.status}>{job.status}</StatusBadge>
              <Tooltip>
                <TooltipTrigger asChild>
                  <code className="truncate font-mono">{job.job_id}</code>
                </TooltipTrigger>
                <TooltipContent>{job.job_id}</TooltipContent>
              </Tooltip>
              <span>{job.width} x {job.height}</span>
              <span>{job.steps} steps</span>
              <p className="truncate">{job.prompt}</p>
              <div className="flex gap-1.5">
                {output && (
                  <Button variant="outline" size="icon" asChild>
                    <a href={api.outputUrl(job.job_id, output)} download title={t.downloadOutput}><Download size={15} /></a>
                  </Button>
                )}
                {job.status === 'succeeded' && !pending && !failed && (
                  <Button variant="outline" size="icon" onClick={() => upload(job)} disabled={busy === job.job_id} title={t.immichUpload}><CloudUpload size={15} /></Button>
                )}
                {failed && (
                  <Button variant="outline" size="icon" onClick={() => retry(job)} disabled={busy === job.job_id} title={t.immichRetry}><RotateCcw size={15} /></Button>
                )}
                <Button variant="outline" size="icon" className="text-destructive hover:text-destructive" onClick={() => remove(job.job_id)} title={t.deleteJob}><Trash2 size={15} /></Button>
              </div>
              <ImmichUploadStatus job={job} t={t} />
            </div>
          )
        })}
        {jobs.length === 0 && (
          <Empty className="border-0 py-6">
            <EmptyHeader>
              <EmptyTitle>{t.noTask}</EmptyTitle>
            </EmptyHeader>
          </Empty>
        )}
      </div>
    </Panel>
  )
}
