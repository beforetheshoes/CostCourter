import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig({
    plugins: [vue()],
    server: {
        host: true,
        port: 5173,
        strictPort: false,
        proxy: {
            // Forward API requests to FastAPI to avoid CORS during dev
            '/api': {
                target: 'http://localhost:8000',
                changeOrigin: true,
            },
        },
    },
    test: {
        globals: true,
        environment: 'jsdom',
        setupFiles: ['./vitest.setup.ts'],
        coverage: {
            reporter: ['text', 'html', 'lcov'],
            include: [
                'src/components/**/*.{ts,tsx,js,jsx,vue}',
                'src/stores/**/*.{ts,tsx,js,jsx}',
                'src/lib/**/*.{ts,tsx,js,jsx}',
                'src/router/**/*.{ts,tsx,js,jsx}',
            ],
            exclude: ['src/views/**'],
        },
    },
})
