<template>
  <header class="app-topbar">
    <!-- Desktop Window Navigation Cluster -->
    <div v-if="platformRuntime === 'desktop'" class="topbar-nav-cluster">
      <button
        type="button"
        class="icon-button"
        :aria-label="tx('Précédent')"
        :title="tx('Précédent')"
        @click="router.back()"
      >
        <ArrowLeft :size="17" aria-hidden="true" />
      </button>
      <button
        type="button"
        class="icon-button"
        :aria-label="tx('Suivant')"
        :title="tx('Suivant')"
        @click="router.forward()"
      >
        <ArrowRight :size="17" aria-hidden="true" />
      </button>
    </div>

    <!-- Mobile Contextual App Bar Leading Area -->
    <div class="topbar-mobile-leading">
      <button
        v-if="isMobileSubPage"
        type="button"
        class="icon-button"
        :aria-label="tx('Retour')"
        :title="tx('Retour')"
        @click="goBack"
      >
        <ArrowLeft :size="19" aria-hidden="true" />
      </button>
      <span class="topbar-mobile-title">{{ tx(mobileTitle) }}</span>
    </div>

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
      <Search :size="17" class="search-icon" aria-hidden="true" />
      <span>{{ tx('Rechercher') }}</span>
      <kbd class="search-shortcut">{{ searchShortcut }}</kbd>
    </button>

    <div class="top-actions">
      <a
        v-if="sharedUser"
        href="/auth/account"
        class="icon-button"
        :title="i18nStore.currentLang === 'fr' ? 'Mon compte' : 'My account'"
        :aria-label="i18nStore.currentLang === 'fr' ? 'Mon compte' : 'My account'"
      >
        <User :size="18" aria-hidden="true" />
      </a>

      <!-- Language toggle (hidden on mobile; reachable inside MoreView) -->
      <button
        class="icon-button lang-toggle-btn"
        type="button"
        :title="tx('Changer de langue')"
        :aria-label="tx('Changer de langue')"
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
        :aria-label="tx('Basculer le thème')"
        @click="toggleTheme"
      >
        <Moon v-if="theme === 'dark'" :size="18" aria-hidden="true" />
        <Sun v-else :size="18" aria-hidden="true" />
      </button>

      <!-- Settings shortcut (desktop) -->
      <router-link
        to="/settings"
        class="icon-button settings-shortcut-link"
        :title="tx('Paramètres')"
        :aria-label="tx('Paramètres')"
      >
        <Settings :size="18" aria-hidden="true" />
      </router-link>
    </div>
  </header>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, ArrowRight, Moon, Search, Settings, Sun, User } from 'lucide-vue-next'
import brandIcon from '@/assets/brand-icon.png'
import { tx } from '@/utils/locale'
import { formatShortcut, platformRuntime } from '@/utils/platform'
import { effectiveTheme as theme, palette, setAppearance } from '@/stores/appearance'
import { api } from '@/api/client'
import { useI18nStore } from '@/stores/i18n'
import { sharedUser } from '@/stores/sharedSession'

const emit = defineEmits<{
  (e: 'open-palette'): void
}>()

const route = useRoute()
const router = useRouter()
const i18nStore = useI18nStore()

const searchShortcut = computed(() => formatShortcut('K'))
const isMobileSubPage = computed(() => Boolean(route.meta?.isSubPage || route.params?.sourceId))
const mobileTitle = computed(() => String(route.meta?.titleKey || 'AnimeLab'))

function emitOpenPalette() {
  emit('open-palette')
}

function goBack() {
  if (window.history.length > 1) router.back()
  else void router.push('/')
}

function toggleTheme() {
  const newTheme = theme.value === 'dark' ? 'light' : 'dark'
  setAppearance(newTheme, palette.value)
  void api.saveAppPreferences({ theme: newTheme, palette: palette.value }).catch(() => {})
}

function toggleLang() {
  const next = i18nStore.currentLang === 'fr' ? 'en' : 'fr'
  i18nStore.changeLanguage(next)
}
</script>
