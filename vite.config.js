import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '127.0.0.1',
    port: 7645,
    proxy: { '/api': 'http://127.0.0.1:7646' },
    fs: {
      deny: ['.env', '.env.*', '*.{crt,pem}', '**/.git/**', '**/data/**',
        '**/.venv/**', '**/backend/**', '**/scripts/**', '**/*.sqlite3*'],
    },
  },
})
