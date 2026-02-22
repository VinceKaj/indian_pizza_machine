import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      jerrypick: path.resolve(__dirname, 'src/lib/jerrypick-shim.js'),
      'd3-scale-chromatic': path.resolve(__dirname, 'src/lib/d3-scale-chromatic-shim.js'),
      'd3-dispatch': path.resolve(__dirname, 'src/lib/d3-dispatch-shim.js'),
    },
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:9000',
        changeOrigin: true,
      },
    },
  },
})
