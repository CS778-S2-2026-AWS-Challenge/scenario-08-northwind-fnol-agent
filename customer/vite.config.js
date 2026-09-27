import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// scripts/start-dev.ps1 sets VITE_BACKEND_PORT when it starts the backend on a non-default port.
const backendPort = process.env.VITE_BACKEND_PORT || '8000'

// https://vite.dev/config/
export default defineConfig({
  server: {
    host: '0.0.0.0',
    allowedHosts: ['terminal.local'],
    proxy: {
      '/api': {
        target: `http://127.0.0.1:${backendPort}`,
        changeOrigin: true,
      },
    },
  },
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.js',
  },
})
