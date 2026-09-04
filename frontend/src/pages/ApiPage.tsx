import { useEffect, useState } from 'react'
import { KeyRound, ShieldCheck, UserCircle2 } from 'lucide-react'
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

function GuideCode({ children }: { children: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <pre
      className="api-guide-code"
      title={copied ? '✓' : 'copy'}
      onClick={() => {
        navigator.clipboard?.writeText(children).then(() => {
          setCopied(true)
          setTimeout(() => setCopied(false), 1500)
        }, () => {})
      }}
    >
      {children}
    </pre>
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

  return (
    <section className="panel api-panel">
      <div className="panel-title">{t.api}</div>
      <p>{t.apiHelp}</p>
      <div className="auth-section-label" style={{ marginTop: 20 }}>{t.immichTitle}</div>
      <p>{t.immichHelp}</p>
      <div className="auth-card">
        <label htmlFor="immich-api-url">{t.immichApiUrl}</label>
        <input id="immich-api-url" value={immichUrl} onChange={event => setImmichUrl(event.target.value)} placeholder="https://immich.example.com/api" />
        <label htmlFor="immich-api-key">{t.immichApiKey}</label>
        <input id="immich-api-key" type="password" value={immichKey} onChange={event => setImmichKey(event.target.value)} placeholder={immichConfigured ? t.immichKeyKeep : t.immichKeyPlaceholder} autoComplete="new-password" />
        <label className="checkbox-row"><input type="checkbox" checked={immichVerifySsl} onChange={event => setImmichVerifySsl(event.target.checked)} />{t.immichVerifySsl}</label>
        <button className="secondary-action" onClick={saveImmich} disabled={immichSaving || !immichUrl.trim() || (!immichConfigured && !immichKey.trim())}>{immichSaving ? t.submitting : t.immichSave}</button>
        {immichMessage && <p className="api-note" role="status">{immichMessage}</p>}
      </div>
      <div className="endpoint-grid">
        <div><span>{t.baseUrl}</span><code>/api/com.ictrek.image-studio</code></div>
        <div><span>{t.createImage}</span><code>POST /api/v1/generate</code></div>
        <div><span>{t.jobList}</span><code>GET /api/v1/jobs</code></div>
        <div><span>Job</span><code>GET /api/v1/jobs/&lt;job_id&gt;</code> <code>DELETE …</code></div>
        <div><span>{t.outputFile}</span><code>GET /api/v1/outputs/&lt;job_id&gt;/&lt;filename&gt;</code></div>
        <div><span>Outputs</span><code>GET /api/v1/outputs</code></div>
        <div><span>Pull</span><code>POST /api/v1/models/&lt;key&gt;/pull?variant=&amp;force=</code> <code>POST …/stop?variant=</code></div>
        <div><span>Upload input</span><code>POST /api/v1/inputs</code> <code>GET /api/v1/inputs</code></div>
        <div><span>{t.modelList}</span><code>GET /api/v1/models</code></div>
        <div><span>{t.sessionUser}</span><code>GET /api/v1/me</code></div>
        <div><span>{t.healthCheck}</span><code>GET /health</code></div>
      </div>

      <div className="auth-section-label" style={{ marginTop: 20 }}>{t.apiFlowTitle}</div>
      <p>{t.apiFlowHelp}</p>
      <p className="api-note">{t.apiStatusNote}</p>
      <GuideCode>{SETUP_EXAMPLE}</GuideCode>
      <p className="api-note">{t.apiSetupNote}</p>

      <h4 className="api-recipe-title">{t.apiRecipeA}</h4>
      <GuideCode>{RECIPE_A}</GuideCode>
      <h4 className="api-recipe-title">{t.apiRecipeB}</h4>
      <p className="api-note">{t.apiRecipeBNote}</p>
      <GuideCode>{RECIPE_B}</GuideCode>
      <h4 className="api-recipe-title">{t.apiRecipeC}</h4>
      <p className="api-note">{t.apiRecipeCNote}</p>
      <GuideCode>{RECIPE_C}</GuideCode>
      <h4 className="api-recipe-title">{t.apiRecipeD}</h4>
      <p className="api-note">{t.apiRecipeDNote}</p>
      <GuideCode>{RECIPE_D}</GuideCode>
      <h4 className="api-recipe-title">{t.apiRecipeE}</h4>
      <p className="api-note">{t.apiRecipeENote}</p>
      <GuideCode>{RECIPE_E}</GuideCode>
      <h4 className="api-recipe-title">{t.apiRecipeF}</h4>
      <GuideCode>{RECIPE_F}</GuideCode>
      <h4 className="api-recipe-title">{t.apiRecipeG}</h4>
      <p className="api-note">{t.apiRecipeGNote}</p>
      <GuideCode>{RECIPE_G}</GuideCode>
      <h4 className="api-recipe-title">{t.apiRecipeH}</h4>
      <p className="api-note">{t.apiRecipeHNote}</p>
      <GuideCode>{RECIPE_H}</GuideCode>

      <h4 className="api-recipe-title">{t.apiErrorsTitle}</h4>
      <pre className="api-err-list">{t.apiErrList}</pre>

      <div className="auth-section-label" style={{ marginTop: 20 }}>{t.apiParamsTitle}</div>
      <p>{t.apiParamsHelp}</p>
      <table className="api-table">
        <thead>
          <tr><th>{t.apiColParam}</th><th>{t.apiColType}</th><th>{t.apiColDefault}</th><th>{t.apiColDesc}</th></tr>
        </thead>
        <tbody>
          {PARAMS.map(([p, ty, d, descKey]) => (
            <tr key={p}>
              <td><code>{p}</code></td>
              <td>{ty}</td>
              <td><code>{d}</code></td>
              <td>{t[descKey]}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h4 className="api-recipe-title">{t.apiModelShapeTitle}</h4>
      <p className="api-note">{t.apiModelShapeNote}</p>
      <GuideCode>{MODEL_SHAPE_EXAMPLE}</GuideCode>

      <div className="auth-section-label" style={{ marginTop: 20 }}>{t.apiModelsTitle}</div>
      <p>{t.apiModelsHelp}</p>
      <table className="api-table api-table-models">
        <thead>
          <tr><th>{t.apiColKey}</th><th>{t.apiColVariant}</th><th>{t.paramsLabel}</th><th>{t.source}</th><th>{t.apiColFamily}</th><th>{t.apiColName}</th><th>{t.apiColCaps}</th></tr>
        </thead>
        <tbody>
          {modelRows.map(row => (
            <tr key={`${row.key}:${row.variant || 'default'}`}>
              <td><code>{row.key}</code></td>
              <td><code>{row.variant || '""'}</code></td>
              <td>{row.params || '—'}</td>
              <td>{row.source || '—'}</td>
              <td>{row.family}</td>
              <td>{row.name}</td>
              <td><span className={row.caps.includes('video') ? 'api-cap api-cap-video' : 'api-cap'}>{row.caps.join(', ')}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="api-note">{t.apiVideoNote}</p>

      <div className="auth-section-label" style={{ marginTop: 20 }}>{t.apiPullTitle}</div>
      <p>{t.apiPullHelp}</p>
      <GuideCode>{PULL_EXAMPLE}</GuideCode>

      <div className="auth-section-label" style={{ marginTop: 20 }}><KeyRound size={15} /> {t.authGuide}</div>
      <p>{t.authIntro}</p>

      <div className="auth-card">
        <div className="auth-card-title"><ShieldCheck size={15} /> {t.authSameAccountTitle}</div>
        <p>{t.authSameAccountBody}</p>
        <pre>{`# VOS 内同账户前端 / app 直接携带当前登录用户的 token：
curl -X POST /api/com.ictrek.image-studio/api/v1/generate \\
  -H "Authorization: Bearer <当前VOS用户的access_token>" \\
  -H "Content-Type: application/json" \\
  -d '{"prompt":"a quiet tea house by the lake","model_key":"sd15","width":768,"height":768}'`}</pre>
      </div>

      <div className="auth-card">
        <div className="auth-card-title"><UserCircle2 size={15} /> {t.authExternalTitle}</div>
        <p>{t.authExternalBody}</p>
        <pre>{`# VOS 外部调用：换成 VOS 网关域名即可，token 决定数据归属账户
curl -X POST https://<vos-host>/api/com.ictrek.image-studio/api/v1/generate \\
  -H "Authorization: Bearer <目标账户的VOS access_token>" \\
  -H "Content-Type: application/json" \\
  -d '{"prompt":"a quiet tea house by the lake","model_key":"sd15"}'

# 查询该账户的任务与图片（同样需要 token）：
curl https://<vos-host>/api/com.ictrek.image-studio/api/v1/jobs \\
  -H "Authorization: Bearer <同一账户的token>"

# 图片直链下载（浏览器场景可用 access_token 查询参数）：
https://<vos-host>/api/com.ictrek.image-studio/api/v1/outputs/<job_id>/output.png?access_token=<token>`}</pre>
      </div>

      <div className="auth-card warn">
        <div className="auth-card-title">{t.authAnonymousTitle}</div>
        <p>{t.authAnonymousBody}</p>
      </div>

      <p className="api-session-now">
        {t.apiCurrentSession}
        <code>{session ? session.user_key : '...'}</code>
        {session && !session.authenticated && <span className="tag-anonymous">{t.anonymousSession}</span>}
      </p>
    </section>
  )
}
