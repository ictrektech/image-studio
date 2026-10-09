import { Globe } from 'lucide-react'
import { Select, SelectContent, SelectItem, SelectSeparator, SelectTrigger } from '@/components/ui/select'
import { messages, setLanguageMode, useLanguage, type LanguageMode } from '@/i18n'

// 语言切换器：触发器显示当前语言（图标 + 语言名 + 箭头），
// 下拉 = 语言列表 + 分隔线 + 「跟随 VOS」。
// 样式与 header 其余按钮一致（outline、h-[34px]）；不用 flag emoji，
// Windows Chrome 不渲染国旗（会显示成 CN/TW 字母）。
const MODES: Exclude<LanguageMode, 'auto'>[] = ['zh-CN', 'zh-TW', 'en']

const nativeLabels: Record<Exclude<LanguageMode, 'auto'>, string> = {
  'zh-CN': '简体中文',
  'zh-TW': '繁體中文',
  en: 'English',
}

export function LocaleSwitcher() {
  const { mode, locale } = useLanguage()
  const t = messages[locale]
  const label = mode === 'auto' ? t.followVos : nativeLabels[mode]
  return (
    <Select value={mode} onValueChange={value => setLanguageMode(value as LanguageMode)}>
      <SelectTrigger
        className="h-[34px] w-[34px] shrink-0 justify-center rounded-md border border-input bg-transparent px-0 text-muted-foreground shadow-none transition-colors outline-none hover:bg-accent hover:text-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 [&>svg:last-of-type]:hidden"
        aria-label={t.languageSelect}
      >
        <Globe className="h-4 w-4 shrink-0" />
        <span className="sr-only">{label}</span>
      </SelectTrigger>
      <SelectContent position="popper" align="end">
        {MODES.map(value => (
          <SelectItem key={value} value={value}>
            {nativeLabels[value]}
          </SelectItem>
        ))}
        <SelectSeparator />
        <SelectItem value="auto">{t.followVos}</SelectItem>
      </SelectContent>
    </Select>
  )
}
