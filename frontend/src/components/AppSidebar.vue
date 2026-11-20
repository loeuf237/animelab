<template>
  <aside class="app-sidebar" :aria-label="tx('Navigation principale')">
    <div class="sidebar-top-row">
      <router-link to="/" class="brand-mark" aria-label="AnimeLab">
        <span class="brand-icon">
          <img :src="brandIcon" :alt="tx('AnimeLab Logo')" class="brand-logo-img" />
        </span>
        <span class="brand-name">Anime<span>Lab</span></span>
      </router-link>

      <button
        type="button"
        class="sidebar-collapse-btn"
        :aria-label="tx(collapsed ? 'Déplier la barre latérale' : 'Réduire la barre latérale')"
        :title="tx(collapsed ? 'Déplier la barre latérale' : 'Réduire la barre latérale')"
        :aria-pressed="collapsed"
        @click="toggleCollapse"
      >
        <PanelLeftOpen v-if="collapsed" :size="18" aria-hidden="true" />
        <PanelLeftClose v-else :size="18" aria-hidden="true" />
      </button>
    </div>

    <div class="sidebar-menu">
      <div class="sidebar-group">
        <span class="sidebar-group-label">{{ tx('Principal') }}</span>
        <router-link
          to="/"
          :aria-label="tx('Accueil')"
          :title="tx('Accueil')"
          class="side-link"
          active-class="active"
          exact-active-class="active"
        >
          <Home :size="19" aria-hidden="true" />
          <span>{{ tx(i18nStore.t('nav_home') || 'Accueil') }}</span>
        </router-link>

        <router-link
          to="/library"
          :aria-label="tx('Bibliothèque')"
          :title="tx('Bibliothèque')"
          class="side-link"
          active-class="active"
        >
          <Library :size="19" aria-hidden="true" />
          <span>{{ tx(i18nStore.t('nav_library') || 'Bibliothèque') }}</span>
        </router-link>

        <router-link
          to="/history"
          :aria-label="tx('Historique')"
          :title="tx('Historique')"
          class="side-link"
          active-class="active"
        >
          <History :size="19" aria-hidden="true" />
          <span>{{ tx(i18nStore.t('nav_history') || 'Historique') }}</span>
        </router-link>
      </div>

      <div class="sidebar-group">
        <span class="sidebar-group-label">{{ tx('Découverte') }}</span>
        <router-link
          to="/sources"
          aria-label="Sources"
          :title="tx('Sources')"
          class="side-link"
          active-class="active"
        >
          <Compass :size="19" aria-hidden="true" />
          <span>Sources</span>
        </router-link>

        <router-link
          to="/extensions"
          aria-label="Extensions"
          :title="tx('Extensions')"
          class="side-link"
          active-class="active"
        >
          <Puzzle :size="19" aria-hidden="true" />
          <span>{{ tx(i18nStore.t('nav_extensions') || 'Extensions') }}</span>
        </router-link>
      </div>

      <div class="sidebar-group">
        <span class="sidebar-group-label">{{ tx('Application') }}</span>
        <router-link
          to="/downloads"
          :aria-label="tx('Téléchargements')"
          :title="tx('Téléchargements')"
          class="side-link"
          active-class="active"
        >
          <Download :size="19" aria-hidden="true" />
          <span>{{ tx(i18nStore.t('nav_downloads') || 'Téléchargements') }}</span>
          <span v-if="downloadStore.stats.activeCount > 0" class="side-badge">
            {{ tx(downloadStore.stats.activeCount) }}
          </span>
        </router-link>

        <router-link
          to="/settings"
          :aria-label="tx('Paramètres')"
          :title="tx('Paramètres')"
          class="side-link"
          active-class="active"
        >
          <Settings :size="19" aria-hidden="true" />
          <span>{{ tx(i18nStore.t('nav_settings') || 'Paramètres') }}</span>
        </router-link>
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import {
  Compass,
  Download,
  History,
  Home,
  Library,
  PanelLeftClose,
  PanelLeftOpen,
  Puzzle,
  Settings,
} from 'lucide-vue-next'
import brandIcon from '@/assets/brand-icon.png'
import { readPreference, tx, writePreference } from '@/utils/locale'
import { useDownloadStore } from '@/stores/downloads'
import { useI18nStore } from '@/stores/i18n'

const downloadStore = useDownloadStore()
const i18nStore = useI18nStore()

const collapsed = ref(readPreference('sidebar_collapsed') === '1')

function applyCollapsed(state: boolean) {
  if (typeof document !== 'undefined') {
    document.documentElement.classList.toggle('sidebar-collapsed', state)
  }
}

function toggleCollapse() {
  collapsed.value = !collapsed.value
  writePreference('sidebar_collapsed', collapsed.value ? '1' : '0')
  applyCollapsed(collapsed.value)
}

onMounted(() => {
  applyCollapsed(collapsed.value)
})
</script>
