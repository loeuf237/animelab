<template>
  <div v-if="isOpen" class="palette-backdrop" @click="close">
    <div
      class="palette-card"
      role="dialog"
      aria-modal="true"
      :aria-label="tx('Recherche d’animés')"
      @click.stop
    >
      <div class="palette-header">
        <div class="palette-search-field">
          <svg viewBox="0 0 24 24" class="palette-search-icon">
            <circle cx="11" cy="11" r="7" />
            <path d="m20 20-4-4" />
          </svg>
          <input
            ref="inputRef"
            v-model="query"
            type="text"
            class="palette-search-input"
            :placeholder="tx('Rechercher un animé…')"
            :aria-label="tx('Titre de l’animé')"
            role="combobox"
            aria-autocomplete="list"
            :aria-expanded="results.length > 0"
            :aria-activedescendant="results.length ? `search-result-${activeIdx}` : undefined"
            aria-controls="search-results"
            autocomplete="off"
            spellcheck="false"
            @input="onInput"
            @keydown.down.prevent="navigateResults(1)"
            @keydown.up.prevent="navigateResults(-1)"
            @keydown.enter.prevent="selectActive"
            @keydown.esc="close"
          />
          <button
            v-if="query"
            type="button"
            class="palette-clear-btn"
            :aria-label="tx('Effacer la recherche')"
            @click="clearQuery"
          >
            ✕
          </button>
          <button
            type="button"
            class="palette-esc-badge palette-close-button"
            :aria-label="tx('Fermer la recherche')"
            @click="close"
          >
            {{ tx('Fermer') }}
          </button>
        </div>

        <div class="palette-source-bar">
          <SourceSelector
            :model-value="selectedSource"
            :sources="sourceOptions"
            @update:model-value="setSource"
          />
        </div>
      </div>

      <div class="palette-body">
        <VerificationPrompt :challenges="challenges" />
        <p v-if="error" class="palette-error" role="alert">{{ tx(error) }}</p>
        <p v-for="warning in warnings" :key="warning.source" class="palette-error">
          {{ tx(warning.source) }} : {{ tx(warning.message) }}
          <a v-if="warning.url" :href="warning.url" target="_blank" rel="noopener noreferrer">{{
            tx('Ouvrir le site')
          }}</a>
          <ProxyRotationButton
            v-if="warning.domain"
            :domain="warning.domain"
            :retry="executeSearch"
          />
        </p>
        <!-- Spinner -->
        <div v-if="isLoading" class="palette-loading" role="status">
          <div class="spinner"></div>
          <span>{{ tx('Recherche en cours…') }}</span>
        </div>

        <!-- Results List -->
        <div
          v-else-if="results.length > 0"
          id="search-results"
          role="listbox"
          :aria-label="tx('Résultats de recherche')"
          class="palette-results-list"
        >
          <button
            v-for="(item, idx) in results"
            type="button"
            :key="item.url"
            :id="`search-result-${idx}`"
            role="option"
            :aria-selected="activeIdx === idx"
            tabindex="-1"
            class="palette-result-item"
            :class="{ 'is-active': activeIdx === idx }"
            @click="openAnime(item)"
            @mouseenter="activeIdx = idx"
          >
            <img :src="item.imageUrl || '/static/placeholder.jpg'" class="palette-thumb" alt="" />
            <div class="palette-item-info">
              <span class="palette-item-title">{{ tx(item.title) }}</span>
              <div class="palette-item-meta">
                <span class="badge badge-source">{{ tx(item.source) }}</span>
                <span v-if="item.latestEpisode || item.episodeInfo" class="palette-item-ep">
                  {{ tx(item.latestEpisode || item.episodeInfo) }}
                </span>
                <span v-if="item.type" class="palette-item-type">{{ tx(item.type) }}</span>
              </div>
            </div>
            <span class="palette-enter-hint">{{ tx('Entrée ↵') }}</span>
          </button>
        </div>

        <!-- Empty State -->
        <div
          v-else-if="hasSearched && !challenges.length && !error && !warnings.length"
          class="palette-empty-hint"
        >
          <p>
            {{ tx('Aucun résultat trouvé pour "') }}{{ tx(query) }}{{ tx('" sur cette source.') }}
          </p>
        </div>

        <!-- Initial Hint -->
        <div v-else-if="!hasSearched" class="palette-empty-hint">
          <p>{{ tx('Tapez au moins 2 lettres pour rechercher dans la sélection de sources.') }}</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { tx } from '@/utils/locale'
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useSourcePreferences } from '@/stores/sourcePreferences'
import { useSearchContext } from '@/stores/searchContext'
import { api } from '@/api/client'
import VerificationPrompt from './VerificationPrompt.vue'
import ProxyRotationButton from './ProxyRotationButton.vue'
import SourceSelector from './SourceSelector.vue'
import { useVerificationStore, challengeFromError } from '@/stores/verification'
import type { AnimeResult, SourceChallenge, CatalogueSource } from '@/types'

const props = defineProps<{ isOpen: boolean; initialQuery?: string; initialSource?: string }>()
const emit = defineEmits<{ (e: 'close'): void }>()
const router = useRouter()
const searchContext = useSearchContext()
const verification = useVerificationStore()
const query = ref('')
const preferences = useSourcePreferences()
const selectedSource = ref(preferences.defaultSource)
watch(
  () => preferences.defaultSource,
  (source) => {
    if (!hasSearched.value) selectedSource.value = source
  },
)
const results = ref<AnimeResult[]>([])
const challenges = ref<SourceChallenge[]>([])
const warnings = ref<{ source: string; message: string; url?: string; domain?: string }[]>([])
const enabledExtensions = ref<CatalogueSource[]>([])
const error = ref('')
const isLoading = ref(false)
const hasSearched = ref(false)
const activeIdx = ref(0)
const inputRef = ref<HTMLInputElement | null>(null)
const sourceOptions = computed(() => [
  { id: 'french-manga', name: 'French-Manga' },
  { id: 'voir-anime', name: 'VoirAnime' },
  { id: 'animepahe', name: 'AnimePahe' },
  ...enabledExtensions.value.map((source) => ({
    id: source.id,
    name: source.name.replace(/^Aniyomi:\s*/i, ''),
  })),
])
let returnFocus: HTMLElement | null = null
let previousOverflow = ''
let interrupted = false
let debounceTimer: ReturnType<typeof setTimeout> | undefined
let sequence = 0

function invalidate() {
  sequence++
  clearTimeout(debounceTimer)
  verification.clearPending('palette-search')
  challenges.value = []
  warnings.value = []
  error.value = ''
  isLoading.value = false
}
watch(
  () => props.isOpen,
  async (open) => {
    if (open) {
      returnFocus = document.activeElement as HTMLElement
      previousOverflow = document.body.style.overflow
      document.body.style.overflow = 'hidden'
      const changed =
        (props.initialQuery !== undefined && props.initialQuery !== query.value) ||
        (props.initialSource !== undefined && props.initialSource !== selectedSource.value)
      if (changed) {
        invalidate()
        results.value = []
        hasSearched.value = false
      }
      if (props.initialQuery !== undefined) query.value = props.initialQuery
      if (props.initialSource !== undefined) selectedSource.value = props.initialSource
      await nextTick()
      inputRef.value?.focus()
      void api
        .getSources()
        .then((res) => {
          enabledExtensions.value = res.sources.filter((s) => s.isEnabled && s.type === 'imported')
        })
        .catch(() => {})
      if (
        query.value.trim().length >= 2 &&
        (changed || interrupted || !hasSearched.value || challenges.value.length)
      )
        void executeSearch()
      interrupted = false
    } else {
      interrupted = interrupted || isLoading.value
      sequence++
      clearTimeout(debounceTimer)
      isLoading.value = false
      verification.clearPending('palette-search')
      document.body.style.overflow = previousOverflow
      await nextTick()
      if (returnFocus?.isConnected) returnFocus.focus()
    }
  },
)
function close() {
  interrupted = interrupted || isLoading.value
  sequence++
  clearTimeout(debounceTimer)
  isLoading.value = false
  verification.clearPending('palette-search')
  emit('close')
}
function clearQuery() {
  query.value = ''
  results.value = []
  hasSearched.value = false
  invalidate()
  inputRef.value?.focus()
}
function setSource(src: string) {
  invalidate()
  selectedSource.value = src
  preferences.setDefault(src)
  results.value = []
  if (query.value.trim().length >= 2) void executeSearch()
}
function onInput() {
  invalidate()
  results.value = []
  if (query.value.trim().length < 2) {
    hasSearched.value = false
    return
  }
  debounceTimer = setTimeout(() => void executeSearch(), 300)
}
async function executeSearch() {
  if (!query.value.trim() || !props.isOpen) return
  const current = ++sequence
  const requestedQuery = query.value.trim(),
    source = selectedSource.value
  verification.clearPending('palette-search')
  isLoading.value = true
  hasSearched.value = true
  activeIdx.value = 0
  error.value = ''
  try {
    const response = await api.searchAnimeDetailed(requestedQuery, source)
    if (current !== sequence || !props.isOpen) return
    results.value = response.results
    challenges.value = response.challenges
    warnings.value = response.errors
    verification.waitForVerification(
      'palette-search',
      [
        ...response.challenges,
        ...response.errors.flatMap((e) => (e.domain ? [{ domain: e.domain }] : [])),
      ],
      async () => {
        if (current === sequence && props.isOpen) await executeSearch()
      },
    )
  } catch (exc) {
    if (current !== sequence || !props.isOpen) return
    const challenge = challengeFromError(exc)
    results.value = []
    if (challenge) {
      challenges.value = [challenge]
      verification.waitForVerification('palette-search', [challenge], async () => {
        if (current === sequence && props.isOpen) await executeSearch()
      })
    } else error.value = exc instanceof Error ? exc.message : 'La recherche a échoué.'
  } finally {
    if (current === sequence) isLoading.value = false
  }
}
function navigateResults(delta: number) {
  const next = activeIdx.value + delta
  if (next >= 0 && next < results.value.length) {
    activeIdx.value = next
    void nextTick(() =>
      document
        .querySelector('.palette-result-item.is-active')
        ?.scrollIntoView({ block: 'nearest' }),
    )
  }
}
function selectActive() {
  if (results.value[activeIdx.value]) openAnime(results.value[activeIdx.value]!)
  else if (!isLoading.value) void executeSearch()
}
function openAnime(item: AnimeResult) {
  searchContext.markDetail(item.url)
  close()
  void router.push({
    path: '/anime',
    query: { url: item.url, source: item.source || 'french-manga' },
  })
}
function onEscape(event: KeyboardEvent) {
  if (!props.isOpen) return
  if (event.key === 'Escape') close()
  if (event.key === 'Tab') {
    const elements = [
      ...document.querySelectorAll<HTMLElement>(
        '.palette-card input, .palette-card button:not(:disabled), .palette-card select',
      ),
    ].filter((el) => el.getClientRects().length)
    const first = elements[0],
      last = elements[elements.length - 1]
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      last?.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first?.focus()
    }
  }
}
onMounted(() => window.addEventListener('keydown', onEscape))
onUnmounted(() => {
  invalidate()
  if (props.isOpen) document.body.style.overflow = previousOverflow
  window.removeEventListener('keydown', onEscape)
})
</script>

<style scoped>
.palette-close-button {
  display: inline-flex !important;
}
.palette-result-item {
  width: 100%;
  border: 0;
  background: transparent;
  color: inherit;
  text-align: left;
  font: inherit;
}
.palette-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(8, 12, 22, 0.75);
  backdrop-filter: blur(12px);
  z-index: 500;
  display: flex;
  justify-content: center;
  align-items: flex-start;
  padding-top: min(12vh, 120px);
}

.palette-card {
  width: min(720px, 94vw);
  max-height: 75vh;
  display: flex;
  flex-direction: column;
  background: var(--panel);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow);
  overflow: hidden;
}

.palette-header {
  padding: 18px 20px 14px;
  border-bottom: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.palette-search-field {
  position: relative;
  display: flex;
  align-items: center;
}

.palette-search-icon {
  position: absolute;
  left: 14px;
  width: 20px;
  height: 20px;
  color: var(--muted);
  pointer-events: none;
}

.palette-search-input {
  width: 100%;
  height: 48px;
  background: var(--input-bg);
  border: 1px solid var(--input-border);
  border-radius: var(--radius-pill);
  color: var(--text);
  font-size: 16px;
  padding: 0 90px 0 46px;
  outline: none;
}

.palette-search-input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-container);
}

.palette-clear-btn {
  position: absolute;
  right: 68px;
  background: none;
  border: none;
  color: var(--muted);
  font-size: 14px;
  cursor: pointer;
}

.palette-esc-badge {
  position: absolute;
  right: 14px;
  background: var(--panel-subtle);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  padding: 2px 8px;
  font-size: 11px;
  color: var(--faint);
  font-weight: 700;
  cursor: pointer;
}

.palette-tabs-bar {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding-bottom: 4px;
}

.palette-tab-chip {
  padding: 4px 12px;
  border-radius: var(--radius-pill);
  background: var(--panel-subtle);
  border: 1px solid var(--line);
  color: var(--muted);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
}

.palette-tab-chip.active {
  background: var(--accent-container);
  color: var(--on-accent-container);
  border-color: var(--accent);
}

.palette-error {
  padding: 12px 16px;
  color: var(--yellow, #d9a441);
}
.palette-body > .verification-prompt {
  margin: 12px;
}
.palette-body {
  flex: 1;
  overflow-y: auto;
  min-height: 240px;
  max-height: 55vh;
  padding: 12px 14px;
}

.palette-loading,
.palette-empty-hint {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 220px;
  color: var(--muted);
  gap: 12px;
  font-size: 14px;
}

.palette-results-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.palette-result-item {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 10px 14px;
  border-radius: var(--radius);
  cursor: pointer;
  transition: all var(--transition);
}

.palette-result-item:hover,
.palette-result-item.is-active {
  background: var(--accent-container);
}

.palette-thumb {
  width: 40px;
  height: 56px;
  border-radius: 6px;
  object-fit: cover;
  background: var(--surface);
  flex-shrink: 0;
}

.palette-item-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
  overflow: hidden;
}

.palette-item-title {
  font-weight: 700;
  font-size: 14px;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.palette-item-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.palette-item-ep {
  color: var(--accent);
  font-weight: 600;
}

.palette-item-type {
  color: var(--faint);
}

.palette-enter-hint {
  font-size: 11px;
  color: var(--faint);
  font-weight: 600;
  opacity: 0;
  transition: opacity var(--transition);
}

.palette-result-item.is-active .palette-enter-hint {
  opacity: 1;
}

/* One flex row owns spacing; icons and actions do not overlap the input. */
.palette-search-field {
  padding: 4px 6px 4px 14px;
  gap: 8px;
  min-width: 0;
  background: var(--input-bg);
  border: 1px solid var(--input-border);
  border-radius: var(--radius-pill);
}
.palette-search-field:focus-within {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-container);
}
.palette-search-icon {
  position: static;
  transform: none;
  flex: 0 0 20px;
}
.palette-search-input {
  flex: 1;
  width: 0;
  min-width: 0;
  height: 40px;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
}
.palette-search-input:focus {
  box-shadow: none;
}
.palette-search-input:focus-visible {
  outline: none !important;
}
.palette-clear-btn,
.palette-close-button {
  position: static;
  flex-shrink: 0;
  min-width: 40px;
  min-height: 40px;
  display: inline-flex !important;
  align-items: center;
  justify-content: center;
}
.palette-close-button {
  padding: 0 10px;
  border-radius: var(--radius-pill);
  font-size: 12px;
  color: var(--text);
}
</style>
