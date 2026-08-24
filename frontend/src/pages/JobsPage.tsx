import { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { api, JobRecord } from '../api/client'
import { messages } from '../i18n'

export default function JobsPage({ t }: { t: typeof messages['zh-CN'] }) {
  const [jobs, setJobs] = useState<JobRecord[]>([])

  const load = async () => setJobs(await api.listJobs())

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
        {jobs.map(job => (
          <div className="job-row" key={job.job_id}>
            <span className={`job-status ${job.status}`}>{job.status}</span>
            <code>{job.job_id}</code>
            <span>{job.width} x {job.height}</span>
            <span>{job.steps} steps</span>
            <p>{job.prompt}</p>
          </div>
        ))}
        {jobs.length === 0 && <div className="empty-small">{t.noTask}</div>}
      </div>
    </section>
  )
}
