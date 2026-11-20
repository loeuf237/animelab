import { computed, ref } from 'vue'

export type PlatformRuntime = 'android' | 'desktop' | 'web'
export type PlatformOs = 'android' | 'ios' | 'windows' | 'macos' | 'linux'
export type HapticKind = 'selection' | 'impact' | 'confirm'

interface AndroidUiBridge {
  syncSystemBars?: (statusHex: string, navHex: string, lightIcons: boolean) => void
  haptic?: (kind: HapticKind) => void
  getPlatformInfo?: () => string
  exportDiagnostics?: (jsonPayload: string) => string
}

interface PyWebViewBridge {
  api?: {
    platform_info?: () => Promise<{ runtime?: string; os?: string }>
    set_theme?: (theme: 'dark' | 'light') => Promise<unknown> | void
    set_title?: (title: string) => Promise<unknown> | void
    choose_download_directory?: () => Promise<string | null>
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

export function exportNativeDiagnostics(jsonPayload: string): string | null {
  if (typeof window === 'undefined') return null
  try {
    const result = (window as NativeWindow).AnimeLabAndroid?.exportDiagnostics?.(jsonPayload)
    return typeof result === 'string' && result.trim() ? result.trim() : null
  } catch {
    return null
  }
}
