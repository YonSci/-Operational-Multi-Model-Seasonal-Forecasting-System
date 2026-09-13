import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // Dev server proxy (dev only -- nginx handles this in production)
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8765',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    rollupOptions: {
      output: {
        // Split large deps into separate chunks for better caching
        manualChunks: {
          maplibre: ['maplibre-gl'],
          recharts: ['recharts'],
          react:    ['react', 'react-dom'],
        },
      },
    },
  },
})
