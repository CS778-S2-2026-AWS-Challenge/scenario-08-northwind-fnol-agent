import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  return {
    base: '/workbench/',
    server: {
      host: '0.0.0.0',
      allowedHosts: ['terminal.local'],
      proxy: {
        '/api': {
          target: env.WORKBENCH_API_TARGET || 'http://127.0.0.1:8000',
          changeOrigin: true,
        },
      },
    },
    plugins: [react()],
    test: {
      environment: 'jsdom',
      setupFiles: './src/test/setup.js',
    },
  }
})
