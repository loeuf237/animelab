import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  // Android 10/11 devices can retain older System WebView builds. Lower modern
  // syntax (including logical assignments) instead of shipping a blank screen.
  build: {
    target: 'chrome80',
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    host: '127.0.0.1',
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8080',
        changeOrigin: true,
      },
      '/static': {
        target: 'http://127.0.0.1:8080',
        changeOrigin: true,
      },
      '/manifest.json': {
        target: 'http://127.0.0.1:8080',
        changeOrigin: true,
      },
      '/sw.js': {
        target: 'http://127.0.0.1:8080',
        changeOrigin: true,
      },
      '/offline.html': {
        target: 'http://127.0.0.1:8080',
        changeOrigin: true,
      },
    },
  },
})
