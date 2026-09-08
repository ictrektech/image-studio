import { useEffect, useState, type ReactNode } from 'react'
import { KeyRound, ShieldCheck, UserCircle2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Separator } from '@/components/ui/separator'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { CheckRow, Field } from '@/components/app/field'
import { Panel, PanelTitle } from '@/components/app/panel'
import { api, ModelInfo, SessionInfo } from '../api/client'
import { messages } from '../i18n'

type T = typeof messages['zh-CN']

// 内置注册表快照（实时状态以 GET /api/v1/models 为准）
const MODEL_KEYS: [string, string, string, string, string][] = [
  ['sd15', '860M', 'SD 1.x', 'Stable Diffusion v1.5 EMA', 'txt2img, img2img'],
  ['sd2', '865M', 'SD 2.x', 'Stable Diffusion 2.1', 'txt2img, img2img'],
  ['sd-turbo', '860M', 'SD Turbo', 'SD Turbo', 'txt2img, img2img'],
  ['sdxl', '3.5B', 'SDXL', 'Stable Diffusion XL Base', 'txt2img, img2img'],
  ['sdxl-turbo', '3.5B', 'SDXL Turbo', 'SDXL Turbo', 'txt2img, img2img'],
  ['sd3', '2B', 'SD3', 'Stable Diffusion 3', 'txt2img'],
  ['sd35', '8.1B', 'SD3.5', 'Stable Diffusion 3.5 Large', 'txt2img'],
  ['sd35-medium', '2.5B', 'SD3.5', 'Stable Diffusion 3.5 Medium', 'txt2img'],
  ['flux-schnell', '12B', 'FLUX', 'FLUX.1 Schnell', 'txt2img'],
  ['flux-dev', '12B', 'FLUX', 'FLUX.1 Dev', 'txt2img'],
  ['flux-kontext', '12B', 'FLUX Edit', 'FLUX.1 Kontext Dev', 'img2img, edit'],
  ['flux2', '32B', 'FLUX', 'FLUX.2', 'txt2img'],
  ['qwen-image', '20B', 'Qwen', 'Qwen Image', 'txt2img'],
  ['qwen-image-edit', '20B', 'Qwen Edit', 'Qwen Image Edit', 'img2img, edit'],
  ['lens', '', 'Image', 'Lens', 'txt2img'],
  ['chroma', '6B', 'Image', 'Chroma', 'txt2img'],
  ['chroma-radiance', '6B', 'Image', 'Chroma1 Radiance', 'txt2img'],
  ['longcat-image', '', 'Image', 'LongCat Image', 'txt2img'],
  ['longcat-image-edit', '', 'Image Edit', 'LongCat Image Edit', 'img2img, edit'],
  ['z-image', '6B', 'Image', 'Z-Image', 'txt2img'],
  ['minit2i', '', 'Image', 'MiniT2I', 'txt2img'],
  ['ovis-image', '', 'Image', 'Ovis-Image', 'txt2img'],
  ['anima', '', 'Image', 'Anima', 'txt2img'],
  ['ernie-image', '', 'Image', 'ERNIE-Image', 'txt2img'],
  ['boogu-image', '', 'Image', 'Boogu Image', 'txt2img'],
  ['boogu-image-edit', '', 'Image Edit', 'Boogu Image Edit', 'img2img, edit'],
  ['krea2', '', 'Image', 'Krea2', 'txt2img'],
  ['mage-flow', '', 'Image', 'Mage-Flow', 'txt2img'],
  ['mage-flow-edit', '', 'Image Edit', 'Mage-Flow Edit', 'img2img, edit'],
  ['sefi-image', '', 'Image', 'SeFi-Image', 'txt2img'],
  ['hidream-o1', '', 'Image', 'HiDream-O1-Image', 'txt2img'],
  ['ideogram4', '', 'Image', 'Ideogram4', 'txt2img'],
  ['wan21', '1.3B', 'Wan Video', 'Wan 2.1 T2V 1.3B', 'video'],
  ['wan21-t2v-14b', '14B', 'Wan Video', 'Wan 2.1 T2V 14B', 'video'],
  ['wan21-i2v-14b', '14B', 'Wan Video', 'Wan 2.1 I2V 14B 480P', 'video (首帧 -i)'],
  ['wan22', '5B', 'Wan Video', 'Wan 2.2 TI2V 5B', 'video (首帧 -i)'],
  ['wan22-t2v-a14b', '14B×2', 'Wan Video', 'Wan 2.2 T2V A14B', 'video'],
  ['wan22-i2v-a14b', '14B×2', 'Wan Video', 'Wan 2.2 I2V A14B', 'video (首帧 -i)'],
  ['ltx-video', '22B', 'Video', 'LTX Video', 'video (首帧 -i)'],
  ['hunyuan-video', '8.3B', 'Video', 'HunyuanVideo 1.5 T2V 720P', 'video'],
  ['hunyuan-i2v-720p', '8.3B', 'Video', 'HunyuanVideo 1.5 I2V 720P', 'video (首帧 -i)'],
  ['hunyuan-t2v-480p', '8.3B', 'Video', 'HunyuanVideo 1.5 T2V 480P', 'video'],
  ['minimax-h3', '', 'Video', 'MiniMax-H3', 'video (首帧 -i)'],
  ['minimax-ref2va', '', 'Video', 'MiniMax-H3 Ref2VA', 'video (参考图 -r)'],
  ['lingbot-video', '1.3B', 'Video', 'LingBot Video', 'video (首帧 -i)'],
]

const PARAMS: [string, string, string, keyof T & string][] = [
  ['prompt', 'string · 1~4000 字符', '必填', 'apiP_prompt'],
  ['model_key', 'string', 'sd15', 'apiP_model_key'],
  ['model_variant', 'string', '""', 'apiP_model_variant'],
  ['negative_prompt', 'string', '""', 'apiP_negative_prompt'],
  ['width / height', 'int · 256~2048', '768', 'apiP_size'],
  ['steps', 'int · 1~150', '30', 'apiP_steps'],
  ['cfg_scale', 'float · 1.0~30.0', '7.0', 'apiP_cfg'],
  ['strength', 'float · 0.0~1.0', '0.75', 'apiP_strength'],
  ['sampler', 'sd-cli sampling-method', 'euler_a', 'apiP_sampler'],
  ['seed', 'int', '-1', 'apiP_seed'],
  ['batch_count', 'int · 1~4', '1', 'apiP_batch'],
  ['scheduler', 'string', '""', 'apiP_scheduler'],
  ['clip_skip', 'int · -1~24', '-1', 'apiP_clip_skip'],
  ['guidance / img_cfg_scale', 'float · 0~30', '0', 'apiP_guidance'],
  ['eta / flow_shift', 'float', '0', 'apiP_flow_shift'],
  ['high_noise_*', 'int/float/string', '0 / ""', 'apiP_high_noise'],
  ['slg_scale / skip_layer_*', 'float', '0', 'apiP_slg'],
  ['rng / sampler_rng', 'cuda | cpu | std_default', '""', 'apiP_rng'],
  ['prediction', 'eps | v | edm_v | sd3_flow | flux_flow | sefi_flow', '""', 'apiP_prediction'],
  ['weight_type / tensor_type_rules', 'string', '""', 'apiP_weight_type'],
  ['cache_mode / cache_option', 'string', '""', 'apiP_cache'],
  ['qwen_image_layers', 'int · 0~16', '0', 'apiP_qwen_layers'],
  ['hires*', 'boolean / numbers', 'false', 'apiP_hires'],
  ['vae_tiling / clip_on_cpu / offload_to_cpu / max_vram / backend...', 'boolean / string / number', '模型默认', 'apiP_memory'],
  ['video_frames', 'int · 0~240', '0 (家族默认)', 'apiP_video_frames'],
  ['fps', 'int · 0~60', '0 (家族默认)', 'apiP_video_fps'],
  ['init_job_id', 'string', '""', 'apiP_init_job'],
  ['init_filename', 'string', '""', 'apiP_init_file'],
  ['init_input_id', 'string', '""', 'apiP_init_input'],
]

const SETUP_EXAMPLE = `BASE='https://<vos-host>/api/com.ictrek.image-studio'
AUTH='Authorization: Bearer <token>'`

const RECIPE_A = `# 1) 创建任务（立即返回 job_id，不阻塞）
curl -X POST $BASE/api/v1/generate -H "$AUTH" -H 'Content-Type: application/json' \\
  -d '{"prompt":"a quiet tea house by the lake","model_key":"sdxl","width":1024,"height":1024}'
# → {"job_id":"j_ab12...","status":"queued",...}

# 2) 轮询直到 succeeded / failed（脚本化等待）
JOB=j_ab12...
while [ "$(curl -s $BASE/api/v1/jobs/$JOB -H "$AUTH" | jq -r .status)" = "running" ] \\
   || [ "$(curl -s $BASE/api/v1/jobs/$JOB -H "$AUTH" | jq -r .status)" = "queued" ]; do sleep 3; done
curl -s $BASE/api/v1/jobs/$JOB -H "$AUTH" | jq '{status,progress,outputs,error}'

# 3) 下载图片（浏览器场景可用 access_token 查询参数）
curl -o output.png "$BASE/api/v1/outputs/$JOB/output.png?access_token=<token>"`

const RECIPE_B = `# 1) 上传参考图（png/jpg/jpeg/webp，≤20MB，按账户隔离）
curl -X POST $BASE/api/v1/inputs -H "$AUTH" -F 'file=@ref.png'
# → {"input_id":"in_20260825_...","url":"/api/v1/inputs/in_20260825_..."}

# 2) 用支持参考图的模型生成（引用上传图用 init_input_id）
curl -X POST $BASE/api/v1/generate -H "$AUTH" -H 'Content-Type: application/json' \\
  -d '{"prompt":"make it a snowy night","model_key":"qwen-image-edit",
       "init_input_id":"in_20260825_...","strength":0.8,"width":1024,"height":1024}'

# 3) 轮询 + 下载同流程 A；查看已上传的参考图：
curl $BASE/api/v1/inputs -H "$AUTH"`

const RECIPE_C = `# 把上一轮的输出作为下一轮输入（网页「继续这一轮」/「基于此图生成」的 API 形式），
# init_job_id + init_filename 取自上一个 succeeded 任务的 job_id 和 outputs[0]
curl -X POST $BASE/api/v1/generate -H "$AUTH" -H 'Content-Type: application/json' \\
  -d '{"prompt":"add warm lights in the windows","model_key":"flux-kontext",
       "init_job_id":"j_ab12...","init_filename":"output.png"}'

# 可跨模型迭代：SDXL 生成 → Qwen-Image-Edit 修改 → 再交给支持参考图的视频模型生成视频
curl -X POST $BASE/api/v1/generate -H "$AUTH" -H 'Content-Type: application/json' \\
  -d '{"prompt":"slow camera push in, cinematic light","model_key":"wan22",
       "init_job_id":"j_ab12...","init_filename":"output.png",
       "width":512,"height":320,"video_frames":33,"fps":24}'`

const RECIPE_D = `# 1) 模型未下载时，generate 会返回 409「模型文件未就绪」；先触发下载（后台执行）
curl -X POST $BASE/api/v1/models/sd35/pull -H "$AUTH"

# 2) 轮询直到 status 变为 ready（progress 为下载进度）
watch -n 10 "curl -s $BASE/api/v1/models -H \\"$AUTH\\" \\
  | jq '.[] | select(.key==\\"sd35\\") | {status,progress,downloaded_bytes,total_bytes}'"

# 3) ready 后即可按流程 A 生成；所有可用 key/variant（含未下载）见 GET /api/v1/models`

const RECIPE_E = `# 批量：一次任务出 4 张，outputs 为多个文件名，逐个下载
curl -X POST $BASE/api/v1/generate -H "$AUTH" -H 'Content-Type: application/json' \\
  -d '{"prompt":"portrait of a fox","model_key":"sd15","batch_count":4}'
# → outputs: ["output.png", ...]（每个文件一个下载 URL）

# 复现：固定 seed + 相同参数 → 每次得到同一张图；seed 省略或 -1 为随机
curl -X POST $BASE/api/v1/generate -H "$AUTH" -H 'Content-Type: application/json' \\
  -d '{"prompt":"portrait of a fox","model_key":"sd15","seed":42,"steps":30,
       "cfg_scale":7,"sampler":"euler_a","width":512,"height":512}'`

const RECIPE_F = `# 任务：列表 / 详情 / 删除（删除任务同时删除其图片文件）
curl $BASE/api/v1/jobs -H "$AUTH"
curl $BASE/api/v1/jobs/j_ab12... -H "$AUTH"
curl -X DELETE $BASE/api/v1/jobs/j_ab12... -H "$AUTH"

# 图片：一次列出该账户全部图片（含下载直链 url 与所属 prompt）
curl $BASE/api/v1/outputs -H "$AUTH" | jq '.[] | {job_id,filename,url,prompt}'

# 参考图：列表 / 下载 / 删除
curl $BASE/api/v1/inputs -H "$AUTH"
curl -o ref.png "$BASE/api/v1/inputs/in_20260825_...?access_token=<token>"
curl -X DELETE $BASE/api/v1/inputs/in_20260825_... -H "$AUTH"

# 确认当前 token 归属（排障第一步）
curl $BASE/api/v1/me -H "$AUTH"`

const RECIPE_G = `# 文生视频：纯 T2V 模型不传参考图，输出 output.webm
curl -X POST $BASE/api/v1/generate -H "$AUTH" -H 'Content-Type: application/json' \\
  -d '{"prompt":"a dancer under warm stage light","model_key":"wan21",
       "width":512,"height":320,"steps":12,"cfg_scale":6,
       "video_frames":33,"fps":24,
       "vae_tiling":true,"temporal_tiling":true,"max_vram":-2}'

# 图生视频：先上传首帧，再传给 I2V / TI2V / Ref2VA 模型
curl -X POST $BASE/api/v1/inputs -H "$AUTH" -F 'file=@first-frame.png'
curl -X POST $BASE/api/v1/generate -H "$AUTH" -H 'Content-Type: application/json' \\
  -d '{"prompt":"slow camera push in, soft light","model_key":"wan22",
       "init_input_id":"in_20260825_...","width":512,"height":320,
       "video_frames":33,"fps":24,"temporal_tiling":true}'`

const RECIPE_H = `# 查看模型支持哪些参数、默认值和量化版本
curl $BASE/api/v1/models -H "$AUTH" \\
  | jq '.[] | select(.key=="qwen-image") | {key, runtime, variants}'

# 使用量化版本生成：model_key 仍是基础模型 key，model_variant 指定版本
curl -X POST $BASE/api/v1/generate -H "$AUTH" -H 'Content-Type: application/json' \\
  -d '{"prompt":"clean product photo on white background",
       "model_key":"qwen-image","model_variant":"q4_k_m",
       "width":1024,"height":1024,"steps":20,"cfg_scale":4}'

# 低显存优先策略：先选量化版本，再缩小 width/height/frames/steps，
# 最后按模型支持情况打开 vae_tiling / temporal_tiling / stream_layers / vae_cpu_fallback；
# offload_to_cpu 默认关闭，只在明确接受变慢换显存时打开
curl -X POST $BASE/api/v1/generate -H "$AUTH" -H 'Content-Type: application/json' \\
  -d '{"prompt":"small low-vram smoke test","model_key":"wan21",
       "model_variant":"q8_0","width":384,"height":240,"steps":8,
       "video_frames":17,"fps":12,"vae_tiling":true,
       "temporal_tiling":true,"stream_layers":true,"vae_cpu_fallback":true,
       "offload_to_cpu":false}'`

const MODEL_SHAPE_EXAMPLE = `curl $BASE/api/v1/models -H "$AUTH" | jq '.[0] | {
  key, name, status, progress, total_bytes, size,
  runtime: {mode: .runtime.mode, defaults: .runtime.defaults, parameters: .runtime.parameters},
  variants: [.variants[]? | {id, name, status, progress, total_bytes, runtime}]
}'`

const PULL_EXAMPLE = `# 触发下载（后台异步执行，接口立即返回）
curl -X POST https://<vos-host>/api/com.ictrek.image-studio/api/v1/models/flux-schnell/pull \\
  -H "Authorization: Bearer <token>"

# 下载某个量化/替代版本（variant 来自 GET /api/v1/models 的 variants[].id）
curl -X POST "https://<vos-host>/api/com.ictrek.image-studio/api/v1/models/qwen-image/pull?variant=q4_k_m" \\
  -H "Authorization: Bearer <token>"

# 强制重新下载（取消旧任务并从头/断点重来）
curl -X POST "https://<vos-host>/api/com.ictrek.image-studio/api/v1/models/flux-schnell/pull?force=true" \\
  -H "Authorization: Bearer <token>"

# 停止下载（保留断点，可续传）
curl -X POST https://<vos-host>/api/com.ictrek.image-studio/api/v1/models/flux-schnell/stop \\
  -H "Authorization: Bearer <token>"

# 停止某个 variant
curl -X POST "https://<vos-host>/api/com.ictrek.image-studio/api/v1/models/qwen-image/stop?variant=q4_k_m" \\
  -H "Authorization: Bearer <token>"

# 轮询下载进度（status=downloading + progress / downloaded_bytes / total_bytes）
curl https://<vos-host>/api/com.ictrek.image-studio/api/v1/models \\
  -H "Authorization: Bearer <token>" | jq '.[] | select(.key=="flux-schnell") | {status,progress,downloaded_bytes,total_bytes}'`

const preCode = 'mt-3.5 overflow-auto rounded-lg bg-slate-900 p-3.5 font-mono text-xs text-slate-200'

function GuideCode({ children, t }: { children: string; t: T }) {
  return (
    <pre
      className={`${preCode} cursor-pointer`}
      title="copy"
      onClick={() => {
        navigator.clipboard?.writeText(children).then(() => {
          toast.success(t.copiedToClipboard)
        }, () => {})
      }}
    >
      {children}
    </pre>
  )
}

function SectionHeading({ children }: { children: ReactNode }) {
  return (
    <div className="mt-5">
      <Separator className="mb-3" />
      <div className="flex items-center gap-1.5 text-xs font-bold text-foreground">
        {children}
      </div>
    </div>
  )
}

function AuthCard({ warn, children }: { warn?: boolean; children: ReactNode }) {
  return (
    <Card className={`mt-3 gap-0 rounded-lg px-3.5 py-3 ${warn ? 'border-orange-200 bg-orange-50 dark:border-orange-900/60 dark:bg-orange-950/30' : 'bg-card'}`}>
      {children}
    </Card>
  )
}

export default function ApiPage({ models, t }: { models: ModelInfo[]; t: T }) {
  const [session, setSession] = useState<SessionInfo | null>(null)
  const [immichUrl, setImmichUrl] = useState('')
  const [immichKey, setImmichKey] = useState('')
  const [immichVerifySsl, setImmichVerifySsl] = useState(true)
  const [immichConfigured, setImmichConfigured] = useState(false)
  const [immichSaving, setImmichSaving] = useState(false)
  const [immichMessage, setImmichMessage] = useState('')

  const loadImmich = () => api.immichSettings().then(config => {
    setImmichUrl(config.api_url)
    setImmichVerifySsl(config.verify_ssl)
    setImmichConfigured(config.configured)
  }).catch(() => undefined)

  useEffect(() => {
    api.me().then(setSession).catch(() => undefined)
    loadImmich()
  }, [])

  const saveImmich = async () => {
    setImmichSaving(true)
    setImmichMessage('')
    try {
      const config = await api.updateImmichSettings({
        api_url: immichUrl,
        ...(immichKey ? { api_key: immichKey } : {}),
        verify_ssl: immichVerifySsl,
      })
      setImmichKey('')
      setImmichConfigured(config.configured)
      setImmichMessage(t.immichSaved)
    } catch (error: any) {
      setImmichMessage(error.message || t.immichSaveFailed)
    } finally {
      setImmichSaving(false)
    }
  }

  const modelRows = models.length
    ? models.flatMap(model => [
      ...(model.variants || []).map(variant => ({
        key: model.key,
        variant: variant.id || '',
        params: variant.params || model.params || '',
        family: variant.family || model.family,
        name: `${model.name} · ${variant.name}`,
        caps: variant.capabilities || model.capabilities,
        source: variant.source || model.source,
      })),
      {
        key: model.key,
        variant: '',
        params: model.params || '',
        family: model.family,
        name: model.name,
        caps: model.capabilities,
        source: model.source,
      },
    ])
    : MODEL_KEYS.map(([key, params, family, name, caps]) => ({
      key,
      variant: '',
      params,
      family,
      name,
      caps: caps.split(',').map(item => item.trim()),
      source: '',
    }))

  const endpoints: [string, string[]][] = [
    [t.baseUrl, ['/api/com.ictrek.image-studio']],
    [t.createImage, ['POST /api/v1/generate']],
    [t.jobList, ['GET /api/v1/jobs']],
    ['Job', ['GET /api/v1/jobs/<job_id>', 'DELETE …']],
    [t.outputFile, ['GET /api/v1/outputs/<job_id>/<filename>']],
    ['Outputs', ['GET /api/v1/outputs']],
    ['Pull', ['POST /api/v1/models/<key>/pull?variant=&force=', 'POST …/stop?variant=']],
    ['Upload input', ['POST /api/v1/inputs', 'GET /api/v1/inputs']],
    [t.modelList, ['GET /api/v1/models']],
    [t.sessionUser, ['GET /api/v1/me']],
    [t.healthCheck, ['GET /health']],
  ]

  return (
    <Panel className="mx-auto max-w-[980px] p-3">
      <PanelTitle>{t.api}</PanelTitle>
      <p className="mt-0.5 text-xs text-muted-foreground">{t.apiHelp}</p>

      <SectionHeading>{t.immichTitle}</SectionHeading>
      <p className="mt-0.5 text-xs text-muted-foreground">{t.immichHelp}</p>
      <AuthCard>
        <Field label={t.immichApiUrl} className="mb-1">
          <Input id="immich-api-url" value={immichUrl} onChange={event => setImmichUrl(event.target.value)} placeholder="https://immich.example.com/api" />
        </Field>
        <Field label={t.immichApiKey} className="mb-1">
          <Input id="immich-api-key" type="password" value={immichKey} onChange={event => setImmichKey(event.target.value)} placeholder={immichConfigured ? t.immichKeyKeep : t.immichKeyPlaceholder} autoComplete="new-password" />
        </Field>
        <CheckRow className="my-2">
          <Checkbox checked={immichVerifySsl} onCheckedChange={checked => setImmichVerifySsl(checked === true)} />
          <span>{t.immichVerifySsl}</span>
        </CheckRow>
        <Button variant="outline" className="self-start" onClick={saveImmich} disabled={immichSaving || !immichUrl.trim() || (!immichConfigured && !immichKey.trim())}>{immichSaving ? t.submitting : t.immichSave}</Button>
        {immichMessage && <p className="mt-2 text-xs text-muted-foreground" role="status">{immichMessage}</p>}
      </AuthCard>

      <Table className="mt-3.5 text-xs">
        <TableBody>
          {endpoints.map(([label, codes]) => (
            <TableRow key={label}>
              <TableCell className="w-[96px] align-middle text-muted-foreground">{label}</TableCell>
              <TableCell className="py-2.5">
                <span className="flex min-w-0 flex-wrap gap-1.5">
                  {codes.map(code => <code className="min-w-0 truncate rounded border bg-secondary px-1.5 py-0.5 font-mono" key={code}>{code}</code>)}
                </span>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <SectionHeading>{t.apiFlowTitle}</SectionHeading>
      <p className="mt-0.5 text-xs text-muted-foreground">{t.apiFlowHelp}</p>
      <p className="mt-2 text-[12.5px] leading-relaxed text-muted-foreground">{t.apiStatusNote}</p>
      <GuideCode t={t}>{SETUP_EXAMPLE}</GuideCode>
      <p className="mt-2 text-[12.5px] leading-relaxed text-muted-foreground">{t.apiSetupNote}</p>

      <h4 className="mt-4 mb-1 text-[13.5px] font-bold">{t.apiRecipeA}</h4>
      <GuideCode t={t}>{RECIPE_A}</GuideCode>
      <h4 className="mt-4 mb-1 text-[13.5px] font-bold">{t.apiRecipeB}</h4>
      <p className="mt-2 text-[12.5px] leading-relaxed text-muted-foreground">{t.apiRecipeBNote}</p>
      <GuideCode t={t}>{RECIPE_B}</GuideCode>
      <h4 className="mt-4 mb-1 text-[13.5px] font-bold">{t.apiRecipeC}</h4>
      <p className="mt-2 text-[12.5px] leading-relaxed text-muted-foreground">{t.apiRecipeCNote}</p>
      <GuideCode t={t}>{RECIPE_C}</GuideCode>
      <h4 className="mt-4 mb-1 text-[13.5px] font-bold">{t.apiRecipeD}</h4>
      <p className="mt-2 text-[12.5px] leading-relaxed text-muted-foreground">{t.apiRecipeDNote}</p>
      <GuideCode t={t}>{RECIPE_D}</GuideCode>
      <h4 className="mt-4 mb-1 text-[13.5px] font-bold">{t.apiRecipeE}</h4>
      <p className="mt-2 text-[12.5px] leading-relaxed text-muted-foreground">{t.apiRecipeENote}</p>
      <GuideCode t={t}>{RECIPE_E}</GuideCode>
      <h4 className="mt-4 mb-1 text-[13.5px] font-bold">{t.apiRecipeF}</h4>
      <GuideCode t={t}>{RECIPE_F}</GuideCode>
      <h4 className="mt-4 mb-1 text-[13.5px] font-bold">{t.apiRecipeG}</h4>
      <p className="mt-2 text-[12.5px] leading-relaxed text-muted-foreground">{t.apiRecipeGNote}</p>
      <GuideCode t={t}>{RECIPE_G}</GuideCode>
      <h4 className="mt-4 mb-1 text-[13.5px] font-bold">{t.apiRecipeH}</h4>
      <p className="mt-2 text-[12.5px] leading-relaxed text-muted-foreground">{t.apiRecipeHNote}</p>
      <GuideCode t={t}>{RECIPE_H}</GuideCode>

      <h4 className="mt-4 mb-1 text-[13.5px] font-bold">{t.apiErrorsTitle}</h4>
      <pre className="mt-1.5 whitespace-pre-wrap font-sans text-[12.5px] leading-loose text-muted-foreground">{t.apiErrList}</pre>

      <SectionHeading>{t.apiParamsTitle}</SectionHeading>
      <p className="mt-0.5 text-xs text-muted-foreground">{t.apiParamsHelp}</p>
      <Table className="mt-2 text-[13px]">
        <TableHeader>
          <TableRow><TableHead>{t.apiColParam}</TableHead><TableHead>{t.apiColType}</TableHead><TableHead>{t.apiColDefault}</TableHead><TableHead>{t.apiColDesc}</TableHead></TableRow>
        </TableHeader>
        <TableBody>
          {PARAMS.map(([p, ty, d, descKey]) => (
            <TableRow key={p}>
              <TableCell><code className="rounded border bg-secondary px-1.5 py-0.5 font-mono text-xs">{p}</code></TableCell>
              <TableCell>{ty}</TableCell>
              <TableCell><code className="rounded border bg-secondary px-1.5 py-0.5 font-mono text-xs">{d}</code></TableCell>
              <TableCell>{t[descKey]}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <h4 className="mt-4 mb-1 text-[13.5px] font-bold">{t.apiModelShapeTitle}</h4>
      <p className="mt-2 text-[12.5px] leading-relaxed text-muted-foreground">{t.apiModelShapeNote}</p>
      <GuideCode t={t}>{MODEL_SHAPE_EXAMPLE}</GuideCode>

      <SectionHeading>{t.apiModelsTitle}</SectionHeading>
      <p className="mt-0.5 text-xs text-muted-foreground">{t.apiModelsHelp}</p>
      <Table className="mt-2 text-[13px]">
        <TableHeader>
          <TableRow><TableHead>{t.apiColKey}</TableHead><TableHead>{t.apiColVariant}</TableHead><TableHead>{t.paramsLabel}</TableHead><TableHead>{t.source}</TableHead><TableHead>{t.apiColFamily}</TableHead><TableHead>{t.apiColName}</TableHead><TableHead>{t.apiColCaps}</TableHead></TableRow>
        </TableHeader>
        <TableBody>
          {modelRows.map(row => (
            <TableRow key={`${row.key}:${row.variant || 'default'}`}>
              <TableCell><code className="rounded border bg-secondary px-1.5 py-0.5 font-mono text-xs">{row.key}</code></TableCell>
              <TableCell className="whitespace-nowrap"><code className="rounded border bg-secondary px-1.5 py-0.5 font-mono text-xs">{row.variant || '""'}</code></TableCell>
              <TableCell className="whitespace-nowrap">{row.params || '—'}</TableCell>
              <TableCell className="whitespace-nowrap">{row.source || '—'}</TableCell>
              <TableCell>{row.family}</TableCell>
              <TableCell>{row.name}</TableCell>
              <TableCell className={row.caps.includes('video') ? 'opacity-70' : ''}>{row.caps.join(', ')}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <p className="mt-2 text-[12.5px] leading-relaxed text-muted-foreground">{t.apiVideoNote}</p>

      <SectionHeading>{t.apiPullTitle}</SectionHeading>
      <p className="mt-0.5 text-xs text-muted-foreground">{t.apiPullHelp}</p>
      <GuideCode t={t}>{PULL_EXAMPLE}</GuideCode>

      <SectionHeading><KeyRound size={15} /> {t.authGuide}</SectionHeading>
      <p className="mt-0.5 text-xs text-muted-foreground">{t.authIntro}</p>

      <AuthCard>
        <div className="mb-1.5 flex items-center gap-1.5 text-[13px] font-bold"><ShieldCheck size={15} /> {t.authSameAccountTitle}</div>
        <p className="mb-2 text-xs text-muted-foreground">{t.authSameAccountBody}</p>
        <pre className={preCode}>{`# VOS 内同账户前端 / app 直接携带当前登录用户的 token：
curl -X POST /api/com.ictrek.image-studio/api/v1/generate \\
  -H "Authorization: Bearer <当前VOS用户的access_token>" \\
  -H "Content-Type: application/json" \\
  -d '{"prompt":"a quiet tea house by the lake","model_key":"sd15","width":768,"height":768}'`}</pre>
      </AuthCard>

      <AuthCard>
        <div className="mb-1.5 flex items-center gap-1.5 text-[13px] font-bold"><UserCircle2 size={15} /> {t.authExternalTitle}</div>
        <p className="mb-2 text-xs text-muted-foreground">{t.authExternalBody}</p>
        <pre className={preCode}>{`# VOS 外部调用：换成 VOS 网关域名即可，token 决定数据归属账户
curl -X POST https://<vos-host>/api/com.ictrek.image-studio/api/v1/generate \\
  -H "Authorization: Bearer <目标账户的VOS access_token>" \\
  -H "Content-Type: application/json" \\
  -d '{"prompt":"a quiet tea house by the lake","model_key":"sd15"}'

# 查询该账户的任务与图片（同样需要 token）：
curl https://<vos-host>/api/com.ictrek.image-studio/api/v1/jobs \\
  -H "Authorization: Bearer <同一账户的token>"

# 图片直链下载（浏览器场景可用 access_token 查询参数）：
https://<vos-host>/api/com.ictrek.image-studio/api/v1/outputs/<job_id>/output.png?access_token=<token>`}</pre>
      </AuthCard>

      <AuthCard warn>
        <div className="mb-1.5 text-[13px] font-bold">{t.authAnonymousTitle}</div>
        <p className="text-xs text-muted-foreground">{t.authAnonymousBody}</p>
      </AuthCard>

      <p className="mt-3.5 text-xs">
        {t.apiCurrentSession}
        <code className="mx-1.5 rounded bg-secondary px-2 py-0.5 font-mono text-xs">{session ? session.user_key : '...'}</code>
        {session && !session.authenticated && <span className="ml-1.5 rounded-full bg-orange-100 px-1.5 py-px text-[10px] font-bold text-orange-900 dark:bg-orange-950 dark:text-orange-300">{t.anonymousSession}</span>}
      </p>
    </Panel>
  )
}
