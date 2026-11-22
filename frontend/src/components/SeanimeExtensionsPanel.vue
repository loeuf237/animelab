<template>
  <section class="seanime-panel" data-testid="seanime-extensions-panel">
    <!-- Status & global actions bar -->
    <div class="glass-panel seanime-status-bar">
      <div class="seanime-status-info">
        <div class="seanime-title-row">
          <h2>{{ tx('Extensions Seanime') }}</h2>
          <span
            class="seanime-engine-pill"
            :class="{ ok: runtimeAvailable, warn: !runtimeAvailable }"
            data-testid="seanime-engine-badge"
          >
            {{
              runtimeAvailable
                ? engine === 'android-webview'
                  ? tx('Moteur WebView Android')
                  : tx('Moteur V8 (mini-racer)')
                : tx('Moteur JS indisponible')
            }}
          </span>
        </div>
        <p class="seanime-subtitle">
          {{
            tx(
              'Importez des Marketplaces ou dépôts Seanime à côté d’Aniyomi. Les extensions de streaming vidéo (onlinestream-provider) s’exécutent directement dans AnimeLab.',
            )
          }}
        </p>
      </div>

      <div class="seanime-global-actions">
        <button
          type="button"
          class="btn btn-secondary"
          :disabled="isCheckingUpdates"
          data-testid="seanime-check-updates"
          @click="handleCheckUpdates"
        >
          <RefreshCw :size="15" />
          {{ tx(isCheckingUpdates ? 'Vérification…' : 'Vérifier les mises à jour') }}
        </button>
        <button
          v-if="updatesCount > 0"
          type="button"
          class="btn btn-primary"
          :disabled="isUpdatingAll"
          data-testid="seanime-update-all"
          @click="handleUpdateAll"
        >
          <Download :size="15" />
          {{ tx('Tout mettre à jour') }} ({{ updatesCount }})
        </button>
      </div>
    </div>

    <!-- Repositories & Marketplace importer -->
    <details
      class="extension-management"
      :open="repositories.length === 0"
      data-testid="seanime-repositories-details"
    >
      <summary>{{ tx('Dépôts & Marketplaces Seanime') }} ({{ repositories.length }})</summary>

      <div class="glass-panel seanime-import-card">
        <form class="seanime-import-row" @submit.prevent="handleImportRepo">
          <input
            v-model="repoUrl"
            type="url"
            class="input-premium seanime-url-input"
            :placeholder="tx('URL Marketplace Main.json, dépôt {urls:[...]} ou manifest.json')"
            aria-label="URL du dépôt ou Marketplace Seanime"
            data-testid="seanime-repo-url-input"
          />
          <button
            type="submit"
            class="btn btn-primary"
            :disabled="isImporting || !repoUrl.trim()"
            data-testid="seanime-import-repo-btn"
          >
            <Download :size="15" />
            {{ tx(isImporting ? 'Importation…' : 'Importer le dépôt') }}
          </button>
          <button
            type="button"
            class="btn btn-secondary"
            :disabled="isImporting"
            data-testid="seanime-import-bas1874-btn"
            @click="importBas1874Marketplace"
          >
            {{ tx('Bas1874 Seanime Marketplace') }}
          </button>
        </form>

        <form
          class="seanime-import-row seanime-manifest-row"
          @submit.prevent="handleInstallManifest"
        >
          <input
            v-model="manifestUrl"
            type="url"
            class="input-premium seanime-url-input"
            :placeholder="tx('Installer directement depuis une URL de manifeste (.json)')"
            aria-label="URL de manifeste Seanime"
            data-testid="seanime-manifest-url-input"
          />
          <button
            type="submit"
            class="btn btn-secondary"
            :disabled="isInstallingManifest || !manifestUrl.trim()"
            data-testid="seanime-install-manifest-btn"
          >
            {{ tx(isInstallingManifest ? 'Installation…' : 'Installer le manifeste') }}
          </button>
        </form>

        <div v-if="repositories.length > 0" class="seanime-repo-list">
          <div
            v-for="repo in repositories"
            :key="repo.id"
            class="seanime-repo-item"
            :data-testid="`seanime-repo-${repo.id}`"
          >
            <div class="seanime-repo-meta">
              <div class="seanime-repo-title">
                <strong>{{ repo.name }}</strong>
                <span class="seanime-pill">{{ repoKindLabel(repo.kind) }}</span>
                <span class="seanime-pill">
                  {{ repo.extension_count }} {{ tx('ext.') }} · {{ repo.installed_count }}
                  {{ tx('inst.') }}
                </span>
              </div>
              <small class="seanime-repo-url">{{ repo.url }}</small>
              <small v-if="repo.last_error" class="seanime-error-text">{{ repo.last_error }}</small>
            </div>
            <div class="seanime-repo-actions">
              <button
                type="button"
                class="btn btn-secondary btn-sm"
                @click="handleToggleRepo(repo, !repo.is_active)"
              >
                {{ tx(repo.is_active ? 'Actif' : 'Inactif') }}
              </button>
              <button
                type="button"
                class="btn btn-secondary btn-sm"
                :title="tx('Actualiser ce dépôt')"
                @click="handleRefreshRepo(repo.id)"
              >
                <RefreshCw :size="14" />
              </button>
              <button
                type="button"
                class="btn btn-secondary btn-sm danger-btn"
                :title="tx('Supprimer ce dépôt')"
                @click="handleDeleteRepo(repo.id)"
              >
                <Trash2 :size="14" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </details>

    <!-- Search & filter toolbar -->
    <div class="seanime-toolbar">
      <label class="explorer-search seanime-search-label">
        <span>{{ tx('Rechercher dans Seanime') }}</span>
        <div class="seanime-search-box">
          <Search :size="15" class="seanime-search-icon" />
          <input
            v-model="searchQuery"
            type="search"
            class="input-premium"
            :placeholder="tx('Nom, identifiant, auteur ou description')"
            data-testid="seanime-search-input"
          />
        </div>
      </label>

      <div class="seanime-filter-group">
        <div class="seanime-tabs" role="tablist">
          <button
            type="button"
            class="tab-btn"
            :class="{ active: viewFilter === 'streaming' }"
            data-testid="seanime-filter-streaming"
            @click="viewFilter = 'streaming'"
          >
            {{ tx('Streaming vidéo') }} ({{ streamingCount }})
          </button>
          <button
            type="button"
            class="tab-btn"
            :class="{ active: viewFilter === 'installed' }"
            data-testid="seanime-filter-installed"
            @click="viewFilter = 'installed'"
          >
            {{ tx('Installées') }} ({{ installedCount }})
          </button>
          <button
            type="button"
            class="tab-btn"
            :class="{ active: viewFilter === 'updates' }"
            data-testid="seanime-filter-updates"
            @click="viewFilter = 'updates'"
          >
            {{ tx('Mises à jour') }} ({{ updatesCount }})
          </button>
          <button
            type="button"
            class="tab-btn"
            :class="{ active: viewFilter === 'all' }"
            data-testid="seanime-filter-all"
            @click="viewFilter = 'all'"
          >
            {{ tx('Tout le catalogue') }} ({{ extensions.length }})
          </button>
        </div>

        <select
          v-model="langFilter"
          class="input-premium seanime-lang-select"
          aria-label="Filtrer par langue"
          data-testid="seanime-lang-filter"
        >
          <option value="all">{{ tx('Toutes les langues') }}</option>
          <option v-for="code in availableLanguages" :key="code" :value="code">
            {{ code.toUpperCase() }}
          </option>
        </select>
      </div>
    </div>

    <!-- Loading & empty state -->
    <div v-if="isLoading && extensions.length === 0" class="seanime-empty-state">
      {{ tx('Chargement du catalogue Seanime…') }}
    </div>
    <div v-else-if="filteredExtensions.length === 0" class="glass-panel seanime-empty-state">
      <p v-if="extensions.length === 0">
        {{
          tx(
            'Aucun dépôt Seanime importé. Cliquez sur « Bas1874 Seanime Marketplace » ou collez une URL ci-dessus pour commencer.',
          )
        }}
      </p>
      <p v-else>{{ tx('Aucune extension Seanime ne correspond à ces filtres.') }}</p>
    </div>

    <!-- Extensions list -->
    <div v-else class="seanime-ext-list" data-testid="seanime-extension-list">
      <article
        v-for="ext in visibleExtensions"
        :key="`${ext.repo_id}:${ext.ext_id}`"
        class="seanime-ext-card"
        :data-testid="`seanime-ext-${ext.ext_id}`"
      >
        <div class="seanime-ext-avatar">
          <img
            v-if="ext.icon_url && !brokenIcons.has(ext.ext_id)"
            :src="ext.icon_url"
            :alt="ext.name"
            loading="lazy"
            @error="brokenIcons.add(ext.ext_id)"
          />
          <span v-else>{{ initials(ext.name) }}</span>
        </div>

        <div class="seanime-ext-body">
          <div class="seanime-ext-heading">
            <strong>{{ ext.name }}</strong>
            <span class="seanime-pill">{{ ext.ext_id }}</span>
            <span class="seanime-pill">
              v{{ ext.installed_version || ext.version }}
              <template v-if="ext.has_update"> → v{{ ext.available_version }}</template>
            </span>
            <span class="seanime-pill">{{ ext.language.toUpperCase() }}</span>
            <span class="seanime-pill">{{ ext.lang.toUpperCase() }}</span>
            <span class="seanime-pill" :class="{ muted: !ext.supported }">
              {{ ext.ext_type }}
            </span>
            <span
              v-if="ext.marketplace_meta?.workingTag"
              class="seanime-pill ok"
              :title="
                tx(
                  'Étiquette déclarée dans l’index distant du Marketplace Seanime (non vérifiée localement).',
                )
              "
            >
              {{ tx('Tag marketplace : OK') }}
            </span>
            <span v-if="ext.marketplace_meta?.brokenTag" class="seanime-pill warn">
              {{ tx('Signalée cassée') }}
            </span>
            <span
              v-if="ext.installed && ext.health?.last_diagnose"
              class="seanime-pill"
              :class="ext.health.last_diagnose.ok ? 'ok' : 'warn'"
              :title="
                ext.health.last_diagnose.ok
                  ? `${tx('Dernier test local réussi')} (${ext.health.last_diagnose.stream_count} ${tx('flux')})`
                  : ext.health.last_diagnose.error || tx('Dernier test local en échec')
              "
            >
              {{ tx(ext.health.last_diagnose.ok ? 'Test local : OK' : 'Test local : Échec') }}
            </span>
            <span v-if="ext.needs_config && ext.installed" class="seanime-pill warn">
              {{ tx('Configuration requise') }}
            </span>
          </div>

          <p v-if="ext.description" class="seanime-ext-desc">{{ ext.description }}</p>

          <div class="seanime-ext-sub">
            <span v-if="ext.author">{{ tx('Auteur :') }} {{ ext.author }}</span>
            <span v-if="ext.repo_name">· {{ ext.repo_name }}</span>
            <a
              v-if="ext.website"
              :href="ext.website"
              target="_blank"
              rel="noopener noreferrer"
              class="seanime-ext-link"
            >
              <Globe :size="13" /> {{ tx('Site') }}
            </a>
          </div>

          <p v-if="ext.last_error" class="seanime-error-text">{{ ext.last_error }}</p>
        </div>

        <div class="seanime-ext-actions">
          <template v-if="!ext.supported">
            <span
              class="seanime-non-exec-badge"
              data-testid="seanime-non-executable-badge"
              :title="
                tx(
                  'Seules les extensions Seanime de type onlinestream-provider sont exécutées dans AnimeLab.',
                )
              "
            >
              {{ tx('Non exécutable (streaming uniquement)') }}
            </span>
          </template>
          <template v-else-if="!ext.installed">
            <button
              type="button"
              class="btn btn-primary btn-sm"
              :disabled="busyIds.has(ext.ext_id) || !runtimeAvailable"
              :data-testid="`seanime-install-${ext.ext_id}`"
              @click="handleInstallExtension(ext)"
            >
              <Download :size="14" />
              {{ tx(busyIds.has(ext.ext_id) ? 'Installation…' : 'Installer') }}
            </button>
          </template>
          <template v-else>
            <button
              type="button"
              class="btn btn-sm"
              :class="ext.enabled ? 'btn-primary' : 'btn-secondary'"
              :disabled="busyIds.has(ext.ext_id)"
              :data-testid="`seanime-toggle-${ext.ext_id}`"
              @click="handleToggleExtension(ext, !ext.enabled)"
            >
              {{ tx(ext.enabled ? 'Activée' : 'Désactivée') }}
            </button>

            <router-link
              v-if="ext.enabled && ext.source_id"
              :to="{
                name: 'sources',
                params: { sourceId: ext.source_id },
                query: { mode: 'search' },
              }"
              class="btn btn-secondary btn-sm"
            >
              <Search :size="14" />
              {{ tx('Rechercher') }}
            </router-link>

            <button
              v-if="(ext.user_config?.fields?.length || 0) > 0"
              type="button"
              class="btn btn-secondary btn-sm"
              :data-testid="`seanime-config-${ext.ext_id}`"
              @click="openConfigModal(ext)"
            >
              <Settings2 :size="14" />
              {{ tx('Configurer') }}
            </button>

            <button
              type="button"
              class="btn btn-secondary btn-sm"
              :disabled="busyIds.has(ext.ext_id)"
              :data-testid="`seanime-diagnose-${ext.ext_id}`"
              @click="handleDiagnoseExtension(ext)"
            >
              <Zap :size="14" />
              {{ tx('Tester') }}
            </button>

            <button
              v-if="ext.has_update"
              type="button"
              class="btn btn-primary btn-sm"
              :disabled="busyIds.has(ext.ext_id)"
              :data-testid="`seanime-update-${ext.ext_id}`"
              @click="handleUpdateExtension(ext)"
            >
              {{ tx('Mettre à jour') }}
            </button>

            <button
              type="button"
              class="btn btn-secondary btn-sm danger-btn"
              :disabled="busyIds.has(ext.ext_id)"
              :data-testid="`seanime-uninstall-${ext.ext_id}`"
              @click="handleUninstallExtension(ext)"
            >
              <Trash2 :size="14" />
              {{ tx('Désinstaller') }}
            </button>
          </template>
        </div>
      </article>

      <div v-if="filteredExtensions.length > visibleLimit" class="seanime-load-more">
        <button type="button" class="btn btn-secondary" @click="visibleLimit += 60">
          {{ tx('Afficher plus') }} ({{ filteredExtensions.length - visibleLimit }}
          {{ tx('restantes') }})
        </button>
      </div>
    </div>

    <!-- UserConfig Modal -->
    <div
      v-if="configModal"
      class="seanime-modal-backdrop"
      role="dialog"
      aria-modal="true"
      data-testid="seanime-config-modal"
    >
      <div class="glass-panel seanime-modal">
        <header class="seanime-modal-header">
          <h3>{{ tx('Configuration :') }} {{ configModal.name }}</h3>
          <button type="button" class="btn btn-secondary btn-sm" @click="configModal = null">
            <X :size="16" />
          </button>
        </header>
        <form class="seanime-config-form" @submit.prevent="saveConfig">
          <div
            v-for="field in configModal.schema.fields || []"
            :key="field.name"
            class="seanime-config-field"
          >
            <label :for="`cfg-${field.name}`">{{ field.label }}</label>
            <select
              v-if="field.type === 'select'"
              :id="`cfg-${field.name}`"
              v-model="configValues[field.name]"
              class="input-premium"
            >
              <option v-for="opt in field.options || []" :key="opt.value" :value="opt.value">
                {{ opt.label }}
              </option>
            </select>
            <label v-else-if="field.type === 'switch'" class="seanime-switch-row">
              <input
                :id="`cfg-${field.name}`"
                type="checkbox"
                :checked="configValues[field.name] === 'true'"
                @change="
                  configValues[field.name] = ($event.target as HTMLInputElement).checked
                    ? 'true'
                    : 'false'
                "
              />
              <span>{{ tx('Activé') }}</span>
            </label>
            <input
              v-else
              :id="`cfg-${field.name}`"
              v-model="configValues[field.name]"
              type="text"
              class="input-premium"
              :placeholder="field.default || ''"
            />
          </div>
          <div class="seanime-modal-footer">
            <button type="button" class="btn btn-secondary" @click="configModal = null">
              {{ tx('Annuler') }}
            </button>
            <button
              type="submit"
              class="btn btn-primary"
              :disabled="isSavingConfig"
              data-testid="seanime-config-save"
            >
              {{ tx(isSavingConfig ? 'Enregistrement…' : 'Enregistrer') }}
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- Diagnose Result Modal -->
    <div
      v-if="diagnoseResult"
      class="seanime-modal-backdrop"
      role="dialog"
      aria-modal="true"
      data-testid="seanime-diagnose-modal"
    >
      <div class="glass-panel seanime-modal">
        <header class="seanime-modal-header">
          <h3>{{ tx('Diagnostic :') }} {{ diagnoseResult.extension_id }}</h3>
          <button type="button" class="btn btn-secondary btn-sm" @click="diagnoseResult = null">
            <X :size="16" />
          </button>
        </header>
        <div class="seanime-diagnose-body">
          <p>
            <strong>{{ tx('Statut :') }}</strong>
            {{ diagnoseResult.ok ? tx('OK') : tx('Échec') }} · <strong>{{ tx('Moteur :') }}</strong>
            {{ diagnoseResult.engine }} · <strong>{{ tx('Durée :') }}</strong>
            {{ diagnoseResult.duration_ms }} ms
          </p>
          <p>
            <strong>{{ tx('Compilation JS/TS :') }}</strong>
            {{ diagnoseResult.syntax_ok ? tx('OK') : tx('Échec') }}
          </p>
          <p v-if="diagnoseResult.settings">
            <strong>{{ tx('Serveurs détectés :') }}</strong>
            {{ diagnoseResult.settings.episodeServers.join(', ') || '—' }}
          </p>
          <p>
            <strong>{{ tx('Résultats de recherche :') }}</strong>
            {{ diagnoseResult.search_count }} · <strong>{{ tx('Épisodes :') }}</strong>
            {{ diagnoseResult.episode_count }} · <strong>{{ tx('Flux vidéo :') }}</strong>
            {{ diagnoseResult.stream_count }}
          </p>
          <p v-if="diagnoseResult.sample_titles?.length">
            <strong>{{ tx('Exemples :') }}</strong> {{ diagnoseResult.sample_titles.join(' · ') }}
          </p>
          <p v-if="diagnoseResult.error" class="seanime-error-text">
            {{ diagnoseResult.error }}
          </p>
        </div>
        <div class="seanime-modal-footer">
          <button type="button" class="btn btn-primary" @click="diagnoseResult = null">
            {{ tx('Fermer') }}
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Download, Globe, RefreshCw, Search, Settings2, Trash2, X, Zap } from 'lucide-vue-next'
import { api } from '@/api/client'
import { useAnimeStore } from '@/stores/anime'
import { useNotifications } from '@/stores/notifications'
import type {
  SeanimeConfigResponse,
  SeanimeDiagnoseResult,
  SeanimeExtension,
  SeanimeRepository,
} from '@/types/extensions'
import { tx } from '@/utils/locale'

const BAS1874_URL =
  'https://raw.githubusercontent.com/Bas1874/Seanime-Marketplace/refs/heads/main/Marketplace/Main.json'

const animeStore = useAnimeStore()
const notifications = useNotifications()

const runtimeAvailable = ref(true)
const engine = ref('mini-racer')
const extensions = ref<SeanimeExtension[]>([])
const repositories = ref<SeanimeRepository[]>([])
const isLoading = ref(false)
const isImporting = ref(false)
const isInstallingManifest = ref(false)
const isCheckingUpdates = ref(false)
const isUpdatingAll = ref(false)
const isSavingConfig = ref(false)

const repoUrl = ref(BAS1874_URL)
const manifestUrl = ref('')
const searchQuery = ref('')
const viewFilter = ref<'streaming' | 'installed' | 'updates' | 'all'>('streaming')
const langFilter = ref('all')
const visibleLimit = ref(60)

const busyIds = reactive(new Set<string>())
const brokenIcons = reactive(new Set<string>())

const configModal = ref<SeanimeConfigResponse | null>(null)
const configValues = ref<Record<string, string>>({})
const diagnoseResult = ref<SeanimeDiagnoseResult | null>(null)

const streamingCount = computed(() => extensions.value.filter((ext) => ext.supported).length)
const installedCount = computed(() => extensions.value.filter((ext) => ext.installed).length)
const updatesCount = computed(
  () => extensions.value.filter((ext) => ext.installed && ext.has_update).length,
)

const availableLanguages = computed(() => {
  const langs = new Set<string>()
  for (const ext of extensions.value) {
    if (ext.lang) langs.add(ext.lang.toLowerCase())
  }
  return Array.from(langs).sort()
})

const filteredExtensions = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  const lang = langFilter.value.toLowerCase()
  return extensions.value.filter((ext) => {
    if (viewFilter.value === 'streaming' && !ext.supported) return false
    if (viewFilter.value === 'installed' && !ext.installed) return false
    if (viewFilter.value === 'updates' && !(ext.installed && ext.has_update)) return false
    if (lang !== 'all' && (ext.lang || '').toLowerCase() !== lang) return false
    if (q) {
      const hay = `${ext.name} ${ext.ext_id} ${ext.author} ${ext.description}`.toLowerCase()
      if (!hay.includes(q)) return false
    }
    return true
  })
})

const visibleExtensions = computed(() => filteredExtensions.value.slice(0, visibleLimit.value))

function initials(name: string): string {
  const words = (name || '?').trim().split(/\s+/)
  return words
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() || '')
    .join('')
}

function repoKindLabel(kind: string): string {
  if (kind === 'marketplace') return 'Marketplace'
  if (kind === 'repository') return tx('Dépôt')
  return 'Manifeste'
}

async function loadCatalog(silent = false) {
  if (!silent && extensions.value.length === 0) isLoading.value = true
  try {
    const res = await api.getSeanimeExtensions()
    runtimeAvailable.value = res.runtime_available
    engine.value = res.engine
    extensions.value = res.extensions || []
    repositories.value = res.repositories || []
  } catch (err: any) {
    if (!silent) {
      notifications.notify(err?.message || 'Erreur lors du chargement Seanime.', 'error')
    }
  } finally {
    isLoading.value = false
  }
}

async function handleImportRepo() {
  const target = repoUrl.value.trim()
  if (!target) return
  isImporting.value = true
  try {
    const res = await api.importSeanimeRepository(target)
    await loadCatalog(true)
    notifications.notify(
      `Dépôt « ${res.repo.name} » importé (${res.count} extensions, ${res.executable_count} streaming).`,
      'success',
    )
  } catch (err: any) {
    notifications.notify(err?.message || "Échec de l'importation Seanime.", 'error')
  } finally {
    isImporting.value = false
  }
}

function importBas1874Marketplace() {
  repoUrl.value = BAS1874_URL
  void handleImportRepo()
}

async function handleInstallManifest() {
  const target = manifestUrl.value.trim()
  if (!target) return
  isInstallingManifest.value = true
  try {
    const ext = await api.installSeanimeManifest(target, true)
    manifestUrl.value = ''
    animeStore.homeFeed = null
    await loadCatalog(true)
    notifications.notify(`${ext.name} installée et activée.`, 'success')
  } catch (err: any) {
    notifications.notify(err?.message || "Échec de l'installation du manifeste.", 'error')
  } finally {
    isInstallingManifest.value = false
  }
}

async function handleToggleRepo(repo: SeanimeRepository, enabled: boolean) {
  try {
    await api.toggleSeanimeRepository(repo.id, enabled)
    animeStore.homeFeed = null
    await loadCatalog(true)
  } catch (err: any) {
    notifications.notify(err?.message || 'Erreur lors de la mise à jour du dépôt.', 'error')
  }
}

async function handleRefreshRepo(repoId: number) {
  try {
    await api.refreshSeanimeRepositories(repoId)
    await loadCatalog(true)
    notifications.notify('Dépôt Seanime actualisé.', 'success')
  } catch (err: any) {
    notifications.notify(err?.message || "Échec de l'actualisation.", 'error')
  }
}

async function handleDeleteRepo(repoId: number) {
  try {
    await api.deleteSeanimeRepository(repoId)
    animeStore.homeFeed = null
    await loadCatalog(true)
    notifications.notify('Dépôt Seanime supprimé.', 'info')
  } catch (err: any) {
    notifications.notify(err?.message || 'Erreur lors de la suppression.', 'error')
  }
}

async function handleInstallExtension(ext: SeanimeExtension) {
  busyIds.add(ext.ext_id)
  try {
    const res = await api.installSeanimeExtension(ext.ext_id, { repoId: ext.repo_id, enable: true })
    animeStore.homeFeed = null
    await loadCatalog(true)
    notifications.notify(`${res.name} installée et activée.`, 'success')
  } catch (err: any) {
    notifications.notify(err?.message || "Échec de l'installation Seanime.", 'error')
    await loadCatalog(true)
  } finally {
    busyIds.delete(ext.ext_id)
  }
}

async function handleToggleExtension(ext: SeanimeExtension, enabled: boolean) {
  busyIds.add(ext.ext_id)
  try {
    await api.toggleSeanimeExtension(ext.ext_id, enabled)
    animeStore.homeFeed = null
    await loadCatalog(true)
    notifications.notify(`${ext.name} ${enabled ? 'activée' : 'désactivée'}.`, 'success')
  } catch (err: any) {
    notifications.notify(err?.message || "Échec de la bascule d'état.", 'error')
  } finally {
    busyIds.delete(ext.ext_id)
  }
}

async function handleUninstallExtension(ext: SeanimeExtension) {
  busyIds.add(ext.ext_id)
  try {
    await api.uninstallSeanimeExtension(ext.ext_id)
    animeStore.homeFeed = null
    await loadCatalog(true)
    notifications.notify(`${ext.name} désinstallée.`, 'info')
  } catch (err: any) {
    notifications.notify(err?.message || 'Erreur lors de la désinstallation.', 'error')
  } finally {
    busyIds.delete(ext.ext_id)
  }
}

async function handleUpdateExtension(ext: SeanimeExtension) {
  busyIds.add(ext.ext_id)
  try {
    const updated = await api.updateSeanimeExtension(ext.ext_id)
    await loadCatalog(true)
    notifications.notify(`${updated.name} mise à jour en v${updated.installed_version}.`, 'success')
  } catch (err: any) {
    notifications.notify(err?.message || 'Erreur lors de la mise à jour.', 'error')
  } finally {
    busyIds.delete(ext.ext_id)
  }
}

async function handleCheckUpdates() {
  isCheckingUpdates.value = true
  try {
    const res = await api.checkSeanimeUpdates()
    await loadCatalog(true)
    notifications.notify(
      res.count > 0
        ? `${res.count} mise(s) à jour Seanime disponible(s).`
        : 'Toutes vos extensions Seanime sont à jour.',
      res.count > 0 ? 'info' : 'success',
    )
    if (res.count > 0) viewFilter.value = 'updates'
  } catch (err: any) {
    notifications.notify(err?.message || 'Erreur lors de la vérification.', 'error')
  } finally {
    isCheckingUpdates.value = false
  }
}

async function handleUpdateAll() {
  isUpdatingAll.value = true
  try {
    const res = await api.updateAllSeanimeExtensions()
    await loadCatalog(true)
    notifications.notify(`${res.updated.length} extension(s) mise(s) à jour.`, 'success')
  } catch (err: any) {
    notifications.notify(err?.message || 'Erreur lors de la mise à jour globale.', 'error')
  } finally {
    isUpdatingAll.value = false
  }
}

async function openConfigModal(ext: SeanimeExtension) {
  try {
    const cfg = await api.getSeanimeExtensionConfig(ext.ext_id)
    configValues.value = { ...(cfg.values || {}) }
    configModal.value = cfg
  } catch (err: any) {
    notifications.notify(err?.message || 'Impossible de charger la configuration.', 'error')
  }
}

async function saveConfig() {
  if (!configModal.value) return
  isSavingConfig.value = true
  try {
    await api.saveSeanimeExtensionConfig(configModal.value.ext_id, configValues.value)
    await loadCatalog(true)
    notifications.notify(`Configuration enregistrée pour ${configModal.value.name}.`, 'success')
    configModal.value = null
  } catch (err: any) {
    notifications.notify(err?.message || "Erreur lors de l'enregistrement.", 'error')
  } finally {
    isSavingConfig.value = false
  }
}

async function handleDiagnoseExtension(ext: SeanimeExtension) {
  busyIds.add(ext.ext_id)
  try {
    diagnoseResult.value = await api.diagnoseSeanimeExtension(ext.ext_id)
    await loadCatalog(true)
  } catch (err: any) {
    notifications.notify(err?.message || 'Diagnostic Seanime échoué.', 'error')
  } finally {
    busyIds.delete(ext.ext_id)
  }
}

onMounted(() => {
  void loadCatalog()
})
</script>

<style scoped>
.seanime-panel {
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.seanime-status-bar {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: 14px;
  padding: 18px 20px;
}
.seanime-title-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  margin-bottom: 4px;
}
.seanime-title-row h2 {
  margin: 0;
  font-size: 1.15rem;
}
.seanime-subtitle {
  margin: 0;
  color: var(--muted);
  font-size: 0.9rem;
}
.seanime-global-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.seanime-engine-pill,
.seanime-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 9px;
  border-radius: 999px;
  font-size: 0.76rem;
  font-weight: 600;
  background: var(--panel);
  border: 1px solid var(--line);
  color: var(--text);
}
.seanime-engine-pill.ok,
.seanime-pill.ok {
  color: #16a34a;
  border-color: rgba(22, 163, 74, 0.35);
}
.seanime-engine-pill.warn,
.seanime-pill.warn {
  color: #d97706;
  border-color: rgba(217, 119, 6, 0.4);
}
.seanime-pill.muted {
  color: var(--muted);
}
.seanime-import-card {
  padding: 16px;
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.seanime-import-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}
.seanime-url-input {
  flex: 1;
  min-width: min(280px, 100%);
}
.seanime-repo-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 6px;
}
.seanime-repo-item {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--panel);
  border: 1px solid var(--line);
}
.seanime-repo-meta {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
  flex: 1;
}
.seanime-repo-title {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.seanime-repo-url {
  color: var(--muted);
  word-break: break-all;
}
.seanime-repo-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.seanime-toolbar {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.seanime-search-box {
  position: relative;
  display: flex;
  align-items: center;
}
.seanime-search-box input {
  padding-left: 36px;
  width: 100%;
}
.seanime-search-icon {
  position: absolute;
  left: 12px;
  color: var(--muted);
  pointer-events: none;
}
.seanime-filter-group {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
}
.seanime-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.seanime-lang-select {
  width: auto;
  min-width: 170px;
}
.seanime-ext-list {
  display: flex;
  flex-direction: column;
}
.seanime-ext-card {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 14px;
  padding: 14px 6px;
  border-bottom: 1px solid var(--line);
}
.seanime-ext-avatar {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  overflow: hidden;
  background: var(--panel);
  border: 1px solid var(--line);
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 0.85rem;
  flex-shrink: 0;
}
.seanime-ext-avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.seanime-ext-body {
  flex: 1;
  min-width: min(260px, 100%);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.seanime-ext-heading {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.seanime-ext-desc {
  margin: 0;
  color: var(--muted);
  font-size: 0.87rem;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.seanime-ext-sub {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  font-size: 0.8rem;
  color: var(--muted);
}
.seanime-ext-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--accent);
}
.seanime-ext-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.seanime-non-exec-badge {
  font-size: 0.8rem;
  color: var(--muted);
  padding: 4px 10px;
  border-radius: 999px;
  background: var(--panel);
  border: 1px dashed var(--line);
}
.seanime-error-text {
  margin: 2px 0 0;
  color: #ef4444;
  font-size: 0.82rem;
}
.seanime-empty-state {
  padding: 28px 20px;
  text-align: center;
  color: var(--muted);
}
.seanime-load-more {
  padding: 16px 0;
  display: flex;
  justify-content: center;
}
.seanime-modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  z-index: 90;
}
.seanime-modal {
  width: min(540px, 100%);
  max-height: 85vh;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.seanime-modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.seanime-modal-header h3 {
  margin: 0;
  font-size: 1.05rem;
}
.seanime-config-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.seanime-config-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.seanime-switch-row {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}
.seanime-modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 6px;
}
.seanime-diagnose-body p {
  margin: 6px 0;
  font-size: 0.92rem;
}
.btn-sm {
  padding: 6px 11px;
  font-size: 0.84rem;
}
.danger-btn:hover {
  color: #ef4444;
  border-color: rgba(239, 68, 68, 0.45);
}
</style>
