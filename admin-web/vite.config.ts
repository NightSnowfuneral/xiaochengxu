import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 生产构建由 deploy/deploy.sh 传入 `--base=/admin/`；
// 开发环境保持根路径，与 backend 的 CORS 默认源
// http://127.0.0.1:5173 / http://localhost:5173 对齐。
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    strictPort: true
  },
  build: {
    outDir: 'dist',
    sourcemap: false
  }
})
