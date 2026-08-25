import { useEffect, useState } from 'react'
import { KeyRound, ShieldCheck, UserCircle2 } from 'lucide-react'
import { api, SessionInfo } from '../api/client'
import { messages } from '../i18n'

type T = typeof messages['zh-CN']

// 内置注册表快照（实时状态以 GET /api/v1/models 为准）
const MODEL_KEYS: [string, string, string, string][] = [
  ['sd15', 'SD 1.x', 'Stable Diffusion v1.5 EMA', 'txt2img, img2img'],
  ['sd2', 'SD 2.x', 'Stable Diffusion 2.1', 'txt2img, img2img'],
  ['sd-turbo', 'SD Turbo', 'SD Turbo', 'txt2img, img2img'],
  ['sdxl', 'SDXL', 'Stable Diffusion XL Base', 'txt2img, img2img'],
  ['sdxl-turbo', 'SDXL Turbo', 'SDXL Turbo', 'txt2img, img2img'],
  ['sd3', 'SD3', 'Stable Diffusion 3', 'txt2img'],
  ['sd35', 'SD3.5', 'Stable Diffusion 3.5', 'txt2img'],
  ['flux-schnell', 'FLUX', 'FLUX.1 Schnell', 'txt2img'],
  ['flux-dev', 'FLUX', 'FLUX.1 Dev', 'txt2img'],
  ['flux-kontext', 'FLUX Edit', 'FLUX.1 Kontext Dev', 'img2img, edit'],
  ['flux2', 'FLUX', 'FLUX.2', 'txt2img'],
  ['qwen-image', 'Qwen', 'Qwen Image', 'txt2img'],
  ['qwen-image-edit', 'Qwen Edit', 'Qwen Image Edit', 'img2img, edit'],
  ['lens', 'Image', 'Lens', 'txt2img'],
  ['chroma', 'Image', 'Chroma', 'txt2img'],
  ['chroma-radiance', 'Image', 'Chroma1 Radiance', 'txt2img'],
  ['longcat-image', 'Image', 'LongCat Image', 'txt2img'],
  ['longcat-image-edit', 'Image Edit', 'LongCat Image Edit', 'img2img, edit'],
  ['z-image', 'Image', 'Z-Image', 'txt2img'],
  ['minit2i', 'Image', 'MiniT2I', 'txt2img'],
  ['ovis-image', 'Image', 'Ovis-Image', 'txt2img'],
  ['anima', 'Image', 'Anima', 'txt2img'],
  ['ernie-image', 'Image', 'ERNIE-Image', 'txt2img'],
  ['boogu-image', 'Image', 'Boogu Image', 'txt2img'],
  ['boogu-image-edit', 'Image Edit', 'Boogu Image Edit', 'img2img, edit'],
  ['krea2', 'Image', 'Krea2', 'txt2img'],
  ['mage-flow', 'Image', 'Mage-Flow', 'txt2img'],
  ['mage-flow-edit', 'Image Edit', 'Mage-Flow Edit', 'img2img, edit'],
  ['sefi-image', 'Image', 'SeFi-Image', 'txt2img'],
  ['hidream-o1', 'Image', 'HiDream-O1-Image', 'txt2img'],
  ['ideogram4', 'Image', 'Ideogram4', 'txt2img'],
  ['wan21', 'Wan Video', 'Wan 2.1', 'video'],
  ['wan22', 'Wan Video', 'Wan 2.2', 'video'],
  ['ltx-video', 'Video', 'LTX Video', 'video'],
  ['hunyuan-video', 'Video', 'HunyuanVideo 1.5', 'video'],
  ['minimax-h3', 'Video', 'MiniMax-H3', 'video'],
  ['lingbot-video', 'Video', 'LingBot Video', 'video'],
]

const PARAMS: [string, string, string, keyof T & string][] = [
  ['prompt', 'string · 1~4000 字符', '必填', 'apiP_prompt'],
  ['model_key', 'string', 'sd15', 'apiP_model_key'],
  ['negative_prompt', 'string', '""', 'apiP_negative_prompt'],
  ['width / height', 'int · 256~2048', '768', 'apiP_size'],
  ['steps', 'int · 1~150', '30', 'apiP_steps'],
  ['cfg_scale', 'float · 1.0~30.0', '7.0', 'apiP_cfg'],
  ['strength', 'float · 0.0~1.0', '0.75', 'apiP_strength'],
  ['sampler', 'euler_a | euler | heun | dpm++2m', 'euler_a', 'apiP_sampler'],
  ['seed', 'int', '-1', 'apiP_seed'],
  ['batch_count', 'int · 1~4', '1', 'apiP_batch'],
  ['init_job_id', 'string', '""', 'apiP_init_job'],
  ['init_filename', 'string', '""', 'apiP_init_file'],
]

const FLOW_EXAMPLE = `# 1) 创建生成任务（校验后立即返回，不阻塞）
curl -X POST https://<vos-host>/api/com.ictrek.image-studio/api/v1/generate \\
  -H "Authorization: Bearer <token>" \\
  -H "Content-Type: application/json" \\
  -d '{"prompt":"a quiet tea house by the lake","model_key":"sdxl","width":1024,"height":1024}'
# → {"job_id":"j_ab12...","status":"queued",...}

# 2) 轮询任务直到 succeeded / failed
curl https://<vos-host>/api/com.ictrek.image-studio/api/v1/jobs/j_ab12... \\
  -H "Authorization: Bearer <token>"
# → {"status":"running","progress":0.42,...}
# → {"status":"succeeded","outputs":["output.png"],...}

# 3) 下载图片（也可在浏览器用 access_token 查询参数）
curl -o output.png "https://<vos-host>/api/com.ictrek.image-studio/api/v1/outputs/j_ab12.../output.png?access_token=<token>"

# 4) 列出该账户全部图片（含 url 字段，url 即下载直链）
curl https://<vos-host>/api/com.ictrek.image-studio/api/v1/outputs \\
  -H "Authorization: Bearer <token>"`

const PULL_EXAMPLE = `# 触发下载（后台异步执行，接口立即返回）
curl -X POST https://<vos-host>/api/com.ictrek.image-studio/api/v1/models/flux-schnell/pull \\
  -H "Authorization: Bearer <token>"

# 强制重新下载（取消旧任务并从头/断点重来）
curl -X POST "https://<vos-host>/api/com.ictrek.image-studio/api/v1/models/flux-schnell/pull?force=true" \\
  -H "Authorization: Bearer <token>"

# 停止下载（保留断点，可续传）
curl -X POST https://<vos-host>/api/com.ictrek.image-studio/api/v1/models/flux-schnell/stop \\
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

export default function ApiPage({ t }: { t: T }) {
  const [session, setSession] = useState<SessionInfo | null>(null)

  useEffect(() => {
    api.me().then(setSession).catch(() => undefined)
  }, [])

  return (
    <section className="panel api-panel">
      <div className="panel-title">{t.api}</div>
      <p>{t.apiHelp}</p>
      <div className="endpoint-grid">
        <div><span>{t.baseUrl}</span><code>/api/com.ictrek.image-studio</code></div>
        <div><span>{t.createImage}</span><code>POST /api/v1/generate</code></div>
        <div><span>{t.jobList}</span><code>GET /api/v1/jobs</code></div>
        <div><span>Job</span><code>GET /api/v1/jobs/&lt;job_id&gt;</code> <code>DELETE …</code></div>
        <div><span>{t.outputFile}</span><code>GET /api/v1/outputs/&lt;job_id&gt;/&lt;filename&gt;</code></div>
        <div><span>Outputs</span><code>GET /api/v1/outputs</code></div>
        <div><span>Pull</span><code>POST /api/v1/models/&lt;key&gt;/pull?force=</code> <code>POST …/stop</code></div>
        <div><span>{t.modelList}</span><code>GET /api/v1/models</code></div>
        <div><span>{t.sessionUser}</span><code>GET /api/v1/me</code></div>
        <div><span>{t.healthCheck}</span><code>GET /health</code></div>
      </div>

      <div className="auth-section-label" style={{ marginTop: 20 }}>{t.apiFlowTitle}</div>
      <p>{t.apiFlowHelp}</p>
      <GuideCode>{FLOW_EXAMPLE}</GuideCode>
      <p className="api-note">{t.apiStatusNote}</p>

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

      <div className="auth-section-label" style={{ marginTop: 20 }}>{t.apiModelsTitle}</div>
      <p>{t.apiModelsHelp}</p>
      <table className="api-table api-table-models">
        <thead>
          <tr><th>{t.apiColKey}</th><th>{t.apiColFamily}</th><th>{t.apiColName}</th><th>{t.apiColCaps}</th></tr>
        </thead>
        <tbody>
          {MODEL_KEYS.map(([key, family, name, caps]) => (
            <tr key={key}>
              <td><code>{key}</code></td>
              <td>{family}</td>
              <td>{name}</td>
              <td><span className={caps.includes('video') ? 'api-cap api-cap-video' : 'api-cap'}>{caps}</span></td>
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
