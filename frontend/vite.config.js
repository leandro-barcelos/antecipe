import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [
    vue(),
    tailwindcss()
  ],

  optimizeDeps: {
    exclude: [
      '@tailwindcss/oxide',
      '@tailwindcss/oxide-win32-x64-msvc'
    ]
  }
})