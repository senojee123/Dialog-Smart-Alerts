import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In dev (`npm run dev`, port 5173) these paths are proxied to the Python
// backend on :8000, so the SPA, API, SSE stream and uploads all work together
// with hot-reload. In production the backend serves the built dist/ directly.
export default defineConfig({
  plugins: [react()],
  base: './',
  server: {
    proxy: {
      '/api':     { target: 'http://localhost:8000', changeOrigin: true, ws: true },
      '/uploads': { target: 'http://localhost:8000', changeOrigin: true },
      '/upload':  { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
