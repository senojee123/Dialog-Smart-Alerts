import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In dev (`npm run dev`, port 5173) these paths are proxied to the Python
// backend on :8000, so the SPA, API, SSE stream and uploads all work together
// with hot-reload. In production the backend serves the built dist/ directly.
export default defineConfig({
  plugins: [react()],
  base: '/',
  server: {
    proxy: {
      // SSE stream — must NOT buffer; configure http-proxy to flush headers
      // immediately so EventSource frames arrive in real time.
      '/api/stream': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        // Disable Vite's response buffering for this endpoint so SSE events
        // are forwarded to the browser the moment the backend writes them.
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes, req, res) => {
            // Force chunked / streaming mode through the proxy
            res.flushHeaders?.()
          })
        },
      },
      '/api':     { target: 'http://localhost:8000', changeOrigin: true, ws: true },
      '/uploads': { target: 'http://localhost:8000', changeOrigin: true },
      '/upload':  { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
