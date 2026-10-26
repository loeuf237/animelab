import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { language, readPreference, writePreference } from '@/utils/locale'
const defaults = ['french-manga', 'voir-anime', 'animepahe']
function readPinned(): string[] {
  try {
    const saved = JSON.parse(readPreference('pinned_sources') || 'null')
    return Array.isArray(saved) ? saved.filter((id) => typeof id === 'string') : defaults
  } catch {
    return defaults
  }
}
export const useSourcePreferences = defineStore('source-preferences', () => {
  const pinned = ref(readPinned())
  let saved: string | null = null
  try {
    saved = readPreference('default_source')
  } catch {
    /* Storage is optional. */
  }
  const preferred = ref(saved || '')
  const defaultSource = computed(
    () => preferred.value || (language.value === 'en' ? 'animepahe' : 'french-manga'),
  )
  function setDefault(id: string) {
    preferred.value = id
    try {
      writePreference('default_source', id)
    } catch {
      /* Keep the session choice. */
    }
  }
  function toggle(id: string) {
    pinned.value = pinned.value.includes(id)
      ? pinned.value.filter((item) => item !== id)
      : [...pinned.value, id]
    try {
      writePreference('pinned_sources', JSON.stringify(pinned.value))
    } catch {
      /* Preferences remain usable in memory. */
    }
  }
  return { pinned, toggle, defaultSource, setDefault }
})
