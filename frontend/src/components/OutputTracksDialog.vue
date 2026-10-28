<template>
  <ConfirmDialog
    :open="true"
    :title="tx('Pistes et format')"
    :confirm-label="tx('Produire le fichier')"
    :busy="loading || saving || sourcesBusy || refreshing"
    @cancel="$emit('close')"
    @confirm="submit"
  >
    <p>{{ tx('Le traitement utilise le master local, sans retélécharger la vidéo.') }}</p>
    <p v-if="error" role="alert" class="output-error">{{ error }}</p>
    <template v-if="!loading">
      <label class="output-field"
        >{{ tx('Format de sortie') }}
        <select v-model="mode" class="input-premium" @change="resetChoices">
          <option
            v-for="profile in profiles.filter((p) => p.mode !== 'ORIGINAL')"
            :key="profile.mode"
            :value="profile.mode"
            :disabled="!profile.available"
          >
            {{ tx(labels[profile.mode]) }}{{ profile.reason ? ` — ${tx(profile.reason)}` : '' }}
          </option>
        </select>
      </label>
      <p v-if="mode === 'MP4_HARD'" class="source-hint">
        {{ tx('Réencodage complet ; une interruption recommence la conversion.') }}
      </p>
      <p v-if="mode === 'SIDECAR'" class="source-hint">
        {{
          tx(
            'La vidéo et son audio restent inchangés. Seuls les sous-titres sont sélectionnés ici.',
          )
        }}
      </p>
      <div class="output-tracks">
        <section v-for="row in rows" :key="row.id" class="output-track">
          <label class="output-track-title">
            <input
              :key="`${mode}:${row.id}`"
              :type="
                row.kind === 'video' ||
                (mode === 'MP4_HARD' && ['audio', 'subtitle'].includes(row.kind))
                  ? 'radio'
                  : 'checkbox'
              "
              :name="`output-${row.kind}`"
              :checked="row.checked"
              :disabled="row.kind === 'font' || (mode === 'SIDECAR' && row.kind !== 'subtitle')"
              @change="toggle(row, ($event.target as HTMLInputElement).checked)"
            />
            <span
              >{{ tx(kinds[row.kind]) }} · {{ row.label }} · {{ row.lang }}
              <small v-if="row.automatic">{{ tx('Automatique') }}</small></span
            >
          </label>
          <button
            v-if="row.canRestore"
            type="button"
            class="btn btn-sm"
            :disabled="sourcesBusy || refreshing || saving"
            @click="restoreOriginal(row)"
          >
            {{ tx('Restaurer la piste originale') }}
          </button>
          <div
            v-if="
              row.checked &&
              ['audio', 'subtitle'].includes(row.kind) &&
              (mode !== 'SIDECAR' || row.kind === 'subtitle')
            "
            class="output-track-settings"
          >
            <label
              >{{ tx('Décalage (secondes)')
              }}<input
                v-model.number="row.offset"
                class="input-premium"
                type="number"
                step="0.1"
                min="-86400"
                max="86400"
            /></label>
            <label
              ><input
                type="checkbox"
                :checked="row.preferred"
                @change="prefer(row, ($event.target as HTMLInputElement).checked)"
              />{{ tx('Par défaut') }}</label
            >
            <label v-if="row.kind === 'subtitle'"
              ><input type="checkbox" v-model="row.forced" />{{ tx('Forcé') }}</label
            >
          </div>
        </section>
      </div>
      <SubtitleSourcesPanel
        :task="task"
        :reference-tracks="
          rows.filter((row) => row.kind === 'subtitle' && (row.local || row.embedded))
        "
        @added="loadInventory"
        @busy="sourcesBusy = $event"
      />
      <label class="output-field"
        ><span
          ><input type="checkbox" v-model="keepOriginals" />{{
            tx('Conserver les fichiers sources visibles')
          }}</span
        ></label
      >
      <p class="source-hint">
        {{
          tx('Un master privé est conservé pour changer de format. Il utilise de l’espace disque.')
        }}
      </p>
      <p v-for="warning in warnings" :key="warning" role="status">{{ tx(warning) }}</p>
    </template>
  </ConfirmDialog>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api } from '@/api/client'
import { tx } from '@/utils/locale'
import ConfirmDialog from './ConfirmDialog.vue'
import SubtitleSourcesPanel from './SubtitleSourcesPanel.vue'
import type {
  DownloadTask,
  OutputMediaTrack,
  OutputProfile,
  OutputProfileCapability,
} from '@/types'

type Row = OutputMediaTrack & { checked: boolean; offset: number; preferred: boolean }
const props = defineProps<{ task: DownloadTask }>()
const emit = defineEmits<{ close: []; saved: [] }>()
const loading = ref(true),
  saving = ref(false),
  error = ref(''),
  mode = ref<OutputProfile['mode']>('MKV_SOFT')
const profiles = ref<OutputProfileCapability[]>([]),
  rows = ref<Row[]>([]),
  warnings = ref<string[]>([])
const keepOriginals = ref(true),
  sourcesBusy = ref(false),
  refreshing = ref(false)
const labels = {
  ORIGINAL: 'Vidéo originale',
  SIDECAR: 'Sous-titres séparés',
  MKV_SOFT: 'MKV multipiste',
  MP4_HARD: 'MP4 avec sous-titres incrustés',
}
const kinds = { video: 'Vidéo', audio: 'Audio', subtitle: 'Sous-titres', font: 'Police' }

function resetChoices() {
  for (const kind of ['video', 'audio', 'subtitle', 'font']) {
    const candidates = rows.value.filter((row) => row.kind === kind && !row.automatic)
    const first = candidates.find((row) => row.default) || candidates[0]
    for (const row of rows.value.filter((item) => item.kind === kind)) {
      row.checked =
        !row.automatic &&
        (kind === 'video' || (mode.value === 'MP4_HARD' && ['audio', 'subtitle'].includes(kind))
          ? row === first
          : true)
      row.preferred = row === first
    }
  }
}
function toggle(row: Row, checked: boolean) {
  if (
    row.kind === 'video' ||
    (mode.value === 'MP4_HARD' && ['audio', 'subtitle'].includes(row.kind))
  ) {
    for (const other of rows.value.filter((item) => item.kind === row.kind)) other.checked = false
  }
  row.checked = checked
}
function prefer(row: Row, checked: boolean) {
  if (checked) {
    for (const other of rows.value.filter((item) => item.kind === row.kind)) other.preferred = false
  }
  row.preferred = checked
}
async function loadInventory(addedId?: string) {
  refreshing.value = true
  const previous = new Map(rows.value.map((row) => [row.id, { ...row }]))
  try {
    const data = await api.getOutputInventory(props.task.id)
    profiles.value = data.profiles
    warnings.value = data.warnings
    if (!previous.size) {
      mode.value = data.outputProfile.mode === 'ORIGINAL' ? 'MKV_SOFT' : data.outputProfile.mode
      keepOriginals.value = data.outputProfile.keepOriginals
    }
    rows.value = data.tracks.map((track) => ({
      ...track,
      checked: false,
      offset: 0,
      preferred: false,
    }))
    resetChoices()
    if (!previous.size && data.outputProfile.selections?.length) {
      for (const row of rows.value) {
        const selected = data.outputProfile.selections.find((item) => item.trackId === row.id)
        row.checked = !!selected || row.kind === 'font' || row.kind === 'video'
        row.offset = selected?.offsetSeconds || 0
        row.preferred = selected?.default || false
        row.forced = selected?.forced || false
      }
    }
    if (previous.size) {
      for (const row of rows.value) {
        const old = previous.get(row.id)
        if (old)
          Object.assign(row, {
            checked: old.checked,
            offset: old.offset,
            preferred: old.preferred,
            forced: old.forced,
          })
      }
    }
    if (addedId) {
      for (const row of rows.value.filter((item) => item.kind === 'subtitle')) {
        if (mode.value === 'MP4_HARD') row.checked = row.preferred = false
        if (row.id === addedId) {
          row.checked = true
          row.preferred = mode.value === 'MP4_HARD'
        }
      }
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : tx('Impossible de charger les pistes')
  } finally {
    loading.value = false
    refreshing.value = false
  }
}
onMounted(() => loadInventory())
async function restoreOriginal(row: Row) {
  sourcesBusy.value = true
  try {
    const data = await api.restoreSubtitle(props.task.id, row.id)
    await loadInventory(data.trackId)
    const corrected = rows.value.find((item) => item.id === row.id)
    if (corrected) corrected.checked = false
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : tx('Restauration impossible')
  } finally {
    sourcesBusy.value = false
  }
}
async function submit() {
  if (loading.value || saving.value || sourcesBusy.value || refreshing.value || !rows.value.length)
    return
  const selected = rows.value.filter(
    (row) =>
      row.checked && row.kind !== 'font' && (mode.value !== 'SIDECAR' || row.kind === 'subtitle'),
  )
  if (mode.value === 'MP4_HARD' && selected.filter((row) => row.kind === 'subtitle').length !== 1) {
    error.value = tx('Choisissez une seule piste de sous-titres pour l’incrustation.')
    return
  }
  const profile: OutputProfile = {
    version: 1,
    mode: mode.value,
    keepOriginals: keepOriginals.value,
    selections: selected.map((row) => ({
      trackId: row.id,
      offsetSeconds: Number(row.offset),
      default: row.preferred,
      forced: row.forced,
      required: true,
    })),
    burnTrackId:
      mode.value === 'MP4_HARD' ? selected.find((row) => row.kind === 'subtitle')?.id : null,
  }
  saving.value = true
  try {
    await api.reprocessOutput(props.task.id, profile)
    emit('saved')
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : tx('Le traitement a échoué')
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.output-field {
  display: grid;
  gap: 6px;
  margin: 12px 0;
  min-width: 0;
}
.output-field select {
  width: 100%;
  min-width: 0;
}
.output-tracks {
  display: grid;
  gap: 10px;
  max-height: 45vh;
  overflow: auto;
}
.output-track {
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 10px;
  min-width: 0;
}
.output-track-title {
  display: flex;
  gap: 8px;
  align-items: start;
  overflow-wrap: anywhere;
}
.output-track-settings {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 10px;
  align-items: center;
}
.output-track-settings label {
  max-width: 100%;
}
.output-track-settings input[type='number'] {
  display: block;
  width: 130px;
  max-width: 100%;
}
.output-error {
  color: var(--danger, #f87171);
}
</style>
