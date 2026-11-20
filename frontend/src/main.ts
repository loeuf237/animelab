import { createApp } from 'vue'
import { createPinia } from 'pinia'
import router from './router'
import './style.css'
import './themes.css'
import './styles/tokens.css'
import './styles/native-os.css'
import './styles/sheets.css'
import App from './App.vue'
import { initializeSharedSession, sharedUser } from './stores/sharedSession'
import { initializePwa } from './pwa'
import { initializeAppearance } from './stores/appearance'
import { initializePlatform } from './utils/platform'
import { api } from './api/client'

const app = createApp(App)
initializePlatform()
initializeAppearance()

const reportedErrors = new Set<string>()
let reportCount = 0
function captureClientError(
  kind: 'js_error' | 'unhandled_rejection' | 'vue_error',
  rawCode: unknown,
  component?: string,
) {
  if (reportCount >= 10) return
  const code = String(rawCode || 'unknown')
    .replace(/[^A-Za-z0-9_.:-]/g, '_')
    .slice(0, 80)
  const route = typeof window !== 'undefined' ? window.location.pathname.slice(0, 120) : undefined
  const key = `${kind}:${code}:${route || ''}`
  if (reportedErrors.has(key)) return
  reportedErrors.add(key)
  reportCount++
  void api.reportClientError({ kind, code, component: component?.slice(0, 80), route })
}

app.config.errorHandler = (err, instance, info) => {
  console.error(err)
  const name = err instanceof Error ? err.name : typeof err
  const comp = (instance?.$options as { name?: string; __name?: string } | undefined)?.name || info
  captureClientError('vue_error', name, comp)
}

if (typeof window !== 'undefined') {
  window.addEventListener('error', (event) => {
    captureClientError('js_error', event.error?.name || event.message || 'window_error')
  })
  window.addEventListener('unhandledrejection', (event) => {
    const reason = event.reason
    captureClientError('unhandled_rejection', reason instanceof Error ? reason.name : typeof reason)
  })
}

const pinia = createPinia()

app.use(pinia)
app.use(router)

// Resolve account identity before any store loads private data or opens SSE.
initializeSharedSession().then(async (ready) => {
  if (ready) {
    await router.isReady()
    app.mount('#app')
    if (!sharedUser.value) initializePwa()
  }
})
