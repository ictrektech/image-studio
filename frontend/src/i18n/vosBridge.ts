import { normalizeLocale, type Locale } from './vosLocale'

interface VosLocaleBridge {
  getState?: () => Promise<{ locale?: unknown }>
  broadcast?: {
    on: (event: 'locale-change', handler: (state: { locale?: unknown }) => void) => () => void
  }
}

// vos_platform 的完整类型在 api/vos-auth.ts 声明（oauth2）；这里只取语言桥部分，
// 用断言而非重复 declare global，避免两个全局声明冲突。
type WindowWithVosBridge = Window & { vos_platform?: VosLocaleBridge }

/**
 * 订阅 VOS 桥接对象的语言快照与即时通知。
 * VOS 在 iframe onload 之后才注入桥，React 可能已经挂载完成，
 * 所以注入晚时用 50ms 轮询等待（最多 10s）。
 */
export function listenForVosBridgeLocale(apply: (locale: Locale) => void): () => void {
  let active = true
  let stop: (() => void) | undefined
  let timer: ReturnType<typeof setInterval> | undefined
  let revision = 0
  const started = Date.now()

  function connect() {
    const bridge = (window as unknown as WindowWithVosBridge).vos_platform
    if (!bridge) return false
    const update = (state: { locale?: unknown }) => {
      const locale = normalizeLocale(state.locale)
      if (active && locale) apply(locale)
    }
    try {
      // 先订阅再读快照，启动期间的变更不会丢失。
      stop = bridge.broadcast?.on('locale-change', state => {
        revision++
        update(state)
      })
      const snapshotRevision = revision
      void bridge.getState?.().then(state => {
        if (revision === snapshotRevision) update(state)
      }).catch(() => undefined)
    } catch {
      /* Older bridges may not expose the state API. */
    }
    return true
  }

  if (!connect() && window.parent !== window) {
    timer = setInterval(() => {
      if (connect() || Date.now() - started >= 10000) clearInterval(timer)
    }, 50)
  }
  return () => {
    active = false
    clearInterval(timer)
    stop?.()
  }
}
