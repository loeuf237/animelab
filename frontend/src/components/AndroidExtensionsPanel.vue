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
      <button class="btn btn-secondary" :disabled="busy" @click="reload">
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
    <article v-for="extension in state.packages" :key="extension.pkg" class="apk-item">
      <h3>{{ extension.name }}</h3>
      <p>{{ extension.pkg }}</p>
      <p>v{{ extension.version }} · API {{ extension.api }} · {{ tx(status(extension.state)) }}</p>
      <p v-if="extension.error" role="alert">
        {{ tx('Le chargement a échoué :') }} {{ extension.error }}
      </p>
      <details>
        <summary>{{ tx('Identité du paquet') }}</summary>
        <p>{{ tx('Code de version :') }} {{ extension.versionCode }}</p>
        <p class="fingerprint">SHA-256 {{ extension.signer }}</p>
      </details>
      <div class="actions">
        <button
          v-if="!extension.trusted"
          class="btn btn-primary"
          :disabled="busy || !extension.compatible"
          @click="trust(extension)"
        >
          {{ tx('Approuver cet APK') }}
        </button>
        <button
          v-else
          class="btn btn-secondary"
          :disabled="busy"
          @click="run(() => api.revokeAndroidExtension(extension.pkg))"
        >
          {{ tx('Révoquer la confiance') }}
        </button>
        <button class="btn btn-secondary" :disabled="busy" @click="uninstall(extension)">
          {{ tx('Désinstaller le paquet partagé') }}
        </button>
      </div>
      <ul>
        <li v-for="source in extension.sources" :key="source.id">
          <strong>{{ source.name }}</strong> · {{ source.lang }}
          <label>
            <input
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
            {{ tx('Activer cette source') }}
          </label>
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
          </div>
        </li>
      </ul>
    </article>
    <section v-if="editing" class="preferences" :aria-label="tx('Préférences de la source')">
      <h3>{{ editing.name }}</h3>
      <form @submit.prevent="savePreferences">
        <template v-for="(preference, index) in preferences" :key="preference.key || index">
          <h4 v-if="preference.type === 'group'">{{ preference.title }}</h4>
          <label v-else>
            {{ preference.title }}
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
        <span v-if="operation.error">({{ operation.error }})</span>
      </li>
    </ul>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from '@/api/client'
import { tx } from '@/utils/locale'
import type {
  AndroidExtensionState,
  NativeExtension,
  NativePreference,
  NativeSource,
} from '@/types/extensions'

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
  emit('changed')
}
async function run(work: () => Promise<unknown>) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    await work()
    await reload()
  } catch (failure) {
    error.value = failure instanceof Error ? failure.message : tx('Échec de l’opération.')
  } finally {
    busy.value = false
  }
}
async function trust(extension: NativeExtension) {
  if (
    !window.confirm(
      `${tx('Cette extension exécutera du code avec accès aux données et au réseau de l’application. Approuver cette version ?')}\n${extension.pkg}\nv${extension.version}\nSHA-256 ${extension.signer}`,
    )
  )
    return
  await run(() => api.trustAndroidExtension(extension))
}
async function uninstall(extension: NativeExtension) {
  if (
    !window.confirm(
      tx(
        'Désinstaller ce paquet Android affectera aussi Aniyomi et Anikku. La bibliothèque et les vidéos seront conservées. Continuer ?',
      ),
    )
  )
    return
  await run(() => api.uninstallAndroidExtension(extension.pkg))
}
async function importFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) await run(() => api.importAndroidAPK(file))
  input.value = ''
}
async function editPreferences(source: NativeSource) {
  await run(async () => {
    preferences.value = (await api.androidSource(`aniyomi:${source.id}`, 'preferences')).result
    values.value = Object.fromEntries(
      preferences.value.filter((p) => p.key).map((p) => [p.key!, p.value ?? '']),
    )
    changed.clear()
    editing.value = source
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
    if (
      !busy.value &&
      state.value?.operations?.some((op) =>
        ['waiting_user', 'permission_required', 'installing'].includes(op.state),
      )
    )
      void run(() => Promise.resolve())
  }, 4000)
})
onUnmounted(() => clearInterval(timer))
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
