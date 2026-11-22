<template>
  <div class="favorites-view">
    <div class="view-header">
      <div>
        <h1>{{ tx('Mes Favoris') }}</h1>
        <p class="subtitle">
          {{ tx('Vos animés enregistrés et suivis pour le téléchargement automatique.') }}
        </p>
      </div>
      <button class="btn-secondary" @click="libraryStore.fetchFavorites">
        {{ tx('Actualiser') }}
      </button>
    </div>

    <!-- Loading -->
    <div v-if="libraryStore.isLoading && !libraryStore.favorites.length" class="loading-state">
      <div class="spinner"></div>
      <p>{{ tx('Chargement des favoris...') }}</p>
    </div>

    <!-- Empty State -->
    <div v-else-if="!libraryStore.favorites.length" class="empty-state glass-panel">
      <p>{{ tx("Vous n'avez aucun animé en favori pour l'instant.") }}</p>
      <router-link to="/" class="btn-primary">{{ tx('Découvrir les sorties') }}</router-link>
    </div>

    <!-- Favorites Grid -->
    <div v-else class="favorites-grid">
      <div v-for="fav in libraryStore.favorites" :key="fav.url" class="favorite-card glass-panel">
        <div class="card-thumb" @click="openAnime(fav)">
          <img :src="resolveImageUrl(fav.imageUrl)" :alt="tx(fav.title)" />
          <span class="badge badge-source card-source">{{ tx(fav.source) }}</span>
        </div>

        <div class="card-content">
          <h3 class="card-title" :title="tx(fav.title)" @click="openAnime(fav)">
            {{ tx(fav.title) }}
          </h3>

          <div class="card-options">
            <label class="auto-dl-checkbox">
              <input
                type="checkbox"
                :checked="fav.autoDownload"
                @change="libraryStore.toggleAutoDownload(fav.url, fav.autoDownload)"
              />
              <span>{{ tx('Téléchargement auto') }}</span>
            </label>
          </div>

          <div class="card-actions">
            <button class="btn-primary btn-sm" @click="openAnime(fav)">
              {{ tx('Voir la fiche') }}
            </button>
            <button
              class="btn-icon"
              :title="tx('Retirer des favoris')"
              @click="removeFavorite(fav)"
            >
              🗑
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { tx } from '@/utils/locale'
import { resolveImageUrl } from '@/utils/media'
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useLibraryStore } from '@/stores/library'
import type { FavoriteItem } from '@/types'

const router = useRouter()
const libraryStore = useLibraryStore()

onMounted(() => {
  libraryStore.fetchFavorites()
})

function openAnime(fav: FavoriteItem) {
  router.push({
    path: '/anime',
    query: { url: fav.url, source: fav.source || 'french-manga' },
  })
}

async function removeFavorite(fav: FavoriteItem) {
  await libraryStore.toggleFavorite({
    url: fav.url,
    title: fav.title,
    imageUrl: fav.imageUrl,
    source: fav.source,
  })
}
</script>

<style scoped>
.favorites-view {
  max-width: 1440px;
  margin: 0 auto;
  padding: 30px 24px 60px;
  display: flex;
  flex-direction: column;
  gap: 28px;
}

.view-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.subtitle {
  color: var(--text-muted);
  font-size: 0.95rem;
}

.empty-state {
  padding: 80px 20px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  color: var(--text-muted);
}

.favorites-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 20px;
}

.favorite-card {
  display: flex;
  gap: 16px;
  padding: 14px;
  border-radius: var(--radius-md);
  transition: all var(--transition-normal);
}

.favorite-card:hover {
  transform: translateY(-4px);
  border-color: var(--accent-primary);
}

.card-thumb {
  position: relative;
  width: 90px;
  aspect-ratio: 2 / 3;
  border-radius: var(--radius-sm);
  overflow: hidden;
  flex-shrink: 0;
  cursor: pointer;
}

.card-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.card-source {
  position: absolute;
  bottom: 4px;
  left: 4px;
  font-size: 0.65rem;
  padding: 2px 6px;
}

.card-content {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  flex: 1;
  overflow: hidden;
}

.card-title {
  font-size: 1rem;
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  cursor: pointer;
}

.card-options {
  font-size: 0.8rem;
  color: var(--text-muted);
}

.auto-dl-checkbox {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
}

.card-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.btn-sm {
  padding: 6px 14px;
  font-size: 0.85rem;
}
</style>
