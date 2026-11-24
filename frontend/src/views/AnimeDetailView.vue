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
        <!-- Bouton Actualiser (style Mihon) -->
        <button
          type="button"
          class="tachiyomi-bar-btn"
          :class="{ 'is-spinning': Boolean(animeStore.isDetailRefreshing) }"
          :disabled="Boolean(animeStore.isDetailRefreshing)"
          :aria-label="tx('Actualiser la fiche')"
          :title="tx('Actualiser la fiche')"
          @click="refreshDetail"
        >
          <RefreshCw :size="18" aria-hidden="true" />
        </button>

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
          <button
            type="button"
            class="tachiyomi-menu-item"
            :disabled="Boolean(animeStore.isDetailRefreshing)"
            @click="refreshDetail"
          >
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

    <VerificationPrompt :challenges="animeStore.detailChallenges" />
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
      <section class="tachiyomi-hero fade-in" :style="{ '--hero-bg-img': heroBgImg }">
        <div class="tachiyomi-cover-wrap">
          <img
            v-if="coverSrc && !coverBroken"
            class="tachiyomi-cover"
            :src="coverSrc"
            :alt="tx(detail.anime.title)"
            @error="onCoverError"
          />
          <div v-else class="tachiyomi-cover-placeholder" aria-hidden="true">
            <span>{{ (detail.anime.title || 'A').slice(0, 2).toUpperCase() }}</span>
          </div>
        </div>

        <div class="tachiyomi-meta">
          <h1 class="tachiyomi-main-title">{{ tx(detail.anime.title) }}</h1>
          <div class="tachiyomi-meta-line">
            <Building2 :size="15" class="tachiyomi-meta-icon" aria-hidden="true" />
            <span>{{ tx(detail.anime.studio || detail.anime.type || 'Auteur inconnu') }}</span>
          </div>
          <div class="tachiyomi-meta-line">
            <Languages :size="15" class="tachiyomi-meta-icon" aria-hidden="true" />
            <span>{{ tx(detail.anime.version || 'VOSTFR / VF') }}</span>
          </div>
          <div class="tachiyomi-meta-line">
            <Clock :size="15" class="tachiyomi-meta-icon" aria-hidden="true" />
            <span
              >{{ tx(detail.anime.status || nativeStatus) }} •
              {{ tx(detail.sourceName || detail.source) }}</span
            >
          </div>
          <div
            v-if="detail.fromCache || animeStore.isOfflineSnapshot"
            class="tachiyomi-meta-line tachiyomi-cache-line"
          >
            <HardDrive :size="14" class="tachiyomi-meta-icon" aria-hidden="true" />
            <span>
              {{
                tx(
                  animeStore.isOfflineSnapshot
                    ? 'Hors ligne · fiche locale'
                    : 'Fiche enregistrée localement',
                )
              }}<template v-if="formattedCachedAt"> · {{ formattedCachedAt }}</template>
            </span>
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

        <label class="episode-order"
          >{{ tx('Ordre des épisodes') }}
          <select v-model="episodeOrder">
            <option value="source">{{ tx('Ordre de la source') }}</option>
            <option value="asc">{{ tx('Du premier au dernier') }}</option>
            <option value="desc">{{ tx('Du dernier au premier') }}</option>
          </select>
        </label>
        <p v-if="!filteredEpisodes.length" class="episode-empty" role="status">
          {{
            tx(
              detail.anime.episodes.length
                ? 'Aucun épisode ne correspond aux filtres.'
                : 'La source n’a renvoyé aucun épisode pour cette série.',
            )
          }}
          <button
            v-if="!detail.anime.episodes.length"
            class="btn btn-secondary"
            @click="fetchDetail"
          >
            {{ tx('Réessayer') }}
          </button>
        </p>
        <!-- Episodes List (Tachiyomi Style) -->
        <div class="episode-list">
          <div
            v-for="ep in filteredEpisodes"
            :key="rowKey(ep)"
            class="episode-item tachiyomi-episode-item"
            :class="{
              'ep-downloaded': isEpisodeDownloaded(ep),
              'ep-watched': isWatched(ep),
            }"
          >
            <!-- Gauche: Checkbox, Unread dot, Thumbnail, Informations -->
            <div class="tachiyomi-ep-left">
              <label
                class="episode-selection-target"
                :class="{ 'is-disabled': isEpisodeDownloaded(ep) }"
                @click.stop
              >
                <input
                  type="checkbox"
                  class="episode-check"
                  :aria-label="tx(`Sélectionner l’épisode ${ep.number} ${ep.version || ''}`)"
                  :disabled="isEpisodeDownloaded(ep)"
                  :checked="!isEpisodeDownloaded(ep) && selectedEpisodes.has(rowKey(ep))"
                  @click.stop
                  @change="toggleEpisodeSelection(rowKey(ep))"
                />
              </label>

              <span
                class="tachiyomi-unread-dot"
                :style="{ visibility: isWatched(ep) ? 'hidden' : 'visible' }"
              ></span>

              <div v-if="ep.thumbnailUrl" class="tachiyomi-ep-thumb-wrap">
                <img
                  :src="resolveImageUrl(ep.thumbnailUrl)"
                  class="tachiyomi-ep-thumb"
                  alt=""
                  loading="lazy"
                />
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
                    v-if="isEpisodeDownloaded(ep)"
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
                  <div v-if="!isEpisodeDownloaded(ep)" class="ep-sub-control" @click.stop>
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
                :class="isEpisodeDownloaded(ep) ? 'btn-play-local' : 'btn-play-stream'"
                :aria-label="tx(`Lire l’épisode ${ep.number} ${ep.version || ''}`)"
                :title="
                  tx(
                    isEpisodeDownloaded(ep)
                      ? 'Lecture locale (Disque dur)'
                      : 'Streaming direct (En ligne)',
                  )
                "
                @click.stop="playEpisode(ep)"
              >
                <svg viewBox="0 0 24 24"><path d="M7 4v16l13-8Z" /></svg>
              </button>

              <button
                v-if="playerStore.canLaunchExternal"
                type="button"
                class="btn btn-icon btn-secondary"
                :disabled="playerStore.externalLaunching"
                :aria-label="tx(`Ouvrir l’épisode ${ep.number} dans un lecteur externe`)"
                :title="tx('Ouvrir dans un lecteur externe')"
                @click.stop="playEpisodeExternal(ep)"
              >
                <ExternalLink :size="15" aria-hidden="true" />
              </button>

              <!-- Bouton Suppression téléchargement / Bouton Téléchargement Circulaire -->
              <button
                v-if="isEpisodeDownloaded(ep)"
                type="button"
                class="btn btn-icon btn-danger-outline btn-delete-ep"
                :disabled="deletingEpisodeKey === rowKey(ep)"
                :aria-label="
                  tx(`Supprimer le téléchargement de l’épisode ${ep.number} ${ep.version || ''}`)
                "
                :title="tx('Supprimer l’épisode téléchargé')"
                @click.stop="promptDeleteDownloaded(ep)"
              >
                <Trash2 :size="15" aria-hidden="true" />
              </button>

              <!-- Indicateur déjà téléchargé / Bouton Téléchargement Circulaire -->
              <span
                v-if="isEpisodeDownloaded(ep)"
                class="tachiyomi-circle-btn is-downloaded"
                role="img"
                :title="tx('Déjà téléchargé')"
                :aria-label="tx('Déjà téléchargé')"
              >
                <svg viewBox="0 0 24 24" aria-hidden="true">
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
              </span>

              <button
                v-else
                type="button"
                class="tachiyomi-circle-btn btn-download-ep"
                :class="{ 'is-loading': downloadingEpisodes.has(rowKey(ep)) }"
                :disabled="downloadingEpisodes.has(rowKey(ep))"
                :aria-label="tx(`Télécharger l’épisode ${ep.number} ${ep.version || ''}`)"
                :title="tx('Télécharger l\'épisode')"
                @click.stop="downloadEp(ep)"
              >
                <svg v-if="!downloadingEpisodes.has(rowKey(ep))" viewBox="0 0 24 24">
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
        <button
          v-if="nextUnwatchedEpisode"
          type="button"
          class="tachiyomi-fab"
          :title="tx(fabText)"
          @click="onFabClick"
        >
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
            {{ tx('Épisode') }} {{ tx(ep.number) }}
            <span v-if="ep.title">· {{ tx(ep.title) }}</span> ·
            {{ tx(ep.version || 'Version non précisée') }}
            <span v-if="ep.downloadSubtitles">{{ tx('· Sous-titres demandés') }}</span>
          </li>
        </ul>
      </template>
    </ConfirmDialog>

    <ConfirmDialog
      :open="!!pendingDeleteEpisode"
      :title="tx('Supprimer l’épisode téléchargé')"
      :confirm-label="tx('Supprimer')"
      :busy="!!deletingEpisodeKey"
      :danger="true"
      @cancel="pendingDeleteEpisode = null"
      @confirm="confirmDeleteDownloaded"
    >
      <template v-if="pendingDeleteEpisode">
        <p>
          {{
            tx(
              `Voulez-vous supprimer définitivement le fichier local de l’épisode ${pendingDeleteEpisode.number}${pendingDeleteEpisode.version ? ` (${pendingDeleteEpisode.version})` : ''} ?`,
            )
          }}
        </p>
        <p class="source-hint">
          {{
            tx(
              'Le fichier vidéo et ses sous-titres locaux seront supprimés du disque dur. Votre progression de visionnage sera conservée.',
            )
          }}
        </p>
      </template>
    </ConfirmDialog>
  </div>
</template>

<script setup lang="ts">
import { tx } from '@/utils/locale'
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import {
  Building2,
  Clock,
  ExternalLink,
  HardDrive,
  Languages,
  RefreshCw,
  Trash2,
} from 'lucide-vue-next'
import { api } from '@/api/client'
import { useAnimeStore } from '@/stores/anime'
import { usePlayerStore } from '@/stores/player'
import { useDownloadStore } from '@/stores/downloads'
import { useLibraryStore } from '@/stores/library'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { useSearchContext } from '@/stores/searchContext'
import { useNotifications } from '@/stores/notifications'
import { buildEpisodeRowKeys, episodeKey, episodeFileName } from '@/utils/episodes'
import { canFallbackToImageProxy, proxyImageUrl, resolveImageUrl } from '@/utils/media'
import type { Episode, OutputProfile } from '@/types'
import OutputProfilePicker from '@/components/OutputProfilePicker.vue'
import VerificationPrompt from '@/components/VerificationPrompt.vue'

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
const episodeOrder = ref('source')
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
const pendingDeleteEpisode = ref<Episode | null>(null)
const deletingEpisodeKey = ref<string | null>(null)
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
const episodeRowKeys = computed(() => buildEpisodeRowKeys(detail.value?.anime.episodes || []))
function rowKey(ep: Episode): string {
  return episodeRowKeys.value.get(ep) || episodeKey(ep)
}
function episodeSeason(ep: Episode): number {
  const val = Number(ep.nativeMetadata?.season)
  return Number.isInteger(val) && val > 0 ? val : 0
}
const coverUseProxy = ref(false)
const coverBroken = ref(false)
const coverSrc = computed(() => {
  const raw = detail.value?.anime.imageUrl
  if (!raw) return ''
  return coverUseProxy.value || detail.value?.isFavorite ? proxyImageUrl(raw) : resolveImageUrl(raw)
})
const heroBgImg = computed(() => {
  const raw = detail.value?.anime.backdropUrl || detail.value?.anime.imageUrl
  if (!raw) return 'none'
  const resolved =
    detail.value?.isFavorite || (coverUseProxy.value && raw === detail.value?.anime.imageUrl)
      ? proxyImageUrl(raw)
      : resolveImageUrl(raw)
  return resolved ? `url("${resolved.replace(/"/g, '\\"')}")` : 'none'
})
const formattedCachedAt = computed(() => {
  const raw = detail.value?.cachedAt
  if (!raw) return ''
  const dt = new Date(raw)
  if (Number.isNaN(dt.getTime())) return ''
  return dt.toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' })
})
function onCoverError() {
  const raw = detail.value?.anime.imageUrl
  if (!coverUseProxy.value && canFallbackToImageProxy(raw, coverSrc.value)) {
    coverUseProxy.value = true
    return
  }
  coverBroken.value = true
}
watch(
  () => detail.value?.anime.imageUrl,
  () => {
    coverUseProxy.value = false
    coverBroken.value = false
  },
)
const nativeStatus = computed(
  () =>
    (({ 1: 'En cours', 2: 'Terminé', 4: 'En pause', 5: 'Annulé' }) as Record<number, string>)[
      Number(detail.value?.anime.nativeMetadata?.status)
    ] || 'Inconnu',
)
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
  if (episodeOrder.value !== 'source')
    list.sort(
      (a, b) =>
        ((episodeSeason(a) - episodeSeason(b)) * 100000 + (Number(a.number) - Number(b.number))) *
        (episodeOrder.value === 'desc' ? -1 : 1),
    )
  if (!epFilter.value.trim()) return list
  const q = epFilter.value.trim().toLowerCase()
  return list.filter(
    (e) => String(e.number).includes(q) || (e.title && e.title.toLowerCase().includes(q)),
  )
})

const selectedCount = computed(() => selectedEpisodes.value.size)
const hiddenSelectedCount = computed(() =>
  Math.max(
    0,
    selectedCount.value -
      filteredEpisodes.value.filter((ep) => selectedEpisodes.value.has(rowKey(ep))).length,
  ),
)

const nextUnwatchedEpisode = computed(() => {
  if (!detail.value) return null
  const episodes = [...detail.value.anime.episodes]
    .filter((ep) => !versionFilter.value || ep.version === versionFilter.value)
    .sort((a, b) => episodeSeason(a) - episodeSeason(b) || Number(a.number) - Number(b.number))
  return episodes.find((e) => !isWatched(e)) || episodes[0]
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
  const num = rowKey(ep)
  if (epSubtitles.value[num] !== undefined) {
    return epSubtitles.value[num]
  }
  return batchSubtitles.value
}

function toggleEpSub(ep: Episode) {
  const num = rowKey(ep)
  const current = isSubEnabled(ep)
  epSubtitles.value[num] = !current
}

function toggleBatchSubtitles() {
  const val = batchSubtitles.value
  if (detail.value) {
    for (const ep of filteredEpisodes.value) {
      epSubtitles.value[rowKey(ep)] = val
    }
  }
}

function normalizeVersionKey(version?: string | null): string {
  return (version || '').trim().toUpperCase()
}

function equivalentUrlStem(url?: string | null): string {
  return (url || '').trim().replace(/\/+$/, '')
}

function findCompletedDownloadTask(ep: Episode) {
  const taskList = Array.isArray(downloadStore.tasks) ? downloadStore.tasks : []
  if (!taskList.length || !detail.value) return undefined
  const epNum = Number(ep.number)
  const epVer = normalizeVersionKey(ep.version || detail.value.anime.version || '')
  const epUrls = new Set([ep.downloadPageUrl, ep.playerUrl].map(equivalentUrlStem).filter(Boolean))
  const curAnimeName = (detail.value.anime.title || '').trim().toLowerCase()
  const curAnimeUrl = equivalentUrlStem(detail.value.anime.url)
  return taskList.find((t) => {
    const st = String(t.rawStatus || t.status || '').toUpperCase()
    if (st !== 'COMPLETED') return false
    if (Number(t.episodeNumber) !== epNum) return false
    const taskVer = normalizeVersionKey(t.version)
    if (epVer && taskVer && taskVer !== epVer) return false
    if (epVer && !taskVer && !epUrls.has(equivalentUrlStem(t.fileUrl))) return false
    if (epUrls.size && epUrls.has(equivalentUrlStem(t.fileUrl))) return true
    if (curAnimeUrl && equivalentUrlStem(t.animeUrl) === curAnimeUrl) {
      return !epVer || taskVer === epVer
    }
    return (
      Boolean(curAnimeName) &&
      (t.animeName || '').trim().toLowerCase() === curAnimeName &&
      (!epVer || taskVer === epVer)
    )
  })
}

function isEpisodeDownloaded(ep: Episode): boolean {
  return Boolean(ep.isDownloaded || findCompletedDownloadTask(ep))
}

function resolvedDownloadTaskId(ep: Episode): string | number | null {
  if (ep.downloadTaskId != null) return ep.downloadTaskId
  const match = findCompletedDownloadTask(ep)
  return match?.id ?? null
}

function episodeByRowKey(key: string): Episode | undefined {
  return detail.value?.anime.episodes.find((ep) => rowKey(ep) === key)
}

function enrichEpisodeForPlayback(ep: Episode): Episode {
  const taskId = resolvedDownloadTaskId(ep)
  const downloaded = isEpisodeDownloaded(ep)
  if (ep.downloadTaskId === taskId && Boolean(ep.isDownloaded) === downloaded) return ep
  return {
    ...ep,
    isDownloaded: downloaded,
    downloadTaskId: taskId,
  }
}

function toggleEpisodeSelection(num: string) {
  const target = episodeByRowKey(num)
  if (target && isEpisodeDownloaded(target)) {
    selectedEpisodes.value.delete(num)
    return
  }
  if (selectedEpisodes.value.has(num)) {
    selectedEpisodes.value.delete(num)
  } else {
    selectedEpisodes.value.add(num)
  }
}

function selectAllEpisodes() {
  if (!detail.value) return
  for (const ep of filteredEpisodes.value) {
    if (!isEpisodeDownloaded(ep)) {
      selectedEpisodes.value.add(rowKey(ep))
    }
  }
}

function selectUnwatchedEpisodes() {
  if (!detail.value) return
  selectedEpisodes.value.clear()
  for (const ep of filteredEpisodes.value) {
    if (!isWatched(ep) && !isEpisodeDownloaded(ep)) {
      selectedEpisodes.value.add(rowKey(ep))
    }
  }
}

function selectNotDownloadedEpisodes() {
  if (!detail.value) return
  selectedEpisodes.value.clear()
  for (const ep of filteredEpisodes.value) {
    if (!isEpisodeDownloaded(ep)) {
      selectedEpisodes.value.add(rowKey(ep))
    }
  }
}

function invertSelection() {
  if (!detail.value) return
  for (const ep of filteredEpisodes.value) {
    const num = rowKey(ep)
    if (isEpisodeDownloaded(ep)) {
      selectedEpisodes.value.delete(num)
      continue
    }
    if (selectedEpisodes.value.has(num)) {
      selectedEpisodes.value.delete(num)
    } else {
      selectedEpisodes.value.add(num)
    }
  }
}

watch(
  () => downloadStore.tasks,
  () => {
    if (!detail.value || !selectedEpisodes.value.size) return
    for (const key of [...selectedEpisodes.value]) {
      const ep = episodeByRowKey(key)
      if (ep && isEpisodeDownloaded(ep)) selectedEpisodes.value.delete(key)
    }
  },
  { deep: true },
)

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

async function refreshDetail() {
  isOverflowMenuOpen.value = false
  const url = (route.query.url as string) || detail.value?.anime.url
  const source = (route.query.source as string) || detail.value?.source || 'french-manga'
  if (!url) return
  if (typeof animeStore.refreshAnimeDetail !== 'function') {
    fetchDetail()
    return
  }
  const res = await animeStore.refreshAnimeDetail(url, source, { silent: false })
  if (res?.updated) {
    if ((res.addedEpisodes ?? 0) > 0) {
      showToast(tx(`Fiche mise à jour (+${res.addedEpisodes} épisode(s)).`), 'success')
    } else {
      showToast(tx('Fiche mise à jour.'), 'success')
    }
  } else if (res?.offline && !res?.challenge) {
    showToast(tx('Impossible d’actualiser la fiche : affichage de la copie locale.'), 'info')
  }
}

watch(
  () => [route.query.url, route.query.source],
  () => fetchDetail(),
)

onMounted(() => {
  void playerStore.loadExternalPlayerConfig()
  fetchDetail()
})
onUnmounted(() => animeStore.clearDetail())

async function launchEpisodeExternal(ep: Episode): Promise<boolean> {
  if (!detail.value) return false
  const playbackEp = enrichEpisodeForPlayback(ep)
  try {
    const res = await playerStore.launchEpisodeExternal({
      title: detail.value.anime.title,
      animeUrl: detail.value.anime.url,
      source: detail.value.source,
      episode: playbackEp,
      allEpisodes: detail.value.anime.episodes.map(enrichEpisodeForPlayback),
      taskId: playbackEp.isDownloaded ? playbackEp.downloadTaskId : null,
    })
    showToast(`${tx('Ouverture dans')} ${res.player}`, 'info')
    return true
  } catch (err) {
    showToast(
      err instanceof Error ? err.message : 'Impossible d’ouvrir le lecteur externe.',
      'error',
    )
    return false
  }
}

async function playEpisodeExternal(ep: Episode) {
  await launchEpisodeExternal(ep)
}

async function playEpisode(ep: Episode) {
  if (!detail.value) return
  if (playerStore.prefersExternal) {
    if (await launchEpisodeExternal(ep)) return
  }
  const playbackEp = enrichEpisodeForPlayback(ep)
  playerStore.openPlayer(
    detail.value.anime.title,
    detail.value.anime.url,
    detail.value.source,
    playbackEp,
    detail.value.anime.episodes.map(enrichEpisodeForPlayback),
  )
}

async function downloadEp(ep: Episode) {
  if (!detail.value || isEpisodeDownloaded(ep)) return
  const numStr = rowKey(ep)
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

function promptDeleteDownloaded(ep: Episode) {
  if (deletingEpisodeKey.value) return
  pendingDeleteEpisode.value = ep
}

async function confirmDeleteDownloaded() {
  const ep = pendingDeleteEpisode.value
  if (!ep || !detail.value || deletingEpisodeKey.value) return
  const key = rowKey(ep)
  deletingEpisodeKey.value = key
  const taskId = resolvedDownloadTaskId(ep)
  const ver = ep.version || detail.value.anime.version || ''
  try {
    const res = await api.deleteDownloadedEpisode({
      taskId: taskId != null ? String(taskId) : undefined,
      animeUrl: detail.value.anime.url,
      animeName: detail.value.anime.title,
      episodeUrl: ep.downloadPageUrl || ep.playerUrl || '',
      episodeNumber: Number(ep.number),
      version: ver,
      source: detail.value.source,
      season: episodeSeason(ep) || undefined,
    })
    ep.isDownloaded = false
    ep.downloadTaskId = null
    if (Array.isArray(detail.value.downloadedEpisodes)) {
      detail.value.downloadedEpisodes = detail.value.downloadedEpisodes.filter(
        (item) => String(item) !== String(ep.number) && String(item) !== `${ep.number}-${ver}`,
      )
    }
    detail.value.downloadedCount = detail.value.anime.episodes.filter((item) =>
      isEpisodeDownloaded(item),
    ).length
    const removedSet = new Set((res.removedTaskIds || []).map((id) => String(id)))
    if (taskId != null) removedSet.add(String(taskId))
    downloadStore.tasks = downloadStore.tasks.filter((t) => !removedSet.has(String(t.id)))
    void downloadStore.fetchTasks()
    if (
      playerStore.isOpen &&
      playerStore.isDownloaded &&
      playerStore.currentEpisode &&
      Number(playerStore.currentEpisode.number) === Number(ep.number) &&
      (playerStore.currentEpisode.version || '') === (ep.version || '')
    ) {
      playerStore.closePlayer()
    }
    pendingDeleteEpisode.value = null
    showToast('Épisode téléchargé supprimé.', 'success')
  } catch (err) {
    showToast(
      err instanceof Error ? err.message : 'Impossible de supprimer l’épisode téléchargé.',
      'error',
    )
  } finally {
    deletingEpisodeKey.value = null
  }
}

function previewBatch(targetEps: Episode[]) {
  const eligible = targetEps.filter((ep) => !isEpisodeDownloaded(ep))
  if (!detail.value || !eligible.length || isBatchDownloading.value) return
  pendingBatch.value = {
    animeName: detail.value.anime.title,
    source: detail.value.source,
    preferredQuality: batchQuality.value !== 'auto' ? batchQuality.value : undefined,
    episodes: eligible.map((ep) => ({
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
    detail.value?.anime.episodes.filter(
      (ep) => !isEpisodeDownloaded(ep) && selectedEpisodes.value.has(rowKey(ep)),
    ) || [],
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
  const all = [...filteredEpisodes.value]
    .filter((ep) => !isEpisodeDownloaded(ep))
    .sort((a, b) => Number(a.number) - Number(b.number))
  let targets: Episode[] = []
  if (mode.startsWith('next-'))
    targets = all.filter((ep) => !isWatched(ep)).slice(0, Number(mode.slice(5)))
  else if (mode === 'unwatched') targets = all.filter((ep) => !isWatched(ep))
  else if (mode === 'not-downloaded' || mode === 'all') targets = all
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
  padding: 28px;
  background-color: var(--panel);
  background-image: none;
  display: flex;
  gap: 26px;
  align-items: center;
  box-shadow: var(--shadow);
  border: 1px solid var(--line-strong, var(--line));
  overflow: hidden;
}

.tachiyomi-hero::before {
  content: '';
  position: absolute;
  inset: -24px;
  background-image: var(--hero-bg-img, none);
  background-size: cover;
  background-position: center 25%;
  background-repeat: no-repeat;
  filter: blur(28px) saturate(1.18);
  transform: scale(1.08);
  opacity: var(--hero-backdrop-opacity, 0.5);
  pointer-events: none;
  z-index: 0;
}

.tachiyomi-hero::after {
  content: '';
  position: absolute;
  inset: 0;
  background: var(--hero-radial-overlay), var(--hero-overlay-gradient);
  pointer-events: none;
  z-index: 1;
}

.tachiyomi-cover-wrap,
.tachiyomi-meta {
  position: relative;
  z-index: 2;
}

.tachiyomi-cover {
  width: 150px;
  aspect-ratio: 2 / 3;
  border-radius: var(--radius);
  box-shadow: var(--hero-cover-shadow, 0 12px 28px rgba(0, 0, 0, 0.42));
  border: 1px solid var(--line-strong, var(--line));
  object-fit: cover;
  background: var(--surface);
}

.tachiyomi-cover-placeholder {
  width: 150px;
  aspect-ratio: 2 / 3;
  border-radius: var(--radius);
  background: var(--surface);
  border: 1px solid var(--line-strong, var(--line));
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 28px;
  font-weight: 800;
  color: var(--accent);
}

.tachiyomi-main-title {
  font-size: 26px;
  font-weight: 900;
  margin: 0 0 10px;
  color: var(--hero-title-color, var(--text));
  text-shadow: var(--hero-title-shadow, none);
}

.tachiyomi-meta-line {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 500;
  color: var(--hero-meta-color, var(--muted));
  margin-top: 4px;
}

.tachiyomi-meta-icon {
  color: var(--accent);
  flex-shrink: 0;
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
  border-left: 4px solid var(--accent);
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

.tachiyomi-bar-btn.is-spinning svg {
  animation: spin 0.8s linear infinite;
}

.tachiyomi-cache-line {
  font-size: 12px;
  opacity: 0.9;
}
</style>
