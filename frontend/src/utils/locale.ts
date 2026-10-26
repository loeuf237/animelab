import { ref } from 'vue'
import english from '@/locales/en.json'
export type Language = 'fr' | 'en'
export function readPreference(name: string): string | null {
  try {
    if (typeof localStorage === 'undefined') return null
    const current = localStorage.getItem(`animelab_${name}`)
    if (current !== null) return current
    const legacy = localStorage.getItem(`animan_${name}`)
    if (legacy !== null) {
      try {
        localStorage.setItem(`animelab_${name}`, legacy)
      } catch {
        /* A read-only profile still retains its existing preference. */
      }
    }
    return legacy
  } catch {
    return null
  }
}
export function writePreference(name: string, value: string) {
  try {
    localStorage.setItem(`animelab_${name}`, value)
  } catch {
    /* Browser preferences remain optional. */
  }
}
export function resolveClientLanguage(): Language {
  let saved: string | null = null
  try {
    const query =
      typeof location !== 'undefined' ? new URLSearchParams(location.search).get('lang') : null
    const cookie =
      typeof document !== 'undefined'
        ? document.cookie.match(/(?:^|;\s*)animelab_lang=(fr|en)(?:;|$)/)?.[1] ||
          document.cookie.match(/(?:^|;\s*)animan_lang=(fr|en)(?:;|$)/)?.[1]
        : null
    let local: string | null = null
    try {
      local = readPreference('lang')
    } catch {
      /* Cookies and detection still work. */
    }
    saved = [query, cookie, local].find((value) => value === 'fr' || value === 'en') || null
  } catch {
    /* Browser storage may be unavailable. */
  }
  if (saved === 'fr' || saved === 'en') return saved
  const languages = typeof navigator !== 'undefined' ? navigator.languages : []
  const first = languages?.[0] || (typeof navigator !== 'undefined' ? navigator.language : 'fr')
  return /^fr(?:-|$)/i.test(first) ? 'fr' : 'en'
}
export const language = ref<Language>(resolveClientLanguage())
const catalog: Record<string, string> = english
const patterns = Object.entries(catalog)
  .filter(([key]) => /\{\d+\}/.test(key))
  .sort(([a], [b]) => b.replace(/\{\d+\}/g, '').length - a.replace(/\{\d+\}/g, '').length)
  .map(([key, translation]) => {
    const names: string[] = []
    const expression = key
      .split(/(\{\d+\})/)
      .map((chunk) => {
        if (/^\{\d+\}$/.test(chunk)) {
          names.push(chunk)
          return '(.*?)'
        }
        return chunk.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      })
      .join('')
    return { expression: new RegExp('^' + expression + '$', 's'), names, translation }
  })
export function tx(value: unknown): string {
  const text = value == null ? '' : String(value)
  if (language.value === 'fr') return text
  if (catalog[text]) return catalog[text]
  for (const pattern of patterns) {
    const match = text.match(pattern.expression)
    if (match) {
      let result = pattern.translation
      pattern.names.forEach((name, index) => {
        result = result.split(name).join(tx(match[index + 1]))
      })
      return result
    }
  }
  return text
}
export function applyLanguage(lang: Language, persist = false) {
  language.value = lang
  if (typeof document !== 'undefined') {
    document.documentElement.lang = lang
    if (persist) document.cookie = `animan_lang=${lang};path=/;max-age=31536000;SameSite=Lax`
  }
  if (persist)
    try {
      writePreference('lang', lang)
    } catch {
      /* Session preference still applies. */
    }
}
