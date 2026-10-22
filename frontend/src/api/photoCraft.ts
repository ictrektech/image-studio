import { api } from './client'

// 平台路径；openTab 的 url 相对平台 origin 解析。
const PHOTOCRAFT_PATH = '/app/com.ictrek.photocraft/'
const SOURCE_APP_ID = 'com.ictrek.image-studio'

// 仅声明本文件用到的 vos_platform 子集。
type WindowWithOpenTab = Window & {
  vos_platform?: {
    platform?: {
      openTab?: (options: { url: string; title?: string }) => Promise<void>
    }
  }
}

/** PhotoCraft 用当前账户取回同源图片，交接地址不携带源应用令牌。 */
export function photoCraftUrl(jobId: string, filename: string): string {
  const params = new URLSearchParams({
    open: api.outputUrl(jobId, filename).split('?')[0],
    name: filename,
    source: SOURCE_APP_ID,
  })
  return `${PHOTOCRAFT_PATH}?${params.toString()}`
}

/** 打开 PhotoCraft 编辑这张图；返回 false 表示当前环境没有桥，调用方降级。 */
export async function openInPhotoCraft(jobId: string, filename: string, title = 'PhotoCraft'): Promise<boolean> {
  const openTab = (window as WindowWithOpenTab).vos_platform?.platform?.openTab
  if (typeof openTab !== 'function') return false
  await openTab({ url: photoCraftUrl(jobId, filename), title })
  return true
}
