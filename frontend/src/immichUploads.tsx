import { useState } from 'react'
import { toast } from 'sonner'
import { StatusBadge } from '@/components/app/status-badge'
import { api, JobRecord } from './api/client'
import { messages } from './i18n'
type T = typeof messages['zh-CN']

const uploadState = (job: JobRecord) => Object.values(job.immich_uploads || {})
export const hasPendingUpload = (job: JobRecord) => uploadState(job).some(item => item.status === 'queued' || item.status === 'uploading')
export const hasFailedUpload = (job: JobRecord) => uploadState(job).some(item => item.status === 'failed')
export const hasPendingUploads = (jobs: JobRecord[]) => jobs.some(hasPendingUpload)

export function useImmichUploads(t: T, refresh: () => Promise<void>, confirm: (title: string) => Promise<boolean>) {
  const [busy, setBusy] = useState('')

  const upload = async (job: JobRecord) => {
    // 已上传过的输出默认会被后端跳过，此时先确认是否强制重传。
    const done = uploadState(job).filter(item => item.status === 'uploaded' || item.status === 'duplicate')
    if (done.length && !(await confirm(t.immichReuploadConfirm))) return
    setBusy(job.job_id)
    try {
      await api.uploadJobToImmich(job.job_id, done.length > 0)
      await refresh()
    } catch (error: any) {
      toast.error(error.message || t.immichUploadFailed)
    } finally {
      setBusy('')
    }
  }

  const retry = async (job: JobRecord) => {
    setBusy(job.job_id)
    try {
      await api.retryImmichUpload(job.job_id)
      await refresh()
    } catch (error: any) {
      toast.error(error.message || t.immichUploadFailed)
    } finally {
      setBusy('')
    }
  }

  return { upload, retry, busy }
}

export function ImmichUploadStatus({ job, t }: { job: JobRecord; t: T }) {
  return (
    <>
      {Object.entries(job.immich_uploads || {}).map(([filename, item]) => (
        <div className="col-span-full flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground" key={filename}>
          <StatusBadge status={item.status} className="px-2 text-[10px]">{item.status}</StatusBadge>
          <span>{filename}</span>
          <span>
            {item.status === 'uploaded'
              ? t.immichUploaded
              : item.status === 'duplicate'
                ? t.immichDuplicate
                : item.status === 'failed'
                  ? `${t.immichUploadFailed}: ${item.error}`
                  : t.immichUploading}
          </span>
        </div>
      ))}
    </>
  )
}
