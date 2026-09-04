import { useEffect, useState } from 'react'
import { CloudUpload, Download, RefreshCw, RotateCcw, Trash2 } from 'lucide-react'
import { api, JobRecord } from '../api/client'
import { messages } from '../i18n'
import { hasFailedUpload, hasPendingUpload, hasPendingUploads, ImmichUploadStatus, useImmichUploads } from '../immichUploads'

export default function JobsPage({ t }: { t: typeof messages['zh-CN'] }) {
  const [jobs, setJobs] = useState<JobRecord[]>([])

  const load = async () => setJobs(await api.listJobs())
  const { upload, retry, busy } = useImmichUploads(t, load, message => alert(message))

  const remove = async (jobId: string) => {
    if (!window.confirm(t.confirmDelete)) return
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
    <section className="panel">
      <div className="model-header">
        <div>
          <div className="panel-title">{t.jobs}</div>
          <p>{t.jobsHelp}</p>
        </div>
        <button className="secondary-action" onClick={load}><RefreshCw size={15} />{t.refresh}</button>
      </div>
      <div className="job-list">
        {jobs.map(job => {
          const output = job.outputs[0]
          const isVideo = output ? /\.(mp4|webm|mov)$/i.test(output) : false
          const pending = hasPendingUpload(job)
          const failed = hasFailedUpload(job)
          return (
            <div className="job-row rich" key={job.job_id}>
              <div className="job-thumb">
                {output && isVideo ? (
                  <video src={api.outputUrl(job.job_id, output)} preload="metadata" muted />
                ) : output ? (
                  <img src={api.outputUrl(job.job_id, output)} alt="" />
                ) : (
                  <span>{job.status}</span>
                )}
              </div>
              <span className={`job-status ${job.status}`}>{job.status}</span>
              <code>{job.job_id}</code>
              <span>{job.width} x {job.height}</span>
              <span>{job.steps} steps</span>
              <p>{job.prompt}</p>
              <div className="row-actions">
                {output && <a className="icon-button" href={api.outputUrl(job.job_id, output)} download title={t.downloadOutput}><Download size={15} /></a>}
                {job.status === 'succeeded' && !pending && !failed && (
                  <button className="icon-button" onClick={() => upload(job)} disabled={busy === job.job_id} title={t.immichUpload}><CloudUpload size={15} /></button>
                )}
                {failed && <button className="icon-button" onClick={() => retry(job)} disabled={busy === job.job_id} title={t.immichRetry}><RotateCcw size={15} /></button>}
                <button className="icon-button" onClick={() => remove(job.job_id)} title={t.deleteJob}><Trash2 size={15} /></button>
              </div>
              <ImmichUploadStatus job={job} t={t} />
            </div>
          )
        })}
        {jobs.length === 0 && <div className="empty-small">{t.noTask}</div>}
      </div>
    </section>
  )
}
