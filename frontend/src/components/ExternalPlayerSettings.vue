<template>
  <section v-if="loaded && config.available" class="settings-card-pro ext-player-card">
    <div class="settings-card-header-pro">
      <div class="settings-card-icon-pro">
        <ExternalLink :size="20" aria-hidden="true" />
      </div>
      <div>
        <h2 class="settings-card-title-pro">{{ tx('Lecteur vidéo externe') }}</h2>
        <p class="settings-card-sub-pro">
          {{
            tx(
              config.platform === 'android'
                ? 'Ouvre vos épisodes dans VLC, mpv-android ou MX Player via le sélecteur Android.'
                : 'Lancez vos épisodes locaux ou en streaming dans mpv, VLC ou un lecteur personnalisé.',
            )
          }}
        </p>
      </div>
    </div>

    <div class="settings-card-body-pro ext-player-body">
      <template v-if="config.platform === 'desktop'">
        <div class="ext-field-group">
          <label class="setting-title-pro" for="external-player-preset">
            {{ tx('Lecteur externe') }}
          </label>
          <div class="ext-preset-row">
            <select
              id="external-player-preset"
              v-model="form.preset"
              class="input-premium ext-select"
              :disabled="saving"
            >
              <option value="none">{{ tx('Lecteur intégré uniquement') }}</option>
              <option v-if="hasSystemOpener || form.preset === 'system'" value="system">
                {{ tx('Lecteur par défaut du système') }}
              </option>
              <option value="mpv">{{ optionLabel('mpv', 'mpv') }}</option>
              <option value="vlc">{{ optionLabel('vlc', 'VLC') }}</option>
              <option v-for="extra in extraDetectedPlayers" :key="extra.id" :value="extra.id">
                {{ extra.label }} ({{ tx('détecté') }})
              </option>
              <option value="custom">{{ tx('Chemin personnalisé') }}</option>
            </select>
            <div v-if="config.detected.length" class="ext-detected-chips">
              <button
                v-for="item in config.detected"
                :key="item.id"
                type="button"
                class="speed-preset-chip"
                :class="{ active: form.preset === item.id }"
                @click="form.preset = item.id as ExternalPlayerSettings['preset']"
              >
                {{ tx(item.label) }}
              </button>
            </div>
          </div>
          <p v-if="!config.detected.length" class="setting-desc-pro">
            {{
              tx(
                'Aucun lecteur détecté automatiquement : indiquez un chemin personnalisé si mpv ou VLC est installé ailleurs.',
              )
            }}
          </p>
          <p v-else-if="form.preset === 'none'" class="setting-desc-pro">
            {{
              tx(
                `Le bouton « Lecteur externe » utilisera automatiquement ${config.detected[0].label}. Choisissez un lecteur ci-dessus si vous voulez l’utiliser par défaut à la lecture.`,
              )
            }}
          </p>
        </div>

        <div v-if="form.preset === 'custom'" class="ext-field-group">
          <label class="setting-title-pro" for="external-player-path">
            {{ tx('Chemin de l’exécutable') }}
          </label>
          <div class="ext-path-row">
            <input
              id="external-player-path"
              v-model="form.customPath"
              type="text"
              class="input-premium ext-path-input"
              :placeholder="tx('/usr/bin/mpv ou C:\\Program Files\\mpv\\mpv.exe')"
              :disabled="saving"
              autocomplete="off"
            />
            <button
              v-if="canBrowseDesktop"
              type="button"
              class="btn btn-secondary"
              :disabled="saving"
              @click="browseExecutable"
            >
              {{ tx('Parcourir…') }}
            </button>
          </div>
        </div>

        <label v-if="form.preset !== 'none'" class="ext-toggle-row">
          <input v-model="form.preferExternal" type="checkbox" :disabled="saving" />
          <span>{{ tx('Ouvrir les épisodes par défaut dans le lecteur externe') }}</span>
        </label>
      </template>

      <template v-else>
        <label class="ext-toggle-row">
          <input v-model="form.preferExternal" type="checkbox" :disabled="saving" />
          <span>{{ tx('Ouvrir les épisodes par défaut dans un lecteur externe') }}</span>
        </label>
      </template>

      <div class="ext-actions-row">
        <button type="button" class="btn btn-secondary" :disabled="saving" @click="save">
          {{ tx(saving ? 'Enregistrement...' : 'Enregistrer le lecteur') }}
        </button>
        <p v-if="statusMessage" role="status" class="ext-status-msg" :class="{ isError }">
          {{ tx(statusMessage) }}
        </p>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ExternalLink } from 'lucide-vue-next'
import { api } from '@/api/client'
import { usePlayerStore } from '@/stores/player'
import type { ExternalPlayerSettings } from '@/types/api'
import { chooseDesktopExternalPlayer } from '@/utils/platform'
import { tx } from '@/utils/locale'

const playerStore = usePlayerStore()
const loaded = ref(false)
const saving = ref(false)
const statusMessage = ref('')
const isError = ref(false)

const config = ref<ExternalPlayerSettings>({
  available: false,
  platform: 'desktop',
  clientLocal: false,
  preset: 'none',
  customPath: '',
  preferExternal: false,
  configured: false,
  resolvedPath: null,
  detected: [],
})

const form = reactive<{
  preset: ExternalPlayerSettings['preset']
  customPath: string
  preferExternal: boolean
}>({
  preset: 'none',
  customPath: '',
  preferExternal: false,
})

const hasSystemOpener = computed(() => config.value.detected.some((item) => item.id === 'system'))
const extraDetectedPlayers = computed(() =>
  config.value.detected.filter(
    (item) => !['none', 'system', 'mpv', 'vlc', 'custom'].includes(item.id),
  ),
)

const canBrowseDesktop = computed(() => {
  if (typeof window === 'undefined') return false
  return (
    typeof (window as Window & { pywebview?: { api?: { choose_external_player?: unknown } } })
      .pywebview?.api?.choose_external_player === 'function'
  )
})

function optionLabel(id: string, name: string): string {
  const found = config.value.detected.some((item) => item.id === id)
  return found ? `${name} (${tx('détecté')})` : `${name} (${tx('introuvable')})`
}

function applySnapshot(snapshot: ExternalPlayerSettings) {
  config.value = snapshot
  form.preset = snapshot.preset
  form.customPath = snapshot.customPath || ''
  form.preferExternal = Boolean(snapshot.preferExternal)
  playerStore.setExternalPlayerConfig(snapshot)
}

async function load() {
  try {
    const snapshot = await api.getExternalPlayerSettings()
    applySnapshot(snapshot)
    loaded.value = true
  } catch {
    loaded.value = false
  }
}

async function browseExecutable() {
  const selected = await chooseDesktopExternalPlayer()
  if (selected) {
    form.customPath = selected
    form.preset = 'custom'
  }
}

async function save() {
  saving.value = true
  statusMessage.value = ''
  isError.value = false
  try {
    const payload =
      config.value.platform === 'android'
        ? {
            preset: (form.preferExternal ? 'system' : 'none') as ExternalPlayerSettings['preset'],
            customPath: '',
            preferExternal: form.preferExternal,
          }
        : {
            preset: form.preset,
            customPath: form.customPath,
            preferExternal: form.preset === 'none' ? false : form.preferExternal,
          }
    const saved = await api.saveExternalPlayerSettings(payload)
    applySnapshot(saved)
    statusMessage.value = 'Lecteur externe enregistré.'
  } catch (err) {
    isError.value = true
    statusMessage.value = err instanceof Error ? err.message : 'Enregistrement impossible.'
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  void load()
})
</script>

<style scoped>
.ext-player-card {
  margin-top: 16px;
}

.ext-player-body {
  display: grid;
  gap: 14px;
  padding: 20px;
  min-width: 0;
}

.ext-field-group {
  display: grid;
  gap: 8px;
  min-width: 0;
}

.ext-preset-row,
.ext-path-row,
.ext-actions-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.ext-select,
.ext-path-input {
  flex: 1 1 220px;
  min-width: 0;
  max-width: 100%;
  box-sizing: border-box;
}

.ext-detected-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.ext-toggle-row {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  color: var(--text);
  font-size: 0.9rem;
}

.ext-status-msg {
  margin: 0;
  font-size: 0.85rem;
  color: var(--muted);
}

.ext-status-msg.isError {
  color: #f87171;
}
</style>
