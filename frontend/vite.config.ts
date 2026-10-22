import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'
import { VitePWA } from 'vite-plugin-pwa'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    // P43 - makes the app installable (Android "Add to Home Screen" / the
    // TWA wrapper's launch surface, see docs/ANDROID_APP.md). Deliberately
    // precaches only the static app shell (JS/CSS/fonts/icons) - it must
    // never cache a single byte from the backend API. Every screen in this
    // app (positions, approvals, prices, risk state) is live financial/
    // approval data; a service worker silently serving a stale cached
    // response for any of it would show the user a wrong balance or a
    // decided-looking approval that's actually gone. `workbox.runtimeCaching`
    // is intentionally left empty for that reason - do not add an entry
    // matching the API origin without re-reading this comment first.
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.svg', 'icons/apple-touch-icon.png'],
      manifest: {
        name: 'Multi Asset Radar',
        short_name: '자산레이더',
        description: '국내주식(KIS) + 코인(Upbit) 사전 돌파 레이더 - 모든 실거래는 사람의 승인이 필요합니다.',
        lang: 'ko-KR',
        start_url: '/',
        scope: '/',
        display: 'standalone',
        orientation: 'portrait',
        background_color: '#f2f4f6',
        theme_color: '#3182f6',
        icons: [
          { src: 'icons/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
          { src: 'icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
          { src: 'icons/icon-192-maskable.png', sizes: '192x192', type: 'image/png', purpose: 'maskable' },
          { src: 'icons/icon-512-maskable.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        // Only the build's own static output - never a runtime/API entry.
        globPatterns: ['**/*.{js,css,html,woff2,svg,png}'],
        runtimeCaching: [],
      },
    }),
  ],
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    globals: true,
  },
})
