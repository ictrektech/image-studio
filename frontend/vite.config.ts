import { readFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// 后端端口统一配置在仓库根 .env.dev 的 IMAGE_STUDIO_PORT，与 run_dev.sh 共用同一来源；
// BACKEND_ORIGIN 环境变量仍可整体覆盖代理目标（后端不在本机时使用，见 AGENTS.md 多机共享一节）。
function readDevEnv(): Record<string, string> {
  try {
    const raw = readFileSync(fileURLToPath(new URL('../.env.dev', import.meta.url)), 'utf8')
    return Object.fromEntries(
      raw
        .split('\n')
        .filter(line => /^[A-Za-z_][A-Za-z0-9_]*=/.test(line))
        .map(line => {
          const i = line.indexOf('=')
          return [line.slice(0, i).trim(), line.slice(i + 1).trim().replace(/^["']|["']$/g, '')]
        }),
    )
  } catch {
    return {}
  }
}

const backendOrigin = process.env.BACKEND_ORIGIN || `http://127.0.0.1:${readDevEnv().IMAGE_STUDIO_PORT || '5000'}`

export default defineConfig({
  base: '/app/com.ictrek.image-studio/',
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: '0.0.0.0',
    // VOS 联调时经平台域名（Traefik 临时路由）访问 dev server，需放开 Host 校验；
    // 仅影响 dev server（VITE_ALLOWED_HOSTS=true 时放开），不影响生产构建。
    allowedHosts: process.env.VITE_ALLOWED_HOSTS === 'true' ? true : undefined,
    proxy: {
      // 生产环境由 VOS 网关剥掉 /api/com.ictrek.image-studio 前缀；
      // 本地开发由代理完成同样的前缀剥离，再转发给 uvicorn。
      '/api': {
        target: backendOrigin,
        rewrite: (path) => path.replace('/api/com.ictrek.image-studio', ''),
      },
    },
  },
})
