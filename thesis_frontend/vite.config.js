import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    allowedHosts: ['test.netdisk.n1n3bird.top'],
    proxy: {
      '/ws': {
        target: 'ws://localhost:8080',
        ws: true,
        rewriteWsOrigin: true,
      },
      '/api/v1/transfers': {
        target: 'http://localhost:8082',
        changeOrigin: true,
      },
      '/api/waf': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
      '/api/admin': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
      '/api/preview': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
      '/api/log4shell': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
    },
  },
})
