<template>
  <div class="library-container">
    <div class="page-header">
      <div>
        <h1 class="page-title">{{ tx('Ma Bibliothèque') }}</h1>
        <p class="page-sub">
          {{
            tx('Gérez vos séries favorites et la surveillance automatique des nouveaux épisodes.')
          }}
        </p>
      </div>

      <div style="display: flex; gap: 10px">
        <details v-if="favorites.length" class="library-options">
          <summary class="btn">Options</summary>
          <button type="button" class="btn btn-danger" @click="clearDialogOpen = true">
            {{ tx('Vider la bibliothèque') }}
          </button>
        </details>
        <button class="btn btn-primary" @click="libraryStore.fetchFavorites">
          {{ tx('Actualiser') }}
        </button>
      </div>
    </div>

    <!-- Title filter: local only, never touches the store -->
    <div class="library-filter">
      <label class="sr-only" for="library-filter-input">{{
        tx('Filtrer les titres de la bibliothèque')
      }}</label>
      <input
        id="library-filter-input"
        v-model="query"
        type="search"
        class="library-filter-input"
        :placeholder="tx('Filtrer par titre')"
        :aria-label="tx('Filtrer les titres de la bibliothèque')"
      />
      <button
        v-if="query"
        type="button"
        class="icon-button library-filter-clear"
        :title="tx('Effacer le filtre')"
        :aria-label="tx('Effacer le filtre')"
        @click="query = ''"
      >
        ✕
      </button>
    </div>

    <!-- Compact Metrics Bar -->
    <div class="native-summary-pills" style="margin-bottom: 18px">
      <div class="metric-pill">
        <strong>{{ tx(favorites.length) }}</strong>
        <span>{{ tx('Séries suivies') }}</span>
      </div>
      <div class="metric-pill">
        <strong>{{ tx(autoDownloadCount) }}</strong>
        <span>{{ tx('Téléchargement auto actif') }}</span>
      </div>
      <div class="metric-pill">
        <strong>{{ tx(distinctSourcesCount) }}</strong>
        <span>{{ tx('Sources représentées') }}</span>
      </div>
    </div>

    <p v-if="libraryStore.favoritesError" role="alert">{{ tx(libraryStore.favoritesError) }}</p>
    <p v-if="libraryStore.isLoading && !favorites.length" role="status">
      {{ tx('Chargement de la bibliothèque…') }}
    </p>
    <!-- Empty State -->
    <div
      v-if="!libraryStore.isLoading && !libraryStore.favoritesError && favorites.length === 0"
      class="empty-state"
    >
      <h3>{{ tx('Aucun animé dans votre bibliothèque') }}</h3>
      <p>
        {{
          tx('Parcourez les sorties ou utilisez la recherche pour ajouter des séries en favoris.')
        }}
      </p>
      <router-link to="/" class="btn btn-primary" style="margin-top: 14px">{{
        tx('Découvrir les animés')
      }}</router-link>
      <button
        type="button"
        class="btn btn-secondary"
        style="margin-top: 12px"
        @click="startup.screen = 'theme'"
      >
        {{ tx('Guide de démarrage') }}
      </button>
    </div>

    <!-- No match for the current filter -->
    <div v-else-if="visibleFavorites.length === 0" class="empty-state" role="status">
      <h3>{{ tx('Aucune série ne correspond à votre filtre') }}</h3>
      <p>{{ tx('La bibliothèque est inchangée : seul l’affichage est filtré.') }}</p>
      <button type="button" class="btn" style="margin-top: 14px" @click="query = ''">
        {{ tx('Effacer le filtre') }}
      </button>
    </div>

    <!-- Favorites Grid -->
    <div v-else class="results-grid animate-fade-in">
      <PosterCard
        v-for="fav in visibleFavorites"
        :key="fav.url"
        :title="fav.title"
        :image-url="fav.imageUrl"
        :to="{ path: '/anime', query: { url: fav.url, source: fav.source || 'french-manga' } }"
        :subtitle="fav.source || 'french-manga'"
        :favorite="true"
        :auto-download="fav.autoDownload"
      >
        <template #footer>
          <div style="width: 100%">
            <div
              style="display: flex; justify-content: space-between; align-items: center; gap: 8px"
            >
              <label class="native-switch" style="font-size: 12px; color: var(--muted)">
                <input type="checkbox" :checked="fav.autoDownload" @change="toggleAuto(fav)" />
                <span class="native-switch-track" aria-hidden="true"></span>
                <span>Auto-DL</span>
              </label>

              <button
                class="icon-button"
                style="width: 34px; height: 34px"
                :title="tx('Retirer de la bibliothèque')"
                :aria-label="tx(`Retirer ${fav.title} de la bibliothèque`)"
                @click="removeFav(fav)"
              >
                <X :size="15" aria-hidden="true" />
              </button>
            </div>
            <AutoDownloadPreferences v-if="fav.autoDownload" :favorite="fav" />
          </div>
        </template>
      </PosterCard>
    </div>
    <ConfirmDialog
      :open="clearDialogOpen"
      :title="tx('Vider la bibliothèque ?')"
      :confirm-label="tx('Vider')"
      :busy="clearing"
      danger
      @cancel="clearDialogOpen = false"
      @confirm="clearAll"
      ><p>
        {{
          tx(
            'Les séries seront retirées de votre bibliothèque. Les fichiers téléchargés seront conservés.',
          )
        }}
      </p></ConfirmDialog
    >
  </div>
</template>

<script setup lang="ts">
import { X } from 'lucide-vue-next'
import { tx } from '@/utils/locale'
import { useStartupStore } from '@/stores/startup'
const startup = useStartupStore()
import { ref, computed, onMounted, onActivated } from 'vue'
import { useLibraryStore } from '@/stores/library'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import AutoDownloadPreferences from '@/components/AutoDownloadPreferences.vue'
import PosterCard from '@/components/PosterCard.vue'
import { useNotifications } from '@/stores/notifications'
import type { FavoriteItem } from '@/types'

defineOptions({ name: 'LibraryView' })
const libraryStore = useLibraryStore(),
  notifications = useNotifications()
const clearDialogOpen = ref(false),
  clearing = ref(false)
let firstActivation = true
onActivated(() => {
  if (firstActivation) firstActivation = false
  else void libraryStore.fetchFavorites()
})

onMounted(() => {
  libraryStore.fetchFavorites()
})

const favorites = computed<FavoriteItem[]>(() => {
  return libraryStore.favorites
})

const query = ref('')

// Fold both sides so "soma" finds "Sōma" and "pokemon" finds "Pokémon": the
// filter must never make an accented title unreachable from a plain keyboard.
function foldTitle(value: string) {
  return value
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
}

const visibleFavorites = computed<FavoriteItem[]>(() => {
  const needle = foldTitle(query.value.trim())
  if (!needle) return favorites.value
  return favorites.value.filter((fav) => foldTitle(fav.title).includes(needle))
})

const autoDownloadCount = computed(() => {
  return favorites.value.filter((f) => f.autoDownload).length
})

const distinctSourcesCount = computed(() => {
  const s = new Set(favorites.value.map((f) => f.source))
  return s.size
})

function toggleAuto(fav: FavoriteItem) {
  void libraryStore.toggleAutoDownload(fav.url, fav.autoDownload).catch(() => {})
}

function removeFav(fav: FavoriteItem) {
  void libraryStore
    .toggleFavorite({
      url: fav.url,
      title: fav.title,
      imageUrl: fav.imageUrl,
      source: fav.source,
    })
    .catch((error) =>
      notifications.notify(error.message || 'Impossible de retirer cette série.', 'error'),
    )
}

async function clearAll() {
  clearing.value = true
  try {
    await libraryStore.clearAllFavorites()
    clearDialogOpen.value = false
  } catch (error) {
    notifications.notify(
      error instanceof Error ? error.message : 'Impossible de vider la bibliothèque.',
      'error',
    )
  } finally {
    clearing.value = false
  }
}
</script>

<style scoped>
.library-container {
  display: flex;
  flex-direction: column;
}

.library-filter {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
}

.library-filter-input {
  flex: 1;
  max-width: 420px;
  padding: 10px 14px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  color: var(--text);
}

.library-filter-input:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.library-filter-clear {
  width: 32px;
  height: 32px;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80px 20px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  color: var(--muted);
  text-align: center;
}
</style>
