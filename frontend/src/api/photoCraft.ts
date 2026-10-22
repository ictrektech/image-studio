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

/** 只传递已授权的临时图片地址，不把 VOS 登录令牌放进交接 URL。 */
export function photoCraftUrl(outputPath: string, filename: string): string {
  const params = new URLSearchParams({
    open: outputPath,
    name: filename,
    source: SOURCE_APP_ID,
  })
  return `${PHOTOCRAFT_PATH}?${params.toString()}`
}

/** 打开编辑器；无平台桥或桥不可用时打开新窗口。 */
export async function openInPhotoCraft(jobId: string, filename: string, title = 'PhotoCraft'): Promise<void> {
  const handoff = await api.photoCraftHandoff(jobId, filename)
  const url = photoCraftUrl(handoff.url, filename)
  const platform = (window as WindowWithOpenTab).vos_platform?.platform
  if (typeof platform?.openTab === 'function') {
    try { await platform.openTab({ url, title }); return } catch { /* fall back below */ }
  }
  window.open(url, '_blank', 'noopener')
}
