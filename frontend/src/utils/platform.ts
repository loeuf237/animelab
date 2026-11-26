import { computed, ref } from 'vue'

export type PlatformRuntime = 'android' | 'desktop' | 'web'
export type PlatformOs = 'android' | 'ios' | 'windows' | 'macos' | 'linux'
export type HapticKind = 'selection' | 'impact' | 'confirm'

interface AndroidUiBridge {
  syncSystemBars?: (statusHex: string, navHex: string, lightIcons: boolean) => void
  haptic?: (kind: HapticKind) => void
  setKeepScreenOn?: (enabled: boolean) => void
  getPlatformInfo?: () => string
  getEngineState?: () => string
  exportDiagnostics?: (jsonPayload: string) => string
  openExternalPlayer?: (payloadJson: string) => string
}

export interface AndroidEngineState {
  ready: boolean
  fullyReady: boolean
  error: string | null
}

interface PyWebViewBridge {
  api?: {
    platform_info?: () => Promise<{ runtime?: string; os?: string }>
    set_theme?: (theme: 'dark' | 'light') => Promise<unknown> | void
    set_title?: (title: string) => Promise<unknown> | void
    choose_download_directory?: () => Promise<string | null>
    choose_external_player?: () => Promise<string | null>
  }
}

type NativeWindow = Window & {
  AnimeLabAndroid?: AndroidUiBridge
  pywebview?: PyWebViewBridge
}

export const platformRuntime = ref<PlatformRuntime>('web')
export const platformOs = ref<PlatformOs>('linux')
export const isTouchDevice = ref(false)
export const isStandalonePwa = ref(false)
export const isMacOs = computed(() => platformOs.value === 'macos')

let lastChrome: { bgHex: string; navHex: string; isLight: boolean } | null = null
let lastTitle = 'AnimeLab'
let initialized = false

function normalizeOs(raw?: string): PlatformOs | null {
  const val = (raw || '').trim().toLowerCase()
  if (!val) return null
  if (val === 'android') return 'android'
  if (val === 'ios' || val === 'iphone' || val === 'ipad') return 'ios'
  if (val === 'windows' || val === 'win32' || val === 'win64') return 'windows'
  if (val === 'macos' || val === 'darwin' || val === 'mac') return 'macos'
  if (val === 'linux') return 'linux'
  return null
}

function detectInitialOs(): PlatformOs {
  if (typeof navigator === 'undefined') return 'linux'
  const win = typeof window !== 'undefined' ? (window as NativeWindow) : undefined
  if (win?.AnimeLabAndroid) return 'android'
  const ua = navigator.userAgent || ''
  const plat = (navigator.platform || '').toLowerCase()
  if (/Android/i.test(ua)) return 'android'
  if (/iPhone|iPad|iPod/i.test(ua) || (plat === 'macintel' && navigator.maxTouchPoints > 1))
    return 'ios'
  if (/Win/i.test(plat) || /Windows/i.test(ua)) return 'windows'
  if (/Mac/i.test(plat) || /Macintosh|Mac OS X/i.test(ua)) return 'macos'
  return 'linux'
}

function detectInitialRuntime(os: PlatformOs): PlatformRuntime {
  if (typeof window === 'undefined') return 'web'
  const win = window as NativeWindow
  if (win.AnimeLabAndroid) return 'android'
  if (win.pywebview || /pywebview/i.test(navigator.userAgent || '')) return 'desktop'
  if (os === 'android' && /; wv\)/i.test(navigator.userAgent || '')) return 'android'
  return 'web'
}

function writeDataset() {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  root.dataset.runtime = platformRuntime.value
  root.dataset.os = platformOs.value
  root.dataset.standalone = isStandalonePwa.value ? 'true' : 'false'
}

function pushDesktopBridge() {
  if (typeof window === 'undefined') return
  const api = (window as NativeWindow).pywebview?.api
  if (!api) return
  if (lastChrome) {
    try {
      void api.set_theme?.(lastChrome.isLight ? 'light' : 'dark')
    } catch {
      /* ignore unavailable desktop hook */
    }
  }
  if (lastTitle) {
    try {
      void api.set_title?.(lastTitle)
    } catch {
      /* ignore unavailable desktop hook */
    }
  }
}

export function initializePlatform() {
  if (typeof window === 'undefined' || initialized) return
  initialized = true
  const os = detectInitialOs()
  platformOs.value = os
  platformRuntime.value = detectInitialRuntime(os)

  try {
    isTouchDevice.value = window.matchMedia?.('(pointer: coarse)')?.matches ?? false
    isStandalonePwa.value =
      window.matchMedia?.('(display-mode: standalone)')?.matches ||
      Boolean((navigator as Navigator & { standalone?: boolean }).standalone)
  } catch {
    isTouchDevice.value = false
    isStandalonePwa.value = false
  }

  writeDataset()

  window.addEventListener('pywebviewready', () => {
    platformRuntime.value = 'desktop'
    writeDataset()
    pushDesktopBridge()
  })
}

export function applyStartupPlatform(runtime?: string, os?: string) {
  if (runtime === 'android' || runtime === 'desktop' || runtime === 'web') {
    platformRuntime.value = runtime
  }
  const normalized = normalizeOs(os)
  if (normalized) {
    platformOs.value = normalized
  }
  writeDataset()
  pushDesktopBridge()
}

export function formatShortcut(key: string): string {
  return isMacOs.value ? `⌘ ${key}` : `Ctrl + ${key}`
}

export function syncNativeChrome(bgHex: string, navHex: string, isLight: boolean) {
  lastChrome = { bgHex, navHex, isLight }
  if (typeof document !== 'undefined') {
    const meta = document.querySelector('meta[name="theme-color"]')
    if (meta) meta.setAttribute('content', bgHex)
  }
  if (typeof window === 'undefined') return
  const win = window as NativeWindow
  try {
    win.AnimeLabAndroid?.syncSystemBars?.(bgHex, navHex, isLight)
  } catch {
    /* ignore unavailable Android hook */
  }
  try {
    void win.pywebview?.api?.set_theme?.(isLight ? 'light' : 'dark')
  } catch {
    /* ignore unavailable desktop hook */
  }
}

export function syncNativeTitle(title: string) {
  const clean = (title || 'AnimeLab').trim() || 'AnimeLab'
  lastTitle = clean
  if (typeof document !== 'undefined') {
    document.title = clean
  }
  if (typeof window === 'undefined') return
  try {
    void (window as NativeWindow).pywebview?.api?.set_title?.(clean)
  } catch {
    /* ignore unavailable desktop hook */
  }
}

export function triggerHaptic(kind: HapticKind = 'selection') {
  if (typeof window === 'undefined') return
  try {
    ;(window as NativeWindow).AnimeLabAndroid?.haptic?.(kind)
  } catch {
    /* ignore unavailable Android hook */
  }
}

export function setNativeKeepScreenOn(enabled: boolean) {
  if (typeof window === 'undefined') return
  try {
    ;(window as NativeWindow).AnimeLabAndroid?.setKeepScreenOn?.(enabled)
  } catch {
    /* ignore unavailable Android hook */
  }
}

export function exportNativeDiagnostics(jsonPayload: string): string | null {
  if (typeof window === 'undefined') return null
  try {
    const result = (window as NativeWindow).AnimeLabAndroid?.exportDiagnostics?.(jsonPayload)
    return typeof result === 'string' && result.trim() ? result.trim() : null
  } catch {
    return null
  }
}

export function openNativeExternalPlayer(
  payload: Record<string, unknown>,
): { launched: boolean; error?: string } | null {
  if (typeof window === 'undefined') return null
  try {
    const bridge = (window as NativeWindow).AnimeLabAndroid
    if (typeof bridge?.openExternalPlayer !== 'function') return null
    const raw = bridge.openExternalPlayer(JSON.stringify(payload))
    if (!raw) return null
    const parsed = JSON.parse(raw) as { launched?: unknown; error?: unknown }
    return {
      launched: Boolean(parsed?.launched),
      error: typeof parsed?.error === 'string' ? parsed.error : undefined,
    }
  } catch {
    return null
  }
}

export async function chooseDesktopExternalPlayer(): Promise<string | null> {
  if (typeof window === 'undefined') return null
  try {
    const api = (window as NativeWindow).pywebview?.api
    if (typeof api?.choose_external_player !== 'function') return null
    const selected = await api.choose_external_player()
    return typeof selected === 'string' && selected.trim() ? selected.trim() : null
  } catch {
    return null
  }
}

export function readAndroidEngineState(): AndroidEngineState | null {
  if (typeof window === 'undefined') return null
  const bridge = (window as NativeWindow).AnimeLabAndroid
  if (typeof bridge?.getEngineState !== 'function') return null
  try {
    const raw = bridge.getEngineState()
    if (!raw) return null
    const parsed = JSON.parse(raw) as {
      ready?: unknown
      fullyReady?: unknown
      error?: unknown
    }
    return {
      ready: Boolean(parsed?.ready),
      fullyReady: Boolean(parsed?.fullyReady),
      error: typeof parsed?.error === 'string' && parsed.error ? parsed.error : null,
    }
  } catch {
    return null
  }
}

export function isAndroidEngineBooting(): boolean {
  const state = readAndroidEngineState()
  return state !== null && !state.ready && !state.error
}

export function waitForAndroidEngine(
  signal?: AbortSignal,
): Promise<{ ready: boolean; error?: string }> {
  if (typeof window === 'undefined') return Promise.resolve({ ready: true })
  const initial = readAndroidEngineState()
  if (!initial || initial.ready) return Promise.resolve({ ready: true })
  if (initial.error) return Promise.resolve({ ready: false, error: initial.error })
  if (signal?.aborted) return Promise.resolve({ ready: false, error: 'Aborted' })

  return new Promise((resolve) => {
    let settled = false
    let pollTimer: ReturnType<typeof setInterval> | null = null

    const finish = (result: { ready: boolean; error?: string }) => {
      if (settled) return
      settled = true
      window.removeEventListener('animelab:engine-ready', onReady)
      window.removeEventListener('animelab:engine-error', onError)
      signal?.removeEventListener('abort', onAbort)
      if (pollTimer !== null) {
        clearInterval(pollTimer)
        pollTimer = null
      }
      resolve(result)
    }

    const onReady = () => finish({ ready: true })
    const onError = (event: Event) => {
      const detail = (event as CustomEvent<unknown>)?.detail
      const latest = readAndroidEngineState()
      const message =
        typeof detail === 'string' && detail.trim() ? detail : latest?.error || undefined
      finish({ ready: false, error: message })
    }
    const onAbort = () => finish({ ready: false, error: 'Aborted' })

    window.addEventListener('animelab:engine-ready', onReady)
    window.addEventListener('animelab:engine-error', onError)
    signal?.addEventListener('abort', onAbort, { once: true })

    pollTimer = setInterval(() => {
      const state = readAndroidEngineState()
      if (!state || state.ready) finish({ ready: true })
      else if (state.error) finish({ ready: false, error: state.error })
    }, 150)
  })
}
