import { computed, ref } from 'vue'
import { readPreference, writePreference } from '@/utils/locale'
import { platformRuntime, syncNativeChrome } from '@/utils/platform'
import type { Palette, ThemeMode } from '@/types/startup'

const CHROME_COLORS: Record<'dark' | 'light', Record<Palette, { bg: string; nav: string }>> = {
  dark: {
    classic: { bg: '#1b1b1f', nav: '#211f26' },
    teal: { bg: '#0b1517', nav: '#0f1b1e' },
    lavender: { bg: '#15121d', nav: '#191622' },
    ember: { bg: '#1c1510', nav: '#211913' },
    amoled: { bg: '#000000', nav: '#000000' },
  },
  light: {
    classic: { bg: '#fefbff', nav: '#f3edf7' },
    teal: { bg: '#f5fafb', nav: '#eaf2f3' },
    lavender: { bg: '#f8f6fc', nav: '#eee8f6' },
    ember: { bg: '#fcf7f4', nav: '#f2e7df' },
    amoled: { bg: '#ffffff', nav: '#f5f5f5' },
  },
}

const saved = readPreference('theme')
export const themeMode = ref<ThemeMode>(saved === 'light' || saved === 'system' ? saved : 'dark')
const savedPalette = readPreference('palette')
export const palette = ref<Palette>(
  ['classic', 'teal', 'lavender', 'ember', 'amoled'].includes(savedPalette || '')
    ? (savedPalette as Palette)
    : 'teal',
)
const systemDark = ref(true)
export const effectiveTheme = computed(() =>
  themeMode.value === 'system' ? (systemDark.value ? 'dark' : 'light') : themeMode.value,
)
function paint(syncChrome = true) {
  const mode = effectiveTheme.value
  const variant = palette.value
  document.documentElement.dataset.theme = mode
  document.documentElement.dataset.palette = variant
  document.documentElement.style.colorScheme = mode
  if (syncChrome) {
    const colors = CHROME_COLORS[mode][variant]
    syncNativeChrome(colors.bg, colors.nav, mode === 'light')
  }
}
export function setAppearance(mode: ThemeMode, variant: Palette) {
  themeMode.value = mode
  palette.value = variant
  writePreference('theme', mode)
  writePreference('palette', variant)
  paint()
}
export function initializeAppearance() {
  const media = window.matchMedia('(prefers-color-scheme: dark)')
  systemDark.value = media.matches
  media.addEventListener('change', (event) => {
    systemDark.value = event.matches
    paint()
  })
  // When Android boots on a fresh ephemeral loopback port with empty localStorage,
  // avoid overwriting persisted native SharedPreferences bar colors before /api/app/startup restores them.
  const deferAndroidChrome =
    platformRuntime.value === 'android' && !readPreference('theme') && !readPreference('palette')
  paint(!deferAndroidChrome)
}
