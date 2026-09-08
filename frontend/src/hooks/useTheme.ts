import { useCallback, useEffect, useState } from 'react'

export type Theme = 'light' | 'dark' | 'auto'

const STORAGE_KEY = 'image-studio-theme'

function systemPrefersDark() {
  return window.matchMedia('(prefers-color-scheme: dark)').matches
}

function applyTheme(theme: Theme) {
  const dark = theme === 'dark' || (theme === 'auto' && systemPrefersDark())
  document.documentElement.classList.toggle('dark', dark)
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(() => {
    const saved = localStorage.getItem(STORAGE_KEY)
    return saved === 'light' || saved === 'dark' || saved === 'auto' ? saved : 'auto'
  })

  useEffect(() => {
    applyTheme(theme)
    localStorage.setItem(STORAGE_KEY, theme)
  }, [theme])

  useEffect(() => {
    if (theme !== 'auto') return
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => applyTheme('auto')
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [theme])

  const cycleTheme = useCallback(() => {
    setTheme(prev => (prev === 'light' ? 'dark' : prev === 'dark' ? 'auto' : 'light'))
  }, [])

  return { theme, cycleTheme }
}
