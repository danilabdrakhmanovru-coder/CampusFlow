import { defineConfig } from 'vite'

export default defineConfig({
  server: {
    host: 'localhost',
    port: 8765,
    strictPort: true,
    proxy: { '/api': { target: process.env.CAMPUSFLOW_API_TARGET ?? 'http://127.0.0.1:8766', changeOrigin: false, configure(proxy) { proxy.on('proxyReq', (outgoing, incoming) => { if (incoming.headers.host) outgoing.setHeader('host', incoming.headers.host) }) } } },
  },
})
