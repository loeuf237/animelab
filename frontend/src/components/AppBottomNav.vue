<template>
  <nav class="bottom-nav" :aria-label="tx('Navigation mobile')">
    <router-link
      to="/"
      class="bottom-nav-link"
      :class="{ active: isTabActive('home') }"
      :aria-label="tx('Accueil')"
      @click="onSelect"
    >
      <div class="bottom-nav-pill" aria-hidden="true">
        <Home :size="20" />
      </div>
      <span>{{ tx('Accueil') }}</span>
    </router-link>

    <router-link
      to="/library"
      class="bottom-nav-link"
      :class="{ active: isTabActive('library') }"
      :aria-label="tx('Bibliothèque')"
      @click="onSelect"
    >
      <div class="bottom-nav-pill" aria-hidden="true">
        <Library :size="20" />
      </div>
      <span>{{ tx('Biblio.') }}</span>
    </router-link>

    <router-link
      to="/sources"
      class="bottom-nav-link"
      :class="{ active: isTabActive('explore') }"
      :aria-label="tx('Explorer')"
      @click="onSelect"
    >
      <div class="bottom-nav-pill" aria-hidden="true">
        <Compass :size="20" />
      </div>
      <span>{{ tx('Explorer') }}</span>
    </router-link>

    <router-link
      to="/downloads"
      class="bottom-nav-link"
      :class="{ active: isTabActive('downloads') }"
      :aria-label="tx('Téléchargements')"
      @click="onSelect"
    >
      <div class="bottom-nav-pill" aria-hidden="true">
        <Download :size="20" />
        <span v-if="downloadStore.stats.activeCount > 0" class="bottom-nav-badge">
          {{ tx(downloadStore.stats.activeCount) }}
        </span>
      </div>
      <span>{{ tx('Téléch.') }}</span>
    </router-link>

    <router-link
      to="/more"
      class="bottom-nav-link"
      :class="{ active: isTabActive('more') }"
      :aria-label="tx('Plus')"
      @click="onSelect"
    >
      <div class="bottom-nav-pill" aria-hidden="true">
        <Menu :size="20" />
      </div>
      <span>{{ tx('Plus') }}</span>
    </router-link>
  </nav>
</template>

<script setup lang="ts">
import { useRoute } from 'vue-router'
import { Compass, Download, Home, Library, Menu } from 'lucide-vue-next'
import { tx } from '@/utils/locale'
import { triggerHaptic } from '@/utils/platform'
import { useDownloadStore } from '@/stores/downloads'

const route = useRoute()
const downloadStore = useDownloadStore()

function isTabActive(tab: string) {
  if (route.meta?.rootTab) return route.meta.rootTab === tab
  if (tab === 'home') return route.path === '/'
  if (tab === 'library') return route.path.startsWith('/library')
  if (tab === 'explore')
    return route.path.startsWith('/sources') || route.path.startsWith('/extensions')
  if (tab === 'downloads') return route.path.startsWith('/downloads')
  if (tab === 'more')
    return (
      route.path.startsWith('/more') ||
      route.path.startsWith('/history') ||
      route.path.startsWith('/settings')
    )
  return false
}

function onSelect() {
  triggerHaptic('selection')
}
</script>
