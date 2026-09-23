import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  appType: 'spa',
  // Local development only. Production domains and routing are managed by Vercel.
  server: {
    port: 5173,
    strictPort: true,
    allowedHosts: ['projecthelios.localhost'],
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
