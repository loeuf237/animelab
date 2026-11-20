<template>
  <div class="sources-view">
    <template v-if="!sourceId">
      <header class="source-heading">
        <div>
          <h1>{{ tx('Explorer') }}</h1>
          <p>{{ tx('Parcourez vos catalogues et les extensions installées.') }}</p>
        </div>
        <router-link to="/extensions" class="btn btn-secondary">{{
          tx('Gérer les extensions')
        }}</router-link>
      </header>
      <ExplorerNavigation active="sources" />
      <input
        v-model="sourceQuery"
        class="input"
        type="search"
        :placeholder="tx('Filtrer les sources par nom ou langue')"
        :aria-label="tx('Filtrer les sources')"
      />
      <p v-if="listError" role="alert">
        {{ tx(listError) }}
        <button class="btn btn-secondary" @click="loadSources">{{ tx('Réessayer') }}</button>
      </p>
      <p v-if="listLoading" role="status">{{ tx('Chargement des sources…') }}</p>
      <section v-for="group in groups" :key="group.type" class="source-group">
        <h2>{{ tx(group.label) }}</h2>
        <div v-if="group.sources.length" class="source-list">
          <article v-for="item in group.sources" :key="item.id" class="source-card">
            <div class="source-identity">
              <ExtensionAvatar :name="item.name" />
              <button
                class="source-open"
                :disabled="!item.isEnabled"
                @click="openSource(item.id, defaultView(item))"
              >
                <h3>{{ tx(item.name) }}</h3>
                <p>{{ tx(item.lang.toUpperCase()) }} · {{ tx(host(item.baseUrl)) }}</p>
              </button>
              <details v-if="item.isEnabled" class="source-view-menu">
                <summary
                  :aria-label="tx(`Catalogues de ${item.name}`)"
                  :title="tx(`Catalogues de ${item.name}`)"
                >
                  <SlidersHorizontal :size="20" />
                </summary>
                <div class="source-card-actions">
                  <button
                    v-for="view in item.views"
                    :key="view.id"
                    class="btn btn-secondary"
                    @click="openSource(item.id, view.id)"
                  >
                    {{ tx(view.label) }}
                  </button>
                </div>
              </details>
              <router-link v-else to="/extensions" class="source-enable">{{
                tx('Activer')
              }}</router-link>
              <button
                type="button"
                class="source-pin"
                :aria-label="
                  tx(
                    `${preferences.pinned.includes(item.id) ? 'Désépingler' : 'Épingler'} ${item.name}`,
                  )
                "
                :aria-pressed="preferences.pinned.includes(item.id)"
                @click="preferences.toggle(item.id)"
              >
                <Star
                  :size="18"
                  :fill="preferences.pinned.includes(item.id) ? 'currentColor' : 'none'"
                  aria-hidden="true"
                />
              </button>
            </div>
          </article>
        </div>
        <p v-else class="source-empty">
          {{
            tx(
              group.type === 'native'
                ? 'Aucune source ne correspond.'
                : 'Aucune extension installée ne correspond. Ajoutez et activez une extension depuis Extensions.',
            )
          }}
        </p>
      </section>
    </template>

    <template v-else>
      <router-link to="/sources" class="source-back">{{ tx('← Toutes les sources') }}</router-link>
      <header class="source-heading">
        <div>
          <h1>{{ tx(currentSource?.name || 'Catalogue') }}</h1>
          <p>{{ tx(currentSource ? host(currentSource.baseUrl) : sourceId) }}</p>
        </div>
        <button class="btn btn-secondary" :disabled="loading" @click="refreshCatalogue">
          {{ tx('Actualiser') }}
        </button>
      </header>
      <p v-if="listError" role="alert">{{ tx(listError) }}</p>
      <template v-if="currentSource?.isEnabled">
        <nav class="catalogue-tabs" :aria-label="tx('Catalogues de la source')">
          <button
            v-for="view in currentSource.views"
            :key="view.id"
            class="btn"
            :class="mode === view.id ? 'btn-primary' : 'btn-secondary'"
            :aria-pressed="mode === view.id"
            @click="changeMode(view.id)"
          >
            {{ tx(view.label) }}
          </button>
        </nav>
        <form class="catalogue-controls" @submit.prevent="applyFilters">
          <div class="catalogue-search">
            <input
              v-model="query"
              class="input"
              type="search"
              :placeholder="
                tx(
                  selectedTags.length && !currentSource.multiTags
                    ? 'Rechercher dans la page filtrée'
                    : 'Rechercher un animé dans cette source',
                )
              "
              :aria-label="tx('Rechercher dans cette source')"
              @input="invalidatePending"
            /><button class="btn btn-primary" type="submit">{{ tx('Rechercher') }}</button>
          </div>
          <div class="catalogue-tools">
            <button
              class="btn btn-secondary"
              type="button"
              :aria-expanded="filtersOpen"
              @click="filtersOpen = !filtersOpen"
            >
              {{ tx('Genres et filtres')
              }}{{ tx(selectedTags.length ? ` (${selectedTags.length})` : '') }}
            </button>
            <label
              >{{ tx('Tri') }}
              <select v-model="order" @change="applyFilters">
                <option v-for="option in filters.orders" :key="option.id" :value="option.id">
                  {{ tx(option.label) }}
                </option>
              </select></label
            >
            <button
              v-if="selectedTags.length || order !== 'source'"
              type="button"
              class="btn btn-secondary"
              @click="resetFilters"
            >
              {{ tx('Réinitialiser') }}
            </button>
          </div>
          <div v-if="filtersOpen" class="source-filters">
            <p v-if="filtersLoading" role="status">{{ tx('Chargement des filtres…') }}</p>
            <p v-if="filtersError" role="alert">
              {{ tx(filtersError) }}
              <button class="btn btn-secondary" type="button" @click="loadFilters">
                {{ tx('Réessayer') }}
              </button>
            </p>
            <template v-if="nativeFilters.length">
              <NativeSourceFilters v-model="nativeFilters" />
              <button type="submit" class="btn btn-primary">
                {{ tx('Appliquer les filtres') }}
              </button>
            </template>
            <template v-else-if="filters.tags.length">
              <input
                v-model="tagQuery"
                type="search"
                class="input"
                :placeholder="tx('Trouver un genre ou un tag')"
                :aria-label="tx('Rechercher un tag')"
              />
              <p v-if="!currentSource.multiTags">
                {{ tx('Cette source accepte un filtre à la fois.') }}
              </p>
              <div v-for="group in tagGroups" :key="group.name" class="tag-group">
                <strong>{{ tx(group.name) }}</strong>
                <div class="tag-options">
                  <label
                    v-for="tag in group.tags"
                    :key="tag.id"
                    class="tag-option"
                    :class="{ selected: selectedTags.includes(tag.id) }"
                    ><input
                      type="checkbox"
                      :checked="selectedTags.includes(tag.id)"
                      @change="toggleTag(tag.id)"
                    />{{ tx(tag.label) }}</label
                  >
                </div>
              </div>
              <button type="submit" class="btn btn-primary">
                {{ tx('Appliquer les filtres') }}
              </button>
            </template>
            <p v-else-if="!filtersLoading && !filtersError">
              {{ tx('Cette source ne propose pas de filtres par genre ou tag dans ce catalogue.') }}
            </p>
          </div>
        </form>
        <VerificationPrompt :challenges="challenges" />
        <p v-if="pageError" class="catalogue-error" role="alert">
          {{ tx(pageError) }}
          <button class="btn btn-secondary" @click="refreshCatalogue">{{ tx('Réessayer') }}</button>
          <ProxyRotationButton
            :domain="host(currentSource.baseUrl)"
            :retry="
              async () => {
                refreshCatalogue()
              }
            "
          />
        </p>
        <p v-if="queryScope === 'page'" class="source-hint">
          {{
            tx(
              'Le titre est filtré dans la page affichée. Chargez la suite pour parcourir les autres résultats du tag.',
            )
          }}
        </p>
        <div class="catalogue-result-heading">
          <h2>{{ tx(currentSource.views.find((v) => v.id === mode)?.label) }}</h2>
          <span>
            <template v-if="loading && results.length">
              {{ tx(results.length) }} {{ tx('résultat(s) chargé(s)') }} · {{ tx('chargement…') }}
            </template>
            <template v-else-if="loading">
              {{ tx('Chargement du catalogue…') }}
            </template>
            <template v-else> {{ tx(results.length) }} {{ tx('résultat(s) chargé(s)') }} </template>
          </span>
        </div>
        <div v-if="loading" class="catalogue-progress-bar" aria-hidden="true">
          <span />
        </div>
        <SkeletonGrid
          v-if="loading && !results.length"
          :count="8"
          :label="tx('Chargement des animés en cours…')"
        />
        <div v-else-if="results.length || loading" class="anime-grid">
          <AnimeCard
            v-for="anime in results"
            :key="`${anime.source}:${anime.url}`"
            :anime="anime"
          />
          <SkeletonGrid v-if="loading" inline :count="4" />
        </div>
        <p
          v-if="!loading && !results.length && !pageError && !pageChallenges.length"
          class="source-empty"
        >
          {{
            tx(
              mode === 'search' && !query.trim() && !selectedTags.length
                ? 'Saisissez un titre pour lancer la recherche.'
                : 'Aucun résultat avec ces critères.',
            )
          }}
        </p>
        <p v-if="hasUnappliedFilters" class="source-hint">
          {{ tx('Appliquez vos critères pour actualiser les résultats.') }}
        </p>
        <button
          v-if="nextCursor && !hasUnappliedFilters"
          class="btn btn-secondary catalogue-more"
          :disabled="loading"
          @click="fetchPage(nextCursor, true)"
        >
          {{ tx(loading ? 'Chargement…' : 'Charger la suite') }}
        </button>
      </template>
      <p v-else-if="!listLoading" role="alert">
        {{ tx('Cette source est introuvable ou désactivée.') }}
        <router-link to="/extensions">{{ tx('Gérer les extensions') }}</router-link>
      </p>
    </template>
  </div>
</template>

<script setup lang="ts">
import { SlidersHorizontal, Star } from 'lucide-vue-next'
import ExplorerNavigation from '@/components/ExplorerNavigation.vue'
import ExtensionAvatar from '@/components/ExtensionAvatar.vue'
import SkeletonGrid from '@/components/SkeletonGrid.vue'
import { tx } from '@/utils/locale'
import { ref, computed, watch, onMounted, onUnmounted, onActivated, onDeactivated } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useSourcePreferences } from '@/stores/sourcePreferences'
import { api } from '@/api/client'
import { useVerificationStore, challengeFromError } from '@/stores/verification'
import AnimeCard from '@/components/AnimeCard.vue'
import VerificationPrompt from '@/components/VerificationPrompt.vue'
import ProxyRotationButton from '@/components/ProxyRotationButton.vue'
import NativeSourceFilters from '@/components/NativeSourceFilters.vue'
import type { NativeFilter } from '@/types/extensions'
import type { AnimeResult, CatalogueSource, CatalogueFilters, SourceChallenge } from '@/types'

defineOptions({ name: 'SourcesView' })
const preferences = useSourcePreferences()
const route = useRoute(),
  router = useRouter()
const verification = useVerificationStore()
const sources = ref<CatalogueSource[]>([]),
  sourceQuery = ref('')
const sourceId = computed(() => String(route.params.sourceId || ''))
const currentSource = computed(() => sources.value.find((s) => s.id === sourceId.value))
const mode = ref('latest'),
  query = ref(''),
  order = ref('source'),
  selectedTags = ref<string[]>([])
const filters = ref<CatalogueFilters>({
  tags: [],
  orders: [{ id: 'source', label: 'Ordre de la source' }],
})
const filtersOpen = ref(false),
  tagQuery = ref(''),
  filtersLoading = ref(false)
const nativeFilters = ref<NativeFilter[]>([])
const listLoading = ref(false),
  loading = ref(false),
  listError = ref(''),
  pageError = ref(''),
  filtersError = ref('')
const results = ref<AnimeResult[]>([]),
  nextCursor = ref<string | null>(null),
  queryScope = ref('catalogue')
const pageChallenges = ref<SourceChallenge[]>([]),
  filterChallenges = ref<SourceChallenge[]>([])
const challenges = computed(() => [...pageChallenges.value, ...filterChallenges.value])
const appliedCriteria = ref('')
const criteria = computed(() =>
  JSON.stringify([
    mode.value,
    query.value.trim(),
    order.value,
    [...selectedTags.value].sort(),
    nativeFilters.value,
  ]),
)
const hasUnappliedFilters = computed(() => criteria.value !== appliedCriteria.value)
let generation = 0,
  pageSequence = 0,
  filterSequence = 0,
  disposed = false
let pageAbort: AbortController | null = null
const loadedFiltersSource = ref('')
const groups = computed(() => {
  const visible = sources.value.filter((s) =>
    `${s.name} ${s.lang}`.toLocaleLowerCase().includes(sourceQuery.value.toLocaleLowerCase()),
  )
  const pinned = visible.filter((s) => preferences.pinned.includes(s.id))
  const remaining = visible.filter((s) => !preferences.pinned.includes(s.id))
  const labels: Record<string, string> = { fr: 'Français', en: 'English', all: 'Multilingue' }
  return [
    ...(pinned.length ? [{ type: 'pinned', label: 'Épinglées', sources: pinned }] : []),
    ...[...new Set(remaining.map((s) => s.lang))].sort().map((lang) => ({
      type: lang,
      label: labels[lang] || lang.toUpperCase(),
      sources: remaining
        .filter((s) => s.lang === lang)
        .sort((a, b) => a.name.localeCompare(b.name)),
    })),
    ...(!visible.length ? [{ type: 'empty', label: 'Sources', sources: [] }] : []),
  ]
})
const tagGroups = computed(() =>
  [...new Set(filters.value.tags.map((t) => t.group))]
    .map((name) => ({
      name,
      tags: filters.value.tags.filter(
        (t) =>
          t.group === name &&
          t.label.toLocaleLowerCase().includes(tagQuery.value.toLocaleLowerCase()),
      ),
    }))
    .filter((g) => g.tags.length),
)
function host(url: string) {
  try {
    return new URL(url).host
  } catch {
    return ''
  }
}
function invalidatePending() {
  pageSequence++
  pageAbort?.abort()
  pageAbort = null
  loading.value = false
  verification.clearPending('source-page')
  pageChallenges.value = []
}
async function loadSources() {
  listLoading.value = true
  listError.value = ''
  try {
    sources.value = (await api.getSources()).sources
  } catch (exc) {
    listError.value = exc instanceof Error ? exc.message : 'Impossible de charger les sources.'
  } finally {
    listLoading.value = false
  }
}
function defaultView(item: CatalogueSource) {
  return (
    ['popular', 'latest', 'catalogue', 'search'].find((mode) =>
      item.views.some((view) => view.id === mode),
    ) ||
    item.views[0]?.id ||
    'search'
  )
}
function openSource(id: string, view: string) {
  void router.push({ name: 'sources', params: { sourceId: id }, query: { mode: view } })
}
function applyFilters() {
  const selectedMode =
    (query.value.trim() || nativeFilters.value.length) &&
    !selectedTags.value.length &&
    sourceId.value !== 'voir-anime'
      ? 'search'
      : mode.value
  void router
    .push({
      name: 'sources',
      params: { sourceId: sourceId.value },
      query: {
        mode: selectedMode,
        q: query.value.trim() || undefined,
        order: order.value,
        tags: selectedTags.value.length ? selectedTags.value : undefined,
        nativeFilters: nativeFilters.value.length ? JSON.stringify(nativeFilters.value) : undefined,
      },
    })
    .then(() => {
      // Submitting unchanged criteria is an explicit retry.
      if (!loading.value) void fetchPage()
    })
}
function changeMode(value: string) {
  mode.value = value
  query.value = ''
  selectedTags.value = []
  order.value = 'source'
  nativeFilters.value = JSON.parse(JSON.stringify(filters.value.nativeFilters || []))
  applyFilters()
}
function toggleTag(id: string) {
  invalidatePending()
  if (selectedTags.value.includes(id)) {
    selectedTags.value = selectedTags.value.filter((t) => t !== id)
    return
  }
  if (!currentSource.value?.multiTags) {
    selectedTags.value = [id]
    return
  }
  const tagObj = filters.value.tags.find((t) => t.id === id)
  const groupMeta = tagObj
    ? (filters.value.groups || []).find((g) => g.name === tagObj.group)
    : undefined
  if (groupMeta?.single && tagObj) {
    const otherGroups = selectedTags.value.filter((tid) => {
      const other = filters.value.tags.find((t) => t.id === tid)
      return !other || other.group !== tagObj.group
    })
    selectedTags.value = [...otherGroups, id]
  } else {
    selectedTags.value = [...selectedTags.value, id]
  }
}
function resetFilters() {
  selectedTags.value = []
  order.value = 'source'
  nativeFilters.value = JSON.parse(JSON.stringify(filters.value.nativeFilters || []))
  applyFilters()
}
async function loadFilters() {
  const current = generation,
    source = sourceId.value,
    sequence = ++filterSequence
  verification.clearPending('source-filters')
  filtersLoading.value = true
  filtersError.value = ''
  filterChallenges.value = []
  try {
    const response = await api.getCatalogueFilters(source)
    if (current === generation && sequence === filterSequence && !disposed) {
      const wasUntouched = criteria.value === appliedCriteria.value
      filters.value = response
      loadedFiltersSource.value = source
      if (!nativeFilters.value.length && response.nativeFilters?.length) {
        nativeFilters.value = JSON.parse(JSON.stringify(response.nativeFilters))
        if (wasUntouched) appliedCriteria.value = criteria.value
      }
    }
  } catch (exc) {
    if (current !== generation || sequence !== filterSequence || disposed) return
    const challenge = challengeFromError(exc)
    if (challenge) {
      filterChallenges.value = [challenge]
      verification.waitForVerification('source-filters', [challenge], async () => {
        if (current === generation && !disposed) await loadFilters()
      })
    } else filtersError.value = exc instanceof Error ? exc.message : 'Filtres indisponibles.'
  } finally {
    if (current === generation && sequence === filterSequence) filtersLoading.value = false
  }
}
async function fetchPage(cursor?: string | null, append = false) {
  const current = generation,
    source = sourceId.value,
    sequence = ++pageSequence
  pageAbort?.abort()
  const controller = new AbortController()
  pageAbort = controller
  const params = {
    mode: mode.value,
    q: query.value.trim(),
    tags: [...selectedTags.value],
    order: order.value,
    cursor: cursor || undefined,
    nativeFilters: nativeFilters.value.length ? nativeFilters.value : undefined,
  }
  verification.clearPending('source-page')
  loading.value = true
  pageError.value = ''
  pageChallenges.value = []
  if (!append) {
    results.value = []
    nextCursor.value = null
  }
  const seenUrls = new Set(results.value.map((x) => x.url))
  try {
    const response = await api.browseCatalogueStream(source, params, {
      signal: controller.signal,
      onItems(batch) {
        if (current !== generation || sequence !== pageSequence || disposed) return
        const fresh: AnimeResult[] = []
        for (const item of batch) {
          if (item && item.url && !seenUrls.has(item.url)) {
            seenUrls.add(item.url)
            fresh.push(item)
          }
        }
        if (fresh.length) {
          results.value = [...results.value, ...fresh]
        }
      },
    })
    if (current !== generation || sequence !== pageSequence || disposed) return
    nextCursor.value = response.nextCursor
    queryScope.value = response.queryScope
  } catch (exc) {
    if (exc instanceof Error && exc.name === 'AbortError') return
    if (current !== generation || sequence !== pageSequence || disposed) return
    const challenge = challengeFromError(exc)
    if (challenge) {
      pageChallenges.value = [challenge]
      verification.waitForVerification('source-page', [challenge], async () => {
        if (current === generation && sequence === pageSequence && !disposed)
          await fetchPage(cursor, append)
      })
    } else pageError.value = exc instanceof Error ? exc.message : 'Catalogue indisponible.'
  } finally {
    if (pageAbort === controller) pageAbort = null
    if (current === generation && sequence === pageSequence) loading.value = false
  }
}
let lastReadPath = ''
async function readRoute() {
  if (route.name !== 'sources') return
  lastReadPath = route.fullPath
  const prevSource = loadedFiltersSource.value
  const targetSource = sourceId.value
  generation++
  pageSequence++
  filterSequence++
  pageAbort?.abort()
  pageAbort = null
  verification.clearPending('source-page')
  verification.clearPending('source-filters')
  pageChallenges.value = []
  filterChallenges.value = []
  pageError.value = ''
  filtersError.value = ''
  results.value = []
  nextCursor.value = null
  loading.value = false
  mode.value = typeof route.query.mode === 'string' ? route.query.mode : 'latest'
  query.value = typeof route.query.q === 'string' ? route.query.q : ''
  order.value = typeof route.query.order === 'string' ? route.query.order : 'source'
  selectedTags.value = (
    Array.isArray(route.query.tags) ? route.query.tags : route.query.tags ? [route.query.tags] : []
  ).filter((t): t is string => typeof t === 'string')
  nativeFilters.value = []
  if (typeof route.query.nativeFilters === 'string' && route.query.nativeFilters.length <= 32768) {
    try {
      const saved = JSON.parse(route.query.nativeFilters)
      if (Array.isArray(saved)) nativeFilters.value = saved
    } catch {
      /* Invalid URL state is replaced with the source defaults. */
    }
  }
  const sameSourceFiltersCached =
    Boolean(targetSource) &&
    prevSource === targetSource &&
    (filters.value.tags.length > 0 || (filters.value.nativeFilters?.length || 0) > 0)
  if (
    sameSourceFiltersCached &&
    !nativeFilters.value.length &&
    filters.value.nativeFilters?.length
  ) {
    nativeFilters.value = JSON.parse(JSON.stringify(filters.value.nativeFilters))
  } else if (!sameSourceFiltersCached) {
    loadedFiltersSource.value = ''
    filters.value = { tags: [], orders: [{ id: 'source', label: 'Ordre de la source' }] }
  }
  appliedCriteria.value = criteria.value
  if (currentSource.value?.isEnabled) {
    const needsFiltersBeforeFetch =
      selectedTags.value.length > 0 || order.value !== 'source' || nativeFilters.value.length > 0
    if (needsFiltersBeforeFetch && !sameSourceFiltersCached) {
      await loadFilters()
      appliedCriteria.value = criteria.value
    } else if (!sameSourceFiltersCached) {
      void loadFilters()
    }
    await fetchPage()
  }
}
function refreshCatalogue() {
  applyFilters()
}
watch(
  () => route.fullPath,
  () => {
    if (route.name === 'sources' && route.fullPath !== lastReadPath) void readRoute()
  },
)
onMounted(async () => {
  await loadSources()
  await readRoute()
})
let firstActivation = true,
  interruptedLoad = false
onActivated(async () => {
  if (firstActivation) {
    firstActivation = false
    return
  }
  await loadSources()
  if (route.name === 'sources' && interruptedLoad) {
    interruptedLoad = false
    await readRoute()
  }
})
onDeactivated(() => {
  interruptedLoad = loading.value || filtersLoading.value
  pageSequence++
  filterSequence++
  generation++
  pageAbort?.abort()
  pageAbort = null
  loading.value = false
  filtersLoading.value = false
  verification.clearPending('source-page')
  verification.clearPending('source-filters')
})
onUnmounted(() => {
  disposed = true
  generation++
  pageAbort?.abort()
  pageAbort = null
  verification.clearPending('source-page')
  verification.clearPending('source-filters')
})
</script>
<style scoped>
.sources-view {
  max-width: 1400px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 24px;
  padding: 8px 0 32px;
}
.input,
select {
  min-height: 42px;
  padding: 10px 14px;
  background: var(--input-bg, var(--panel));
  color: var(--text);
  border: 1px solid var(--line);
  border-radius: var(--radius-md, 10px);
  font: inherit;
  font-size: 14px;
}
.input {
  width: 100%;
}
.input:focus,
select:focus {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
}
.source-heading,
.source-identity,
.catalogue-result-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}
.source-heading h1 {
  margin: 0 0 8px;
  font-size: 30px;
}
.source-heading p,
.source-identity p,
.source-hint,
.source-empty {
  color: var(--muted);
  line-height: 1.5;
}
.source-group h2 {
  font-size: 19px;
  margin-bottom: 14px;
}
.source-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 370px), 1fr));
  gap: 16px;
}
.source-card {
  border: 1px solid var(--line);
  background: var(--panel);
  border-radius: var(--radius-lg);
  padding: 14px;
}
.source-identity {
  justify-content: flex-start;
  flex-wrap: nowrap;
}
.source-identity h3 {
  margin: 0 0 6px;
  font-size: 16px;
}
.source-identity p {
  margin: 0;
  font-size: 12px;
  overflow-wrap: anywhere;
}
.source-avatar {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: 44px;
  height: 44px;
  background: var(--panel-subtle);
  border-radius: 12px;
  font-weight: 800;
  color: var(--accent);
}
.source-card-actions,
.catalogue-tabs,
.catalogue-tools,
.tag-options {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  align-items: center;
}
.source-card-actions {
  margin-top: 18px;
}
.catalogue-controls {
  padding: 18px;
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  background: var(--panel);
}
.catalogue-search {
  display: flex;
  gap: 10px;
  margin-bottom: 14px;
}
.catalogue-search input {
  flex: 1;
  min-width: 0;
}
.catalogue-tools label {
  display: flex;
  gap: 10px;
  align-items: center;
}
.source-filters {
  margin-top: 18px;
  padding-top: 18px;
  border-top: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 14px;
}
.tag-group {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.tag-option {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
}
.tag-option.selected {
  border-color: var(--accent);
  background: var(--panel-subtle);
}
.anime-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 20px;
}
.catalogue-result-heading h2 {
  font-size: 20px;
}
.catalogue-result-heading span {
  color: var(--muted);
  font-size: 13px;
}
.catalogue-more {
  align-self: center;
}
.catalogue-error {
  color: var(--yellow, #d9a441);
}
.source-back {
  color: var(--muted);
  text-decoration: none;
}
@media (max-width: 600px) {
  .anime-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
  }
  .catalogue-search {
    flex-wrap: wrap;
  }
  .catalogue-search input {
    flex-basis: 100%;
  }
}
</style>

<style scoped>
.source-pin {
  flex-shrink: 0;
  width: 44px;
  height: 44px;
  border: 0;
  border-radius: 10px;
  background: var(--panel-subtle);
  color: var(--accent);
  font-size: 24px;
  cursor: pointer;
}
.source-identity > div {
  min-width: 0;
}
@media (max-width: 768px) {
  .source-avatar {
    display: none;
  }
  .sources-view {
    gap: 16px;
  }
  .source-card-actions {
    margin-top: 12px;
    gap: 8px;
  }
}
</style>

<style scoped>
@media (max-width: 768px) {
  .sources-view {
    padding: 0;
    gap: 16px;
  }
  .source-heading {
    gap: 10px;
  }
  .source-heading h1 {
    font-size: 24px;
    margin-bottom: 4px;
  }
  .source-heading p {
    margin: 0;
    font-size: 13px;
  }
  .source-heading .btn {
    min-height: 44px;
    font-size: 12px;
  }
  .source-group h2 {
    font-size: 16px;
    margin: 0 0 10px;
  }
  .source-list {
    gap: 10px;
  }
  .source-card {
    padding: 12px;
    border-radius: 14px;
  }
  .source-identity {
    gap: 10px;
  }
  .source-identity h3 {
    font-size: 15px;
    line-height: 1.4;
    overflow-wrap: anywhere;
    margin-bottom: 2px;
  }
  .source-pin {
    width: 44px;
    height: 44px;
  }
  .source-card-actions {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 6px;
    margin-top: 10px;
  }
  .source-card-actions .btn {
    padding: 6px 8px;
    border-radius: 10px;
    font-size: 12px;
    min-height: 44px;
    white-space: normal;
  }
  .catalogue-tabs {
    flex-wrap: nowrap;
    overflow-x: auto;
    padding: 4px;
    gap: 6px;
  }
  .catalogue-tabs .btn {
    flex-shrink: 0;
    min-height: 44px;
    padding: 6px 12px;
    font-size: 12px;
  }
  .catalogue-controls {
    padding: 12px;
  }
  .catalogue-tools {
    gap: 8px;
  }
  .catalogue-tools label {
    min-width: 0;
    flex-wrap: wrap;
  }
  .catalogue-tools select {
    max-width: 100%;
    min-width: 0;
  }
  .catalogue-search input {
    font-size: 16px;
  }
  .input[type='search'] {
    min-width: 0;
  }
}
</style>

<style scoped>
.source-list {
  display: flex;
  flex-direction: column;
  gap: 0;
}
.source-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 0.75rem;
  border: 0;
  border-bottom: 1px solid var(--line);
  border-radius: 0;
  background: transparent;
  padding: 1rem 0.25rem;
}
.source-identity {
  flex: 1;
  min-width: min(250px, 100%);
}
.source-card-actions {
  margin: 0;
}
.source-pin {
  order: 2;
  margin-left: auto;
}
.source-group h2 {
  color: var(--muted);
  font-size: 1rem;
}
@media (min-width: 1000px) {
  .source-list {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0 2rem;
  }
}
</style>

<style scoped>
.source-card {
  position: relative;
  padding: 0.75rem 0.25rem;
}
.source-open {
  flex: 1;
  min-width: 0;
  color: var(--text);
  background: none;
  border: 0;
  text-align: left;
  font: inherit;
  cursor: pointer;
  padding: 0.25rem 0;
}
.source-open h3,
.source-open p {
  overflow-wrap: anywhere;
}
.source-open:disabled {
  opacity: 0.55;
  cursor: default;
}
.source-view-menu > summary {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 44px;
  color: var(--muted);
  cursor: pointer;
  list-style: none;
}
.source-view-menu[open] .source-card-actions {
  position: absolute;
  right: 0.25rem;
  top: calc(100% - 5px);
  z-index: 3;
  display: grid;
  padding: 0.5rem;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 12px;
  box-shadow: 0 8px 24px #0003;
  max-width: calc(100% - 0.5rem);
}
.source-pin {
  flex-shrink: 0;
  margin-left: 0;
  width: 40px;
}
.source-identity {
  gap: 0.75rem;
  width: 100%;
  min-width: 0;
}
.source-enable {
  color: var(--accent);
  font-size: 0.8rem;
}
.catalogue-progress-bar {
  position: relative;
  height: 3px;
  border-radius: 999px;
  background: var(--surface-3);
  overflow: hidden;
}
.catalogue-progress-bar > span {
  position: absolute;
  inset: 0 auto 0 0;
  width: 38%;
  border-radius: 999px;
  background: var(--accent);
  animation: catalogueSlide 1.15s ease-in-out infinite;
}
@keyframes catalogueSlide {
  0% {
    transform: translateX(-100%);
  }
  100% {
    transform: translateX(300%);
  }
}
@media (prefers-reduced-motion: reduce) {
  .catalogue-progress-bar > span {
    animation: none;
    width: 100%;
    opacity: 0.55;
  }
}
</style>
