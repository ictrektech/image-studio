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

/** PhotoCraft 的入口 URL；open 指向带凭据的同源图片地址，PhotoCraft 可直接加载。 */
export function photoCraftUrl(jobId: string, filename: string): string {
  const params = new URLSearchParams({
    open: api.outputUrl(jobId, filename),
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
