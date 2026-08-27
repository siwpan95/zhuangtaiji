import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 构建产物输出到 dist/，由后端 web/server.py 托管。
// 默认 base 为 "/"，静态资源以 /assets/... 提供，与后端路由兼容。
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    chunkSizeWarningLimit: 1200,
  },
  server: {
    port: 5173,
  },
})
