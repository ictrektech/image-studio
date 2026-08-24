import { messages } from '../i18n'

export default function ApiPage({ t }: { t: typeof messages['zh-CN'] }) {
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
        <div><span>{t.healthCheck}</span><code>GET /health</code></div>
      </div>
      <pre>{`curl -X POST /api/com.ictrek.image-studio/api/v1/generate \\
  -H "Content-Type: application/json" \\
  -d '{"prompt":"a quiet tea house by the lake","model_key":"sd15","width":768,"height":768}'`}</pre>
    </section>
  )
}
