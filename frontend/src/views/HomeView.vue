<template>
  <div class="home-container">
    <!-- Native Media Header & Quick Status -->
    <header class="page-header home-top-header fade-in">
      <div>
        <h1 class="page-title">{{ tx('Accueil') }}</h1>
        <p class="page-sub">
          {{ tx('Vos séries suivies, activités récentes et dernières sorties.') }}
        </p>
      </div>

      <div class="home-header-tools">
        <div class="native-summary-pills">
          <router-link to="/library" class="metric-pill">
            <strong>{{ tx(animeStore.homeFeed ? favoritesCount : '…') }}</strong>
            <span>{{ tx('Favoris') }}</span>
          </router-link>
          <router-link to="/sources" class="metric-pill">
            <strong>{{ tx(animeStore.homeFeed ? activeSourcesCount : '…') }}</strong>
            <span>{{ tx('Sources') }}</span>
          </router-link>
          <router-link to="/downloads" class="metric-pill">
            <strong>{{ tx(downloadStore.stats.activeCount) }}</strong>
            <span>{{ tx('Actifs') }}</span>
          </router-link>
        </div>

        <button type="button" class="btn btn-primary" @click="emitOpenPalette">
          <Search :size="16" aria-hidden="true" />
          <span>{{ tx('Rechercher') }}</span>
        </button>
      </div>
    </header>

    <!-- Continue / Recent Activity Shelf -->
    <section v-if="recentHistory.length > 0" class="section fade-in" style="margin-top: 0">
      <div class="home-section-head">
        <h2 class="section-title" style="margin: 0">
          <Clock :size="18" aria-hidden="true" />
          {{ tx('Reprendre et récents') }}
        </h2>
        <router-link to="/history" class="btn btn-sm">{{ tx('Historique') }}</router-link>
      </div>

      <div class="native-shelf-row">
        <router-link
          v-for="item in recentHistory.slice(0, 8)"
          :key="`${item.id || item.animeUrl}-${item.episodeNumber}`"
          :to="
            item.animeUrl
              ? {
                  path: '/anime',
                  query: { url: item.animeUrl, source: item.source || 'french-manga' },
                }
              : '/history'
          "
          class="native-shelf-card"
        >
          <div class="shelf-card-top">
            <span class="badge badge-source">{{ tx(item.source || 'Animé') }}</span>
            <span v-if="item.episodeNumber" class="ep-badge">
              {{ tx('Ép.') }} {{ tx(item.episodeNumber) }}
            </span>
          </div>
          <strong class="shelf-card-title">{{
            tx(item.animeName || item.animeTitle || 'Animé')
          }}</strong>
          <span class="shelf-card-sub">{{ tx(item.status || 'Récent') }}</span>
        </router-link>
      </div>
    </section>

    <!-- Quick Favorites Section -->
    <section v-if="favorites.length > 0" class="section fade-in" style="margin-top: 0">
      <div class="home-section-head">
        <h2 class="section-title" style="margin: 0">
          <Bookmark :size="18" aria-hidden="true" />
          {{ tx('Accès rapide aux favoris') }}
        </h2>
        <router-link to="/library" class="btn btn-sm">{{ tx('Voir tout') }}</router-link>
      </div>
      <div class="results-grid">
        <PosterCard
          v-for="fav in favorites.slice(0, 10)"
          :key="fav.url"
          :title="fav.title"
          :image-url="fav.imageUrl"
          :to="{ path: '/anime', query: { url: fav.url, source: fav.source || 'french-manga' } }"
          :subtitle="fav.source || 'french-manga'"
          :favorite="true"
          :auto-download="fav.autoDownload"
        />
      </div>
    </section>

    <!-- Latest Releases Section with Source Chips -->
    <section class="section fade-in" style="margin-top: 0">
      <p v-if="animeStore.error" role="alert">
        {{ tx(animeStore.error) }}
        <button class="btn" @click="refreshFeed">{{ tx('Réessayer') }}</button>
      </p>

      <div class="releases-tabs-header home-releases-head">
        <h2 class="section-title">
          <Sparkles :size="18" aria-hidden="true" />
          {{ tx('Dernières Sorties') }}
        </h2>
        <div class="home-releases-controls">
          <SourceSelector
            v-model="releaseTab"
            :sources="sourceOptions"
            :label="tx('Sorties de')"
            :include-all="false"
            @update:model-value="preferences.setDefault"
          />
          <button
            type="button"
            class="icon-button"
            :title="tx('Actualiser le flux')"
            :aria-label="tx('Actualiser le flux')"
            @click="refreshFeed"
          >
            <RefreshCw :size="16" aria-hidden="true" />
          </button>
        </div>
      </div>

      <div class="source-filter-chips" role="tablist" :aria-label="tx('Sources')">
        <button
          v-for="src in sourceOptions"
          :key="src.id"
          type="button"
          role="tab"
          class="source-chip-btn"
          :class="{ active: releaseTab === src.id }"
          :aria-selected="releaseTab === src.id"
          @click="selectReleaseSource(src.id)"
        >
          {{ tx(src.name) }}
        </button>
      </div>

      <p v-if="feedChallenges.length" class="source-feed-notice">
        {{
          tx(
            'Cette source demande une vérification. Lancez une recherche pour voir les options d’accès.',
          )
        }}
        <button class="btn btn-secondary btn-sm" @click="emit('open-palette', '', releaseTab)">
          {{ tx('Rechercher') }}
        </button>
      </p>
      <p v-for="warning in feedErrors" :key="warning.source" role="alert">
        {{ tx(warning.message) }}
        <a v-if="warning.url" :href="warning.url" target="_blank" rel="noopener noreferrer">{{
          tx('Ouvrir le site')
        }}</a>
        <button class="btn" @click="refreshFeed">{{ tx('Réessayer') }}</button>
        <ProxyRotationButton v-if="warning.domain" :domain="warning.domain" :retry="refreshFeed" />
      </p>

      <!-- Releases Content -->
      <SkeletonGrid
        v-if="isLoadingReleases"
        :count="10"
        :label="tx('Chargement des dernières sorties…')"
      />

      <div v-else-if="currentReleases.length > 0" class="results-grid animate-fade-in">
        <PosterCard
          v-for="anime in currentReleases"
          :key="anime.url"
          :title="anime.title"
          :image-url="anime.imageUrl"
          :to="{ path: '/anime', query: { url: anime.url, source: anime.source || releaseTab } }"
          :subtitle="anime.type || 'Anime'"
          :version="anime.version"
          :episode-info="anime.latestEpisode || anime.episodeInfo"
        />
      </div>

      <div
        v-else-if="!feedChallenges.length && !feedErrors.length && !animeStore.error"
        class="empty-state"
      >
        <h3>{{ tx('Aucune sortie trouvée pour cette source') }}</h3>
        <p>{{ tx('Actualisez le flux ou essayez une autre source ci-dessus.') }}</p>
        <button class="btn btn-primary" style="margin-top: 12px" @click="refreshFeed">
          {{ tx('Actualiser le flux') }}
        </button>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { Bookmark, Clock, RefreshCw, Search, Sparkles } from 'lucide-vue-next'
import { language, tx } from '@/utils/locale'
import { ref, computed, watch, onMounted, onActivated } from 'vue'
import { useSourcePreferences } from '@/stores/sourcePreferences'
import { useDownloadStore } from '@/stores/downloads'
import SourceSelector from '@/components/SourceSelector.vue'
import ProxyRotationButton from '@/components/ProxyRotationButton.vue'
import PosterCard from '@/components/PosterCard.vue'
import SkeletonGrid from '@/components/SkeletonGrid.vue'
import { useAnimeStore } from '@/stores/anime'
import type { AnimeResult, FavoriteItem, HistoryItem } from '@/types'

defineOptions({ name: 'HomeView' })
const animeStore = useAnimeStore()
const downloadStore = useDownloadStore()
let firstActivation = true
onActivated(() => {
  if (firstActivation) firstActivation = false
  else if (!animeStore.homeFeed) void animeStore.fetchHomeFeed()
})

const preferences = useSourcePreferences()
const selectedSource = ref(preferences.defaultSource)
const releaseTab = ref(
  preferences.defaultSource === 'all'
    ? language.value === 'en'
      ? 'animepahe'
      : 'french-manga'
    : preferences.defaultSource,
)
watch(
  () => preferences.defaultSource,
  (source) => {
    selectedSource.value = source
    if (source !== 'all') releaseTab.value = source
  },
)

const emit = defineEmits<{
  (e: 'open-palette', q?: string, source?: string): void
}>()

onMounted(() => {
  animeStore.fetchHomeFeed()
})

const isLoadingReleases = computed(() => {
  return animeStore.isLoading && !animeStore.homeFeed
})

const enabledExtensions = computed(() => {
  return animeStore.homeFeed?.enabledExtensions || []
})

const favorites = computed<FavoriteItem[]>(() => {
  return animeStore.homeFeed?.favorites || []
})

const recentHistory = computed<HistoryItem[]>(() => {
  return animeStore.homeFeed?.recentHistory || []
})

const favoritesCount = computed(() => {
  return favorites.value.length
})

const activeSourcesCount = computed(() => {
  return 3 + enabledExtensions.value.length
})

const feedChallenges = computed(() =>
  (animeStore.homeFeed?.challenges || []).filter((c) => c.source === releaseTab.value),
)
const feedErrors = computed(() =>
  (animeStore.homeFeed?.errors || []).filter((c) => c.source === releaseTab.value),
)
const currentReleases = computed<AnimeResult[]>(() => {
  const feed = animeStore.homeFeed
  if (!feed) return []

  if (feed.latestReleases && feed.latestReleases[releaseTab.value]) {
    return feed.latestReleases[releaseTab.value]
  }
  if (releaseTab.value === 'french-manga') {
    return feed.latestFrenchManga || []
  }
  if (releaseTab.value === 'voir-anime') {
    return feed.latestVoirAnime || []
  }
  if (releaseTab.value === 'animepahe') {
    return feed.latestAnimePahe || []
  }
  if (feed.extensionsReleases && feed.extensionsReleases[releaseTab.value]) {
    return feed.extensionsReleases[releaseTab.value].releases || []
  }

  return []
})

const sourceOptions = computed(() => [
  { id: 'french-manga', name: 'French-Manga' },
  { id: 'voir-anime', name: 'VoirAnime' },
  { id: 'animepahe', name: 'AnimePahe' },
  ...enabledExtensions.value
    .filter((ext) => ext.supportsLatest !== false)
    .map((ext) => ({ id: String(ext.id || ext.pkg), name: ext.name.replace(/^Aniyomi:\s*/i, '') })),
])

function selectReleaseSource(id: string) {
  releaseTab.value = id
  preferences.setDefault(id)
}

function emitOpenPalette() {
  emit('open-palette', '', selectedSource.value)
}

async function refreshFeed() {
  await animeStore.fetchHomeFeed(true)
}
</script>

<style scoped>
.home-container {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.home-top-header {
  margin-bottom: 0;
  flex-wrap: wrap;
}

.home-header-tools {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.home-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.home-releases-head {
  margin-bottom: 12px;
}

.home-releases-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}

.shelf-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}

.shelf-card-title {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--text);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.shelf-card-sub {
  font-size: 11.5px;
  color: var(--muted);
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 20px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  color: var(--muted);
  text-align: center;
}
</style>
