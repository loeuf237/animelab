<template>
  <div class="extensions-view settings-page-layout fade-in">
    <!-- En-tête -->
    <header
      class="page-header"
      style="
        margin-bottom: 28px;
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        flex-wrap: wrap;
        gap: 16px;
      "
    >
      <div>
        <h1 class="page-title" style="display: flex; align-items: center; gap: 12px">
          <svg
            width="28"
            height="28"
            viewBox="0 0 24 24"
            fill="none"
            stroke="#a78bfa"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path
              d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"
            />
            <polyline points="3.27 6.96 12 12.01 20.73 6.96" />
            <line x1="12" y1="22.08" x2="12" y2="12" />
          </svg>
          {{ tx("Gestionnaire d'Extensions Aniyomi") }}
        </h1>
        <p class="page-sub">
          {{
            tx('Installez et activez des extensions tierces pour étendre vos sources de streaming.')
          }}
        </p>
      </div>

      <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap">
        <span
          v-if="updatesCount > 0"
          class="badge"
          style="
            background: rgba(245, 158, 11, 0.18);
            color: #fcd34d;
            border: 1px solid rgba(245, 158, 11, 0.4);
            padding: 8px 14px;
            border-radius: 9999px;
            font-weight: 600;
          "
        >
          🔄 <strong>{{ tx(updatesCount) }}</strong> {{ tx('mise(s) à jour disponible(s)') }}
        </span>
        <span
          class="badge"
          style="
            background: rgba(139, 92, 246, 0.15);
            color: #c4b5fd;
            border: 1px solid rgba(139, 92, 246, 0.3);
            padding: 8px 14px;
            border-radius: 9999px;
            font-weight: 500;
          "
        >
          <strong>{{ tx(enabledCount) }}</strong> / {{ tx(totalCount) }} {{ tx('sources actives') }}
        </span>
      </div>
    </header>

    <AndroidExtensionsPanel ref="androidPanel" @changed="fetchExtensions" />
    <ExtensionRepositoriesPanel ref="repositoryPanel" @changed="fetchExtensions" />

    <!-- Carte d'importation d'un magasin -->
    <section class="settings-card-pro extension-repo-card">
      <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 12px">
        <div
          style="
            width: 40px;
            height: 40px;
            border-radius: 10px;
            background: rgba(139, 92, 246, 0.2);
            display: flex;
            align-items: center;
            justify-content: center;
            color: #a78bfa;
          "
        >
          <svg
            width="22"
            height="22"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
          >
            <path d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242" />
            <path d="M12 12v9" />
            <path d="m8 17 4 4 4-4" />
          </svg>
        </div>
        <div>
          <h2 style="font-size: 1.15rem; font-weight: 600; color: var(--text); margin: 0">
            {{ tx("Magasin d'extensions Aniyomi") }}
          </h2>
          <p style="font-size: 0.85rem; color: var(--muted); margin: 2px 0 0 0">
            {{
              tx('Ajoutez un dépôt pour synchroniser automatiquement les extensions de visionnage.')
            }}
          </p>
        </div>
      </div>

      <!-- Barre d'import -->
      <form @submit.prevent="handleImportRepo" style="margin-top: 16px">
        <div style="display: flex; gap: 10px; flex-wrap: wrap">
          <input
            v-model="repoUrl"
            type="url"
            class="input-premium extension-repo-input"
            placeholder="https://raw.githubusercontent.com/yuzono/anime-repo/repo/index.min.json"
            required
          />
          <button
            type="submit"
            class="btn btn-primary"
            :disabled="isImporting"
            style="
              padding: 12px 24px;
              font-weight: 600;
              display: flex;
              align-items: center;
              gap: 8px;
            "
          >
            <div v-if="isImporting" class="spinner-sm"></div>
            <span>{{ tx(isImporting ? 'Importation en cours...' : 'Importer le magasin') }}</span>
          </button>
        </div>
      </form>

      <!-- Raccourcis Dépôts Populaires -->
      <div
        style="
          margin-top: 14px;
          display: flex;
          align-items: center;
          gap: 8px;
          flex-wrap: wrap;
          font-size: 0.85rem;
          color: #9ca3af;
        "
      >
        <span>{{ tx('Dépôts recommandés :') }}</span>
        <button
          type="button"
          class="speed-preset-chip"
          @click="
            setRepoPreset('https://raw.githubusercontent.com/yuzono/anime-repo/repo/index.min.json')
          "
        >
          ⚡ Yuzono Anime Repo
        </button>
        <button
          type="button"
          class="speed-preset-chip"
          @click="
            setRepoPreset(
              'https://raw.githubusercontent.com/aniyomiorg/aniyomi-extensions/repo/index.min.json',
            )
          "
        >
          📦 Aniyomi Repo
        </button>
      </div>

      <!-- Message d'information de règles -->
      <div
        style="
          margin-top: 16px;
          padding: 10px 14px;
          background: rgba(59, 130, 246, 0.08);
          border-left: 3px solid #60a5fa;
          border-radius: 4px;
          font-size: 0.82rem;
          color: #bfdbfe;
        "
      >
        ℹ️ <strong>{{ tx('Règle de visibilité :') }}</strong>
        {{
          tx(
            'Les dépôts activés sont regroupés ici. Les extensions installées restent disponibles même si leur dépôt est désactivé ou les retire. Les nouvelles extensions sont',
          )
        }}
        <strong>{{ tx('désactivées') }}</strong>
        {{
          tx(
            ': activez manuellement uniquement celles que vous souhaitez utiliser dans la recherche et le streaming.',
          )
        }}
      </div>
    </section>

    <!-- Informations sur le magasin actuellement actif -->
    <div
      v-if="activeRepo"
      style="
        display: flex;
        justify-content: space-between;
        align-items: center;
        background: var(--panel);
        border: 1px solid var(--line);
        padding: 14px 20px;
        border-radius: 12px;
        margin-bottom: 20px;
        flex-wrap: wrap;
        gap: 10px;
      "
    >
      <div style="display: flex; align-items: center; gap: 10px">
        <span
          style="
            display: inline-block;
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: #10b981;
            box-shadow: 0 0 8px #10b981;
          "
        ></span>
        <div>
          <span
            style="
              font-size: 0.8rem;
              text-transform: uppercase;
              letter-spacing: 0.05em;
              color: var(--muted);
            "
            >{{ tx('Dernier dépôt consulté :') }}</span
          >
          <strong style="color: var(--text); margin-left: 6px; font-size: 0.95rem">{{
            tx(activeRepo.name)
          }}</strong>
        </div>
      </div>
      <div
        style="
          font-size: 0.85rem;
          color: #9ca3af;
          display: flex;
          align-items: center;
          gap: 10px;
          flex-wrap: wrap;
        "
      >
        <button
          class="btn btn-sm"
          :disabled="isCheckingUpdates || isImporting"
          @click="checkUpdates"
        >
          {{ tx(isCheckingUpdates ? 'Vérification...' : 'Vérifier les mises à jour') }}
        </button>
        <button
          v-if="updatesCount > 0"
          class="btn btn-sm btn-primary"
          :disabled="isUpdatingAll"
          @click="handleUpdateAll"
        >
          {{ tx(isUpdatingAll ? 'Mise à jour...' : 'Tout mettre à jour') }} ({{ tx(updatesCount) }})
        </button>
        <button class="btn btn-sm" :disabled="isImporting" @click="refreshRepo">
          {{ tx('Actualiser le dépôt') }}
        </button>
        <span>{{ tx('Catalogue :') }} {{ tx(totalCount) }} sources</span>
        <span>{{ tx('Actives :') }} {{ tx(enabledCount) }}</span>
      </div>
    </div>

    <!-- Barre d'outils de filtrage & Recherche instantanée -->
    <div
      style="
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 12px;
        margin-bottom: 20px;
        flex-wrap: wrap;
      "
    >
      <div style="display: flex; gap: 8px; flex-wrap: wrap; align-items: center">
        <button
          type="button"
          class="tab-btn"
          :class="{ active: filterLang === 'all' }"
          @click="filterLang = 'all'"
        >
          {{ tx('Toutes (') }}{{ tx(totalCount) }})
        </button>
        <button
          type="button"
          class="tab-btn"
          :class="{ active: filterLang === 'fr' }"
          @click="filterLang = 'fr'"
        >
          {{ tx('🇫🇷 Français (') }}{{ tx(frCount) }})
        </button>
        <button
          type="button"
          class="tab-btn"
          :class="{ active: filterLang === 'active' }"
          @click="filterLang = 'active'"
        >
          {{ tx('Sources actives uniquement (') }}{{ tx(enabledCount) }})
        </button>
        <button
          type="button"
          class="tab-btn"
          :class="{ active: filterLang === 'updates' }"
          @click="filterLang = 'updates'"
        >
          {{ tx('🔄 Mises à jour (') }}{{ tx(updatesCount) }})
        </button>
      </div>

      <div class="extension-filter-field">
        <input
          v-model="searchQuery"
          type="text"
          class="input-premium"
          style="width: 100%; padding: 8px 12px 8px 36px; font-size: 0.9rem"
          :placeholder="tx('Filtrer une extension par nom ou package...')"
        />
        <svg
          style="
            position: absolute;
            left: 12px;
            top: 50%;
            transform: translateY(-50%);
            color: #9ca3af;
          "
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
        >
          <circle cx="11" cy="11" r="7" />
          <path d="m20 20-4-4" />
        </svg>
      </div>
    </div>

    <!-- Loading spinner -->
    <VerificationPrompt :challenges="extensionChallenges" />
    <p v-if="diagnoseFailure" role="alert">
      {{ tx(diagnoseFailure.message) }}
      <ProxyRotationButton
        :domain="diagnoseFailure.domain"
        :retry="() => diagnose(diagnoseFailure!.extension)"
      />
    </p>
    <div v-if="isLoading" class="loading-state" style="padding: 60px 20px; text-align: center">
      <div class="spinner" style="margin: 0 auto 16px"></div>
      <p style="color: var(--muted)">{{ tx('Chargement du catalogue des extensions...') }}</p>
    </div>

    <!-- Grille des extensions compacte et fluide -->
    <div v-else-if="filteredExtensions.length > 0" class="results-grid extensions-grid">
      <article v-for="ext in filteredExtensions" :key="ext.id" class="ext-card ext-card-compact">
        <div class="ext-compact-left ext-main-info">
          <img
            v-if="ext.icon_url || ext.iconUrl"
            :src="ext.icon_url || ext.iconUrl!"
            :alt="tx(ext.name)"
            class="ext-icon-sm"
            @error="(e) => ((e.target as HTMLElement).style.display = 'none')"
          />
          <div v-else class="ext-avatar-sm">
            {{ tx(ext.name ? ext.name[0].toUpperCase() : 'E') }}
          </div>

          <div style="flex: 1; min-width: 0">
            <div style="display: flex; align-items: center; gap: 6px; flex-wrap: wrap">
              <h3 class="ext-title-text" :title="tx(ext.name)">{{ tx(ext.name) }}</h3>
              <span
                class="version-badge"
                :style="{
                  fontSize: '0.68rem',
                  padding: '1px 5px',
                  background:
                    ext.lang === 'fr' ? '#2563eb' : ext.lang === 'all' ? '#7c3aed' : '#4b5563',
                }"
              >
                {{ tx((ext.lang || 'ALL').toUpperCase()) }}
              </span>
              <span
                v-if="hasExtensionUpdate(ext)"
                class="version-badge"
                style="
                  font-size: 0.68rem;
                  padding: 1px 6px;
                  background: #d97706;
                  color: #fffbeb;
                  font-weight: 600;
                "
              >
                {{ tx('Mise à jour dispo') }}
              </span>
            </div>

            <div
              style="
                display: flex;
                align-items: center;
                gap: 8px;
                font-size: 0.75rem;
                color: #9ca3af;
                margin-top: 2px;
                flex-wrap: wrap;
              "
            >
              <span v-if="hasExtensionUpdate(ext)" style="color: #fbbf24; font-weight: 600">
                v{{ tx(ext.installed_version || ext.version || '1.0') }} → v{{
                  tx(ext.available_version || ext.version || '1.0')
                }}
              </span>
              <span v-else>v{{ tx(ext.installed_version || ext.version || '1.0') }}</span>
              <template v-if="ext.base_url || ext.baseUrl">
                <span>•</span>
                <a
                  :href="ext.base_url || ext.baseUrl!"
                  target="_blank"
                  rel="noopener noreferrer"
                  style="
                    color: #818cf8;
                    text-decoration: none;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    max-width: 140px;
                    white-space: nowrap;
                  "
                  :title="tx(ext.base_url || ext.baseUrl!)"
                >
                  {{ tx(formatDomain(ext.base_url || ext.baseUrl!)) }}
                </a>
              </template>
            </div>

            <div
              v-if="ext.capabilities_summary"
              style="display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px"
            >
              <span
                v-if="ext.capabilities_summary.popular"
                style="
                  font-size: 0.68rem;
                  padding: 1px 6px;
                  border-radius: 999px;
                  background: rgba(16, 185, 129, 0.14);
                  color: #6ee7b7;
                "
              >
                🔥 {{ tx('Populaires') }}
              </span>
              <span
                v-if="(ext.capabilities_summary.tags_count || 0) > 0"
                style="
                  font-size: 0.68rem;
                  padding: 1px 6px;
                  border-radius: 999px;
                  background: rgba(99, 102, 241, 0.15);
                  color: #a5b4fc;
                "
              >
                🏷️ {{ tx(ext.capabilities_summary.tags_count) }} {{ tx('tags') }}
              </span>
              <span
                v-for="feedLabel in (ext.capabilities_summary.custom_feeds || []).slice(0, 2)"
                :key="feedLabel"
                style="
                  font-size: 0.68rem;
                  padding: 1px 6px;
                  border-radius: 999px;
                  background: rgba(236, 72, 153, 0.14);
                  color: #f9a8d4;
                "
              >
                ✨ {{ tx(feedLabel) }}
              </span>
            </div>
          </div>
        </div>

        <div v-if="ext.health?.length" class="extension-health" role="status">
          <strong>{{
            tx(
              ext.health[0]!.recipe_revision === ext.recipe_revision
                ? ext.health[0]!.messageKey
                : 'Recette modifiée, test nécessaire.',
            )
          }}</strong>
          <small
            >{{ tx('Dernière vérification') }} :
            {{ new Date(ext.health[0]!.checked_at).toLocaleString() }} ·
            {{ Math.round(ext.health[0]!.duration_ms) }} ms · r{{
              ext.health[0]!.recipe_revision
            }}</small
          >
        </div>
        <div class="extension-actions">
          <button
            v-if="hasExtensionUpdate(ext)"
            class="btn btn-sm btn-primary"
            :disabled="busyExtensions.has(ext.id)"
            @click="handleUpdateExtension(ext)"
          >
            {{ tx('Mettre à jour') }} (v{{ tx(ext.available_version) }})
          </button>
          <router-link
            v-if="isExtensionActive(ext) && ext.runtime !== 'android-apk'"
            :to="{ name: 'sources', params: { sourceId: ext.pkg } }"
            class="btn btn-sm"
          >
            {{ tx('Explorer') }}
          </router-link>
          <button class="btn btn-sm" :disabled="busyExtensions.has(ext.id)" @click="diagnose(ext)">
            {{ tx('Tester') }}
          </button>
          <button
            v-if="ext.runtime !== 'android-apk'"
            class="btn btn-sm"
            :disabled="busyExtensions.has(ext.id)"
            @click="handleRecompileExtension(ext)"
          >
            {{ tx('Recompiler') }}
          </button>
          <button v-if="ext.runtime !== 'android-apk'" class="btn btn-sm" @click="editRecipe(ext)">
            {{ tx('Configurer') }}
          </button>
          <label class="toggle-switch">
            <input
              type="checkbox"
              :checked="isExtensionActive(ext)"
              :disabled="busyExtensions.has(ext.id)"
              @change="handleToggleExtension(ext, ($event.target as HTMLInputElement).checked)"
            />
            <span class="toggle-slider"></span>
          </label>
        </div>
      </article>
    </div>

    <!-- Empty State -->
    <div
      v-else
      class="empty-state"
      style="
        padding: 60px 20px;
        text-align: center;
        background: rgba(18, 22, 40, 0.4);
        border-radius: 16px;
        border: 1px dashed rgba(255, 255, 255, 0.1);
      "
    >
      <div style="font-size: 2.5rem; margin-bottom: 12px">📦</div>
      <h3 style="font-size: 1.25rem; font-weight: 600; color: #f3f4f6; margin-bottom: 6px">
        {{
          tx(
            extensions.length === 0
              ? "Aucun magasin d'extensions actif"
              : 'Aucune extension ne correspond aux filtres',
          )
        }}
      </h3>
      <p style="color: #9ca3af; max-width: 460px; margin: 0 auto 20px auto; font-size: 0.9rem">
        {{
          tx(
            extensions.length === 0
              ? "Importez un catalogue d'extensions Aniyomi ci-dessus pour afficher et activer vos sources d'animation préférées."
              : 'Modifiez votre recherche ou sélectionnez un autre filtre de langue.',
          )
        }}
      </p>
      <button
        v-if="extensions.length === 0"
        type="button"
        class="btn btn-primary"
        @click="importDefaultRepo"
      >
        {{ tx('⚡ Importer Yuzono Anime Repo en 1 clic') }}
      </button>
    </div>

    <section
      v-if="editingExtension"
      class="settings-card-pro"
      style="padding: 20px; margin-top: 20px"
    >
      <h2>{{ tx('Recette de') }} {{ tx(editingExtension.name) }}</h2>
      <p>
        {{
          tx(
            'Modifiez l’adresse du site et ses sélecteurs si son fonctionnement a changé. Les extensions utilisant une API nécessitent un adaptateur compatible.',
          )
        }}
      </p>
      <textarea
        v-model="recipeText"
        class="input-premium"
        style="width: 100%; min-height: 240px"
        :aria-label="tx('Recette JSON')"
      ></textarea>
      <button
        class="btn btn-primary"
        :disabled="busyExtensions.has(editingExtension.id)"
        @click="saveRecipe"
      >
        {{ tx('Enregistrer') }}
      </button>
      <button class="btn" @click="editingExtension = null">{{ tx('Fermer') }}</button>
      <RecipeHistory
        :key="editingExtension.id"
        :extension-id="editingExtension.id"
        @restored="recipeRestored"
      />
    </section>
    <!-- Notification Toast -->
  </div>
</template>

<script setup lang="ts">
import RecipeHistory from '@/components/RecipeHistory.vue'
import VerificationPrompt from '@/components/VerificationPrompt.vue'
import ProxyRotationButton from '@/components/ProxyRotationButton.vue'
import { useVerificationStore, challengeFromError } from '@/stores/verification'
import type { SourceChallenge } from '@/types'
import { tx } from '@/utils/locale'
import { useNotifications } from '@/stores/notifications'
import { ref, computed, onMounted } from 'vue'
import { api } from '@/api/client'
import AndroidExtensionsPanel from '@/components/AndroidExtensionsPanel.vue'
import ExtensionRepositoriesPanel from '@/components/ExtensionRepositoriesPanel.vue'
const repositoryPanel = ref<InstanceType<typeof ExtensionRepositoriesPanel> | null>(null)
const androidPanel = ref<InstanceType<typeof AndroidExtensionsPanel> | null>(null)
import { useAnimeStore } from '@/stores/anime'
const animeStore = useAnimeStore()
import type { ExtensionSource } from '@/types'

const extensions = ref<ExtensionSource[]>([])
const busyExtensions = ref(new Set<number | string>())
const editingExtension = ref<ExtensionSource | null>(null)
const recipeText = ref('')
const isCheckingUpdates = ref(false)
const isUpdatingAll = ref(false)

function editRecipe(ext: ExtensionSource) {
  editingExtension.value = ext
  recipeText.value = JSON.stringify(
    ext.recipe_json
      ? JSON.parse(ext.recipe_json)
      : {
          base_url: ext.base_url || '',
          search_request_path: '/?s={query}',
          search_selector: 'article',
          episode_list_selector: '.episodes a',
        },
    null,
    2,
  )
}
async function recipeRestored() {
  animeStore.homeFeed = null
  await fetchExtensions()
  const updated = extensions.value.find((ext) => ext.id === editingExtension.value?.id)
  if (updated) editRecipe(updated)
}
async function saveRecipe() {
  const ext = editingExtension.value
  if (!ext) return
  busyExtensions.value.add(ext.id)
  try {
    await api.configureExtension(ext.id, JSON.parse(recipeText.value))
    animeStore.homeFeed = null
    await fetchExtensions()
    editingExtension.value = null
    showToast('Recette enregistrée.', 'success')
  } catch (e: any) {
    showToast(e.message, 'error')
  } finally {
    busyExtensions.value.delete(ext.id)
  }
}
const extensionChallenges = ref<SourceChallenge[]>([])
const diagnoseFailure = ref<{ domain: string; message: string; extension: ExtensionSource } | null>(
  null,
)
function showDiagnoseFailure(ext: ExtensionSource, message: string) {
  try {
    const url = new URL(ext.base_url || ext.baseUrl || '')
    if (['http:', 'https:'].includes(url.protocol) && !url.username && !url.password)
      diagnoseFailure.value = { domain: url.hostname, message, extension: ext }
  } catch {
    /* An invalid recipe has no source session to rotate. */
  }
}
async function diagnose(ext: ExtensionSource) {
  busyExtensions.value.add(ext.id)
  extensionChallenges.value = []
  diagnoseFailure.value = null
  try {
    const result = await api.diagnoseExtension(ext.id)
    if (!result.success) showDiagnoseFailure(ext, result.message)
    showToast(`${ext.name} : ${tx(result.message)}`, result.success ? 'success' : 'error')
  } catch (e: any) {
    const challenge = challengeFromError(e)
    if (challenge) {
      extensionChallenges.value = [challenge]
      useVerificationStore().waitForVerification('extension-diagnose', [challenge], async () => {
        await diagnose(ext)
      })
    } else {
      showDiagnoseFailure(ext, e.message)
      showToast(e.message, 'error')
    }
  } finally {
    await fetchExtensions()
    busyExtensions.value.delete(ext.id)
  }
}
async function refreshRepo() {
  isImporting.value = true
  try {
    await api.refreshExtensions()
    animeStore.homeFeed = null
    await fetchExtensions()
    showToast('Dépôt actualisé.', 'success')
  } catch (e: any) {
    showToast(e.message, 'error')
  } finally {
    isImporting.value = false
  }
}
async function checkUpdates() {
  isCheckingUpdates.value = true
  try {
    const res = await api.checkExtensionUpdates()
    await fetchExtensions()
    showToast(
      res.message ||
        (res.count
          ? `${res.count} mise(s) à jour disponible(s).`
          : 'Toutes vos extensions installées sont à jour.'),
      res.count ? 'info' : 'success',
    )
    if (res.count && res.count > 0) {
      filterLang.value = 'updates'
    }
  } catch (e: any) {
    showToast(e.message || 'Erreur lors de la vérification des mises à jour.', 'error')
  } finally {
    isCheckingUpdates.value = false
  }
}
async function handleUpdateExtension(ext: ExtensionSource) {
  busyExtensions.value.add(ext.id)
  try {
    const res = await api.updateExtension(ext.id)
    animeStore.homeFeed = null
    await fetchExtensions()
    showToast(res.message || `${ext.name} mis à jour.`, 'success')
  } catch (e: any) {
    showToast(e.message || 'Erreur lors de la mise à jour.', 'error')
  } finally {
    busyExtensions.value.delete(ext.id)
  }
}
async function handleUpdateAll() {
  isUpdatingAll.value = true
  try {
    const res = await api.updateAllExtensions()
    animeStore.homeFeed = null
    await fetchExtensions()
    const failed = res.failed?.length || 0
    const pending = res.pending_ids?.length || 0
    showToast(
      res.message ||
        `${res.count || 0} mise(s) à jour terminée(s), ${pending} en attente Android, ${failed} échec(s).`,
      failed ? 'error' : 'success',
    )
  } catch (e: any) {
    showToast(e.message || 'Erreur lors de la mise à jour globale.', 'error')
  } finally {
    isUpdatingAll.value = false
  }
}
async function handleRecompileExtension(ext: ExtensionSource) {
  busyExtensions.value.add(ext.id)
  try {
    const res = await api.recompileExtension(ext.id)
    animeStore.homeFeed = null
    await fetchExtensions()
    showToast(res.message || `Recette recompilée pour ${ext.name}.`, 'success')
  } catch (e: any) {
    showToast(e.message || 'Erreur lors de la recompilation.', 'error')
  } finally {
    busyExtensions.value.delete(ext.id)
  }
}
const activeRepo = ref<any>(null)
const isLoading = ref(false)
const isImporting = ref(false)
const repoUrl = ref('https://raw.githubusercontent.com/yuzono/anime-repo/repo/index.min.json')

const filterLang = ref<'all' | 'fr' | 'active' | 'updates'>('all')
const searchQuery = ref('')

const notifications = useNotifications()
function showToast(message: string, tone: 'success' | 'error' | 'info' = 'info') {
  notifications.notify(message, tone)
}

function formatDomain(url: string) {
  return url.replace('https://', '').replace('http://', '').replace(/\/$/, '')
}

function isExtensionActive(ext: ExtensionSource) {
  return Boolean(ext.is_enabled ?? ext.enabled)
}

function hasExtensionUpdate(ext: ExtensionSource) {
  return Boolean(ext.has_update)
}

const totalCount = computed(() => extensions.value.length)
const enabledCount = computed(() => extensions.value.filter(isExtensionActive).length)
const updatesCount = computed(() => extensions.value.filter(hasExtensionUpdate).length)
const frCount = computed(
  () => extensions.value.filter((e) => (e.lang || '').toLowerCase() === 'fr').length,
)

const filteredExtensions = computed(() => {
  return extensions.value.filter((ext) => {
    // Filter by language / active / updates tab
    if (filterLang.value === 'fr' && (ext.lang || '').toLowerCase() !== 'fr') {
      return false
    }
    if (filterLang.value === 'active' && !isExtensionActive(ext)) {
      return false
    }
    if (filterLang.value === 'updates' && !hasExtensionUpdate(ext)) {
      return false
    }

    // Filter by search query
    if (searchQuery.value.trim()) {
      const q = searchQuery.value.trim().toLowerCase()
      const matchName = (ext.name || '').toLowerCase().includes(q)
      const matchPkg = (ext.pkg || '').toLowerCase().includes(q)
      if (!matchName && !matchPkg) return false
    }

    return true
  })
})

async function fetchExtensions() {
  isLoading.value = true
  try {
    const res = await api.getExtensions()
    if (res) {
      activeRepo.value = res.active_repo || null
      extensions.value = res.extensions || res.installed || []
      await Promise.all([repositoryPanel.value?.reload(), androidPanel.value?.reload()])
    }
  } catch (e: any) {
    showToast(e.message || 'Erreur lors du chargement des extensions.', 'error')
  } finally {
    isLoading.value = false
  }
}

function importDefaultRepo() {
  setRepoPreset('https://raw.githubusercontent.com/yuzono/anime-repo/repo/index.min.json')
  void handleImportRepo()
}

function setRepoPreset(url: string) {
  repoUrl.value = url
}

async function handleImportRepo() {
  const url = repoUrl.value.trim()
  if (!url) return

  isImporting.value = true
  try {
    const res = await api.importExtensionRepo(url)
    animeStore.homeFeed = null
    showToast(
      `Dépôt "${res.repo_name || 'Aniyomi'}" importé avec succès (${res.count || 0} extensions) !`,
      'success',
    )
    await fetchExtensions()
  } catch (e: any) {
    showToast(e.message || "Échec de l'importation du dépôt.", 'error')
  } finally {
    isImporting.value = false
  }
}

async function handleToggleExtension(ext: ExtensionSource, enabled: boolean) {
  busyExtensions.value.add(ext.id)
  try {
    const result = await api.toggleExtension(ext.id, enabled)
    animeStore.homeFeed = null
    await fetchExtensions()
    showToast(result.pending ? 'Confirmez l’installation dans Android, puis approuvez le paquet installé.' : `${ext.name} ${enabled ? 'activée' : 'désactivée'}.`, 'success')
  } catch (e: any) {
    showToast(e.message || "Erreur lors de l'activation/désactivation de l'extension.", 'error')
    await fetchExtensions()
  } finally {
    busyExtensions.value.delete(ext.id)
  }
}

onMounted(() => {
  fetchExtensions()
})
</script>

<style scoped>
.extensions-view {
  max-width: 1200px;
  padding: 24px 20px;
}
.extension-repo-card {
  margin-bottom: 28px;
  padding: 24px;
}
.extension-repo-input {
  flex: 1;
  min-width: min(320px, 100%);
  padding: 12px 16px;
  font-size: 0.95rem;
}
.extension-filter-field {
  position: relative;
  min-width: min(260px, 100%);
  flex: 1;
  max-width: 360px;
}
@media (max-width: 768px) {
  .extensions-view {
    padding: 0;
  }
  .extension-repo-card {
    padding: 14px;
    margin-bottom: 0;
  }
  .extension-repo-input {
    width: 100%;
    min-width: 0;
    flex-basis: 100%;
  }
  .extension-filter-field {
    min-width: 0;
    width: 100%;
    flex-basis: 100%;
  }
  .extension-actions .btn {
    min-height: 44px;
  }
}

.extension-health {
  min-width: 0;
  display: grid;
  gap: 4px;
  font-size: 0.78rem;
  overflow-wrap: anywhere;
}
.extension-health small {
  color: var(--text-secondary);
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

.extensions-grid.results-grid {
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 320px), 1fr)) !important;
  gap: 12px !important;
}
.extensions-grid .ext-card-compact {
  min-width: 0;
  flex-direction: column !important;
  align-items: stretch !important;
}
.ext-main-info {
  width: 100%;
  min-width: 0;
}
.ext-title-text {
  white-space: normal !important;
  overflow-wrap: anywhere;
}
.extension-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.extension-actions .toggle-switch {
  margin-left: auto;
  flex-shrink: 0;
}
.ext-main-info .version-badge {
  flex-shrink: 0;
}
</style>
