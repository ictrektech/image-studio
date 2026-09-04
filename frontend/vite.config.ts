import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  base: '/app/com.ictrek.image-studio/',
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    proxy: {
      // 生产环境由 VOS 网关剥掉 /api/com.ictrek.image-studio 前缀；
      // 本地开发由代理完成同样的前缀剥离，再转发给 uvicorn。
      '/api': {
        target: 'http://127.0.0.1:5000',
        rewrite: (path) => path.replace('/api/com.ictrek.image-studio', ''),
      },
    },
  },
})
