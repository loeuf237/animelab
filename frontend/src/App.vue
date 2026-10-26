<template>
  <div class="app-shell">
    <!-- Left Navigation Sidebar -->
    <a class="skip-link" href="#main-content">{{ tx('Aller au contenu') }}</a>
    <AppSidebar :inert="isPaletteOpen" />

    <!-- Top Action Bar -->
    <AppTopbar :inert="isPaletteOpen" @open-palette="openPalette" />

    <!-- Main Content Area -->
    <main :inert="isPaletteOpen" id="main-content" class="main-content" tabindex="-1">
      <NetworkVerificationPanel />
      <router-view v-slot="{ Component }">
        <transition name="fade">
          <KeepAlive include="HomeView,SourcesView,LibraryView,DownloadsView" :max="4">
            <component :is="Component" @open-palette="openPalette" />
          </KeepAlive>
        </transition>
      </router-view>
    </main>

    <!-- Mobile Bottom Navigation -->
    <AppBottomNav :inert="isPaletteOpen" />

    <!-- Universal Command Palette Modal (Ctrl + K) -->
    <CommandPaletteModal
      :is-open="isPaletteOpen"
      :initial-query="paletteQuery"
      :initial-source="paletteSource"
      @close="isPaletteOpen = false"
    />

    <!-- Global Video Streaming Modal -->
    <VideoPlayerModal />
    <AppNotifications />
  </div>
</template>

<script setup lang="ts">
import { tx } from '@/utils/locale'
import { ref, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useSearchContext } from '@/stores/searchContext'
import AppNotifications from '@/components/AppNotifications.vue'
import NetworkVerificationPanel from '@/components/NetworkVerificationPanel.vue'
import AppSidebar from '@/components/AppSidebar.vue'
import AppTopbar from '@/components/AppTopbar.vue'
import AppBottomNav from '@/components/AppBottomNav.vue'
import CommandPaletteModal from '@/components/CommandPaletteModal.vue'
import VideoPlayerModal from '@/components/VideoPlayerModal.vue'
import { useDownloadStore } from '@/stores/downloads'
import { useI18nStore } from '@/stores/i18n'
import { useRoute } from 'vue-router'

const searchContext = useSearchContext()
const route = useRoute()
watch(
  () => searchContext.restoreSequence,
  async () => {
    await nextTick()
    openPalette()
  },
)
const downloadStore = useDownloadStore()
const i18nStore = useI18nStore()
const isPaletteOpen = ref(false)
const paletteQuery = ref<string | undefined>()
const paletteSource = ref<string | undefined>()
function openPalette(query?: string, source?: string) {
  paletteQuery.value = query
  paletteSource.value = source
  isPaletteOpen.value = true
}

function onKeyDown(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    if (e.repeat || document.querySelector('.dialog-overlay')) return
    if (isPaletteOpen.value) isPaletteOpen.value = false
    else openPalette()
  }
}

onMounted(() => {
  // Initialize i18n
  i18nStore.init()

  // Preserve searches opened through old /search bookmarks after their redirect.
  if (route.query.search === '1' || typeof route.query.q === 'string') {
    openPalette(
      typeof route.query.q === 'string' ? route.query.q : '',
      typeof route.query.source === 'string' ? route.query.source : undefined,
    )
  }

  // Listen for Ctrl+K
  window.addEventListener('keydown', onKeyDown)

  // Start real-time downloads SSE stream
  downloadStore.startSSE()
  downloadStore.fetchTasks()
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeyDown)
  downloadStore.stopSSE()
})
</script>

<style>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
