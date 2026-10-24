import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [
    vue(),
    tailwindcss()
  ],

  server: {
    proxy: {
      '/api': {
        target: process.env.API_PROXY_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: true
      }
    }
  },

  optimizeDeps: {
    exclude: [
      '@tailwindcss/oxide',
      '@tailwindcss/oxide-win32-x64-msvc'
    ]
  }
})
