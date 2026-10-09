export const SUPPORTED_LOCALES = ['zh-CN', 'zh-TW', 'en'] as const
export type Locale = typeof SUPPORTED_LOCALES[number]
export type LanguageMode = Locale | 'auto'

const VOS_KEY = 'preferences-locale'
const VOS_PREFIXES = ['VIVIBIT-', 'vben-web-antd-']
export const VOS_APP_PATH = '/app/com.ictrek.image-studio'

/** 把任意来源的语言值（VOS 可能发 zh_Hant、zh-hk、en-US 等）归一成三选一。 */
export function normalizeLocale(value: unknown): Locale | null {
  if (typeof value !== 'string') return null
  const locale = value.trim().replace(/_/g, '-').toLowerCase()
  if (/^zh-(tw|hk|mo|hant)(-|$)/.test(locale)) return 'zh-TW'
  if (locale === 'zh' || /^zh-(cn|sg|hans)(-|$)/.test(locale)) return 'zh-CN'
  if (locale === 'en' || locale.startsWith('en-')) return 'en'
  return null
}

export function isVosLocaleKey(key: string): boolean {
  return key === VOS_KEY || VOS_PREFIXES.some(prefix => key.startsWith(prefix) && key.endsWith(`-${VOS_KEY}`))
}

export function parseStoredLocale(stored: string | null): Locale | null {
  if (!stored) return null
  try {
    const parsed = JSON.parse(stored)
    return normalizeLocale(parsed?.value ?? parsed)
  } catch {
    return normalizeLocale(stored)
  }
}

/** 回退链：VOS 主应用写在同源 localStorage 的语言键（带版本前缀时取最大的那个）。 */
export function readVosLocale(storage: Storage): Locale | null {
  try {
    const keys = Array.from({ length: storage.length }, (_, index) => storage.key(index))
      .filter((key): key is string => !!key && isVosLocaleKey(key))
      .sort((a, b) => b.localeCompare(a, undefined, { numeric: true }))
    for (const key of keys) {
      const locale = parseStoredLocale(storage.getItem(key))
      if (locale) return locale
    }
  } catch {
    /* Storage may be unavailable in an embedded browser. */
  }
  return null
}

export function resolveLocale(
  mode: LanguageMode,
  hostLocale: Locale | null,
  browserLanguages: readonly string[],
): Locale {
  if (mode !== 'auto') return mode
  if (hostLocale) return hostLocale
  for (const language of browserLanguages) {
    const locale = normalizeLocale(language)
    if (locale) return locale
  }
  return 'zh-CN'
}
