<template>
  <div class="tachiyomi-container">
    <!-- Top Action Bar -->
    <header class="tachiyomi-topbar">
      <div class="tachiyomi-topbar-left">
        <button
          type="button"
          class="tachiyomi-back-btn"
          :aria-label="tx('Retour aux résultats')"
          :title="tx('Retour aux résultats')"
          @click="returnToResults"
        >
          <svg viewBox="0 0 24 24">
            <path
              d="m15 18-6-6 6-6"
              fill="none"
              stroke="currentColor"
              stroke-width="2.5"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
        </button>
        <h1 class="tachiyomi-topbar-title">{{ tx(animeTitle) }}</h1>
      </div>

      <div class="tachiyomi-topbar-actions" v-if="detail">
        <!-- Bouton Téléchargement Massif -->
        <button
          type="button"
          class="tachiyomi-bar-btn"
          :title="tx('Téléchargement massif')"
          @click="isBatchMenuOpen = !isBatchMenuOpen"
        >
          <svg viewBox="0 0 24 24">
            <path
              d="M12 3v11m-4-4 4 4 4-4M5 20h14"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
        </button>

        <!-- Menu Déroulant Téléchargement Massif -->
        <div v-if="isBatchMenuOpen" class="tachiyomi-popup-menu" style="display: block">
          <button type="button" class="tachiyomi-menu-item" @click="triggerBatchPreset('next-1')">
            <span>{{ tx('Épisode suivant') }}</span>
            <small style="color: var(--muted)">{{ tx('1 ép.') }}</small>
          </button>
          <button type="button" class="tachiyomi-menu-item" @click="triggerBatchPreset('next-5')">
            <span>{{ tx('5 épisodes suivants') }}</span>
            <small style="color: var(--muted)">{{ tx('5 ép.') }}</small>
          </button>
          <button type="button" class="tachiyomi-menu-item" @click="triggerBatchPreset('next-10')">
            <span>{{ tx('10 épisodes suivants') }}</span>
            <small style="color: var(--muted)">{{ tx('10 ép.') }}</small>
          </button>
          <button type="button" class="tachiyomi-menu-item" @click="triggerBatchPreset('next-25')">
            <span>{{ tx('25 épisodes suivants') }}</span>
            <small style="color: var(--muted)">{{ tx('25 ép.') }}</small>
          </button>
          <div class="tachiyomi-menu-divider"></div>
          <button
            type="button"
            class="tachiyomi-menu-item"
            @click="triggerBatchPreset('unwatched')"
          >
            <span>{{ tx('Non vus') }}</span>
          </button>
          <button
            type="button"
            class="tachiyomi-menu-item"
            @click="triggerBatchPreset('not-downloaded')"
          >
            <span>{{ tx('Non téléchargés') }}</span>
          </button>
          <button type="button" class="tachiyomi-menu-item" @click="triggerBatchPreset('all')">
            <span>{{ tx('Tous les épisodes') }}</span>
          </button>
        </div>

        <!-- Overflow Button -->
        <button
          type="button"
          class="tachiyomi-bar-btn"
          :title="tx('Plus d\'options')"
          @click="isOverflowMenuOpen = !isOverflowMenuOpen"
        >
          <svg viewBox="0 0 24 24">
            <circle cx="12" cy="6" r="1.8" fill="currentColor" />
            <circle cx="12" cy="12" r="1.8" fill="currentColor" />
            <circle cx="12" cy="18" r="1.8" fill="currentColor" />
          </svg>
        </button>

        <!-- Menu Déroulant Overflow -->
        <div
          v-if="isOverflowMenuOpen"
          class="tachiyomi-popup-menu"
          style="display: block; right: 0"
        >
          <button type="button" class="tachiyomi-menu-item" @click="fetchDetail">
            <span>{{ tx('Actualiser la fiche') }}</span>
          </button>
          <button type="button" class="tachiyomi-menu-item" @click="markAll(true)">
            <span>{{ tx('Tout marquer comme vu') }}</span>
          </button>
          <button type="button" class="tachiyomi-menu-item" @click="markAll(false)">
            <span>{{ tx('Tout marquer comme non vu') }}</span>
          </button>
          <div class="tachiyomi-menu-divider"></div>
          <a
            :href="detail.anime.url"
            target="_blank"
            rel="noopener noreferrer"
            class="tachiyomi-menu-item"
            style="text-decoration: none"
          >
            <span>{{ tx('Ouvrir sur le site source') }}</span>
          </a>
        </div>
      </div>
    </header>

    <!-- Loading -->
    <div v-if="animeStore.isDetailLoading" class="loading-state">
      <div class="spinner"></div>
      <p>{{ tx("Chargement des métadonnées de l'animé...") }}</p>
    </div>

    <!-- Error -->
    <div v-else-if="animeStore.error" class="error-state">
      <h3>{{ tx('Impossible de charger cet animé') }}</h3>
      <p>{{ tx(animeStore.error) }}</p>
      <button class="btn btn-primary" style="margin-top: 14px" @click="fetchDetail">
        {{ tx('Réessayer') }}
      </button>
    </div>

    <!-- Detail Content -->
    <div v-else-if="detail">
      <!-- Immersive Hero Card with Backdrop -->
      <section
        class="tachiyomi-hero fade-in"
        :style="{ '--hero-bg-img': `url('${detail.anime.backdropUrl || detail.anime.imageUrl}')` }"
      >
        <div class="tachiyomi-cover-wrap">
          <img class="tachiyomi-cover" :src="detail.anime.imageUrl" :alt="tx(detail.anime.title)" />
        </div>

        <div class="tachiyomi-meta">
          <h1 class="tachiyomi-main-title">{{ tx(detail.anime.title) }}</h1>
          <div class="tachiyomi-meta-line">
            <span class="tachiyomi-meta-icon">👤</span>
            <span>{{ tx(detail.anime.type || 'Animation') }}</span>
          </div>
          <div class="tachiyomi-meta-line">
            <span class="tachiyomi-meta-icon">✏️</span>
            <span>{{ tx(detail.anime.version || 'VOSTFR / VF') }}</span>
          </div>
          <div class="tachiyomi-meta-line">
            <span class="tachiyomi-meta-icon">🕒</span>
            <span>{{ tx(detail.anime.status || 'En cours') }} • {{ tx(detail.source) }}</span>
          </div>
        </div>
      </section>

      <!-- 4 Action Cards -->
      <section class="tachiyomi-actions-grid">
        <button
          type="button"
          class="tachiyomi-action-card"
          :class="{ active: detail.isFavorite }"
          @click="toggleFav"
        >
          <div class="tachiyomi-action-icon">
            <svg
              viewBox="0 0 24 24"
              :fill="detail.isFavorite ? 'currentColor' : 'none'"
              stroke="currentColor"
              stroke-width="2"
            >
              <path
                d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z"
              />
            </svg>
          </div>
          <span>{{ tx(detail.isFavorite ? 'Dans la bibliothèque' : 'Ajouter') }}</span>
        </button>

        <div class="tachiyomi-action-card">
          <div class="tachiyomi-action-icon">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <path
                d="M5 22h14M5 2h14M17 22v-4.172a2 2 0 0 0-.586-1.414L12 12l-4.414 4.414A2 2 0 0 0 7 17.828V22M7 2v4.172a2 2 0 0 0 .586 1.414L12 12l4.414-4.414A2 2 0 0 0 17 6.172V2"
              />
            </svg>
          </div>
          <span>{{ tx(detail.anime.episodes.length) }} {{ tx('ép.') }}</span>
        </div>

        <button
          v-if="detail.isFavorite"
          type="button"
          class="tachiyomi-action-card"
          :class="{ active: detail.autoDownload }"
          @click="toggleAutoDl"
        >
          <div class="tachiyomi-action-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="7 10 12 15 17 10" />
              <line x1="12" y1="15" x2="12" y2="3" />
            </svg>
          </div>
          <span>{{ tx(detail.autoDownload ? 'Auto-DL Actif' : 'Auto-DL Inactif') }}</span>
        </button>

        <a
          :href="detail.anime.url"
          target="_blank"
          rel="noopener noreferrer"
          class="tachiyomi-action-card"
          style="text-decoration: none"
        >
          <div class="tachiyomi-action-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
              <polyline points="15 3 21 3 21 9" />
              <line x1="10" y1="14" x2="21" y2="3" />
            </svg>
          </div>
          <span>{{ tx('Source Web') }}</span>
        </a>
      </section>

      <!-- Synopsis -->
      <section v-if="detail.anime.synopsis" class="section">
        <p class="tachiyomi-synopsis" :class="{ expanded: isSynopsisExpanded }">
          {{ tx(detail.anime.synopsis) }}
        </p>
        <button
          type="button"
          class="btn-text"
          style="color: var(--accent); font-weight: 600; font-size: 13px; margin-top: 6px"
          @click="isSynopsisExpanded = !isSynopsisExpanded"
        >
          {{ tx(isSynopsisExpanded ? 'Moins' : 'Plus') }}
        </button>
      </section>

      <!-- Genres -->
      <section
        v-if="detail.anime.genres && detail.anime.genres.length"
        class="section"
        style="margin-top: 14px"
      >
        <div class="tachiyomi-tags">
          <span v-for="g in detail.anime.genres" :key="g" class="tachiyomi-tag">
            {{ tx(g) }}
          </span>
        </div>
      </section>

      <!-- Section Épisodes avec Barre d'actions par lot -->
      <section class="section">
        <div
          style="
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
            flex-wrap: wrap;
            gap: 12px;
          "
        >
          <h2 class="section-title" style="margin: 0">
            <svg viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5" /></svg>
            {{ tx(detail.anime.episodes.length) }} {{ tx('Épisodes') }}
            <small style="color: var(--muted); font-size: 14px; font-weight: 500; margin-left: 8px">
              ({{ tx(watchedCount) }} {{ tx('vus)') }}
            </small>
          </h2>

          <input
            v-model="epFilter"
            type="text"
            :placeholder="tx('Filtrer un n° ou titre…')"
            :aria-label="tx('Filtrer les épisodes par numéro ou titre')"
            class="input-premium"
            style="width: 220px; height: 36px; font-size: 13px"
          />
        </div>

        <!-- Batch Toolbar (Barre d'action groupée Tachiyomi) -->
        <div
          class="batch-toolbar"
          style="
            margin-bottom: 16px;
            padding: 12px 16px;
            background: var(--panel-subtle);
            border: 1px solid var(--line);
            border-radius: var(--radius);
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 12px;
          "
        >
          <div
            class="batch-options"
            style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap"
          >
            <button type="button" class="btn btn-sm" @click="selectAllEpisodes">
              {{ tx('Tout') }}
            </button>
            <button type="button" class="btn btn-sm" @click="selectUnwatchedEpisodes">
              {{ tx('Non vus') }}
            </button>
            <button type="button" class="btn btn-sm" @click="selectNotDownloadedEpisodes">
              {{ tx('Non téléchargés') }}
            </button>
            <button type="button" class="btn btn-sm" @click="invertSelection">
              {{ tx('Inverser') }}
            </button>

            <select
              v-model="versionFilter"
              class="input-premium"
              :aria-label="tx('Version des épisodes')"
            >
              <option value="">{{ tx('Toutes les versions') }}</option>
              <option v-for="version in episodeVersions" :key="version" :value="version">
                {{ tx(version) }}
              </option>
            </select>
            <OutputProfilePicker v-model="outputProfile" />
            <!-- Qualité par lot -->
            <select
              v-model="batchQuality"
              :aria-label="tx('Qualité demandée')"
              class="input-premium"
              style="padding: 4px 8px; font-size: 0.8rem; height: 30px"
            >
              <option value="auto">{{ tx('Qualité : Auto') }}</option>
              <option value="1080p">1080p</option>
              <option value="720p">720p</option>
              <option value="480p">480p</option>
            </select>

            <!-- Toggle Sous-titres par lot -->
            <label
              class="subtitle-cb-label"
              style="
                display: inline-flex;
                align-items: center;
                gap: 6px;
                font-size: 0.85rem;
                cursor: pointer;
                color: var(--text);
              "
            >
              <input type="checkbox" v-model="batchSubtitles" @change="toggleBatchSubtitles" />
              <span>{{ tx('Sous-titres') }}</span>
            </label>
          </div>

          <div style="display: flex; align-items: center; gap: 12px">
            <span style="font-size: 0.85rem; color: var(--muted)"
              >{{ tx(selectedCount) }} {{ tx('sélectionné(s)') }}</span
            >
            <button
              type="button"
              class="btn btn-primary btn-sm"
              :disabled="selectedCount === 0 || isBatchDownloading"
              @click="downloadSelectedEpisodes"
            >
              <svg
                viewBox="0 0 24 24"
                style="width: 15px; height: 15px; fill: none; stroke: currentColor; stroke-width: 2"
              >
                <path d="M12 3v11" />
                <path d="m7 10 5 5 5-5" />
                <path d="M5 20h14" />
              </svg>
              <span>{{
                tx(isBatchDownloading ? 'Lancement...' : 'Télécharger la sélection')
              }}</span>
            </button>
          </div>
        </div>

        <p v-if="hiddenSelectedCount" class="selection-hint" role="status">
          {{ tx(hiddenSelectedCount) }}
          {{
            tx(
              'épisode(s) sélectionné(s) sont masqués par le filtre. Ils apparaîtront dans le récapitulatif.',
            )
          }}
        </p>

        <!-- Episodes List (Tachiyomi Style) -->
        <div class="episode-list">
          <div
            v-for="ep in filteredEpisodes"
            :key="episodeKey(ep)"
            class="episode-item tachiyomi-episode-item"
            :class="{
              'ep-downloaded': ep.isDownloaded,
              'ep-watched': isWatched(ep),
            }"
          >
            <!-- Gauche: Checkbox, Unread dot, Thumbnail, Informations -->
            <div class="tachiyomi-ep-left">
              <label class="episode-selection-target" @click.stop>
                <input
                  type="checkbox"
                  class="episode-check"
                  :aria-label="tx(`Sélectionner l’épisode ${ep.number} ${ep.version || ''}`)"
                  :checked="selectedEpisodes.has(episodeKey(ep))"
                  @click.stop
                  @change="toggleEpisodeSelection(episodeKey(ep))"
                />
              </label>

              <span
                class="tachiyomi-unread-dot"
                :style="{ visibility: isWatched(ep) ? 'hidden' : 'visible' }"
              ></span>

              <div v-if="ep.thumbnailUrl" class="tachiyomi-ep-thumb-wrap">
                <img :src="ep.thumbnailUrl" class="tachiyomi-ep-thumb" alt="" loading="lazy" />
              </div>

              <div class="tachiyomi-ep-content">
                <h3 class="tachiyomi-ep-title" :title="tx(ep.title)">
                  {{ tx('Épisode') }} {{ tx(ep.number)
                  }}<span v-if="ep.title && ep.title !== `Épisode ${ep.number}`">
                    - {{ tx(ep.title) }}</span
                  >
                </h3>
                <p v-if="ep.synopsis" class="tachiyomi-ep-synopsis">{{ tx(ep.synopsis) }}</p>

                <div class="tachiyomi-ep-sub">
                  <span
                    v-if="ep.version"
                    class="episode-version-badge"
                    :class="ep.version.toLowerCase().includes('vostfr') ? 'ver-vostfr' : 'ver-vf'"
                  >
                    {{ tx(ep.version) }}
                  </span>

                  <span
                    v-if="ep.isDownloaded"
                    class="ep-done-badge"
                    :title="tx('Fichier disponible sur le disque dur')"
                  >
                    <svg
                      viewBox="0 0 24 24"
                      style="
                        width: 12px;
                        height: 12px;
                        display: inline-block;
                        vertical-align: -1px;
                        margin-right: 2px;
                        fill: currentColor;
                      "
                    >
                      <path
                        d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"
                      />
                    </svg>
                    {{ tx('Téléchargé') }}
                  </span>

                  <!-- Pilule interactive Sous-titres -->
                  <div class="ep-sub-control" @click.stop>
                    <button
                      type="button"
                      class="ep-sub-chip"
                      :class="{ active: isSubEnabled(ep) }"
                      :title="
                        tx(
                          'Activer / désactiver le téléchargement des sous-titres pour cet épisode',
                        )
                      "
                      @click.stop="toggleEpSub(ep)"
                    >
                      <span class="ep-sub-icon">CC</span>
                      <span class="ep-sub-label">{{
                        tx(isSubEnabled(ep) ? '✓ Sous-titres' : 'Sous-titres')
                      }}</span>
                    </button>
                  </div>
                </div>
              </div>
            </div>

            <!-- Droite: Bouton Lecture & Bouton Téléchargement Circulaire -->
            <div class="tachiyomi-ep-right" @click.stop>
              <!-- Bouton Play Cinéma -->
              <button
                type="button"
                class="btn btn-icon btn-play-ep"
                :class="ep.isDownloaded ? 'btn-play-local' : 'btn-play-stream'"
                :aria-label="tx(`Lire l’épisode ${ep.number} ${ep.version || ''}`)"
                :title="
                  tx(
                    ep.isDownloaded ? 'Lecture locale (Disque dur)' : 'Streaming direct (En ligne)',
                  )
                "
                @click.stop="playEpisode(ep)"
              >
                <svg viewBox="0 0 24 24"><path d="M7 4v16l13-8Z" /></svg>
              </button>

              <!-- Bouton Téléchargement Circulaire -->
              <button
                v-if="ep.isDownloaded"
                type="button"
                class="tachiyomi-circle-btn is-downloaded"
                :title="tx('Fichier disponible sur le disque dur')"
              >
                <svg viewBox="0 0 24 24">
                  <circle
                    cx="12"
                    cy="12"
                    r="10"
                    fill="rgba(255,255,255,0.08)"
                    stroke="currentColor"
                    stroke-width="1.8"
                  />
                  <path
                    d="m9 12 2 2 4-4"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="2"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  />
                </svg>
              </button>

              <button
                v-else
                type="button"
                class="tachiyomi-circle-btn btn-download-ep"
                :class="{ 'is-loading': downloadingEpisodes.has(episodeKey(ep)) }"
                :disabled="downloadingEpisodes.has(episodeKey(ep))"
                :aria-label="tx(`Télécharger l’épisode ${ep.number} ${ep.version || ''}`)"
                :title="tx('Télécharger l\'épisode')"
                @click.stop="downloadEp(ep)"
              >
                <svg v-if="!downloadingEpisodes.has(episodeKey(ep))" viewBox="0 0 24 24">
                  <circle
                    cx="12"
                    cy="12"
                    r="10"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.8"
                  />
                  <path
                    d="M12 7v7m-3-3 3 3 3-3M8 17h8"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="2"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  />
                </svg>
                <span v-else class="spinner-sm"></span>
              </button>
            </div>
          </div>
        </div>

        <!-- Floating Action Button (FAB) Tachiyomi -->
        <button type="button" class="tachiyomi-fab" :title="tx(fabText)" @click="onFabClick">
          <svg viewBox="0 0 24 24"><path d="M8 5v14l11-7Z" fill="currentColor" /></svg>
          <span class="tachiyomi-fab-text">{{ tx(fabText) }}</span>
        </button>
      </section>
    </div>

    <ConfirmDialog
      :open="!!pendingBatch"
      :title="tx('Vérifier le téléchargement')"
      :confirm-label="tx('Ajouter à la file')"
      :busy="isBatchDownloading"
      @cancel="pendingBatch = null"
      @confirm="confirmBatchDownload"
    >
      <template v-if="pendingBatch">
        <p>
          <strong>{{ tx(pendingBatch.animeName) }}</strong>
        </p>
        <dl class="batch-summary">
          <div>
            <dt>Versions</dt>
            <dd>{{ tx(batchVersionSummary) }}</dd>
          </div>
          <div>
            <dt>{{ tx('Qualité demandée') }}</dt>
            <dd>{{ tx(pendingBatch.preferredQuality || 'Automatique') }}</dd>
          </div>
          <div>
            <dt>{{ tx('Sous-titres demandés') }}</dt>
            <dd>
              {{ tx(pendingBatch.episodes.filter((ep) => ep.downloadSubtitles).length) }} /
              {{ tx(pendingBatch.episodes.length) }} {{ tx('épisodes') }}
            </dd>
          </div>
        </dl>
        <p v-if="pendingBatch.episodes[0]?.outputProfile" class="source-hint">
          {{ tx('Format de sortie') }} : {{ pendingBatch.episodes[0].outputProfile.mode }}
        </p>
        <p class="source-hint">
          {{ tx('La qualité et les sous-titres dépendent des pistes proposées par la source.') }}
        </p>
        <ul class="batch-preview-list">
          <li v-for="(ep, index) in pendingBatch.episodes" :key="index">
            {{ tx('Épisode') }} {{ tx(ep.number) }} · {{ tx(ep.version || 'Version non précisée') }}
            <span v-if="ep.downloadSubtitles">{{ tx('· Sous-titres demandés') }}</span>
          </li>
        </ul>
      </template>
    </ConfirmDialog>
  </div>
</template>

<script setup lang="ts">
import { tx } from '@/utils/locale'
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAnimeStore } from '@/stores/anime'
import { usePlayerStore } from '@/stores/player'
import { useDownloadStore } from '@/stores/downloads'
import { useLibraryStore } from '@/stores/library'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { useSearchContext } from '@/stores/searchContext'
import { useNotifications } from '@/stores/notifications'
import { episodeKey, episodeFileName } from '@/utils/episodes'
import type { Episode, OutputProfile } from '@/types'
import OutputProfilePicker from '@/components/OutputProfilePicker.vue'

const searchContext = useSearchContext()
const notifications = useNotifications()
const router = useRouter()
const route = useRoute()
const animeStore = useAnimeStore()
const playerStore = usePlayerStore()
const downloadStore = useDownloadStore()
const libraryStore = useLibraryStore()

const isBatchMenuOpen = ref(false)
const isOverflowMenuOpen = ref(false)
const isSynopsisExpanded = ref(false)
const epFilter = ref('')
const versionFilter = ref('')
const episodeVersions = computed(() =>
  [...new Set(detail.value?.anime.episodes.map((ep) => ep.version || '') || [])].filter(Boolean),
)

const epSubtitles = ref<Record<string, boolean>>({})
const batchSubtitles = ref(false)
const batchQuality = ref('auto')
const outputProfile = ref<OutputProfile | undefined>(undefined)
const selectedEpisodes = ref<Set<string>>(new Set())
const downloadingEpisodes = ref<Set<string>>(new Set())
const isBatchDownloading = ref(false)

const pendingBatch = ref<Parameters<typeof downloadStore.startBatchDownload>[0] | null>(null)
const batchVersionSummary = computed(() => {
  const counts = new Map<string, number>()
  for (const ep of pendingBatch.value?.episodes || [])
    counts.set(ep.version || 'Non précisée', (counts.get(ep.version || 'Non précisée') || 0) + 1)
  return [...counts].map(([version, count]) => `${version} : ${count}`).join(' · ')
})
function showToast(message: string, tone: 'success' | 'error' | 'info' = 'info') {
  notifications.notify(message, tone)
}
function notifyQueued(message: string) {
  notifications.notify(message, 'success', {
    label: 'Voir la file',
    run: () => router.push('/downloads'),
  })
}
function returnToResults() {
  const state = router.options.history.state
  searchContext.restore(String(route.query.url || ''))
  if (state.back) router.back()
  else void router.push('/sources')
}

const detail = computed(() => animeStore.currentDetail)
watch(
  () => libraryStore.favorites,
  (favorites) => {
    if (detail.value)
      detail.value.isFavorite = favorites.some((fav) => fav.url === detail.value!.anime.url)
  },
)
const animeTitle = computed(() => detail.value?.anime.title || 'Fiche animé')

const watchedCount = computed(() => {
  if (!detail.value) return 0
  return detail.value.anime.episodes.filter((e) => isWatched(e)).length
})

const filteredEpisodes = computed(() => {
  if (!detail.value) return []
  const list = detail.value.anime.episodes.filter(
    (ep) => !versionFilter.value || ep.version === versionFilter.value,
  )
  if (!epFilter.value.trim()) return list
  const q = epFilter.value.trim().toLowerCase()
  return list.filter(
    (e) => String(e.number).includes(q) || (e.title && e.title.toLowerCase().includes(q)),
  )
})

const selectedCount = computed(() => selectedEpisodes.value.size)
const hiddenSelectedCount = computed(
  () =>
    selectedCount.value -
    filteredEpisodes.value.filter((ep) => selectedEpisodes.value.has(episodeKey(ep))).length,
)

const nextUnwatchedEpisode = computed(() => {
  if (!detail.value) return null
  return detail.value.anime.episodes.find((e) => !isWatched(e)) || detail.value.anime.episodes[0]
})

const fabText = computed(() => {
  if (!detail.value || !detail.value.anime.episodes.length) return 'Commencer'
  if (watchedCount.value === 0) return 'Commencer'
  if (nextUnwatchedEpisode.value) return `Reprendre (Ep. ${nextUnwatchedEpisode.value.number})`
  return 'Revoir (Ep. 1)'
})

function onFabClick() {
  if (nextUnwatchedEpisode.value) {
    playEpisode(nextUnwatchedEpisode.value)
  }
}

function isWatched(ep: Episode) {
  if (!detail.value) return false
  const version = ep.version || detail.value.anime.version || ''
  const override = libraryStore.isWatched(detail.value.anime.url, ep.number, version)
  return (
    override ??
    ep.isWatched ??
    detail.value.watchedEpisodes.map(String).includes(`${ep.number}-${version}`)
  )
}

function isSubEnabled(ep: Episode) {
  const num = episodeKey(ep)
  if (epSubtitles.value[num] !== undefined) {
    return epSubtitles.value[num]
  }
  return batchSubtitles.value
}

function toggleEpSub(ep: Episode) {
  const num = episodeKey(ep)
  const current = isSubEnabled(ep)
  epSubtitles.value[num] = !current
}

function toggleBatchSubtitles() {
  const val = batchSubtitles.value
  if (detail.value) {
    for (const ep of filteredEpisodes.value) {
      epSubtitles.value[episodeKey(ep)] = val
    }
  }
}

function toggleEpisodeSelection(num: string) {
  if (selectedEpisodes.value.has(num)) {
    selectedEpisodes.value.delete(num)
  } else {
    selectedEpisodes.value.add(num)
  }
}

function selectAllEpisodes() {
  if (!detail.value) return
  for (const ep of filteredEpisodes.value) {
    selectedEpisodes.value.add(episodeKey(ep))
  }
}

function selectUnwatchedEpisodes() {
  if (!detail.value) return
  selectedEpisodes.value.clear()
  for (const ep of filteredEpisodes.value) {
    if (!isWatched(ep)) {
      selectedEpisodes.value.add(episodeKey(ep))
    }
  }
}

function selectNotDownloadedEpisodes() {
  if (!detail.value) return
  selectedEpisodes.value.clear()
  for (const ep of filteredEpisodes.value) {
    if (!ep.isDownloaded) {
      selectedEpisodes.value.add(episodeKey(ep))
    }
  }
}

function invertSelection() {
  if (!detail.value) return
  for (const ep of filteredEpisodes.value) {
    const num = episodeKey(ep)
    if (selectedEpisodes.value.has(num)) {
      selectedEpisodes.value.delete(num)
    } else {
      selectedEpisodes.value.add(num)
    }
  }
}

watch(versionFilter, () => selectedEpisodes.value.clear())

function fetchDetail() {
  pendingBatch.value = null
  selectedEpisodes.value.clear()
  versionFilter.value = ''
  epSubtitles.value = {}
  downloadingEpisodes.value.clear()
  const url = route.query.url as string
  const source = (route.query.source as string) || 'french-manga'
  if (url) {
    animeStore.fetchAnimeDetail(url, source)
  }
}

watch(
  () => [route.query.url, route.query.source],
  () => fetchDetail(),
)

onMounted(() => {
  fetchDetail()
})

function playEpisode(ep: Episode) {
  if (!detail.value) return
  playerStore.openPlayer(
    detail.value.anime.title,
    detail.value.anime.url,
    detail.value.source,
    ep,
    detail.value.anime.episodes,
  )
}

async function downloadEp(ep: Episode) {
  if (!detail.value) return
  const numStr = episodeKey(ep)
  downloadingEpisodes.value.add(numStr)
  const targetUrl = ep.downloadPageUrl || ep.playerUrl || detail.value.anime.url
  const subEnabled = isSubEnabled(ep)

  try {
    const res = await downloadStore.startDownload({
      animeName: detail.value.anime.title,
      episodeNumber: ep.number,
      version: ep.version || detail.value.anime.version || '',
      animeUrl: detail.value.anime.url,
      url: targetUrl,
      fileName: episodeFileName(detail.value.anime.title, ep),
      subtitleUrl: ep.subtitleUrl || undefined,
      downloadSubtitles: outputProfile.value ? outputProfile.value.mode !== 'ORIGINAL' : subEnabled,
      outputProfile: outputProfile.value,
      source: detail.value.source,
      selectedQuality: batchQuality.value !== 'auto' ? batchQuality.value : undefined,
    })
    notifyQueued(res.message || `Épisode ${ep.number} ${ep.version || ''} ajouté à la file.`)
  } catch (e: any) {
    showToast(e.message || 'Erreur lors du lancement du téléchargement.', 'error')
  } finally {
    downloadingEpisodes.value.delete(numStr)
  }
}

function previewBatch(targetEps: Episode[]) {
  if (!detail.value || !targetEps.length || isBatchDownloading.value) return
  pendingBatch.value = {
    animeName: detail.value.anime.title,
    source: detail.value.source,
    preferredQuality: batchQuality.value !== 'auto' ? batchQuality.value : undefined,
    episodes: targetEps.map((ep) => ({
      number: ep.number,
      version: ep.version || detail.value!.anime.version || '',
      animeUrl: detail.value!.anime.url,
      url: ep.downloadPageUrl || ep.playerUrl || detail.value!.anime.url,
      title: ep.title,
      fileName: episodeFileName(detail.value!.anime.title, ep),
      subtitleUrl: ep.subtitleUrl || undefined,
      downloadSubtitles: outputProfile.value
        ? outputProfile.value.mode !== 'ORIGINAL'
        : isSubEnabled(ep),
      outputProfile: outputProfile.value,
    })),
  }
}
function downloadSelectedEpisodes() {
  previewBatch(
    detail.value?.anime.episodes.filter((ep) => selectedEpisodes.value.has(episodeKey(ep))) || [],
  )
}
async function confirmBatchDownload() {
  if (!pendingBatch.value || isBatchDownloading.value) return
  const request = pendingBatch.value
  isBatchDownloading.value = true
  try {
    const response = await downloadStore.startBatchDownload(request)
    notifyQueued(response.message || `${request.episodes.length} épisode(s) ajoutés à la file.`)
    pendingBatch.value = null
    selectedEpisodes.value.clear()
  } catch (error) {
    showToast(
      error instanceof Error ? error.message : 'Impossible de lancer ce téléchargement.',
      'error',
    )
  } finally {
    isBatchDownloading.value = false
  }
}
function triggerBatchPreset(mode: string) {
  isBatchMenuOpen.value = false
  const all = filteredEpisodes.value
  let targets: Episode[] = []
  if (mode.startsWith('next-'))
    targets = all.filter((ep) => !isWatched(ep) && !ep.isDownloaded).slice(0, Number(mode.slice(5)))
  else if (mode === 'unwatched') targets = all.filter((ep) => !isWatched(ep))
  else if (mode === 'not-downloaded') targets = all.filter((ep) => !ep.isDownloaded)
  else if (mode === 'all') targets = all
  if (!targets.length) {
    showToast('Aucun épisode correspondant à télécharger.')
    return
  }
  previewBatch(targets)
}

async function toggleFav() {
  if (!detail.value) return
  try {
    const res = await libraryStore.toggleFavorite({
      url: detail.value.anime.url,
      title: detail.value.anime.title,
      imageUrl: detail.value.anime.imageUrl,
      source: detail.value.source,
      autoDownload: detail.value.autoDownload,
      autoDownloadVersion:
        versionFilter.value || (episodeVersions.value.length === 1 ? episodeVersions.value[0] : ''),
    })
    detail.value.isFavorite = res.isFavorite
  } catch (error) {
    showToast(
      error instanceof Error ? error.message : 'Impossible de modifier la bibliothèque.',
      'error',
    )
  }
}

async function toggleAutoDl() {
  if (!detail.value) return
  const newAuto = !detail.value.autoDownload
  try {
    await libraryStore.toggleAutoDownload(
      detail.value.anime.url,
      detail.value.autoDownload,
      newAuto
        ? {
            ...(versionFilter.value ? { autoDownloadVersion: versionFilter.value } : {}),
            ...(batchQuality.value !== 'auto' ? { autoDownloadQuality: batchQuality.value } : {}),
            ...(batchSubtitles.value ? { autoDownloadSubtitles: true } : {}),
          }
        : {},
    )
    detail.value.autoDownload = newAuto
  } catch {
    /* The store reports the error and restores its state. */
  }
}

async function markAll(watched: boolean) {
  if (!detail.value) return
  isOverflowMenuOpen.value = false
  for (const ep of filteredEpisodes.value) {
    await libraryStore.markWatched(
      detail.value.anime.url,
      ep.number,
      watched,
      ep.version || detail.value.anime.version || '',
      detail.value.anime.title,
    )
    ep.isWatched = watched
  }
  detail.value.watchedEpisodes = watched
    ? detail.value.anime.episodes.map(
        (e) => `${e.number}-${e.version || detail.value!.anime.version || ''}`,
      )
    : []
}
</script>

<style scoped>
.batch-options {
  min-width: 0;
  max-width: 100%;
}
.batch-options > select {
  min-width: 0;
  max-width: 100%;
}
.tachiyomi-container {
  display: flex;
  flex-direction: column;
  position: relative;
  padding-bottom: 60px;
}

.tachiyomi-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}

.tachiyomi-topbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.tachiyomi-back-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: var(--radius-pill);
  background: var(--panel-subtle);
  border: 1px solid var(--line);
  color: var(--text);
}

.tachiyomi-topbar-title {
  font-size: 20px;
  font-weight: 800;
  margin: 0;
}

.tachiyomi-topbar-actions {
  position: relative;
  display: flex;
  gap: 8px;
}

.tachiyomi-bar-btn {
  width: 38px;
  height: 38px;
  border-radius: var(--radius-pill);
  background: var(--panel-subtle);
  border: 1px solid var(--line);
  color: var(--text);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}

.tachiyomi-popup-menu {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  min-width: 220px;
  background: var(--panel-strong);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  z-index: 100;
  padding: 6px;
}

.tachiyomi-menu-item {
  width: 100%;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  border: none;
  background: none;
  color: var(--text);
  font-size: 14px;
  border-radius: var(--radius-sm);
  text-align: left;
  cursor: pointer;
}

.tachiyomi-menu-item:hover {
  background: var(--panel-subtle);
  color: var(--accent);
}

.tachiyomi-menu-divider {
  height: 1px;
  background: var(--line);
  margin: 4px 0;
}

.tachiyomi-hero {
  position: relative;
  border-radius: var(--radius-lg);
  padding: 30px;
  background-image: var(--hero-bg-img);
  background-size: cover;
  background-position: center 20%;
  display: flex;
  gap: 28px;
  align-items: flex-end;
  box-shadow: var(--shadow);
  border: 1px solid var(--line);
  overflow: hidden;
}

.tachiyomi-hero::before {
  content: '';
  position: absolute;
  inset: 0;
  background: var(--hero-overlay-gradient);
  z-index: 1;
}

.tachiyomi-cover-wrap,
.tachiyomi-meta {
  position: relative;
  z-index: 2;
}

.tachiyomi-cover {
  width: 160px;
  aspect-ratio: 2 / 3;
  border-radius: var(--radius);
  box-shadow: 0 12px 30px rgba(0, 0, 0, 0.7);
  object-fit: cover;
}

.tachiyomi-main-title {
  font-size: 26px;
  font-weight: 900;
  margin: 0 0 10px;
  color: #fff;
}

.tachiyomi-meta-line {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  color: rgba(255, 255, 255, 0.85);
  margin-top: 4px;
}

.tachiyomi-actions-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-top: 20px;
}

.tachiyomi-action-card {
  padding: 14px 10px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  color: var(--text);
  cursor: pointer;
  transition: all var(--transition);
}

.tachiyomi-action-card:hover {
  background: var(--panel-strong);
  border-color: var(--accent);
}

.tachiyomi-action-card.active {
  color: var(--accent);
  border-color: var(--accent);
  background: var(--accent-container);
}

.tachiyomi-action-icon svg {
  width: 22px;
  height: 22px;
}

.tachiyomi-synopsis {
  font-size: 14px;
  color: var(--muted);
  line-height: 1.6;
  max-height: 72px;
  overflow: hidden;
  transition: max-height 0.3s ease;
}

.tachiyomi-synopsis.expanded {
  max-height: 500px;
}

.tachiyomi-tags {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.tachiyomi-tag {
  font-size: 12px;
  background: var(--panel-subtle);
  border: 1px solid var(--line);
  padding: 4px 10px;
  border-radius: var(--radius-pill);
  color: var(--text);
}

.loading-state,
.error-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80px 20px;
  color: var(--muted);
  text-align: center;
}

.toast-notification {
  position: fixed;
  bottom: 24px;
  right: 24px;
  padding: 12px 20px;
  border-radius: var(--radius-sm);
  background: rgba(15, 23, 42, 0.95);
  border: 1px solid var(--border-highlight);
  color: #fff;
  font-size: 0.9rem;
  font-weight: 600;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
  z-index: 500;
  animation: slideUp 0.25s ease;
}

.toast-success {
  border-left: 4px solid #10b981;
}

.toast-error {
  border-left: 4px solid #ef4444;
}

.toast-info {
  border-left: 4px solid #6366f1;
}

@keyframes slideUp {
  from {
    transform: translateY(20px);
    opacity: 0;
  }
  to {
    transform: translateY(0);
    opacity: 1;
  }
}

.spinner-sm {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  display: inline-block;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
