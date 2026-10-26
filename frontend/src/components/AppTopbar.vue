<template>
  <header class="app-topbar">
    <router-link to="/" class="brand-mark-mobile" aria-label="AnimeLab">
      <img :src="brandIcon" :alt="tx('AnimeLab Logo')" class="brand-logo-img" />
    </router-link>

    <button
      type="button"
      class="top-search search-input-wrap search-trigger"
      :aria-label="tx('Ouvrir la recherche')"
      aria-keyshortcuts="Control+K Meta+K"
      @click="emitOpenPalette"
    >
      <svg viewBox="0 0 24 24" class="search-icon">
        <circle cx="11" cy="11" r="7" />
        <path d="m20 20-4-4" />
      </svg>
      <span>{{ tx('Rechercher') }}</span
      ><kbd class="search-shortcut">Ctrl + K</kbd>
    </button>

    <div class="top-actions">
      <a
        v-if="sharedUser"
        href="/auth/account"
        class="icon-button"
        :title="i18nStore.currentLang === 'fr' ? 'Mon compte' : 'My account'"
        :aria-label="i18nStore.currentLang === 'fr' ? 'Mon compte' : 'My account'"
      >
        <svg viewBox="0 0 24 24">
          <circle cx="12" cy="8" r="4" />
          <path d="M4 21v-2a8 8 0 0 1 16 0v2" />
        </svg>
      </a>
      <!-- Language toggle -->
      <button
        class="icon-button lang-toggle-btn"
        type="button"
        :title="tx('Changer de langue')"
        @click="toggleLang"
      >
        <span style="font-size: 12px; font-weight: 800; letter-spacing: 0.5px">{{
          tx(i18nStore.currentLang.toUpperCase())
        }}</span>
      </button>

      <!-- Theme toggle -->
      <button
        class="icon-button"
        type="button"
        :title="tx('Basculer le thème')"
        @click="toggleTheme"
      >
        <svg v-if="theme === 'dark'" viewBox="0 0 24 24">
          <path d="M21 13a8 8 0 1 1-10-10 7 7 0 0 0 10 10Z" />
        </svg>
        <svg v-else viewBox="0 0 24 24">
          <circle cx="12" cy="12" r="4" />
          <path
            d="M12 2v2M12 20v2M4 12H2M22 12h-2M5 5l1.5 1.5M17.5 17.5 19 19M19 5l-1.5 1.5M6.5 17.5 5 19"
          />
        </svg>
      </button>

      <!-- Settings shortcut -->
      <router-link to="/settings" class="icon-button" :title="tx('Paramètres')">
        <svg viewBox="0 0 24 24">
          <circle cx="12" cy="12" r="3" />
          <path
            d="M19 12a7 7 0 0 0-.1-1l2-1.5-2-3.4-2.4 1a7 7 0 0 0-1.8-1L14.4 3H9.6L9.2 6.1a7 7 0 0 0-1.8 1L5 6.1l-2 3.4L5 11a7 7 0 0 0 0 2l-2 1.5 2 3.4 2.4-1a7 7 0 0 0 1.8 1l.4 3.1h4.8l.4-3.1a7 7 0 0 0 1.8-1l2.4 1 2-3.4-2-1.5a7 7 0 0 0 .1-1Z"
          />
        </svg>
      </router-link>
    </div>
  </header>
</template>

<script setup lang="ts">
import brandIcon from '@/assets/brand-icon.png'
import { tx } from '@/utils/locale'
import { ref, onMounted } from 'vue'
import { useI18nStore } from '@/stores/i18n'
import { sharedUser } from '@/stores/sharedSession'

const emit = defineEmits<{
  (e: 'open-palette'): void
}>()

const i18nStore = useI18nStore()
const theme = ref<'dark' | 'light'>('dark')

onMounted(() => {
  const savedTheme = (localStorage.getItem('animan_theme') as 'dark' | 'light') || 'dark'
  theme.value = savedTheme
  document.documentElement.setAttribute('data-theme', savedTheme)
})

function emitOpenPalette() {
  emit('open-palette')
}

function toggleTheme() {
  const newTheme = theme.value === 'dark' ? 'light' : 'dark'
  theme.value = newTheme
  localStorage.setItem('animan_theme', newTheme)
  document.documentElement.setAttribute('data-theme', newTheme)
}

function toggleLang() {
  const next = i18nStore.currentLang === 'fr' ? 'en' : 'fr'
  i18nStore.changeLanguage(next)
}
</script>
