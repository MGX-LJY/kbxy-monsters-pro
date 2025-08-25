import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    proxy: {
      // 静态资源代理到后端（支持 /media 与 /images 两套挂载）
      '/media':  { target: 'http://localhost:8000', changeOrigin: true },
      '/images': { target: 'http://localhost:8000', changeOrigin: true },
      // 接口代理（可保留）
      '/api':    { target: 'http://localhost:8000', changeOrigin: true },
    }
  }
})