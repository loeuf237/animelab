<template>
  <header class="navbar-wrapper">
    <div class="navbar-container">
      <!-- Logo / Brand -->
      <router-link to="/" class="brand-logo">
        <div class="logo-icon-glow">
          <svg
            viewBox="0 0 24 24"
            width="22"
            height="22"
            fill="none"
            stroke="currentColor"
            stroke-width="2.5"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <polygon points="5 3 19 12 5 21 5 3"></polygon>
          </svg>
        </div>
        <span class="brand-text">AnimeLab</span>
        <span class="brand-badge">SPA</span>
      </router-link>

      <!-- Search Bar -->
      <div class="search-box">
        <div class="search-input-wrapper">
          <svg
            class="search-icon"
            viewBox="0 0 24 24"
            width="18"
            height="18"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
          >
            <circle cx="11" cy="11" r="8"></circle>
            <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
          </svg>
          <input
            v-model="searchQuery"
            type="text"
            :placeholder="tx('Rechercher un animé (ex: Solo Leveling, One Piece)...')"
            class="search-input"
            @input="onSearchInput"
            @focus="isSearchDropdownOpen = true"
            @keydown.enter="triggerSearch"
          />
          <button v-if="searchQuery" class="clear-btn" @click="clearSearch">✕</button>
        </div>

        <!-- Search Auto-suggest dropdown -->
        <div
          v-if="isSearchDropdownOpen && searchStore.searchResults.length > 0"
          class="search-dropdown glass-panel"
        >
          <div class="dropdown-header">
            <span>{{ tx('Résultats de recherche') }}</span>
            <span class="results-count"
              >{{ tx(searchStore.searchResults.length) }} {{ tx('animés') }}</span
            >
          </div>
          <div class="results-list">
            <div
              v-for="item in searchStore.searchResults.slice(0, 7)"
              :key="item.url"
              class="search-result-item"
              @click="selectAnime(item)"
            >
              <img
                :src="resolveImageUrl(item.imageUrl) || '/static/placeholder.jpg'"
                class="result-thumb"
                alt=""
              />
              <div class="result-details">
                <span class="result-title">{{ tx(item.title) }}</span>
                <div class="result-meta">
                  <span class="badge badge-source">{{ tx(item.source) }}</span>
                  <span v-if="item.latestEpisode" class="result-ep">{{
                    tx(item.latestEpisode)
                  }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Navigation Links -->
      <nav class="nav-links">
        <router-link to="/" class="nav-item" active-class="active">
          {{ tx('Accueil') }}
        </router-link>
        <router-link to="/favorites" class="nav-item" active-class="active">
          {{ tx('Favoris') }}
        </router-link>
        <router-link to="/sources" class="nav-item" active-class="active"> Sources </router-link>
        <router-link to="/extensions" class="nav-item" active-class="active">
          Extensions
        </router-link>
      </nav>

      <!-- Actions (Downloads & Status) -->
      <div class="nav-actions">
        <button
          class="downloads-btn"
          :class="{ 'has-active': downloadStore.stats.activeCount > 0 }"
          @click="downloadStore.toggleDrawer"
        >
          <svg
            viewBox="0 0 24 24"
            width="18"
            height="18"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
          >
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
            <polyline points="7 10 12 15 17 10"></polyline>
            <line x1="12" y1="15" x2="12" y2="3"></line>
          </svg>
          <span>{{ tx('Téléchargements') }}</span>
          <span v-if="downloadStore.stats.activeCount > 0" class="dl-count-badge">
            {{ tx(downloadStore.stats.activeCount) }}
          </span>
        </button>
      </div>
    </div>
  </header>
</template>

<script setup lang="ts">
import { tx } from '@/utils/locale'
import { resolveImageUrl } from '@/utils/media'
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAnimeStore } from '@/stores/anime'
import { useDownloadStore } from '@/stores/downloads'
import type { AnimeResult } from '@/types'

const router = useRouter()
const searchStore = useAnimeStore()
const downloadStore = useDownloadStore()

const searchQuery = ref('')
const isSearchDropdownOpen = ref(false)
let debounceTimer: any = null

function onSearchInput() {
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => {
    if (searchQuery.value.trim().length >= 2) {
      searchStore.search(searchQuery.value.trim(), 'all')
      isSearchDropdownOpen.value = true
    } else {
      isSearchDropdownOpen.value = false
    }
  }, 350)
}

function clearSearch() {
  searchQuery.value = ''
  isSearchDropdownOpen.value = false
}

function triggerSearch() {
  if (searchQuery.value.trim()) {
    isSearchDropdownOpen.value = false
    router.push({ path: '/sources', query: { q: searchQuery.value.trim() } })
  }
}

function selectAnime(anime: AnimeResult) {
  isSearchDropdownOpen.value = false
  router.push({
    path: '/anime',
    query: { url: anime.url, source: anime.source },
  })
}
</script>

<style scoped>
.navbar-wrapper {
  position: sticky;
  top: 0;
  z-index: 100;
  background: rgba(10, 13, 20, 0.85);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-bottom: 1px solid var(--border-subtle);
  padding: 12px 24px;
}

.navbar-container {
  max-width: 1440px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  gap: 28px;
}

.brand-logo {
  display: flex;
  align-items: center;
  gap: 10px;
  text-decoration: none;
  font-family: 'Outfit', sans-serif;
  font-size: 1.35rem;
  font-weight: 800;
  color: var(--text-main);
  letter-spacing: -0.03em;
}

.logo-icon-glow {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--accent-gradient);
  border-radius: var(--radius-md);
  color: #fff;
  box-shadow: var(--accent-glow);
}

.brand-badge {
  font-size: 0.65rem;
  background: rgba(99, 102, 241, 0.2);
  color: #a5b4fc;
  border: 1px solid rgba(99, 102, 241, 0.4);
  padding: 2px 6px;
  border-radius: var(--radius-full);
  font-weight: 700;
}

.search-box {
  position: relative;
  flex: 1;
  max-width: 500px;
}

.search-input-wrapper {
  position: relative;
  display: flex;
  align-items: center;
}

.search-icon {
  position: absolute;
  left: 14px;
  color: var(--text-muted);
  pointer-events: none;
}

.search-input {
  width: 100%;
  padding: 10px 38px 10px 42px;
  background: rgba(16, 21, 34, 0.85);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-full);
  color: var(--text-main);
  font-size: 0.9rem;
  outline: none;
  transition: all var(--transition-fast);
}

.search-input:focus {
  border-color: var(--accent-primary);
  background: rgba(22, 29, 48, 0.95);
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.2);
}

.clear-btn {
  position: absolute;
  right: 12px;
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 0.85rem;
}

.search-dropdown {
  position: absolute;
  top: calc(100% + 8px);
  left: 0;
  right: 0;
  padding: 10px;
  max-height: 400px;
  overflow-y: auto;
  z-index: 110;
}

.dropdown-header {
  display: flex;
  justify-content: space-between;
  padding: 6px 10px 10px;
  border-bottom: 1px solid var(--border-subtle);
  font-size: 0.8rem;
  color: var(--text-muted);
  font-weight: 600;
}

.search-result-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background var(--transition-fast);
}

.search-result-item:hover {
  background: rgba(255, 255, 255, 0.08);
}

.result-thumb {
  width: 36px;
  height: 48px;
  border-radius: 4px;
  object-fit: cover;
  background: var(--bg-tertiary);
}

.result-details {
  display: flex;
  flex-direction: column;
  gap: 3px;
  overflow: hidden;
}

.result-title {
  font-size: 0.88rem;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.result-meta {
  display: flex;
  align-items: center;
  gap: 6px;
}

.result-ep {
  font-size: 0.75rem;
  color: var(--text-dim);
}

.nav-links {
  display: flex;
  align-items: center;
  gap: 8px;
}

.nav-item {
  padding: 8px 14px;
  border-radius: var(--radius-md);
  text-decoration: none;
  font-size: 0.92rem;
  font-weight: 500;
  color: var(--text-muted);
  transition: all var(--transition-fast);
}

.nav-item:hover {
  color: var(--text-main);
  background: rgba(255, 255, 255, 0.05);
}

.nav-item.active {
  color: #fff;
  background: rgba(99, 102, 241, 0.2);
  border: 1px solid rgba(99, 102, 241, 0.3);
}

.nav-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-left: auto;
}

.downloads-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-full);
  color: var(--text-main);
  font-size: 0.88rem;
  font-weight: 600;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.downloads-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  border-color: var(--border-highlight);
}

.downloads-btn.has-active {
  border-color: var(--accent-primary);
  background: rgba(99, 102, 241, 0.15);
}

.dl-count-badge {
  background: var(--accent-gradient);
  color: #fff;
  font-size: 0.7rem;
  font-weight: 700;
  padding: 2px 7px;
  border-radius: var(--radius-full);
}
</style>
