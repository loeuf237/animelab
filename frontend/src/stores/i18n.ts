import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/client'
import catalogs from '@/locales/catalogs.json'
import { language, applyLanguage, type Language } from '@/utils/locale'
import { isAndroidEngineBooting, waitForAndroidEngine } from '@/utils/platform'

export const useI18nStore = defineStore('i18n', () => {
  const currentLang = language
  const translations = ref<Record<string, string>>(catalogs[currentLang.value])
  const isLoaded = ref(false)
  let generation = 0
  async function load(lang: Language) {
    const current = ++generation
    translations.value = catalogs[lang]
    if (isAndroidEngineBooting()) {
      const engine = await waitForAndroidEngine()
      if (current !== generation || !engine.ready) {
        if (current === generation) isLoaded.value = true
        return
      }
    }
    try {
      const res = await api.getTranslations(lang)
      if (current === generation && res?.translations)
        translations.value = { ...catalogs[lang], ...res.translations }
    } catch {
      /* Bundled catalogs keep translations available offline. */
    } finally {
      if (current === generation) isLoaded.value = true
    }
  }
  async function init() {
    applyLanguage(currentLang.value)
    await load(currentLang.value)
  }
  async function changeLanguage(lang: Language) {
    if (lang !== 'fr' && lang !== 'en') return
    applyLanguage(lang, true)
    const loading = load(lang)
    try {
      await api.setLanguage(lang)
    } catch {
      /* Local preference remains authoritative. */
    }
    await loading
    // Concurrent server responses must not overwrite the latest local choice.
    applyLanguage(currentLang.value, true)
  }
  function t(key: string, params?: Record<string, string | number>): string {
    let text = translations.value[key] || key
    for (const [name, value] of Object.entries(params || {}))
      text = text.split(`{${name}}`).join(String(value))
    return text
  }
  return { currentLang, translations, isLoaded, init, changeLanguage, t }
})
