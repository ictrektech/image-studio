import { useEffect, useState } from 'react'
import { KeyRound, ShieldCheck, UserCircle2 } from 'lucide-react'
import { api, SessionInfo } from '../api/client'
import { messages } from '../i18n'

export default function ApiPage({ t }: { t: typeof messages['zh-CN'] }) {
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
        <div><span>{t.outputFile}</span><code>GET /api/v1/outputs/&lt;job_id&gt;/&lt;filename&gt;</code></div>
        <div><span>{t.modelList}</span><code>GET /api/v1/models</code></div>
        <div><span>{t.sessionUser}</span><code>GET /api/v1/me</code></div>
        <div><span>{t.healthCheck}</span><code>GET /health</code></div>
      </div>

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
