import { useEffect, useState } from 'react'
import { Download, RefreshCw, Trash2 } from 'lucide-react'
import { api, JobRecord } from '../api/client'
import { messages } from '../i18n'

export default function JobsPage({ t }: { t: typeof messages['zh-CN'] }) {
  const [jobs, setJobs] = useState<JobRecord[]>([])

  const load = async () => setJobs(await api.listJobs())

  const remove = async (jobId: string) => {
    if (!window.confirm(t.confirmDelete)) return
    await api.deleteJob(jobId)
    await load()
  }

  useEffect(() => {
    load().catch(() => undefined)
  }, [])

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
          return (
            <div className="job-row rich" key={job.job_id}>
              <div className="job-thumb">
                {output ? <img src={api.outputUrl(job.job_id, output)} alt="" /> : <span>{job.status}</span>}
              </div>
              <span className={`job-status ${job.status}`}>{job.status}</span>
              <code>{job.job_id}</code>
              <span>{job.width} x {job.height}</span>
              <span>{job.steps} steps</span>
              <p>{job.prompt}</p>
              <div className="row-actions">
                {output && <a className="icon-button" href={api.outputUrl(job.job_id, output)} download title={t.downloadOutput}><Download size={15} /></a>}
                <button className="icon-button" onClick={() => remove(job.job_id)} title={t.deleteJob}><Trash2 size={15} /></button>
              </div>
            </div>
          )
        })}
        {jobs.length === 0 && <div className="empty-small">{t.noTask}</div>}
      </div>
    </section>
  )
}
