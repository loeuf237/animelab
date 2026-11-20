<template>
  <section v-if="state?.available" class="apk-panel">
    <header>
      <div>
        <h2>{{ tx('Extensions APK Android') }}</h2>
        <p>
          {{
            tx(
              'Retrouvez les paquets installés depuis AnimeLab, Aniyomi ou Anikku sur cet appareil.',
            )
          }}
        </p>
      </div>
      <button class="btn btn-secondary" :disabled="busy" @click="refresh">
        {{ tx('Actualiser les APK') }}
      </button>
    </header>
    <p>
      {{
        tx(
          'Les extensions conservées uniquement dans le stockage privé d’une autre application doivent être exportées ou téléchargées comme APK.',
        )
      }}
    </p>
    <label class="apk-import">
      {{ tx('Installer un fichier APK') }}
      <input
        type="file"
        accept=".apk,application/vnd.android.package-archive"
        :disabled="busy"
        @change="importFile"
      />
    </label>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <p v-if="busy" role="status">{{ tx('Opération en cours…') }}</p>
    <p v-if="!state.packages.length">{{ tx('Aucune extension anime installée dans Android.') }}</p>
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
            · {{ extension.version }}
            <span class="apk-state">{{ tx(status(extension.state)) }}</span>
          </p>
        </div>
        <button
          v-if="catalogueEntry(extension.pkg)?.has_update"
          class="btn btn-primary"
          :disabled="busy"
          @click="run(() => api.updateExtension(catalogueEntry(extension.pkg)!.id))"
        >
          {{ tx('Mettre à jour') }}
        </button>
        <button
          v-if="!extension.trusted"
          class="btn btn-primary"
          :disabled="busy || !extension.compatible"
          @click="trust(extension)"
        >
          {{ tx('Approuver cet APK') }}
        </button>
      </header>
      <p v-if="extension.error" role="alert">
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
        <button
          v-if="extension.trusted"
          class="btn btn-secondary"
          :disabled="busy"
          @click="run(() => api.revokeAndroidExtension(extension.pkg))"
        >
          {{ tx('Révoquer la confiance') }}
        </button>
        <p>{{ extension.pkg }}</p>
        <p>{{ tx('Code de version :') }} {{ extension.versionCode }} · API {{ extension.api }}</p>
        <p class="fingerprint">SHA-256 {{ extension.signer }}</p>
        <button class="btn btn-secondary" :disabled="busy" @click="uninstall(extension)">
          {{ tx('Désinstaller le paquet partagé') }}
        </button>
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
                class="btn btn-secondary"
                :disabled="busy"
                @click="editPreferences(source)"
              >
                {{ tx('Préférences de la source') }}
              </button>
              <button
                v-if="!source.aliases?.includes(extension.pkg)"
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
    <ul v-if="pending.length" aria-live="polite">
      <li v-for="operation in pending" :key="operation.id">
        {{ operation.pkg }} — {{ tx(status(operation.state)) }}
        <span v-if="operation.error">({{ tx(operationError(operation.error)) }})</span>
        <button
          v-if="operation.action === 'install' && activeStates.includes(operation.state)"
          type="button"
          class="btn btn-secondary"
          :disabled="busy"
          @click="run(() => api.cancelAndroidInstallation(operation.id))"
        >
          {{ tx('Annuler l’installation') }}
        </button>
      </li>
    </ul>

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
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { api } from '@/api/client'
import { tx } from '@/utils/locale'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import ExtensionAvatar from '@/components/ExtensionAvatar.vue'
import type { ExtensionSource } from '@/types'
import type {
  AndroidExtensionState,
  NativeExtension,
  NativePreference,
  NativeSource,
} from '@/types/extensions'

const props = withDefaults(defineProps<{ query?: string; catalogue?: ExtensionSource[] }>(), {
  query: '',
  catalogue: () => [],
})
const catalogueEntry = (pkg: string) => props.catalogue.find((entry) => entry.pkg === pkg)
const installedPackages = computed(() => state.value?.packages?.map((item) => item.pkg) || [])
const filteredPackages = computed(() =>
  (state.value?.packages || [])
    .filter((item) =>
      `${item.name} ${item.pkg} ${item.sources.map((source) => source.lang).join(' ')}`
        .toLocaleLowerCase()
        .includes(props.query.trim().toLocaleLowerCase()),
    )
    .sort((a, b) => a.name.localeCompare(b.name)),
)
const emit = defineEmits<{ changed: [] }>()
const state = ref<AndroidExtensionState | null>(null)
const busy = ref(false)
const error = ref('')
const editing = ref<NativeSource | null>(null)
const preferences = ref<NativePreference[]>([])
const values = ref<Record<string, string | boolean | string[] | null>>({})
const changed = new Set<string>()
let timer: ReturnType<typeof setInterval> | undefined
const pending = computed(() => state.value?.operations?.slice(-12) || [])
const activeStates = ['preparing', 'waiting_user', 'permission_required', 'installing']
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
    }) as Record<string, string>
  )[code] || code
const status = (value: string) =>
  (
    ({
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
  state.value = await api.androidExtensions()
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
onMounted(async () => {
  try {
    await reload()
  } catch (failure) {
    error.value = failure instanceof Error ? failure.message : ''
  }
  timer = setInterval(() => {
    if (!busy.value && state.value?.operations?.some((op) => activeStates.includes(op.state)))
      void run(() => Promise.resolve())
  }, 4000)
})
onUnmounted(() => clearInterval(timer))
defineExpose({ reload, installedPackages })
</script>

<style scoped>
.apk-panel {
  padding: 1.25rem;
  border: 1px solid var(--border-color, #666);
  border-radius: 14px;
  margin-bottom: 1.5rem;
}
header,
.actions {
  display: flex;
  gap: 0.7rem;
  justify-content: space-between;
  flex-wrap: wrap;
  align-items: center;
}
.actions {
  justify-content: flex-start;
  margin: 0.7rem 0;
}
.apk-item {
  border-top: 1px solid var(--border-color, #666);
  padding: 1rem 0;
}
.apk-item p,
.fingerprint {
  overflow-wrap: anywhere;
}
.apk-import,
.preferences label {
  display: grid;
  gap: 0.5rem;
  margin: 1rem 0;
}
.preferences {
  border-top: 1px solid var(--border-color, #666);
}
.error {
  color: #f87171;
}
</style>

<style scoped>
.apk-panel {
  border: 0;
  padding: 0;
}
.apk-panel > p {
  color: var(--muted);
  font-size: 0.85rem;
}
.apk-item {
  border-color: var(--line);
  padding: 1rem 0.5rem;
}
.apk-identity {
  justify-content: flex-start;
  flex-wrap: nowrap;
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
  margin: 0.4rem 0;
}
.apk-state {
  color: var(--accent);
  margin-left: 0.5rem;
}
.apk-details > summary {
  cursor: pointer;
  color: var(--muted);
  padding: 0.8rem 0 0;
  font-size: 0.85rem;
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
  border-color: var(--line);
  scroll-margin: 5rem;
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
@media (max-width: 600px) {
  .apk-identity {
    flex-wrap: wrap;
  }
  .apk-identity > button {
    margin-left: 60px;
  }
}
</style>
