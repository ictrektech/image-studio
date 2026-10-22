import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { AlertTriangle, Check, ChevronDown, CloudUpload, Database, Download, DownloadCloud, ImageIcon, Pencil, Play, Plus, RefreshCw, RotateCcw, Sparkles, Square, Trash2, UserCircle2, Wand2, X } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from 'cn'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Progress } from '@/components/ui/progress'
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@/components/ui/resizable'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectSeparator, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Spinner } from '@/components/ui/spinner'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { Textarea } from '@/components/ui/textarea'
import { useIsMobile } from '@/hooks/use-mobile'
import { CheckRow, Field, FieldRow, IgnoredTag } from '@/components/app/field'
import { Panel, PanelHeading, PanelTitle } from '@/components/app/panel'
import { StatusBadge } from '@/components/app/status-badge'
import { useConfirm } from '@/components/app/confirm'
import { api, GeneratePayload, InputItem, JobRecord, ModelInfo, SessionInfo, TemplateInfo } from '../api/client'
import { openInPhotoCraft, photoCraftUrl } from '../api/photoCraft'
import { messages } from '../i18n'
import { hasFailedUpload, hasPendingUploads, ImmichUploadStatus, useImmichUploads } from '../immichUploads'

function formatSize(bytes?: number) {
  if (!bytes) return '-'
  const units = ['B', 'KB', 'MB', 'GB']
  let value = bytes
  let idx = 0
  while (value >= 1024 && idx < units.length - 1) {
    value /= 1024
    idx += 1
  }
  return `${value.toFixed(idx === 0 ? 0 : 2)} ${units[idx]}`
}

function modelSize(model?: ModelInfo) {
  if (!model) return undefined
  return model.size || model.total_bytes || model.downloaded_bytes || undefined
}

const isVideoFile = (name: string) => /\.(mp4|webm|mov)$/i.test(name)
const samplerOptions = ['euler_a', 'euler', 'heun', 'dpm2', 'dpm++2s_a', 'dpm++2m', 'dpm++2mv2', 'ipndm', 'ipndm_v', 'lcm', 'ddim_trailing', 'tcd', 'res_multistep', 'res_2s', 'er_sde', 'euler_cfg_pp', 'euler_a_cfg_pp', 'euler_ge', 'dpm++2m_sde', 'dpm++2m_sde_bt', 'lms']
const schedulerOptions = ['', 'discrete', 'karras', 'exponential', 'ays', 'gits', 'sgm_uniform', 'simple', 'smoothstep', 'kl_optimal', 'lcm', 'bong_tangent', 'ltx2', 'logit_normal', 'flux2', 'flux', 'beta']
const rngOptions = ['', 'cuda', 'cpu', 'std_default']
const predictionOptions = ['', 'eps', 'v', 'edm_v', 'sd3_flow', 'flux_flow', 'sefi_flow']
const weightTypeOptions = ['', 'f32', 'f16', 'q4_0', 'q4_1', 'q5_0', 'q5_1', 'q8_0', 'q2_K', 'q3_K', 'q4_K']
const cacheOptions = ['', 'easycache', 'ucache', 'dbcache', 'taylorseer', 'cache-dit', 'spectrum']

// Radix Select 不允许空字符串 value，用哨兵表示「模型默认」。
const EMPTY_OPTION = '__empty__'

function ParamInput({ label, className, ...props }: React.ComponentProps<typeof Input> & { label: ReactNode }) {
  return (
    <Field label={label}>
      <Input className={cn('h-9', className)} {...props} />
    </Field>
  )
}

function ParamSelect({ label, value, onValueChange, options, emptyLabel, disabled }: {
  label: ReactNode
  value: string
  onValueChange: (value: string) => void
  options: string[]
  emptyLabel?: string
  disabled?: boolean
}) {
  return (
    <Field label={label}>
      <Select value={value || EMPTY_OPTION} onValueChange={next => onValueChange(next === EMPTY_OPTION ? '' : next)} disabled={disabled}>
        <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
        <SelectContent position="popper" className="max-h-72">
          {emptyLabel !== undefined && <SelectItem value={EMPTY_OPTION}>{emptyLabel}</SelectItem>}
          {options.map(option => <SelectItem key={option} value={option}>{option}</SelectItem>)}
        </SelectContent>
      </Select>
    </Field>
  )
}

function ParamChecks({ label, checked, onCheckedChange, disabled }: {
  label: ReactNode
  checked: boolean
  onCheckedChange: (checked: boolean) => void
  disabled?: boolean
}) {
  return (
    <CheckRow className={disabled ? 'opacity-55' : ''}>
      <Checkbox checked={checked} onCheckedChange={next => onCheckedChange(next === true)} disabled={disabled} />
      <span>{label}</span>
    </CheckRow>
  )
}

// 参数折叠区：替代原 <details class="parameter-section">。
function ParamSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Collapsible className="mt-3 overflow-hidden rounded-lg border bg-card">
      <CollapsibleTrigger className="group flex min-h-[42px] w-full items-center justify-between gap-2.5 px-2.5 text-xs font-bold text-foreground hover:bg-secondary focus-visible:outline-2 focus-visible:outline-ring data-[state=open]:border-b data-[state=open]:border-border data-[state=open]:bg-secondary">
        <span>{title}</span>
        <ChevronDown size={16} aria-hidden="true" className="shrink-0 text-muted-foreground transition-transform group-data-[state=open]:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="px-2.5 pb-3">{children}</div>
      </CollapsibleContent>
    </Collapsible>
  )
}

const initialPayload: GeneratePayload = {
  prompt: 'a cozy mountain cabin at dusk, warm lights, snowy pine trees, cinematic lighting, ultra detailed',
  negative_prompt: 'blurry, low quality, watermark, text, deformed',
  // 默认模型与参数对齐 NX 实测结论（results/nx_model_report.md）：turbo 512/4步/tiling 约 10s 出图
  model_key: 'sd-turbo',
  model_variant: '',
  init_job_id: '',
  init_filename: '',
  init_input_id: '',
  width: 512,
  height: 512,
  steps: 4,
  cfg_scale: 1,
  strength: 0.75,
  sampler: 'euler_a',
  seed: -1,
  batch_count: 1,
  scheduler: '',
  clip_skip: -1,
  guidance: 0,
  img_cfg_scale: 0,
  eta: 0,
  flow_shift: 0,
  high_noise_steps: 0,
  high_noise_cfg_scale: 0,
  high_noise_sampler: '',
  slg_scale: 0,
  skip_layer_start: 0.01,
  skip_layer_end: 0.2,
  rng: '',
  sampler_rng: '',
  prediction: '',
  weight_type: '',
  tensor_type_rules: '',
  cache_mode: '',
  cache_option: '',
  qwen_image_layers: 0,
  hires: false,
  hires_scale: 2,
  hires_width: 0,
  hires_height: 0,
  hires_steps: 0,
  hires_denoising_strength: 0.7,
  video_frames: 33,
  fps: 24,
  vae_tiling: true,
  vae_tile_size: '128x128',
  vae_tile_overlap: 0.5,
  temporal_tiling: true,
  temporal_tile_frames: 4,
  temporal_tile_overlap: 1,
  max_vram: 0,
  stream_layers: false,
  auto_fit: false,
  clip_on_cpu: false,
  offload_to_cpu: false,
  vae_cpu_fallback: false,
  backend: '',
  params_backend: '',
}

const SELECTED_MODEL_STORAGE_KEY = 'image-studio.generate.selected-model'
const MODEL_PAYLOAD_STORAGE_PREFIX = 'image-studio.generate.payload.'

const modelEntryKey = (key: string, variantId = '') => `${key}::${variantId || ''}`
const payloadStorageKey = (key: string, variantId = '') => `${MODEL_PAYLOAD_STORAGE_PREFIX}${modelEntryKey(key, variantId)}`

function readStoredPayload(key: string, variantId = ''): GeneratePayload | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(payloadStorageKey(key, variantId))
    if (!raw) return null
    return { ...initialPayload, ...JSON.parse(raw), model_key: key, model_variant: variantId }
  } catch {
    return null
  }
}

function readInitialPayload(): GeneratePayload {
  if (typeof window === 'undefined') return initialPayload
  const selected = window.localStorage.getItem(SELECTED_MODEL_STORAGE_KEY) || modelEntryKey(initialPayload.model_key, initialPayload.model_variant)
  const [key, variantId = ''] = selected.split('::')
  return readStoredPayload(key, variantId) || { ...initialPayload, model_key: key || initialPayload.model_key, model_variant: variantId }
}

export default function GeneratePage({ models, onRefresh, onOpenModels, t }: { models: ModelInfo[]; onRefresh: () => void; onOpenModels: () => void; t: typeof messages['zh-CN'] }) {
  const [payload, setPayload] = useState<GeneratePayload>(readInitialPayload)
  const hadStoredPayload = useRef(Boolean(readStoredPayload(payload.model_key, payload.model_variant)))
  const initializedDefaults = useRef(false)
  const [jobs, setJobs] = useState<JobRecord[]>([])
  const [inputs, setInputs] = useState<InputItem[]>([])
  const [session, setSession] = useState<SessionInfo | null>(null)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [templates, setTemplates] = useState<TemplateInfo[]>([])
  const [defaultTplId, setDefaultTplId] = useState('')
  const [tplName, setTplName] = useState('')
  const [tplDialog, setTplDialog] = useState<{ mode: 'create' } | { mode: 'rename'; tpl: TemplateInfo } | null>(null)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [qsOpen, setQsOpen] = useState(true)
  const [negOpen, setNegOpen] = useState(false)
  const [playingUrl, setPlayingUrl] = useState('')
  const messagesRef = useRef<HTMLDivElement | null>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const { confirm, confirmElement } = useConfirm(t)
  const isMobile = useIsMobile()

  const ig = (label: string, ignored: boolean): ReactNode =>
    ignored ? <>{label}<IgnoredTag>{t.paramIgnoredTag}</IgnoredTag></> : label

  const imageModels = useMemo(() => models
    .filter(model => model.capabilities.includes('txt2img') || model.capabilities.includes('img2img') || model.capabilities.includes('video'))
    .flatMap(model => [
      ...(model.variants || []).map(variant => ({ base: model, active: variant, variantId: variant.id || '', label: `${model.name} · ${variant.name}${variant.params ? ` (${variant.params})` : ''}` })),
      { base: model, active: model, variantId: '', label: `${model.name}${model.params ? ` (${model.params})` : ''}` },
    ]), [models])
  const localImageModels = imageModels.filter(entry => entry.active.source !== 'v-router')
  const remoteImageModels = imageModels.filter(entry => entry.active.source === 'v-router')
  const selectedModel = models.find(model => model.key === payload.model_key)
  const selectedVariant = selectedModel?.variants?.find(variant => variant.id === payload.model_variant)
  const activeModel = selectedVariant || selectedModel
  const modelReady = activeModel?.status === 'ready'
  const isVideoModel = activeModel?.runtime?.mode === 'video'
  const supportedParams = activeModel?.runtime?.parameters || {}
  const supportsParam = (name: string, fallback = true) => supportedParams[name] ?? fallback
  const modelUsable = Boolean(activeModel?.capabilities.includes('txt2img') || activeModel?.capabilities.includes('img2img')) || isVideoModel
  const supportsInit = supportsParam('reference_image', !isVideoModel)
  const isEditModel = activeModel?.runtime?.ref_flag === '-r'
  const supportsStrength = supportsParam('strength', !isEditModel && !isVideoModel)
  const negativeIgnored = !supportsParam('negative_prompt', activeModel?.runtime?.negative !== false)
  const hasRunning = jobs.some(job => job.status === 'queued' || job.status === 'running')
  // 上传由后端 worker 异步完成，生成早已结束，必须单独驱动轮询，否则状态会一直停在「上传中」。
  const pendingUploads = hasPendingUploads(jobs)
  const isImg2Img = Boolean((payload.init_job_id && payload.init_filename) || payload.init_input_id)
  const videoDuration = payload.fps > 0 && payload.video_frames > 0 ? (payload.video_frames / payload.fps).toFixed(1) : ''
  const initPreviewUrl = payload.init_input_id
    ? api.inputUrl(payload.init_input_id)
    : payload.init_job_id && payload.init_filename
      ? api.outputUrl(payload.init_job_id, payload.init_filename)
      : ''

  const modelVariantName = (key: string, variantId?: string) => {
    const model = models.find(m => m.key === key)
    if (!variantId) return model?.name || key
    const variant = model?.variants?.find(item => item.id === variantId)
    return variant ? `${model?.name || key} · ${variant.name}` : model?.name || key
  }

  const applyRuntimeDefaults = (base: GeneratePayload, model: ModelInfo | undefined, nextVideoModel: boolean): GeneratePayload => {
    const defaults = model?.runtime?.defaults || {}
    return {
      ...base,
      width: defaults.width ?? base.width,
      height: defaults.height ?? base.height,
      steps: defaults.steps ?? base.steps,
      cfg_scale: defaults.cfg_scale ?? base.cfg_scale,
      sampler: defaults.sampler ?? base.sampler,
      scheduler: defaults.scheduler ?? '',
      clip_skip: defaults.clip_skip ?? -1,
      guidance: defaults.guidance ?? 0,
      img_cfg_scale: defaults.img_cfg_scale ?? 0,
      eta: defaults.eta ?? 0,
      flow_shift: defaults.flow_shift ?? 0,
      high_noise_steps: defaults.high_noise_steps ?? 0,
      high_noise_cfg_scale: defaults.high_noise_cfg_scale ?? 0,
      high_noise_sampler: defaults.high_noise_sampler ?? '',
      slg_scale: defaults.slg_scale ?? 0,
      skip_layer_start: defaults.skip_layer_start ?? 0.01,
      skip_layer_end: defaults.skip_layer_end ?? 0.2,
      rng: defaults.rng ?? '',
      sampler_rng: defaults.sampler_rng ?? '',
      prediction: defaults.prediction ?? '',
      weight_type: defaults.weight_type ?? '',
      tensor_type_rules: defaults.tensor_type_rules ?? '',
      cache_mode: defaults.cache_mode ?? '',
      cache_option: defaults.cache_option ?? '',
      qwen_image_layers: defaults.qwen_image_layers ?? 0,
      hires: defaults.hires ?? false,
      hires_scale: defaults.hires_scale ?? 2,
      hires_width: defaults.hires_width ?? 0,
      hires_height: defaults.hires_height ?? 0,
      hires_steps: defaults.hires_steps ?? 0,
      hires_denoising_strength: defaults.hires_denoising_strength ?? 0.7,
      video_frames: defaults.video_frames ?? base.video_frames,
      fps: defaults.fps ?? base.fps,
      vae_tiling: defaults.vae_tiling ?? nextVideoModel,
      vae_tile_size: defaults.vae_tile_size ?? '',
      vae_tile_overlap: defaults.vae_tile_overlap ?? 0.5,
      temporal_tiling: defaults.temporal_tiling ?? model?.runtime?.parameters?.temporal_tiling ?? false,
      temporal_tile_frames: defaults.temporal_tile_frames ?? 4,
      temporal_tile_overlap: defaults.temporal_tile_overlap ?? 1,
      max_vram: defaults.max_vram ?? (nextVideoModel ? -2 : 0),
      stream_layers: defaults.stream_layers ?? nextVideoModel,
      auto_fit: defaults.auto_fit ?? false,
      clip_on_cpu: defaults.clip_on_cpu ?? false,
      offload_to_cpu: defaults.offload_to_cpu ?? false,
      vae_cpu_fallback: defaults.vae_cpu_fallback ?? nextVideoModel,
      backend: defaults.backend ?? '',
      params_backend: defaults.params_backend ?? '',
      batch_count: nextVideoModel ? 1 : base.batch_count,
    }
  }

  useEffect(() => {
    if (initializedDefaults.current || !activeModel) return
    initializedDefaults.current = true
    setPayload(current => {
      if (!hadStoredPayload.current) return applyRuntimeDefaults(current, activeModel, isVideoModel)
      const defaults = activeModel.runtime?.defaults || {}
      // Repair only the old generic SD-Turbo preset cached on an L4T device.
      // Keep prompts, dimensions and other saved/custom runtime settings.
      if (current.model_key === 'sd-turbo' && !current.model_variant && defaults.weight_type === 'q4_0'
        && defaults.max_vram === 2 && ['', 'f16'].includes(current.weight_type || '')
        && current.max_vram === 0 && current.vae_tile_size === '128x128') {
        return { ...current, weight_type: defaults.weight_type, max_vram: defaults.max_vram, vae_tile_size: defaults.vae_tile_size ?? '' }
      }
      return current
    })
  }, [activeModel, isVideoModel])

  useEffect(() => {
    if (typeof window === 'undefined') return
    try {
      window.localStorage.setItem(SELECTED_MODEL_STORAGE_KEY, modelEntryKey(payload.model_key, payload.model_variant))
      window.localStorage.setItem(payloadStorageKey(payload.model_key, payload.model_variant), JSON.stringify(payload))
    } catch {
      // Ignore quota or privacy-mode storage failures; the generator still works.
    }
  }, [payload])

  useEffect(() => {
    if (!imageModels.length) return
    if (imageModels.some(entry => entry.base.key === payload.model_key && entry.variantId === payload.model_variant)) return
    const first = imageModels[0]
    setPayload(applyRuntimeDefaults({ ...payload, model_key: first.base.key, model_variant: first.variantId }, first.active, first.active.runtime?.mode === 'video'))
  }, [imageModels, payload])

  const applyTemplate = (tpl: TemplateInfo) => {
    const key = tpl.payload.model_key || payload.model_key
    const variant = tpl.payload.model_variant || ''
    const entry = imageModels.find(e => e.base.key === key && e.variantId === variant)
    setPayload(applyRuntimeDefaults({ ...payload, ...tpl.payload, model_key: key, model_variant: variant }, entry?.active, entry?.active?.runtime?.mode === 'video'))
  }

  useEffect(() => {
    api.listTemplates().then(data => {
      setTemplates(data.templates)
      setDefaultTplId(data.default_template || '')
      // 首次使用（无本地选择记录）时应用平台默认模板
      const pristine = !localStorage.getItem(SELECTED_MODEL_STORAGE_KEY)
      const tpl = data.default_template ? data.templates.find(item => item.id === data.default_template) : null
      if (pristine && tpl) applyTemplate(tpl)
    }).catch(() => { /* 模板加载失败不阻塞主流程 */ })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const confirmTplDialog = async () => {
    const name = tplName.trim()
    if (!name || !tplDialog) return
    try {
      if (tplDialog.mode === 'rename') {
        const renamed = await api.renameTemplate(tplDialog.tpl.id, name)
        setTemplates(ts => ts.map(x => (x.id === renamed.id ? renamed : x)))
      } else {
        const entry = await api.saveTemplate(name, payload)
        setTemplates(ts => [entry, ...ts.filter(t => t.name !== entry.name)])
      }
      setTplDialog(null)
    } catch {
      toast.error(t.templateSaveFailed)
    }
  }

  const removeTemplate = async (tpl: TemplateInfo) => {
    if (!(await confirm(`${t.templateDeleteTitle}: ${tpl.name}?`))) return
    try {
      await api.deleteTemplate(tpl.id)
      setTemplates(ts => ts.filter(t => t.id !== tpl.id))
    } catch { /* 删除失败保持原列表 */ }
  }

  const switchModelEntry = (value: string) => {
    const [key, variantId = ''] = value.split('::')
    const base = models.find(model => model.key === key)
    const next = variantId ? base?.variants?.find(variant => variant.id === variantId) : base
    const nextVideoModel = next?.runtime?.mode === 'video'
    const stored = readStoredPayload(key, variantId)
    if (stored) {
      setPayload(stored)
      return
    }
    setPayload(applyRuntimeDefaults({
      ...payload,
      model_key: key,
      model_variant: variantId,
    }, next, Boolean(nextVideoModel)))
  }

  const resetCurrentModelDefaults = () => {
    setPayload(applyRuntimeDefaults({
      ...initialPayload,
      prompt: payload.prompt,
      negative_prompt: payload.negative_prompt,
      model_key: payload.model_key,
      model_variant: payload.model_variant,
      init_job_id: payload.init_job_id,
      init_filename: payload.init_filename,
      init_input_id: payload.init_input_id,
    }, activeModel, isVideoModel))
  }

  const loadJobs = async () => {
    const data = await api.listJobs()
    setJobs(data)
  }

  const loadInputs = () => api.listInputs().then(setInputs).catch(() => undefined)

  useEffect(() => {
    loadJobs().catch(() => undefined)
    loadInputs()
  }, [])

  useEffect(() => {
    api.me().then(setSession).catch(() => undefined)
  }, [])

  // 新消息到达时贴底（Radix ScrollArea 的滚动发生在 viewport 元素上）
  useEffect(() => {
    const viewport = messagesRef.current?.querySelector('[data-radix-scroll-area-viewport]')
    if (viewport) viewport.scrollTop = viewport.scrollHeight
  }, [jobs])

  const roundOf = useMemo(() => {
    const map = new Map<string, number>()
    jobs.forEach((job, index) => map.set(job.job_id, jobs.length - index))
    return map
  }, [jobs])

  const timeOf = (iso: string) => {
    try {
      return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    } catch {
      return ''
    }
  }

  const lineageOf = (job: JobRecord) => {
    if (job.metadata?.init_input_id) return t.uploadedImage
    const parent = job.metadata?.init_job_id
    if (!parent || !roundOf.has(parent)) return ''
    return `${t.basedOnRound} ${roundOf.get(parent)} ${t.turnWord}`
  }

  useEffect(() => {
    if (!hasRunning && !pendingUploads) return
    const timer = window.setInterval(() => loadJobs().catch(() => undefined), 2500)
    return () => window.clearInterval(timer)
  }, [hasRunning, pendingUploads])

  const submit = async () => {
    setSubmitting(true)
    setError('')
    try {
      await api.generate(payload)
      await loadJobs()
    } catch (e: any) {
      setError(e.message || t.submitFailed)
    } finally {
      setSubmitting(false)
    }
  }

  const reuseOutput = (job: JobRecord, output: string) => {
    setPayload({
      ...payload,
      init_job_id: job.job_id,
      init_filename: output,
      init_input_id: '',
      width: job.width,
      height: job.height,
    })
    setPickerOpen(false)
  }

  const reuseInput = (inputId: string) => {
    setPayload({ ...payload, init_job_id: '', init_filename: '', init_input_id: inputId })
    setPickerOpen(false)
  }

  const clearSourceImage = () => {
    setPayload({ ...payload, init_job_id: '', init_filename: '', init_input_id: '' })
  }

  const uploadFile = async (file: File) => {
    setUploading(true)
    setError('')
    try {
      const item = await api.uploadInput(file)
      setPayload({ ...payload, init_job_id: '', init_filename: '', init_input_id: item.input_id })
      await loadInputs()
      setPickerOpen(false)
    } catch (e: any) {
      setError(e.message || t.uploadFailed)
    } finally {
      setUploading(false)
    }
  }

  const downloadModel = async () => {
    if (!selectedModel || activeModel?.status === 'downloading') return
    try {
      await api.pullModel(selectedModel.key, false, payload.model_variant)
      onRefresh()
    } catch { /* 模型管理页有完整反馈，这里静默刷新即可 */ }
  }

  const stopModelDownload = async () => {
    if (!selectedModel || activeModel?.status !== 'downloading') return
    try {
      await api.stopModel(selectedModel.key, payload.model_variant)
      onRefresh()
    } catch { /* 同上 */ }
  }

  const modelDownloading = activeModel?.status === 'downloading'
  const modelProgress = modelDownloading ? Math.round((activeModel?.progress ?? 0) * 100) : 0

  const { upload: uploadJob, retry: retryImmich } = useImmichUploads(t, loadJobs, confirm)

  const deleteJob = async (job: JobRecord) => {
    const hasVideoOutput = job.outputs.some(isVideoFile)
    if (!(await confirm(hasVideoOutput ? t.confirmDeleteVideo : t.confirmDelete))) return
    await api.deleteJob(job.job_id)
    await loadJobs()
  }

  const sortedJobs = useMemo(() => [...jobs].reverse(), [jobs])

  const dotColor = modelReady
    ? { dot: 'bg-emerald-500', halo: 'bg-emerald-100' }
    : modelDownloading
      ? { dot: 'bg-sky-500', halo: 'bg-sky-100' }
      : { dot: 'bg-red-500', halo: 'bg-red-100' }

  return (
    <div className="flex h-full min-h-0 flex-col gap-2.5 overflow-y-auto p-2.5 md:px-3">
      {confirmElement}
      <Panel className="px-3 py-2">
        <Collapsible open={qsOpen} onOpenChange={setQsOpen}>
        <div className="flex min-h-7 flex-wrap items-center gap-x-2 gap-y-1">
          {templates.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            {templates.map(tpl => (
              <DropdownMenu key={tpl.id}>
                <DropdownMenuTrigger asChild>
                  <button
                    className={cn(
                      'inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs text-foreground transition-colors hover:border-indigo-300 hover:text-indigo-600',
                      tpl.id === defaultTplId ? 'border-indigo-500 bg-accent text-accent-foreground' : 'border-border bg-secondary',
                    )}
                    title={tpl.description || tpl.name}
                  >
                    {tpl.name}
                    <ChevronDown size={11} className="text-muted-foreground" />
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" className="min-w-36">
                  <DropdownMenuItem onClick={() => applyTemplate(tpl)}>
                    <Check size={14} />{t.templateApply}
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => { setTplName(tpl.name); setTplDialog({ mode: 'rename', tpl }) }}>
                    <Pencil size={14} />{t.templateRename}
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem className="text-destructive focus:text-destructive" onClick={() => removeTemplate(tpl)}>
                    <Trash2 size={14} />{t.templateDeleteTitle}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            ))}
            <button
              className="inline-flex items-center gap-1 rounded-full border border-dashed border-border bg-secondary px-2.5 py-1 text-xs text-foreground hover:border-indigo-300 hover:text-indigo-600"
              onClick={() => { setTplName(''); setTplDialog({ mode: 'create' }) }}
            >
              <Plus size={12} />{t.templateSave}
            </button>
          </div>
          )}
          <Dialog open={Boolean(tplDialog)} onOpenChange={open => !open && setTplDialog(null)}>
            <DialogContent className="w-[min(380px,100%)] gap-4 rounded-xl p-5 sm:max-w-[380px]">
              <DialogHeader>
                <DialogTitle className="text-base">{tplDialog?.mode === 'rename' ? t.templateRename : t.templateSave}</DialogTitle>
              </DialogHeader>
              <Input
                autoFocus
                value={tplName}
                placeholder={t.templateNameLabel}
                onChange={e => setTplName(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') confirmTplDialog() }}
              />
              <div className="flex justify-end gap-2">
                <Button variant="outline" size="sm" onClick={() => setTplDialog(null)}>{t.dialogCancel}</Button>
                <Button size="sm" disabled={!tplName.trim()} onClick={confirmTplDialog}>{t.dialogConfirm}</Button>
              </div>
            </DialogContent>
          </Dialog>
          <div className="ml-auto flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted-foreground">
            <span className={cn('rounded-full p-[3px]', dotColor.halo)}><span className={cn('block size-[7px] rounded-full', dotColor.dot)} /></span>
            <strong className="whitespace-nowrap text-[11px] text-foreground">{activeModel?.name || selectedModel?.name || t.noModelsConfigured}</strong>
            <span className="hidden sm:inline">{modelReady ? t.modelReady : modelDownloading ? `${t.modelDownloading} ${modelProgress}%` : modelUsable ? t.modelMissing : t.chooseModelHint}</span>
            {activeModel && <code className="min-w-0 truncate">{activeModel.source} · {activeModel.family} · {formatSize(modelSize(activeModel))}</code>}
            {!modelReady && activeModel && (
              <Button variant="ghost" size="xs" disabled={modelDownloading} onClick={downloadModel}>
                {modelDownloading ? <Spinner className="size-3.5" /> : <DownloadCloud size={13} />}
                {modelDownloading ? `${modelProgress}%` : t.downloadModel}
              </Button>
            )}
            {modelDownloading && <Button variant="ghost" size="xs" onClick={stopModelDownload}><Square size={13} />{t.stopDownload}</Button>}
            {(!modelReady || !modelUsable) && <Button variant="ghost" size="xs" onClick={onOpenModels}><Database size={13} />{t.openModelManagement}</Button>}
            <Button variant="ghost" size="icon" className="size-7" onClick={() => setQsOpen(v => !v)} title={t.modelPanelTitle}>
              <ChevronDown size={15} className={cn('transition-transform', qsOpen && 'rotate-180')} />
            </Button>
          </div>
        </div>
        <CollapsibleContent>
          <div className="mt-1.5 grid grid-cols-2 items-end gap-2 lg:[grid-template-columns:repeat(3,minmax(90px,1fr))] xl:[grid-template-columns:minmax(200px,1.5fr)_repeat(6,minmax(82px,0.8fr))_auto]">
          <Field label={t.modelPanelTitle} labelClassName="mb-0.5 text-[10px]">
            <Select value={`${payload.model_key}::${payload.model_variant}`} onValueChange={switchModelEntry}>
              <SelectTrigger className="h-8 w-full"><SelectValue /></SelectTrigger>
              <SelectContent position="popper" className="max-h-72">
                {remoteImageModels.length > 0 && (
                  <SelectGroup>
                    <SelectLabel>{t.vRouterCloudModels}</SelectLabel>
                    {remoteImageModels.map(entry => (
                      <SelectItem key={`${entry.base.key}:${entry.variantId || 'default'}`} value={`${entry.base.key}::${entry.variantId}`}>{entry.label} · {entry.active.params || entry.active.family}</SelectItem>
                    ))}
                  </SelectGroup>
                )}
                {remoteImageModels.length > 0 && <SelectSeparator />}
                <SelectGroup>
                  <SelectLabel>{t.localModels}</SelectLabel>
                  {localImageModels.map(entry => (
                    <SelectItem key={`${entry.base.key}:${entry.variantId || 'default'}`} value={`${entry.base.key}::${entry.variantId}`}>{entry.label} · {entry.active.family}</SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </Field>
          <Field label={t.width} labelClassName="mb-0.5 text-[10px]"><Input type="number" className="h-8 text-xs" value={payload.width} onChange={e => setPayload({ ...payload, width: Number(e.target.value) })} /></Field>
          <Field label={t.height} labelClassName="mb-0.5 text-[10px]"><Input type="number" className="h-8 text-xs" value={payload.height} onChange={e => setPayload({ ...payload, height: Number(e.target.value) })} /></Field>
          <Field label={t.steps} labelClassName="mb-0.5 text-[10px]"><Input type="number" className="h-8 text-xs" value={payload.steps} onChange={e => setPayload({ ...payload, steps: Number(e.target.value) })} /></Field>
          <Field label={ig(t.cfgScale, !supportsParam('cfg_scale'))} labelClassName="mb-0.5 text-[10px]"><Input type="number" step="0.5" className="h-8 text-xs" value={payload.cfg_scale} disabled={!supportsParam('cfg_scale')} onChange={e => setPayload({ ...payload, cfg_scale: Number(e.target.value) })} /></Field>
          <Field label={t.sampler} labelClassName="mb-0.5 text-[10px]">
            <Select value={payload.sampler} onValueChange={value => setPayload({ ...payload, sampler: value })}>
              <SelectTrigger className="h-8 w-full"><SelectValue /></SelectTrigger>
              <SelectContent position="popper" className="max-h-72">
                {samplerOptions.map(v => <SelectItem value={v} key={v}>{v}</SelectItem>)}
              </SelectContent>
            </Select>
          </Field>
          <Field label={t.seed} labelClassName="mb-0.5 text-[10px]"><Input type="number" title={t.randomSeedHint} className="h-8 text-xs" value={payload.seed} onChange={e => setPayload({ ...payload, seed: Number(e.target.value) })} /></Field>
          <div className="flex gap-1 max-lg:col-span-2">
            <Button variant="outline" size="icon" className="size-8" onClick={onRefresh} title={t.refreshModels}><RefreshCw size={15} /></Button>
            <Button variant="outline" size="icon" className="size-8" onClick={resetCurrentModelDefaults} title={t.resetModelDefaults}><RotateCcw size={15} /></Button>
          </div>
        </div>
        </CollapsibleContent>
        </Collapsible>
      </Panel>
      {jobs[0] && (jobs[0].status === 'queued' || jobs[0].status === 'running') && (
        <div className="flex flex-wrap items-center gap-2.5 rounded-lg border bg-card px-3 py-2 text-xs shadow-[0_6px_18px_rgba(15,23,42,0.035)]">
          <span className="whitespace-nowrap font-bold">{t.currentJob}</span>
          <StatusBadge status={jobs[0].status}>{jobs[0].status}</StatusBadge>
          <code className="truncate font-mono">{jobs[0].job_id}</code>
          <Progress max={1} value={jobs[0].progress} className="min-w-[120px] flex-1" />
          <span className="whitespace-nowrap font-bold text-accent-foreground">{Math.round(jobs[0].progress * 100)}%</span>
          <span className="max-w-[40%] truncate text-muted-foreground">{jobs[0].prompt.slice(0, 60)}{jobs[0].prompt.length > 60 ? '…' : ''}</span>
        </div>
      )}
      <ResizablePanelGroup orientation={isMobile ? 'vertical' as const : 'horizontal' as const} className="min-h-[420px] flex-1">
      {/* 左栏：聊天主窗口 */}
      <ResizablePanel defaultSize={isMobile ? 62 : 70} minSize={isMobile ? 35 : 48}>
      <Panel className="flex h-full min-h-0 flex-col overflow-hidden p-0">
        <div className="flex min-h-10 shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-b bg-secondary px-3 py-1.5">
          <PanelTitle className="text-sm">{t.chatTitle}</PanelTitle>
          <div className="flex min-w-0 items-center gap-1.5">
            <UserCircle2 size={15} className="shrink-0 text-muted-foreground" />
            {session && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <code className="max-w-[200px] truncate text-[11px] text-muted-foreground">{session.user_key}</code>
                </TooltipTrigger>
                <TooltipContent>{session.user_key}</TooltipContent>
              </Tooltip>
            )}
            {!session && <code className="text-[11px] text-muted-foreground">...</code>}
            {session && !session.authenticated && <span className="rounded-full bg-orange-100 px-1.5 py-px text-[10px] font-bold text-orange-900">{t.anonymousSession}</span>}
          </div>
          <span className="whitespace-nowrap text-[11px] text-muted-foreground max-lg:hidden">{jobs.length} {t.imageCount} · {t.sessionIsolationHint}</span>
          <Button variant="ghost" size="icon" className="ml-auto size-7 shrink-0" onClick={() => { loadJobs().catch(() => undefined); loadInputs() }} title={t.refreshModels}><RefreshCw size={14} /></Button>
        </div>

        <ScrollArea className="min-h-0 flex-1 bg-background" ref={messagesRef}>
          <div className="flex flex-col gap-3 p-3">
          {sortedJobs.length === 0 && (
            <Empty className="m-auto border-0 bg-transparent">
              <EmptyMedia variant="icon">
                <ImageIcon />
              </EmptyMedia>
              <EmptyHeader>
                <EmptyTitle>{t.chatTitle}</EmptyTitle>
                <EmptyDescription>{t.chatEmptyHint}</EmptyDescription>
              </EmptyHeader>
            </Empty>
          )}
          {sortedJobs.map(job => {
            const round = roundOf.get(job.job_id)
            const lineage = lineageOf(job)
            const initThumb = job.metadata?.init_input_id
              ? api.inputUrl(job.metadata.init_input_id)
              : job.metadata?.init_job_id && job.metadata?.init_filename
                ? api.outputUrl(job.metadata.init_job_id, job.metadata.init_filename)
                : ''
            return (
              <div className="flex flex-col gap-2" key={job.job_id}>
                <div className="flex justify-end">
                  <div className="max-w-[82%] rounded-xl border border-primary/25 bg-accent px-3 py-2.5 text-[13px] shadow-sm">
                    <div className="mb-1.5 flex flex-col gap-0.5">
                      <span className="text-[11px] text-muted-foreground">#{round} {t.meLabel} · {timeOf(job.created_at)}</span>
                      <span className="text-[11px] text-muted-foreground">{modelVariantName(job.model_key, job.model_variant)} · {job.width}×{job.height} · {job.steps} steps · cfg {job.cfg_scale} · {job.sampler}{job.seed >= 0 ? ` · seed ${job.seed}` : ''}{job.video_frames > 1 ? ` · ${job.video_frames}f${job.fps ? `@${job.fps}` : ''}` : ''}</span>
                      {lineage && <span className="text-[11px] text-muted-foreground">↳ {lineage}</span>}
                    </div>
                    {initThumb && <img className="mb-1.5 block max-h-[120px] max-w-[120px] rounded-lg border" src={initThumb} alt="" />}
                    <p className="m-0 whitespace-pre-wrap break-words leading-relaxed">{job.prompt}</p>
                    {job.negative_prompt && <p className="mt-1.5 whitespace-pre-wrap text-xs text-amber-700">− {job.negative_prompt}</p>}
                  </div>
                </div>
                <div className="flex justify-start">
                  <div className={cn(
                    'max-w-[82%] rounded-xl border bg-card px-3 py-2.5 text-[13px] shadow-sm',
                    job.status === 'failed' && 'border-red-300/60 bg-red-50',
                  )}>
                    <div className="mb-1.5 flex flex-col gap-0.5"><span className="text-[11px] text-muted-foreground">{modelVariantName(job.model_key, job.model_variant)}</span></div>
                    {job.status === 'succeeded' && job.outputs.map(output => {
                      const url = api.outputUrl(job.job_id, output)
                      if (isVideoFile(output)) {
                        return (
                          <div className="group relative max-w-[min(420px,100%)] cursor-pointer overflow-hidden rounded-lg border bg-[#0b1220]" key={output} onClick={() => setPlayingUrl(url)} title={t.videoPlayHint}>
                            <video className="block max-h-[280px] w-full object-contain" src={url} preload="metadata" muted />
                            <span className="absolute inset-0 flex items-center justify-center bg-slate-900/30 text-white transition-colors group-hover:bg-slate-900/10"><Play size={22} /></span>
                            <span className="pointer-events-none absolute left-1.5 top-1.5 rounded bg-slate-900/70 px-1.5 py-px text-[10px] text-white">{t.videoBadge}</span>
                          </div>
                        )
                      }
                      return <img className="mb-1.5 block max-w-[min(420px,100%)] cursor-pointer rounded-lg border hover:border-primary" key={output} src={url} alt={job.prompt} onClick={() => reuseOutput(job, output)} title={t.continueThread} />
                    })}
                    {(job.status === 'queued' || job.status === 'running') && (
                      <div className="flex items-center gap-2 text-xs text-muted-foreground">
                        <Spinner className="size-4" />
                        <span>{job.status} · {Math.round(job.progress * 100)}%</span>
                        <Progress max={1} value={job.progress} className="flex-1" />
                      </div>
                    )}
                    {job.status === 'failed' && (
                      <div className="flex items-start gap-2 text-red-700">
                        <AlertTriangle size={16} />
                        <code className="break-all text-xs leading-relaxed">{job.error || t.generationFailed}</code>
                      </div>
                    )}
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {job.outputs[0] && !isVideoFile(job.outputs[0]) && <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={() => reuseOutput(job, job.outputs[0])}><Wand2 size={14} />{t.continueThread}</Button>}
                      {job.outputs[0] && <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" asChild><a href={api.outputUrl(job.job_id, job.outputs[0])} download><Download size={14} />{t.downloadOutput}</a></Button>}
                      {job.outputs[0] && !isVideoFile(job.outputs[0]) && <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={() => {
                        const fallback = () => window.open(photoCraftUrl(job.job_id, job.outputs[0]), '_blank', 'noopener')
                        openInPhotoCraft(job.job_id, job.outputs[0], t.editInPhotoCraft).then(opened => { if (!opened) fallback() }).catch(fallback)
                      }}><Pencil size={14} />{t.editInPhotoCraft}</Button>}
                      {job.status === 'succeeded' && <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={() => uploadJob(job)}><CloudUpload size={14} />{t.immichUpload}</Button>}
                      {hasFailedUpload(job) && <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={() => retryImmich(job)}><RotateCcw size={14} />{t.immichRetry}</Button>}
                      <Button variant="ghost" size="sm" className="h-7 px-2 text-xs text-destructive hover:text-destructive" onClick={() => deleteJob(job)}><Trash2 size={14} />{job.outputs.some(isVideoFile) ? t.deleteVideoOutput : t.deleteOutput}</Button>
                    </div>
                    <ImmichUploadStatus job={job} t={t} />
                  </div>
                </div>
              </div>
            )
          })}
          </div>
        </ScrollArea>

        <Popover open={pickerOpen} onOpenChange={setPickerOpen}>
        <div className="relative border-t bg-card px-3 py-2.5">
          {supportsInit && (
            <input
              ref={fileInputRef}
              type="file"
              accept=".png,.jpg,.jpeg,.webp"
              hidden
              onChange={e => {
                const file = e.target.files?.[0]
                if (file) uploadFile(file)
                e.target.value = ''
              }}
            />
          )}
          {isVideoModel && !supportsInit && (
            <p className="pb-1.5 text-[11px] text-muted-foreground">{t.videoNoRefHint}</p>
          )}
          {error && (
            <Alert variant="destructive" className="mb-2 max-h-[60px] overflow-y-auto border-red-200 bg-red-50 py-2 text-xs">
              <AlertTriangle />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <div className="rounded-xl border bg-card focus-within:border-ring">
            {supportsInit && initPreviewUrl && (
              <div className="relative mx-2.5 mt-2.5 inline-flex">
                <img src={initPreviewUrl} alt="" className="size-16 rounded-lg border object-cover" />
                <button className="absolute -right-1.5 -top-1.5 flex size-5 items-center justify-center rounded-full bg-slate-900/55 text-white" onClick={clearSourceImage} title={t.clearImage}><X size={12} /></button>
                <span className="absolute -bottom-1.5 left-1 rounded bg-slate-900/55 px-1 text-[9px] text-white">
                  {payload.init_input_id ? t.uploadedImage : `${t.basedOnRound} ${roundOf.get(payload.init_job_id) ?? ''} ${t.turnWord}`}
                </span>
              </div>
            )}
            <div className="px-3 pt-2.5">
              <label className="mb-1 block text-[11px] font-medium text-muted-foreground">{t.positivePrompt}</label>
              <Textarea
                value={payload.prompt}
                onChange={e => setPayload({ ...payload, prompt: e.target.value })}
                onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submit() }}
                placeholder={t.positivePrompt}
                className="max-h-40 min-h-[44px] resize-none border-0 bg-transparent px-0 pt-0 shadow-none focus-visible:ring-0"
                rows={2}
              />
            </div>
            <Collapsible open={negOpen} onOpenChange={setNegOpen}>
              <CollapsibleContent>
                <div className="border-t px-3 pt-2">
                  <label className="mb-1 block text-[11px] font-medium text-muted-foreground">{ig(t.negativePrompt, negativeIgnored)}</label>
                  <Textarea
                    value={payload.negative_prompt}
                    onChange={e => setPayload({ ...payload, negative_prompt: e.target.value })}
                    disabled={negativeIgnored}
                    placeholder={negativeIgnored ? t.negativeIgnoredHint : ''}
                    className="min-h-[44px] max-h-[160px] resize-none rounded-none border-0 bg-transparent px-0 pt-0 text-xs shadow-none focus-visible:ring-0"
                    rows={2}
                  />
                </div>
              </CollapsibleContent>
              <div className="flex flex-wrap items-center gap-1 px-2.5 pb-2.5">
                {supportsInit && (
                  <>
                    <Button variant="ghost" size="sm" className="h-7 px-2 text-[11px] text-muted-foreground" onClick={() => fileInputRef.current?.click()} disabled={uploading}>
                      {uploading ? <Spinner className="size-3.5" /> : <DownloadCloud size={13} className="rotate-180" />}{t.uploadImage}
                    </Button>
                    <PopoverTrigger asChild>
                      <Button variant="ghost" size="sm" className="h-7 px-2 text-[11px] text-muted-foreground"><Wand2 size={13} />{t.pickFromHistory}</Button>
                    </PopoverTrigger>
                  </>
                )}
                <CollapsibleTrigger asChild>
                  <Button variant="ghost" size="sm" className={cn('h-7 gap-1 px-2 text-[11px] text-muted-foreground', negativeIgnored && 'opacity-55', !negOpen && payload.negative_prompt && 'text-warning')}>
                    {ig(t.negativePrompt, negativeIgnored)}
                    <ChevronDown size={12} className={cn('transition-transform', negOpen && 'rotate-180')} />
                  </Button>
                </CollapsibleTrigger>
                <Button
                  className="ml-auto h-8 text-xs shadow-[0_8px_20px_rgba(7,137,154,0.18)]"
                  disabled={submitting || !modelReady || !modelUsable}
                  onClick={submit}
                >
                  {submitting ? <Spinner className="size-4" /> : <Sparkles size={15} />}{submitting ? t.submitting : isVideoModel ? t.submitVideo : t.submit}
                </Button>
              </div>
            </Collapsible>
          </div>

          <PopoverContent
            onOpenAutoFocus={e => e.preventDefault()}
            side="top"
            align="start"
            className="max-h-[260px] w-[min(560px,calc(100vw-3rem))] overflow-y-auto p-3.5"
          >
            <div className="mb-1.5 flex items-center justify-between">
              <strong className="text-[13px]">{t.pickSourceTitle}</strong>
              <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={() => setPickerOpen(false)}><X size={14} />{t.closePicker}</Button>
            </div>
            <div className="mb-1.5 mt-2 text-[11px] font-bold text-muted-foreground">{t.recentOutputs}</div>
            <div className="grid gap-2 [grid-template-columns:repeat(auto-fill,minmax(78px,1fr))]">
              {jobs.slice(0, 10).flatMap(job => job.outputs.filter(o => !isVideoFile(o)).map(output => (
                <button key={job.job_id + output} className="flex flex-col items-center gap-1 rounded-lg border bg-secondary p-1 text-[10px] text-muted-foreground hover:border-primary" onClick={() => reuseOutput(job, output)}>
                  <img className="h-[62px] w-full rounded object-cover" src={api.outputUrl(job.job_id, output)} alt="" />
                  <span>#{roundOf.get(job.job_id)}</span>
                </button>
              )))}
            </div>
            <div className="mb-1.5 mt-2 text-[11px] font-bold text-muted-foreground">{t.uploadedImages}</div>
            <div className="grid gap-2 [grid-template-columns:repeat(auto-fill,minmax(78px,1fr))]">
              {inputs.map(item => (
                <button key={item.input_id} className="flex flex-col items-center gap-1 rounded-lg border bg-secondary p-1 text-[10px] text-muted-foreground hover:border-primary" onClick={() => reuseInput(item.input_id)}>
                  <img className="h-[62px] w-full rounded object-cover" src={api.inputUrl(item.input_id)} alt="" />
                  <span>{formatSize(item.size)}</span>
                </button>
              ))}
              <button className="flex flex-col items-center gap-1 rounded-lg border bg-secondary p-1 text-[10px] text-muted-foreground hover:border-primary" onClick={() => fileInputRef.current?.click()} disabled={uploading}>
                {uploading ? <Spinner className="size-4" /> : <DownloadCloud size={18} className="rotate-180" />}
                <span className="text-primary">{t.uploadImage}</span>
              </button>
            </div>
          </PopoverContent>
        </div>
        </Popover>
      </Panel>
      </ResizablePanel>

      <ResizableHandle withHandle />

      {/* 右栏：任务参数检查器 */}
      <ResizablePanel defaultSize={isMobile ? 38 : 28} minSize={isMobile ? 22 : 16}>
      <Panel className="h-full min-h-0">
        <div className="px-3 pt-2.5">
          <PanelHeading className="mb-2">
            <PanelTitle>{isVideoModel ? t.baseParamsTitle : t.imageParamsTitle}</PanelTitle>
          </PanelHeading>
        </div>
        <ScrollArea className="min-h-0 flex-1">
          <div className="px-3 pb-3 pt-1">
        <div className={cn(
          'rounded-lg p-2.5 text-[11px] text-muted-foreground',
          isImg2Img ? 'bg-green-50 text-green-900' : 'bg-secondary',
        )}>
          <strong className="mb-0.5 block text-xs">{isVideoModel ? (isImg2Img ? t.img2Video : t.text2Video) : isImg2Img ? (isEditModel ? t.imageEdit : t.imageToImage) : t.textToImage}</strong>
          <span className="block">{isVideoModel ? t.videoModelHint : isImg2Img ? (isEditModel ? t.imageEditHint : t.sourceImageHint) : t.previewHint}</span>
          {isImg2Img && <code className="mt-1.5 block break-all rounded border bg-secondary px-1.5 py-1 font-mono">{payload.init_input_id || `${payload.init_job_id}/${payload.init_filename}`}</code>}
        </div>
        <FieldRow className="mt-2.5 sm:grid-cols-2">
          <ParamInput label={ig(t.strength, !(isImg2Img && supportsStrength))} type="number" min={0} max={1} step={0.05} value={payload.strength} disabled={!(isImg2Img && supportsStrength)} onChange={e => setPayload({ ...payload, strength: Number(e.target.value) })} />
          <ParamInput label={ig(t.batch, isVideoModel)} type="number" min={1} max={4} value={payload.batch_count} disabled={!supportsParam('batch_count')} onChange={e => setPayload({ ...payload, batch_count: Number(e.target.value) })} />
        </FieldRow>
        {isVideoModel && (
          <ParamSection title={t.videoParamsTitle}>
            <FieldRow className="sm:grid-cols-2">
              <ParamInput label={t.videoFrames} type="number" min={2} max={240} value={payload.video_frames} disabled={!supportsParam('video_frames', isVideoModel)} onChange={e => setPayload({ ...payload, video_frames: Number(e.target.value) })} />
              <ParamInput label={t.videoFps} type="number" min={1} max={60} value={payload.fps} disabled={!supportsParam('fps', isVideoModel)} onChange={e => setPayload({ ...payload, fps: Number(e.target.value) })} />
            </FieldRow>
            <FieldRow className="mt-2.5 sm:grid-cols-2">
              <ParamInput label={ig(t.highNoiseSteps, !supportsParam('high_noise_steps', false))} type="number" min={0} max={150} value={payload.high_noise_steps} disabled={!supportsParam('high_noise_steps', false)} onChange={e => setPayload({ ...payload, high_noise_steps: Number(e.target.value) })} />
              <ParamInput label={ig(t.highNoiseCfg, !supportsParam('high_noise_cfg_scale', false))} type="number" min={0} max={30} step={0.5} value={payload.high_noise_cfg_scale} disabled={!supportsParam('high_noise_cfg_scale', false)} onChange={e => setPayload({ ...payload, high_noise_cfg_scale: Number(e.target.value) })} />
            </FieldRow>
            <div className="mt-2.5">
              <ParamSelect label={ig(t.highNoiseSampler, !supportsParam('high_noise_sampler', false))} value={payload.high_noise_sampler} onValueChange={value => setPayload({ ...payload, high_noise_sampler: value })} options={samplerOptions} emptyLabel={t.modelDefault} disabled={!supportsParam('high_noise_sampler', false)} />
            </div>
            {videoDuration && <span className="mt-1 block text-[11px] text-muted-foreground">{t.videoDurationHint} {videoDuration} {t.videoSeconds}</span>}
          </ParamSection>
        )}
        <ParamSection title={t.imageAdvancedParamsTitle}>
          <FieldRow className="sm:grid-cols-2">
            <ParamSelect label={t.scheduler} value={payload.scheduler} onValueChange={value => setPayload({ ...payload, scheduler: value })} options={schedulerOptions.filter(Boolean)} emptyLabel={t.modelDefault} disabled={!supportsParam('scheduler')} />
            <ParamInput label={t.clipSkip} type="number" min={-1} max={24} value={payload.clip_skip} disabled={!supportsParam('clip_skip')} onChange={e => setPayload({ ...payload, clip_skip: Number(e.target.value) })} />
          </FieldRow>
          <FieldRow className="mt-2.5 sm:grid-cols-2">
            <ParamInput label={t.guidance} type="number" min={0} max={30} step={0.5} value={payload.guidance} disabled={!supportsParam('guidance')} onChange={e => setPayload({ ...payload, guidance: Number(e.target.value) })} />
            <ParamInput label={ig(t.imgCfgScale, !supportsParam('img_cfg_scale', false))} type="number" min={0} max={30} step={0.5} value={payload.img_cfg_scale} disabled={!supportsParam('img_cfg_scale', false)} onChange={e => setPayload({ ...payload, img_cfg_scale: Number(e.target.value) })} />
          </FieldRow>
          <FieldRow className="mt-2.5 sm:grid-cols-2">
            <ParamInput label={t.eta} type="number" min={0} max={10} step={0.05} value={payload.eta} disabled={!supportsParam('eta')} onChange={e => setPayload({ ...payload, eta: Number(e.target.value) })} />
            <ParamInput label={t.flowShift} type="number" min={0} max={20} step={0.1} value={payload.flow_shift} disabled={!supportsParam('flow_shift')} onChange={e => setPayload({ ...payload, flow_shift: Number(e.target.value) })} />
          </FieldRow>
          <FieldRow className="mt-2.5 sm:grid-cols-2">
            <ParamInput label={t.slgScale} type="number" min={0} max={20} step={0.1} value={payload.slg_scale} disabled={!supportsParam('slg_scale')} onChange={e => setPayload({ ...payload, slg_scale: Number(e.target.value) })} />
            <ParamInput label={t.skipLayerRange} value={`${payload.skip_layer_start}-${payload.skip_layer_end}`} disabled={!supportsParam('slg_scale')} onChange={e => {
              const [start, end] = e.target.value.split('-').map(Number)
              setPayload({ ...payload, skip_layer_start: Number.isFinite(start) ? start : payload.skip_layer_start, skip_layer_end: Number.isFinite(end) ? end : payload.skip_layer_end })
            }} />
          </FieldRow>
          <FieldRow className="mt-2.5 sm:grid-cols-2">
            <ParamSelect label={t.rng} value={payload.rng} onValueChange={value => setPayload({ ...payload, rng: value })} options={rngOptions.filter(Boolean)} emptyLabel={t.modelDefault} disabled={!supportsParam('rng')} />
            <ParamSelect label={t.samplerRng} value={payload.sampler_rng} onValueChange={value => setPayload({ ...payload, sampler_rng: value })} options={rngOptions.filter(Boolean)} emptyLabel={t.sameAsRng} disabled={!supportsParam('sampler_rng')} />
          </FieldRow>
          <FieldRow className="mt-2.5 sm:grid-cols-2">
            <ParamSelect label={t.prediction} value={payload.prediction} onValueChange={value => setPayload({ ...payload, prediction: value })} options={predictionOptions.filter(Boolean)} emptyLabel={t.modelDefault} disabled={!supportsParam('prediction')} />
            <ParamInput label={ig(t.qwenImageLayers, !supportsParam('qwen_image_layers', false))} type="number" min={0} max={16} value={payload.qwen_image_layers} disabled={!supportsParam('qwen_image_layers', false)} onChange={e => setPayload({ ...payload, qwen_image_layers: Number(e.target.value) })} />
          </FieldRow>
          <FieldRow className="mt-2.5 sm:grid-cols-2">
            <ParamSelect label={t.weightType} value={payload.weight_type} onValueChange={value => setPayload({ ...payload, weight_type: value })} options={weightTypeOptions.filter(Boolean)} emptyLabel={t.modelDefault} disabled={!supportsParam('weight_type')} />
            <ParamInput label={t.tensorTypeRules} value={payload.tensor_type_rules} disabled={!supportsParam('tensor_type_rules')} onChange={e => setPayload({ ...payload, tensor_type_rules: e.target.value })} placeholder="^vae.=f16,model.=q8_0" />
          </FieldRow>
          <FieldRow className="mt-2.5 sm:grid-cols-2">
            <ParamChecks label={t.hires} checked={payload.hires} onCheckedChange={checked => setPayload({ ...payload, hires: checked })} disabled={!supportsParam('hires', !isVideoModel)} />
            <ParamInput label={t.hiresScale} type="number" min={1} max={8} step={0.1} value={payload.hires_scale} disabled={!payload.hires || !supportsParam('hires_scale', !isVideoModel)} onChange={e => setPayload({ ...payload, hires_scale: Number(e.target.value) })} />
          </FieldRow>
          <FieldRow className="mt-2.5 sm:grid-cols-2">
            <ParamInput label={t.hiresSize} value={`${payload.hires_width || 0}x${payload.hires_height || 0}`} disabled={!payload.hires || !supportsParam('hires_width', !isVideoModel)} onChange={e => {
              const [width, height] = e.target.value.toLowerCase().split('x').map(Number)
              setPayload({ ...payload, hires_width: Number.isFinite(width) ? width : 0, hires_height: Number.isFinite(height) ? height : 0 })
            }} />
            <ParamInput label={t.hiresSteps} type="number" min={0} max={150} value={payload.hires_steps} disabled={!payload.hires || !supportsParam('hires_steps', !isVideoModel)} onChange={e => setPayload({ ...payload, hires_steps: Number(e.target.value) })} />
          </FieldRow>
          <FieldRow className="mt-2.5 sm:grid-cols-2">
            <ParamInput label={t.hiresDenoise} type="number" min={0} max={1} step={0.05} value={payload.hires_denoising_strength} disabled={!payload.hires || !supportsParam('hires_denoising_strength', !isVideoModel)} onChange={e => setPayload({ ...payload, hires_denoising_strength: Number(e.target.value) })} />
            <ParamSelect label={t.cacheMode} value={payload.cache_mode} onValueChange={value => setPayload({ ...payload, cache_mode: value })} options={cacheOptions.filter(Boolean)} emptyLabel={t.disabled} disabled={!supportsParam('cache_mode')} />
          </FieldRow>
          <div className="mt-2.5">
            <ParamInput label={t.cacheOption} value={payload.cache_option} disabled={!supportsParam('cache_option')} onChange={e => setPayload({ ...payload, cache_option: e.target.value })} placeholder="threshold=0.25,start=0.1,end=0.8" />
          </div>
        </ParamSection>
        <ParamSection title={t.memoryParamsTitle}>
          <FieldRow className="sm:grid-cols-2">
            <ParamChecks label={t.vaeTiling} checked={payload.vae_tiling} onCheckedChange={checked => setPayload({ ...payload, vae_tiling: checked })} disabled={!supportsParam('vae_tiling')} />
            <ParamChecks label={t.streamLayers} checked={payload.stream_layers} onCheckedChange={checked => setPayload({ ...payload, stream_layers: checked })} disabled={!supportsParam('stream_layers')} />
          </FieldRow>
          <FieldRow className="mt-2.5 sm:grid-cols-2">
            <ParamInput label={t.maxVram} type="number" min={-64} max={128} step={0.5} value={payload.max_vram} disabled={!supportsParam('max_vram')} onChange={e => setPayload({ ...payload, max_vram: Number(e.target.value) })} />
            <ParamInput label={t.vaeTileSize} value={payload.vae_tile_size} disabled={!payload.vae_tiling || !supportsParam('vae_tile_size')} onChange={e => setPayload({ ...payload, vae_tile_size: e.target.value })} placeholder="32x32" />
          </FieldRow>
          <FieldRow className="mt-2.5 sm:grid-cols-2">
            <ParamInput label={t.vaeTileOverlap} type="number" min={0} max={0.95} step={0.05} value={payload.vae_tile_overlap} disabled={!payload.vae_tiling || !supportsParam('vae_tile_overlap')} onChange={e => setPayload({ ...payload, vae_tile_overlap: Number(e.target.value) })} />
            <ParamChecks label={t.autoFit} checked={payload.auto_fit} onCheckedChange={checked => setPayload({ ...payload, auto_fit: checked })} disabled={!supportsParam('auto_fit')} />
          </FieldRow>
          <FieldRow className="mt-2.5 sm:grid-cols-2">
            <ParamChecks label={t.clipOnCpu} checked={payload.clip_on_cpu} onCheckedChange={checked => setPayload({ ...payload, clip_on_cpu: checked })} disabled={!supportsParam('clip_on_cpu')} />
            <ParamChecks label={t.offloadToCpu} checked={payload.offload_to_cpu} onCheckedChange={checked => setPayload({ ...payload, offload_to_cpu: checked })} disabled={!supportsParam('offload_to_cpu')} />
          </FieldRow>
          <FieldRow className="mt-2.5 sm:grid-cols-2">
            <ParamChecks label={t.vaeCpuFallback} checked={payload.vae_cpu_fallback} onCheckedChange={checked => setPayload({ ...payload, vae_cpu_fallback: checked })} disabled={!supportsParam('vae_cpu_fallback', isVideoModel)} />
            <ParamChecks label={t.temporalTiling} checked={payload.temporal_tiling} onCheckedChange={checked => setPayload({ ...payload, temporal_tiling: checked })} disabled={!supportsParam('temporal_tiling', false)} />
          </FieldRow>
          <FieldRow className="mt-2.5 sm:grid-cols-2">
            <ParamInput label={t.temporalTileFrames} type="number" min={1} max={32} value={payload.temporal_tile_frames} disabled={!payload.temporal_tiling || !supportsParam('temporal_tile_frames', false)} onChange={e => setPayload({ ...payload, temporal_tile_frames: Number(e.target.value) })} />
            <ParamInput label={t.temporalTileOverlap} type="number" min={0} max={16} value={payload.temporal_tile_overlap} disabled={!payload.temporal_tiling || !supportsParam('temporal_tile_overlap', false)} onChange={e => setPayload({ ...payload, temporal_tile_overlap: Number(e.target.value) })} />
          </FieldRow>
          <div className="mt-2.5">
            <ParamInput label={t.paramsBackend} value={payload.params_backend} disabled={!supportsParam('params_backend')} onChange={e => setPayload({ ...payload, params_backend: e.target.value })} placeholder="cpu / disk" />
          </div>
          <div className="mt-2.5">
            <ParamInput label={t.backendAssign} value={payload.backend} disabled={!supportsParam('backend')} onChange={e => setPayload({ ...payload, backend: e.target.value })} placeholder="clip=cpu,vae=cuda0,diffusion=cuda0" />
          </div>
        </ParamSection>
          <p className="mt-2 text-[12.5px] leading-relaxed text-muted-foreground">{t.paramsIgnoredHint}</p>
          </div>
        </ScrollArea>
      </Panel>

      <Dialog open={Boolean(playingUrl)} onOpenChange={open => !open && setPlayingUrl('')}>
        <DialogContent className="w-fit max-w-[min(92vw,1080px)] border-none bg-transparent p-0 shadow-none" showCloseButton={false}>
          <DialogTitle className="sr-only">{t.videoBadge}</DialogTitle>
          <Button
            variant="outline"
            size="icon"
            className="absolute -top-10 right-0 border-white/30 bg-slate-900/60 text-white hover:bg-slate-900/80 hover:text-white"
            onClick={() => setPlayingUrl('')}
            title={t.closeVideo}
          ><X size={18} /></Button>
          <video src={playingUrl} controls autoPlay playsInline className="block max-h-[82vh] max-w-[92vw] rounded-[10px] bg-black shadow-2xl" />
        </DialogContent>
      </Dialog>
      </ResizablePanel>
      </ResizablePanelGroup>
    </div>
  )
}
