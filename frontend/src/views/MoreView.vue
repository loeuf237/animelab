<template>
  <div class="more-container fade-in">
    <header class="page-header more-header">
      <div>
        <h1 class="page-title">{{ tx('Plus') }}</h1>
        <p class="page-sub">
          {{ tx('Outils, apparence, extensions et réglages de l’application.') }}
        </p>
      </div>
    </header>

    <section class="more-identity-card">
      <img :src="brandIcon" :alt="tx('AnimeLab Logo')" class="more-app-icon" />
      <div class="more-app-meta">
        <strong>AnimeLab</strong>
        <span v-if="startup.snapshot?.currentVersion">
          {{ tx('Version') }} {{ startup.snapshot.currentVersion }}
        </span>
      </div>
      <a v-if="sharedUser" href="/auth/account" class="btn btn-sm" :title="tx('Mon compte')">
        <User :size="15" aria-hidden="true" />
        <span>{{ tx('Mon compte') }}</span>
      </a>
    </section>

    <section class="more-quick-card" :aria-label="tx('Apparence et langue')">
      <div class="more-quick-row">
        <span class="more-quick-label">{{ tx('Mode d’affichage') }}</span>
        <div class="more-segmented" role="group" :aria-label="tx('Mode d’affichage')">
          <button
            v-for="mode in modes"
            :key="mode.id"
            type="button"
            class="more-seg-btn"
            :aria-pressed="themeMode === mode.id"
            @click="chooseTheme(mode.id)"
          >
            {{ tx(mode.label) }}
          </button>
        </div>
      </div>

      <div class="more-quick-row">
        <span class="more-quick-label">{{ tx('Langue') }}</span>
        <div class="more-segmented" role="group" :aria-label="tx('Langue')">
          <button
            type="button"
            class="more-seg-btn"
            :aria-pressed="i18nStore.currentLang === 'fr'"
            @click="i18nStore.changeLanguage('fr')"
          >
            FR
          </button>
          <button
            type="button"
            class="more-seg-btn"
            :aria-pressed="i18nStore.currentLang === 'en'"
            @click="i18nStore.changeLanguage('en')"
          >
            EN
          </button>
        </div>
      </div>
    </section>

    <nav class="more-list-card" :aria-label="tx('Raccourcis supplémentaires')">
      <router-link to="/history" class="more-list-row">
        <span class="more-row-icon"><History :size="20" aria-hidden="true" /></span>
        <span class="more-row-text">
          <strong>{{ tx('Historique') }}</strong>
          <small>{{ tx('Épisodes visionnés et téléchargements passés') }}</small>
        </span>
        <ChevronRight :size="18" class="more-chevron" aria-hidden="true" />
      </router-link>

      <router-link to="/extensions" class="more-list-row">
        <span class="more-row-icon"><Puzzle :size="20" aria-hidden="true" /></span>
        <span class="more-row-text">
          <strong>{{ tx('Extensions') }}</strong>
          <small>{{ tx('Dépôts Aniyomi, paquets APK et sources tierces') }}</small>
        </span>
        <ChevronRight :size="18" class="more-chevron" aria-hidden="true" />
      </router-link>

      <router-link to="/settings" class="more-list-row">
        <span class="more-row-icon"><Settings :size="20" aria-hidden="true" /></span>
        <span class="more-row-text">
          <strong>{{ tx('Paramètres') }}</strong>
          <small>{{ tx('Stockage, téléchargements, sources, proxy et mises à jour') }}</small>
        </span>
        <ChevronRight :size="18" class="more-chevron" aria-hidden="true" />
      </router-link>

      <button type="button" class="more-list-row" @click="startup.screen = 'theme'">
        <span class="more-row-icon"><Palette :size="20" aria-hidden="true" /></span>
        <span class="more-row-text">
          <strong>{{ tx('Thèmes et assistant de démarrage') }}</strong>
          <small>{{
            tx('Choisir une palette de couleurs ou revoir la configuration initiale')
          }}</small>
        </span>
        <ChevronRight :size="18" class="more-chevron" aria-hidden="true" />
      </button>
    </nav>
  </div>
</template>

<script setup lang="ts">
import { ChevronRight, History, Palette, Puzzle, Settings, User } from 'lucide-vue-next'
import brandIcon from '@/assets/brand-icon.png'
import { api } from '@/api/client'
import { palette, setAppearance, themeMode } from '@/stores/appearance'
import { useI18nStore } from '@/stores/i18n'
import { sharedUser } from '@/stores/sharedSession'
import { useStartupStore } from '@/stores/startup'
import type { ThemeMode } from '@/types/startup'
import { tx } from '@/utils/locale'

defineOptions({ name: 'MoreView' })

const startup = useStartupStore()
const i18nStore = useI18nStore()

const modes: { id: ThemeMode; label: string }[] = [
  { id: 'system', label: 'Système' },
  { id: 'light', label: 'Clair' },
  { id: 'dark', label: 'Sombre' },
]

function chooseTheme(mode: ThemeMode) {
  setAppearance(mode, palette.value)
  void api.saveAppPreferences({ theme: mode, palette: palette.value }).catch(() => {})
}
</script>

<style scoped>
.more-container {
  max-width: 760px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.more-header {
  margin-bottom: 4px;
}

.more-identity-card,
.more-quick-card,
.more-list-card {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.more-identity-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px;
}

.more-app-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  object-fit: cover;
  flex-shrink: 0;
}

.more-app-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-width: 0;
}

.more-app-meta strong {
  font-size: 16px;
  font-weight: 700;
  color: var(--text);
}

.more-app-meta span {
  font-size: 12.5px;
  color: var(--muted);
}

.more-quick-card {
  display: flex;
  flex-direction: column;
}

.more-quick-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 14px 16px;
  border-bottom: 1px solid var(--line);
}

.more-quick-row:last-child {
  border-bottom: none;
}

.more-quick-label {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}

.more-segmented {
  display: inline-flex;
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-pill);
  overflow: hidden;
}

.more-seg-btn {
  min-height: 36px;
  padding: 0 14px;
  border: 0;
  border-right: 1px solid var(--line-strong);
  background: transparent;
  color: var(--muted);
  font-size: 13px;
  font-weight: 600;
}

.more-seg-btn:last-child {
  border-right: 0;
}

.more-seg-btn[aria-pressed='true'] {
  background: var(--accent-container);
  color: var(--on-accent-container);
}

.more-list-card {
  display: flex;
  flex-direction: column;
}

.more-list-row {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 16px;
  min-height: 60px;
  border: 0;
  border-bottom: 1px solid var(--line);
  background: transparent;
  color: var(--text);
  text-align: left;
  text-decoration: none;
  width: 100%;
  transition: background var(--transition);
}

.more-list-row:last-child {
  border-bottom: none;
}

.more-list-row:hover {
  background: var(--panel-subtle);
}

.more-row-icon {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  background: var(--accent-container);
  color: var(--on-accent-container);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.more-row-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-width: 0;
}

.more-row-text strong {
  font-size: 14.5px;
  font-weight: 600;
}

.more-row-text small {
  font-size: 12px;
  color: var(--muted);
  line-height: 1.35;
}

.more-chevron {
  color: var(--faint);
  flex-shrink: 0;
}
</style>
