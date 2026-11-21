<template>
  <section v-if="state?.available" class="apk-panel">
    <header class="apk-panel-header">
      <div class="apk-panel-heading">
        <h2>
          {{ tx('Extensions APK Android') }}
          <span v-if="state.packages.length" class="apk-count-pill">
            {{ state.packages.length }}
          </span>
        </h2>
        <p>
          {{
            tx(
              'Retrouvez les paquets installés depuis AnimeLab, Aniyomi ou Anikku sur cet appareil.',
            )
          }}
        </p>
      </div>
      <div class="apk-header-actions">
        <button
          v-if="updateableCatalogueEntries.length > 0"
          type="button"
          class="btn btn-primary btn-sm"
          :disabled="busy || updatingAll"
          @click="triggerUpdateAll"
        >
          <span v-if="updatingAll" class="spinner-sm" aria-hidden="true"></span>
          {{ tx('Tout mettre à jour') }} ({{ updateableCatalogueEntries.length }})
        </button>
        <label class="btn btn-secondary btn-sm apk-import" :class="{ 'is-disabled': busy }">
          <PackagePlus :size="15" aria-hidden="true" />
          <span>{{ tx('Importer un APK') }}</span>
          <input
            type="file"
            class="sr-only"
            accept=".apk,application/vnd.android.package-archive"
            :disabled="busy"
            @change="importFile"
          />
        </label>
        <button type="button" class="btn btn-secondary btn-sm" :disabled="busy" @click="refresh">
          {{ tx('Actualiser les APK') }}
        </button>
      </div>
    </header>

    <p class="apk-panel-note">
      {{
        tx(
          'Les extensions conservées uniquement dans le stockage privé d’une autre application doivent être exportées ou téléchargées comme APK.',
        )
      }}
    </p>

    <div v-if="permissionRequiredOps.length > 0" class="apk-banner apk-banner-warn" role="status">
      <div class="apk-banner-copy">
        <strong>{{ tx('Autorisation d’installation requise') }}</strong>
        <p>
          {{
            tx(
              'Autorisez AnimeLab à installer des applications inconnues dans les paramètres Android, puis revenez ici : l’installation reprendra automatiquement.',
            )
          }}
        </p>
      </div>
      <button
        type="button"
        class="btn btn-primary btn-sm"
        :disabled="busy"
        @click="confirmOperation(permissionRequiredOps[0]!.id)"
      >
        {{ tx('Autoriser dans Android') }}
      </button>
    </div>

    <div v-if="untrustedPackages.length > 0" class="apk-banner apk-banner-info" role="status">
      <div class="apk-banner-copy">
        <strong>
          {{ untrustedPackages.length }}
          {{ tx('extension(s) en attente d’approbation') }}
        </strong>
        <p>
          {{
            tx(
              'Nouvel APK installé : vérifiez sa signature et approuvez-le pour activer ses sources.',
            )
          }}
        </p>
      </div>
    </div>

    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <p v-if="busy" role="status" class="apk-working">{{ tx('Opération en cours…') }}</p>

    <ul v-if="visibleOperations.length" class="apk-operations" aria-live="polite">
      <li
        v-for="operation in visibleOperations"
        :key="operation.id"
        class="apk-op-card"
        :class="`apk-op-${operation.state}`"
      >
        <div class="apk-op-main">
          <strong v-if="operationDisplayName(operation.pkg)" class="apk-op-name">
            {{ operationDisplayName(operation.pkg) }}
          </strong>
          <p class="apk-op-status">{{ operation.pkg }} — {{ tx(status(operation.state)) }}</p>
          <p v-if="operation.error" class="apk-op-error">
            ({{ tx(operationError(operation.error)) }})
          </p>
          <small v-if="operation.state === 'waiting_user'" class="apk-op-hint">
            {{ tx('Validez la fenêtre système Android pour terminer.') }}
          </small>
          <small v-else-if="operation.error === 'package_installer_conflict'" class="apk-op-hint">
            {{
              tx(
                'La signature diffère de la version installée (ex. changement de dépôt). Désinstallez l’ancienne version puis réinstallez.',
              )
            }}
          </small>
        </div>
        <div class="apk-op-actions">
          <button
            v-if="operation.state === 'permission_required'"
            type="button"
            class="btn btn-primary btn-sm"
            :disabled="busy"
            @click="confirmOperation(operation.id)"
          >
            {{ tx('Autoriser dans Android') }}
          </button>
          <button
            v-else-if="operation.state === 'waiting_user' && operation.canConfirm"
            type="button"
            class="btn btn-primary btn-sm"
            :disabled="busy"
            @click="confirmOperation(operation.id)"
          >
            {{ tx('Ouvrir la confirmation') }}
          </button>
          <button
            v-if="operation.action === 'install' && activeStates.includes(operation.state)"
            type="button"
            class="btn btn-secondary btn-sm"
            :disabled="busy"
            @click="cancelOperation(operation.id)"
          >
            {{ tx('Annuler l’installation') }}
          </button>
          <button
            v-else-if="operation.action === 'uninstall' && activeStates.includes(operation.state)"
            type="button"
            class="btn btn-secondary btn-sm"
            :disabled="busy"
            @click="cancelOperation(operation.id)"
          >
            {{ tx('Annuler') }}
          </button>
          <button
            v-if="
              operation.state === 'failed' &&
              operation.error === 'package_installer_conflict' &&
              packageByPkg(operation.pkg)
            "
            type="button"
            class="btn btn-secondary btn-sm"
            :disabled="busy"
            @click="uninstall(packageByPkg(operation.pkg)!)"
          >
            {{ tx('Désinstaller l’ancienne version') }}
          </button>
          <button
            v-if="
              (operation.state === 'failed' || operation.state === 'cancelled') &&
              catalogueEntry(operation.pkg)
            "
            type="button"
            class="btn btn-primary btn-sm"
            :disabled="busy || busyPackages.has(operation.pkg)"
            @click="retryCatalogueInstall(catalogueEntry(operation.pkg)!)"
          >
            {{ tx('Réessayer') }}
          </button>
          <button
            v-if="!activeStates.includes(operation.state)"
            type="button"
            class="btn btn-secondary btn-sm"
            @click="dismissOperation(operation.id)"
          >
            {{ tx('Masquer') }}
          </button>
        </div>
      </li>
    </ul>

    <p v-if="!state.packages.length && !visibleOperations.length" class="apk-empty">
      {{ tx('Aucune extension anime installée dans Android.') }}
    </p>

    <article v-for="extension in filteredPackages" :key="extension.pkg" class="apk-item">
      <header class="apk-identity">
        <ExtensionAvatar
          :name="extension.name"
          :src="catalogueEntry(extension.pkg)?.icon_url || catalogueEntry(extension.pkg)?.iconUrl"
        />
        <div class="apk-title">
          <h3>{{ extension.name }}</h3>
          <p>
            {{ extension.sources.map((source) => source.lang.toUpperCase()).join(' · ') || 'APK' }}
            ·
            <template v-if="catalogueEntry(extension.pkg)?.has_update">
              <span class="apk-version-upgrade">
                v{{ extension.version }} → v{{ catalogueEntry(extension.pkg)?.available_version }}
              </span>
            </template>
            <template v-else>v{{ extension.version }}</template>
            <span class="apk-state" :class="`apk-state-${extension.state}`">
              {{ tx(status(extension.state)) }}
            </span>
          </p>
        </div>
        <div class="apk-card-actions">
          <span v-if="activeOperationsByPkg[extension.pkg]" class="apk-op-chip">
            <span class="spinner-sm" aria-hidden="true"></span>
            {{ tx(status(activeOperationsByPkg[extension.pkg]!.state)) }}
          </span>
          <button
            v-else-if="catalogueEntry(extension.pkg)?.has_update"
            type="button"
            class="btn btn-primary btn-sm"
            :disabled="busy || busyPackages.has(extension.pkg)"
            @click="installOrUpdatePackage(catalogueEntry(extension.pkg)!)"
          >
            {{ tx('Mettre à jour') }}
          </button>
          <button
            v-if="!extension.trusted"
            type="button"
            class="btn btn-primary btn-sm"
            :disabled="busy || !extension.compatible"
            @click="trust(extension)"
          >
            {{ tx('Approuver cet APK') }}
          </button>
          <RouterLink
            v-else-if="extension.state === 'loaded' && firstEnabledSource(extension)"
            class="btn btn-secondary btn-sm"
            :to="{
              name: 'sources',
              params: { sourceId: `aniyomi:${firstEnabledSource(extension)!.id}` },
            }"
          >
            {{ tx('Ouvrir') }}
          </RouterLink>
        </div>
      </header>
      <p v-if="extension.error" role="alert" class="apk-load-error">
        {{ tx('Le chargement a échoué :') }} {{ extension.error }}
      </p>
      <p
        v-if="catalogueEntry(extension.pkg)?.catalog_state === 'retired'"
        class="apk-retired"
        role="status"
      >
        {{ tx('Retirée du dépôt : cette extension peut ne plus fonctionner.') }}
      </p>
      <details class="apk-details">
        <summary>
          {{ tx('Informations et réglages') }} · {{ extension.sources.length }}
          {{ tx('source(s)') }}
        </summary>
        <div class="apk-detail-toolbar">
          <button
            v-if="extension.trusted"
            type="button"
            class="btn btn-secondary btn-sm"
            :disabled="busy"
            @click="run(() => api.revokeAndroidExtension(extension.pkg))"
          >
            {{ tx('Révoquer la confiance') }}
          </button>
          <button
            type="button"
            class="btn btn-secondary btn-sm"
            :disabled="busy"
            @click="uninstall(extension)"
          >
            {{ tx('Désinstaller le paquet partagé') }}
          </button>
        </div>
        <p>{{ extension.pkg }}</p>
        <p>{{ tx('Code de version :') }} {{ extension.versionCode }} · API {{ extension.api }}</p>
        <p class="fingerprint">SHA-256 {{ extension.signer }}</p>
        <ul class="apk-source-list">
          <li v-for="source in extension.sources" :key="source.id">
            <div class="apk-source-heading">
              <strong>{{ source.name }}</strong>
              <label
                ><input
                  type="checkbox"
                  :checked="source.enabled !== false"
                  :disabled="busy"
                  @change="
                    run(() =>
                      api.androidSource(`aniyomi:${source.id}`, 'state', {
                        enabled: ($event.target as HTMLInputElement).checked,
                      }),
                    )
                  "
                />
                {{ tx('Activer cette source') }}</label
              >
            </div>
            <div class="actions">
              <RouterLink
                class="btn btn-secondary"
                :to="{ name: 'sources', params: { sourceId: `aniyomi:${source.id}` } }"
                >{{ tx('Ouvrir la source') }}</RouterLink
              >
              <button
                v-if="source.configurable"
                type="button"
                class="btn btn-secondary"
                :disabled="busy"
                @click="editPreferences(source)"
              >
                {{ tx('Préférences de la source') }}
              </button>
              <button
                v-if="!source.aliases?.includes(extension.pkg)"
                type="button"
                class="btn btn-secondary"
                :disabled="busy"
                @click="
                  run(() => api.setExtensionSourceAlias(extension.pkg, `aniyomi:${source.id}`))
                "
              >
                {{ tx('Utiliser pour les anciennes références de ce paquet') }}
              </button>
              <span v-else>{{ tx('Source choisie pour les anciennes références du paquet') }}</span>
            </div>
          </li>
        </ul>
      </details>
    </article>

    <section v-if="editing" class="preferences" :aria-label="tx('Préférences de la source')">
      <h3>{{ editing.name }}</h3>
      <form @submit.prevent="savePreferences">
        <template v-for="(preference, index) in preferences" :key="preference.key || index">
          <h4 v-if="preference.type === 'group'">{{ preference.title }}</h4>
          <label v-else>
            {{ preference.title }}
            <small v-if="preference.summary">{{ preference.summary }}</small>
            <input
              v-if="preference.type === 'boolean'"
              v-model="values[preference.key!]"
              type="checkbox"
              :disabled="!preference.enabled"
              @change="changed.add(preference.key!)"
            />
            <input
              v-else-if="preference.type === 'text'"
              v-model="values[preference.key!]"
              :type="preference.secret ? 'password' : 'text'"
              :disabled="!preference.enabled"
              autocomplete="off"
              @input="changed.add(preference.key!)"
            />
            <select
              v-else-if="preference.type === 'select' || preference.type === 'multiSelect'"
              v-model="values[preference.key!]"
              :multiple="preference.type === 'multiSelect'"
              :disabled="!preference.enabled"
              @change="changed.add(preference.key!)"
            >
              <option v-for="(value, i) in preference.entryValues" :key="value" :value="value">
                {{ preference.entries[i] || value }}
              </option>
            </select>
            <span v-else>{{ tx('Ce contrôle doit être pris en charge par le moteur.') }}</span>
          </label>
        </template>
        <div class="actions">
          <button type="submit" class="btn btn-primary" :disabled="busy">
            {{ tx('Enregistrer') }}
          </button>
          <button type="button" class="btn btn-secondary" @click="editing = null">
            {{ tx('Fermer') }}
          </button>
        </div>
      </form>
    </section>

    <ConfirmDialog
      :open="Boolean(confirmAction)"
      :title="confirmTitle"
      :confirm-label="confirmButtonLabel"
      :busy="busy"
      :danger="confirmAction?.kind === 'uninstall'"
      @cancel="confirmAction = null"
      @confirm="executeConfirmedAction"
    >
      <template v-if="confirmAction?.kind === 'trust'">
        <p>
          {{
            tx(
              'Cette extension exécutera du code avec accès aux données et au réseau de l’application. Approuver cette version ?',
            )
          }}
        </p>
        <p>
          <strong>{{ confirmAction.extension.pkg }}</strong> · v{{
            confirmAction.extension.version
          }}
        </p>
        <p>
          <code>SHA-256 {{ confirmAction.extension.signer }}</code>
        </p>
      </template>
      <template v-else-if="confirmAction?.kind === 'uninstall'">
        <p>
          {{
            tx(
              'Désinstaller ce paquet Android affectera aussi Aniyomi et Anikku. La bibliothèque et les vidéos seront conservées. Continuer ?',
            )
          }}
        </p>
      </template>
    </ConfirmDialog>
  </section>
</template>

<script setup lang="ts">
import { PackagePlus } from 'lucide-vue-next'
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { api } from '@/api/client'
import { tx } from '@/utils/locale'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import ExtensionAvatar from '@/components/ExtensionAvatar.vue'
import type { ExtensionSource } from '@/types'
import type {
  AndroidExtensionState,
  ExtensionOperation,
  NativeExtension,
  NativePreference,
  NativeSource,
} from '@/types/extensions'

const props = withDefaults(
  defineProps<{
    query?: string
    catalogue?: ExtensionSource[]
    filterMode?: 'all' | 'fr' | 'active' | 'updates'
  }>(),
  {
    query: '',
    catalogue: () => [],
    filterMode: 'all',
  },
)

const catalogueEntry = (pkg: string) => props.catalogue.find((entry) => entry.pkg === pkg)
const packageByPkg = (pkg: string) => state.value?.packages?.find((item) => item.pkg === pkg)
const installedPackages = computed(() => state.value?.packages?.map((item) => item.pkg) || [])
const available = computed(() => Boolean(state.value?.available))

const activeStates = ['preparing', 'waiting_user', 'permission_required', 'installing']
const pageLoadedAt = Date.now()

const emit = defineEmits<{ changed: [] }>()
const state = ref<AndroidExtensionState | null>(null)
const busy = ref(false)
const updatingAll = ref(false)
const busyPackages = ref(new Set<string>())
const dismissedOperationIds = ref(new Set<string>())
const seenActiveIds = new Set<string>()
const error = ref('')
const editing = ref<NativeSource | null>(null)
const preferences = ref<NativePreference[]>([])
const values = ref<Record<string, string | boolean | string[] | null>>({})
const changed = new Set<string>()
let timer: ReturnType<typeof setInterval> | undefined
let polling = false

function recordSeenActive(next: AndroidExtensionState | null) {
  for (const op of next?.operations || []) {
    if (activeStates.includes(op.state)) seenActiveIds.add(op.id)
  }
}

function packageSignature(value: AndroidExtensionState | null): string {
  if (!value) return ''
  return JSON.stringify(
    [...(value.packages || [])]
      .sort((a, b) => a.pkg.localeCompare(b.pkg))
      .map((pkg) => [
        pkg.pkg,
        pkg.versionCode,
        pkg.state,
        pkg.trusted,
        pkg.enabled,
        (pkg.sources || [])
          .map((s) => [s.id, s.enabled])
          .sort((a, b) => `${a[0]}`.localeCompare(`${b[0]}`)),
      ]),
  )
}

function operationStateMap(value: AndroidExtensionState | null): Map<string, string> {
  return new Map((value?.operations || []).map((op) => [op.id, op.state]))
}

const activeOperationsByPkg = computed<Record<string, ExtensionOperation>>(() => {
  const map: Record<string, ExtensionOperation> = {}
  for (const op of state.value?.operations || []) {
    if (activeStates.includes(op.state)) {
      map[op.pkg] = op
    }
  }
  return map
})

const hasActiveOperations = computed(() =>
  Boolean(state.value?.operations?.some((op) => activeStates.includes(op.state))),
)

const permissionRequiredOps = computed(() =>
  (state.value?.operations || []).filter((op) => op.state === 'permission_required'),
)

const untrustedPackages = computed(() =>
  (state.value?.packages || []).filter((pkg) => !pkg.trusted),
)

const updateableCatalogueEntries = computed(() =>
  (state.value?.packages || [])
    .map((pkg) => catalogueEntry(pkg.pkg))
    .filter((entry): entry is ExtensionSource => Boolean(entry?.has_update)),
)

const visibleOperations = computed(() => {
  const ops = state.value?.operations || []
  const latestByPkg = new Map<string, ExtensionOperation>()
  for (const op of ops) {
    latestByPkg.set(op.pkg, op)
  }
  return ops.filter((op) => {
    if (dismissedOperationIds.value.has(op.id)) return false
    if (activeStates.includes(op.state)) return true
    if (latestByPkg.get(op.pkg)?.id !== op.id) return false
    if (seenActiveIds.has(op.id)) return true
    if (op.updatedAt == null) return true
    const recent = Date.now() - op.updatedAt < 10 * 60_000
    if (!recent) return false
    return (
      op.updatedAt >= pageLoadedAt - 120_000 || op.state === 'failed' || op.state === 'cancelled'
    )
  })
})

const filteredPackages = computed(() =>
  (state.value?.packages || [])
    .filter((item) => {
      const cat = catalogueEntry(item.pkg)
      if (props.filterMode === 'updates' && !cat?.has_update) return false
      if (
        props.filterMode === 'active' &&
        (!item.trusted || !item.enabled || item.state !== 'loaded')
      ) {
        return false
      }
      if (props.filterMode === 'fr') {
        const hasFr =
          item.sources.some((s) => s.lang.toLowerCase() === 'fr') ||
          (cat?.lang || '').toLowerCase() === 'fr'
        if (!hasFr) return false
      }
      const q = props.query.trim().toLocaleLowerCase()
      if (!q) return true
      return `${item.name} ${item.pkg} ${item.sources.map((source) => source.lang).join(' ')}`
        .toLocaleLowerCase()
        .includes(q)
    })
    .sort((a, b) => {
      const rank = (item: NativeExtension) => {
        if (!item.trusted) return 0
        if (catalogueEntry(item.pkg)?.has_update) return 1
        return item.state === 'loaded' ? 2 : 3
      }
      return rank(a) - rank(b) || a.name.localeCompare(b.name)
    }),
)

const visibleCount = computed(() => filteredPackages.value.length)

function firstEnabledSource(extension: NativeExtension): NativeSource | undefined {
  return extension.sources.find((source) => source.enabled !== false) || extension.sources[0]
}

function operationDisplayName(pkg: string): string {
  const match = packageByPkg(pkg) || catalogueEntry(pkg)
  return match && match.name !== pkg ? match.name : ''
}

function dismissOperation(id: string) {
  dismissedOperationIds.value = new Set([...dismissedOperationIds.value, id])
}

const operationError = (code: string) =>
  (
    ({
      package_installer_conflict:
        'Android refuse le remplacement : conflit avec un paquet installé, notamment sa signature.',
      package_installer_blocked: 'Installation bloquée par une règle ou un contrôle Android.',
      package_installer_incompatible: 'APK incompatible avec cet appareil.',
      package_installer_invalid: 'APK invalide selon Android.',
      package_installer_storage: 'Espace de stockage insuffisant.',
      package_installer_failed: 'Android n’a pas pu installer cet APK.',
      package_installer_confirmation_missing: 'La confirmation Android est indisponible.',
      package_installer_confirmation_unavailable: 'Impossible d’ouvrir la confirmation Android.',
      package_installer_session_expired: 'La confirmation Android a expiré ou a été fermée.',
    }) as Record<string, string>
  )[code] || code

const status = (value: string) =>
  (
    ({
      preparing: 'Préparation de l’installation',
      loaded: 'Chargée',
      untrusted: 'Approbation requise',
      incompatible: 'API incompatible',
      load_failed: 'Échec de chargement',
      installed: 'Installée dans Android',
      uninstalled: 'Désinstallée',
      waiting_user: 'Confirmation Android attendue',
      permission_required: 'Autorisation d’installation requise',
      installing: 'Installation Android en cours',
      failed: 'Échec',
      cancelled: 'Annulée',
    }) as Record<string, string>
  )[value] || value

async function reload() {
  const next = await api.androidExtensions()
  recordSeenActive(next)
  state.value = next
}

async function silentSync() {
  if (busy.value || polling || document.hidden || !state.value?.available) return
  polling = true
  try {
    const prevPkgSig = packageSignature(state.value)
    const prevOpStates = operationStateMap(state.value)
    const next = await api.androidExtensions()
    recordSeenActive(next)
    state.value = next
    const pkgChanged = packageSignature(next) !== prevPkgSig
    const opFinished = (next.operations || []).some((op) => {
      const prev = prevOpStates.get(op.id)
      return prev && activeStates.includes(prev) && !activeStates.includes(op.state)
    })
    if (pkgChanged || opFinished) {
      emit('changed')
    }
  } catch {
    /* Silent background sync must never disrupt or flash UI on transient errors. */
  } finally {
    polling = false
  }
}

function refresh() {
  void run(async () => {})
}

async function run(work: () => Promise<unknown>) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    await work()
    await reload()
    emit('changed')
  } catch (failure) {
    error.value = failure instanceof Error ? failure.message : tx('Échec de l’opération.')
  } finally {
    busy.value = false
  }
}

async function confirmOperation(id: string) {
  await run(() => api.confirmAndroidOperation(id))
}

async function cancelOperation(id: string) {
  await run(() => api.cancelAndroidInstallation(id))
}

async function installOrUpdatePackage(entry: ExtensionSource) {
  busyPackages.value = new Set([...busyPackages.value, entry.pkg])
  try {
    await run(() => api.updateExtension(entry.id))
  } finally {
    const next = new Set(busyPackages.value)
    next.delete(entry.pkg)
    busyPackages.value = next
  }
}

async function retryCatalogueInstall(entry: ExtensionSource) {
  busyPackages.value = new Set([...busyPackages.value, entry.pkg])
  try {
    await run(() => api.toggleExtension(entry.id, true))
  } finally {
    const next = new Set(busyPackages.value)
    next.delete(entry.pkg)
    busyPackages.value = next
  }
}

async function triggerUpdateAll() {
  if (updatingAll.value || busy.value) return
  updatingAll.value = true
  try {
    await run(() => api.updateAllExtensions())
  } finally {
    updatingAll.value = false
  }
}

const confirmAction = ref<{ kind: 'trust' | 'uninstall'; extension: NativeExtension } | null>(null)
const confirmTitle = computed(() =>
  confirmAction.value?.kind === 'uninstall'
    ? tx('Désinstaller cette extension ?')
    : tx('Approuver cette extension Android ?'),
)
const confirmButtonLabel = computed(() =>
  confirmAction.value?.kind === 'uninstall' ? tx('Désinstaller') : tx('Approuver'),
)

function trust(extension: NativeExtension) {
  confirmAction.value = { kind: 'trust', extension }
}

function uninstall(extension: NativeExtension) {
  confirmAction.value = { kind: 'uninstall', extension }
}

async function executeConfirmedAction() {
  const action = confirmAction.value
  if (!action) return
  confirmAction.value = null
  if (action.kind === 'trust') {
    await run(() => api.trustAndroidExtension(action.extension))
  } else {
    await run(() => api.uninstallAndroidExtension(action.extension.pkg))
  }
}

async function importFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) await run(() => api.importAndroidAPK(file))
  input.value = ''
}

async function editPreferences(source: NativeSource) {
  await run(async () => {
    editing.value = null
    preferences.value = (await api.androidSource(`aniyomi:${source.id}`, 'preferences')).result
    values.value = Object.fromEntries(
      preferences.value.filter((p) => p.key).map((p) => [p.key!, p.value ?? '']),
    )
    changed.clear()
    editing.value = source
    await nextTick()
    document.querySelector('.preferences')?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  })
}

async function savePreferences() {
  if (!editing.value) return
  const source = editing.value
  await run(async () => {
    await api.androidSource(
      `aniyomi:${source.id}`,
      'set_preferences',
      Object.fromEntries([...changed].map((key) => [key, values.value[key]])),
    )
    editing.value = null
  })
}

function handleVisibilityOrFocus() {
  if (!document.hidden && state.value?.available) {
    void silentSync()
  }
}

onMounted(async () => {
  try {
    await reload()
  } catch (failure) {
    error.value = failure instanceof Error ? failure.message : ''
  }
  document.addEventListener('visibilitychange', handleVisibilityOrFocus)
  window.addEventListener('focus', handleVisibilityOrFocus)
  timer = setInterval(() => {
    if (!busy.value && !document.hidden && hasActiveOperations.value) {
      void silentSync()
    }
  }, 3000)
})

onUnmounted(() => {
  clearInterval(timer)
  document.removeEventListener('visibilitychange', handleVisibilityOrFocus)
  window.removeEventListener('focus', handleVisibilityOrFocus)
})

defineExpose({
  reload,
  installedPackages,
  available,
  activeOperationsByPkg,
  visibleCount,
  triggerUpdateAll,
  confirmOperation,
  cancelOperation,
})
</script>

<style scoped>
.apk-panel {
  border: 0;
  padding: 0;
  margin-bottom: 1.5rem;
}
.apk-panel-header {
  display: flex;
  gap: 0.75rem;
  justify-content: space-between;
  flex-wrap: wrap;
  align-items: center;
}
.apk-panel-heading {
  min-width: 0;
  flex: 1;
}
.apk-panel-heading h2 {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
  margin: 0;
}
.apk-panel-heading p,
.apk-panel-note {
  color: var(--muted);
  font-size: 0.85rem;
  margin: 0.35rem 0 0;
}
.apk-count-pill {
  font-size: 0.78rem;
  padding: 0.15rem 0.55rem;
  border-radius: 999px;
  background: var(--panel);
  color: var(--text);
  border: 1px solid var(--line);
}
.apk-header-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
}
.apk-import {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  cursor: pointer;
  margin: 0;
}
.apk-import.is-disabled {
  opacity: 0.6;
  pointer-events: none;
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
.apk-banner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.75rem;
  margin: 0.9rem 0;
  padding: 0.85rem 1rem;
  border-radius: 12px;
  border: 1px solid var(--line);
  background: var(--panel);
}
.apk-banner-warn {
  border-color: rgba(245, 158, 11, 0.45);
  background: rgba(245, 158, 11, 0.1);
}
.apk-banner-info {
  border-color: rgba(139, 92, 246, 0.4);
  background: rgba(139, 92, 246, 0.1);
}
.apk-banner-copy {
  flex: 1;
  min-width: min(220px, 100%);
}
.apk-banner-copy strong {
  display: block;
  font-size: 0.92rem;
}
.apk-banner-copy p {
  margin: 0.25rem 0 0;
  font-size: 0.82rem;
  color: var(--muted);
}
.apk-working,
.apk-empty {
  color: var(--muted);
  font-size: 0.88rem;
  margin: 0.75rem 0;
}
.apk-operations {
  list-style: none;
  padding: 0;
  margin: 1rem 0;
  display: grid;
  gap: 0.65rem;
}
.apk-op-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.75rem;
  padding: 0.85rem 1rem;
  border-radius: 12px;
  background: var(--panel);
  border: 1px solid var(--line);
}
.apk-op-failed {
  border-color: rgba(248, 113, 113, 0.45);
}
.apk-op-waiting_user,
.apk-op-permission_required {
  border-color: rgba(245, 158, 11, 0.45);
}
.apk-op-main {
  flex: 1;
  min-width: min(220px, 100%);
  overflow-wrap: anywhere;
}
.apk-op-name {
  display: block;
  font-size: 0.95rem;
  margin-bottom: 0.15rem;
}
.apk-op-status {
  margin: 0;
  font-size: 0.85rem;
}
.apk-op-error {
  margin: 0.25rem 0 0;
  color: #f87171;
  font-size: 0.82rem;
}
.apk-op-hint {
  display: block;
  margin-top: 0.25rem;
  color: var(--muted);
  font-size: 0.78rem;
}
.apk-op-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
}
.apk-item {
  border-top: 1px solid var(--line);
  padding: 1rem 0.5rem;
}
.apk-item p,
.fingerprint {
  overflow-wrap: anywhere;
}
.apk-identity {
  display: flex;
  gap: 0.75rem;
  justify-content: flex-start;
  flex-wrap: nowrap;
  align-items: center;
}
.apk-title {
  flex: 1;
  min-width: 0;
}
.apk-title h3 {
  margin: 0;
  font-size: 1rem;
  overflow-wrap: anywhere;
}
.apk-title p {
  font-size: 0.8rem;
  color: var(--muted);
  margin: 0.4rem 0 0;
}
.apk-version-upgrade {
  color: #fbbf24;
  font-weight: 600;
}
.apk-state {
  color: var(--accent);
  margin-left: 0.5rem;
}
.apk-state-untrusted {
  color: #fbbf24;
}
.apk-state-load_failed,
.apk-state-incompatible {
  color: #f87171;
}
.apk-card-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
}
.apk-op-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.35rem 0.65rem;
  border-radius: 999px;
  font-size: 0.78rem;
  background: var(--panel);
  border: 1px solid var(--line);
  color: var(--text);
}
.apk-details > summary {
  cursor: pointer;
  color: var(--muted);
  padding: 0.8rem 0 0;
  font-size: 0.85rem;
}
.apk-detail-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-top: 0.75rem;
}
.actions {
  display: flex;
  gap: 0.7rem;
  justify-content: flex-start;
  flex-wrap: wrap;
  align-items: center;
  margin: 0.7rem 0;
}
.apk-source-list {
  list-style: none;
  padding: 0;
}
.apk-source-list li {
  margin-top: 1rem;
  padding: 1rem;
  background: var(--panel);
  border-radius: 12px;
}
.apk-source-heading {
  display: flex;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 0.75rem;
}
.preferences {
  padding: 1.25rem;
  background: var(--panel);
  border-radius: 16px;
  border: 1px solid var(--line);
  scroll-margin: 5rem;
}
.preferences label {
  display: grid;
  gap: 0.5rem;
  margin: 1rem 0;
}
.preferences input:not([type='checkbox']),
.preferences select {
  width: 100%;
  min-height: 44px;
  background: var(--input-bg, var(--panel));
  color: var(--text);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 0.6rem;
}
.error,
.apk-load-error {
  color: #f87171;
}
.spinner-sm {
  width: 13px;
  height: 13px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: currentColor;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  display: inline-block;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
@media (max-width: 600px) {
  .apk-identity {
    flex-wrap: wrap;
  }
  .apk-card-actions {
    width: 100%;
    padding-left: 52px;
  }
  .apk-header-actions {
    width: 100%;
  }
}
</style>
