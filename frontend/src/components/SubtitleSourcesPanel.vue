<template>
  <details class="subtitle-sources" @toggle="initialize">
    <summary>{{ tx('Ajouter des sous-titres') }}</summary>
    <p v-if="error" role="alert" class="subtitle-error">{{ error }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <fieldset :disabled="busy">
      <legend>{{ tx('Importer un fichier local') }}</legend>
      <p>
        {{ tx('SRT, VTT, ASS, ZIP ou GZIP · 10 Mo maximum. Choisissez ensuite le bon épisode.') }}
      </p>
      <label
        >{{ tx('Encodage du fichier') }}
        <select v-model="encoding" class="input-premium">
          <option value="auto">{{ tx('Détection UTF-8 / UTF-16') }}</option>
          <option value="windows-1252">Windows-1252</option>
          <option value="iso-8859-1">ISO-8859-1</option>
        </select>
      </label>
      <label
        >{{ tx('Fichier de sous-titres ou archive') }}
        <input type="file" accept=".srt,.vtt,.ass,.ssa,.zip,.gz" @change="upload" />
      </label>
    </fieldset>
    <details v-if="provider" class="provider-settings">
      <summary>
        <span>{{ tx('Compte OpenSubtitles') }}</span> / SubDL
      </summary>
      <label
        >{{ tx('Fournisseur à configurer') }}
        <select v-model="providerName" class="input-premium" @change="switchProvider">
          <option value="opensubtitles">OpenSubtitles</option>
          <option value="subdl">SubDL v2</option>
        </select>
      </label>
      <p v-if="providerName === 'subdl'">
        {{ tx('SubDL utilise uniquement une clé API transmise dans un en-tête sécurisé.') }}
      </p>
      <p v-if="providerName === 'opensubtitles'">
        {{
          tx(
            'Vos identifiants sont envoyés uniquement à OpenSubtitles. Aucun mot de passe n’est conservé dans le navigateur.',
          )
        }}
      </p>
      <p>
        {{
          tx(
            provider.remember
              ? 'Identifiants sauvegardés avec une clé de chiffrement externe.'
              : 'Identifiants en mémoire uniquement ; reconnectez-vous après le redémarrage du serveur.',
          )
        }}
      </p>
      <a
        :href="
          providerName === 'subdl'
            ? 'https://subdl.com/developers'
            : 'https://www.opensubtitles.com/en/consumers'
        "
        target="_blank"
        rel="noopener noreferrer"
        >{{
          providerName === 'subdl'
            ? tx('Créer une clé API SubDL')
            : tx('Créer une clé API OpenSubtitles')
        }}</a
      >
      <fieldset :disabled="busy">
        <label
          >{{ tx(providerName === 'subdl' ? 'Clé API SubDL' : 'Clé API OpenSubtitles')
          }}<input
            v-model="apiKey"
            class="input-premium"
            type="password"
            autocomplete="off"
            :placeholder="provider.configured ? tx('Vide : conserver la clé actuelle') : ''"
        /></label>
        <label v-if="providerName === 'opensubtitles'"
          >{{ tx('Nom d’utilisateur OpenSubtitles (facultatif)')
          }}<input v-model="username" class="input-premium" autocomplete="off"
        /></label>
        <label v-if="providerName === 'opensubtitles'"
          >{{ tx('Mot de passe OpenSubtitles')
          }}<input v-model="password" class="input-premium" type="password" autocomplete="off"
        /></label>
        <label class="check-label"
          ><input
            v-model="remember"
            type="checkbox"
            :disabled="!provider.secureStorageAvailable"
          />{{ tx('Mémoriser les identifiants chiffrés') }}</label
        >
        <small v-if="!provider.secureStorageAvailable">{{
          tx('La mémorisation nécessite une clé externe configurée par l’opérateur.')
        }}</small>
        <div class="subtitle-actions">
          <button class="btn btn-sm" type="button" @click="configure">
            {{ tx(providerName === 'subdl' ? 'Connecter SubDL' : 'Connecter OpenSubtitles') }}
          </button>
          <button class="btn btn-sm" type="button" @click="forget">
            {{ tx('Oublier les identifiants') }}
          </button>
        </div>
      </fieldset>
    </details>
    <fieldset :disabled="busy">
      <legend>{{ tx('Rechercher des sous-titres') }}</legend>
      <label class="check-label"
        ><input
          v-model="query.providers"
          type="checkbox"
          value="opensubtitles"
        />OpenSubtitles</label
      >
      <label class="check-label"
        ><input v-model="query.providers" type="checkbox" value="subdl" />SubDL v2</label
      >
      <p v-for="failure in searchErrors" :key="failure.provider" class="subtitle-warning">
        {{ failure.provider }} : {{ failure.message }}
      </p>
      <p v-if="video">
        {{ tx('Vidéo locale') }} : {{ video.fps ?? tx('Inconnu') }} FPS ·
        {{ video.duration ?? tx('Inconnu') }} s
      </p>
      <p v-if="provider?.quota.downloads">
        SubDL · {{ tx('Téléchargements restants') }} :
        {{ provider.quota.downloads.remaining ?? tx('Inconnu') }}
      </p>
      <p v-if="provider?.quota.remaining != null">
        {{ tx('Téléchargements restants') }} : {{ provider.quota.remaining }}
        <span v-if="provider.quota.reset_time_utc">· {{ provider.quota.reset_time_utc }}</span>
      </p>
      <p v-else-if="provider?.quota.allowed_downloads != null">
        {{ tx('Quota du compte') }} : {{ provider.quota.allowed_downloads }}
      </p>
      <p v-if="provider?.retryAfter">
        {{ tx('Patientez avant de réessayer (secondes)') }} : {{ provider.retryAfter }}
      </p>
      <label
        >{{ tx('Titre de la série ou du film')
        }}<input v-model="query.query" class="input-premium" maxlength="200"
      /></label>
      <div class="subtitle-grid">
        <label
          >{{ tx('Langues (fr,en…)')
          }}<input v-model="query.languages" class="input-premium" maxlength="30"
        /></label>
        <label
          >{{ tx('Type d’identifiant')
          }}<select v-model="query.idType" class="input-premium">
            <option value="series">{{ tx('Série') }}</option>
            <option value="episode">{{ tx('Épisode précis') }}</option>
            <option value="movie">{{ tx('Film') }}</option>
          </select></label
        >
        <label>IMDb<input v-model="query.imdbId" class="input-premium" placeholder="tt…" /></label>
        <label
          >TMDB<input v-model="query.tmdbId" type="number" min="1" class="input-premium"
        /></label>
      </div>
      <template v-if="query.idType === 'series'">
        <label class="check-label"
          ><input v-model="absolute" type="checkbox" />{{ tx('Numérotation absolue') }}</label
        >
        <div v-if="!absolute" class="subtitle-grid">
          <label
            >{{ tx('Saison (si connue)')
            }}<input v-model="query.season" type="number" min="0" class="input-premium"
          /></label>
          <label
            >{{ tx('Épisode recherché')
            }}<input v-model="query.episode" type="number" min="0" class="input-premium"
          /></label>
        </div>
        <label v-else
          >{{ tx('Numéro absolu de l’épisode')
          }}<input v-model="query.absoluteEpisode" type="number" min="1" class="input-premium"
        /></label>
      </template>
      <label
        >{{ tx('Release attendue (facultatif)')
        }}<input v-model="query.expectedRelease" class="input-premium" maxlength="255"
      /></label>
      <div class="subtitle-grid">
        <label
          >{{ tx('FPS attendus (facultatif)')
          }}<input
            v-model="query.expectedFps"
            type="number"
            min="1"
            max="240"
            step="0.001"
            class="input-premium"
        /></label>
        <label
          >{{ tx('Durée vidéo attendue en secondes (facultatif)')
          }}<input
            v-model="query.expectedDuration"
            type="number"
            min="0.001"
            step="0.001"
            class="input-premium"
        /></label>
      </div>
      <p>
        {{
          tx(
            'Vérifiez les identifiants, la saison, l’épisode et la release. Aucun résultat n’est choisi automatiquement.',
          )
        }}
      </p>
      <button
        type="button"
        class="btn btn-sm"
        :disabled="!query.providers?.length"
        @click="search(1)"
      >
        {{ tx('Rechercher les sous-titres') }}
      </button>
      <p>
        {{
          tx('L’aperçu télécharge le sous-titre et peut consommer une unité de quota fournisseur.')
        }}
      </p>
      <div class="subtitle-results">
        <article v-for="result in results" :key="result.id" class="subtitle-result">
          <strong>{{ result.fileName }}</strong> · {{ result.provider || 'OpenSubtitles' }}
          <p>
            {{ result.language }} · {{ result.release }}
            <span v-if="result.fps">· {{ result.fps }} FPS</span>
          </p>
          <p>
            {{ result.feature.parent_title }} {{ result.feature.title }}
            <span v-if="result.feature.season_number != null"
              >· S{{ result.feature.season_number }} E{{ result.feature.episode_number }}</span
            >
          </p>
          <small v-if="result.hearingImpaired">{{ tx('Sourds et malentendants') }}</small>
          <small v-if="result.forced">{{ tx('Forcé') }}</small>
          <p v-for="check in result.checks" :key="check.field">
            {{ check.field }} : {{ check.actual ?? tx('Inconnu') }} · {{ tx('Attendu') }}
            {{ check.expected }} ·
            {{
              tx(
                check.state === 'match'
                  ? 'Correspondance'
                  : check.state === 'mismatch'
                    ? 'Différent de la recherche'
                    : 'Non vérifié',
              )
            }}
          </p>
          <p v-for="warning in result.warnings" :key="warning" class="subtitle-warning">
            {{ tx(warning) }}
          </p>
          <label v-if="result.alternatives && result.alternatives.length > 1"
            >{{ tx('Provenance à télécharger') }}
            <select v-model="alternatives[result.id]" class="input-premium">
              <option v-for="source in result.alternatives" :key="source.id" :value="source.id">
                {{ source.provider }}
              </option>
            </select>
          </label>
          <button type="button" class="btn btn-sm" @click="preview(result)">
            {{ tx('Télécharger et prévisualiser') }}
          </button>
        </article>
      </div>
      <div v-if="totalPages > 1" class="subtitle-actions">
        <button type="button" class="btn btn-sm" :disabled="page <= 1" @click="search(page - 1)">
          {{ tx('Précédent') }}
        </button>
        <span>{{ page }} / {{ totalPages }}</span>
        <button
          type="button"
          class="btn btn-sm"
          :disabled="page >= totalPages"
          @click="search(page + 1)"
        >
          {{ tx('Suivant') }}
        </button>
      </div>
    </fieldset>
    <fieldset v-if="imported" :disabled="busy">
      <legend>{{ tx('Aperçu et sélection du fichier') }}</legend>
      <label
        >{{ tx('Fichier dans l’import')
        }}<select v-model="entryId" class="input-premium" @change="confirmed = false">
          <option disabled value="">{{ tx('Choisir un fichier dans l’archive') }}</option>
          <option v-for="entry in imported.entries" :key="entry.id" :value="entry.id">
            {{ entry.name }}
          </option>
        </select></label
      >
      <template v-if="entry">
        <p>
          {{ entry.cues }} {{ tx('répliques') }} · {{ entry.firstCue.toFixed(1) }}–{{
            entry.lastCue.toFixed(1)
          }}
          s
        </p>
        <p v-if="entry.numbering">
          {{ tx('Numérotation du fichier') }} : S{{ entry.numbering.season }} E{{
            entry.numbering.episode
          }}
        </p>
        <p v-if="wrongEpisode" role="status" class="subtitle-warning">
          {{ tx('Attention : le numéro du fichier diffère de celui de la tâche.') }}
        </p>
        <pre class="subtitle-preview" tabindex="0">{{ entry.preview }}</pre>
        <details class="timing-settings">
          <summary>{{ tx('Corriger la synchronisation') }}</summary>
          <p>
            {{
              tx(
                'Une nouvelle copie est créée. L’original reste disponible ; une correction de timing ne vérifie pas le contenu des répliques.',
              )
            }}
          </p>
          <label
            >{{ tx('Méthode de correction')
            }}<select v-model="timingMethod" class="input-premium">
              <option value="manual">{{ tx('Décalage et cadence manuels') }}</option>
              <option value="alass" :disabled="!syncCaps?.alass">Alass 2.0.0</option>
            </select></label
          >
          <p v-if="!syncCaps?.alass">
            {{ syncCaps?.reason || tx('Synchronisation automatique indisponible') }}
          </p>
          <template v-if="timingMethod === 'manual'">
            <label
              >{{ tx('Décalage à appliquer (secondes)')
              }}<input
                v-model="timingOffset"
                type="number"
                step="0.1"
                min="-86400"
                max="86400"
                class="input-premium"
            /></label>
            <div class="subtitle-grid">
              <label
                >{{ tx('Cadence du sous-titre (facultatif)')
                }}<input
                  v-model="sourceFps"
                  type="number"
                  step="0.001"
                  min="1"
                  max="240"
                  class="input-premium" /></label
              ><label
                >{{ tx('Cadence de la vidéo (facultatif)')
                }}<input
                  v-model="targetFps"
                  type="number"
                  step="0.001"
                  min="1"
                  max="240"
                  class="input-premium"
              /></label>
            </div>
          </template>
          <template v-else>
            <label
              >{{ tx('Piste locale de référence')
              }}<select v-model="referenceId" class="input-premium">
                <option disabled value="">{{ tx('Choisir une référence') }}</option>
                <option v-for="track in referenceTracks" :key="track.id" :value="track.id">
                  {{ track.label }} · {{ track.lang }}
                </option>
              </select></label
            >
            <label class="check-label"
              ><input v-model="referenceConfirmed" type="checkbox" />{{
                tx('Cette référence est déjà synchronisée avec cette vidéo.')
              }}</label
            >
            <label class="check-label"
              ><input v-model="allowSplits" type="checkbox" />{{
                tx('Autoriser plusieurs décalages (montage différent ; contrôle manuel nécessaire)')
              }}</label
            >
            <p>
              {{
                tx(
                  'Le recouvrement mesure les timings, pas la justesse des dialogues. Aucun alignement universel n’est garanti.',
                )
              }}
            </p>
          </template>
          <button
            class="btn btn-sm"
            type="button"
            :disabled="timingMethod === 'alass' && (!referenceId || !referenceConfirmed)"
            @click="correctTiming"
          >
            {{ tx('Créer une copie corrigée') }}
          </button>
          <p v-if="comparison" role="status">
            {{ tx('Correction créée') }} :
            {{
              tx(
                comparison.kind === 'drift'
                  ? 'Dérive de cadence'
                  : comparison.kind === 'nonuniform'
                    ? 'Correction non uniforme'
                    : 'Décalage constant',
              )
            }}
            · {{ comparison.correctedCues }} {{ tx('répliques')
            }}<span v-if="comparison.overlapAfter != null">
              · {{ tx('Recouvrement des timings') }}
              {{ Math.round(comparison.overlapAfter * 100) }} %</span
            >
          </p>
          <button v-if="originalId" type="button" class="btn btn-sm" @click="undoTiming">
            {{ tx('Revenir au sous-titre original') }}
          </button>
        </details>
        <div class="subtitle-grid">
          <label
            >{{ tx('Langue du sous-titre')
            }}<input v-model="selectedLanguage" class="input-premium" maxlength="10"
          /></label>
          <label
            >{{ tx('Nom de la piste')
            }}<input v-model="selectedLabel" class="input-premium" maxlength="255"
          /></label>
        </div>
        <label class="check-label"
          ><input v-model="confirmed" type="checkbox" />{{
            tx('Je confirme que ce fichier correspond au bon épisode et à cette vidéo.')
          }}</label
        >
        <button type="button" class="btn btn-sm" :disabled="!confirmed" @click="attach">
          {{ tx('Ajouter cette piste') }}
        </button>
      </template>
    </fieldset>
    <button v-if="syncBusy" class="btn btn-sm" type="button" @click="cancelTiming">
      {{ tx('Interrompre la synchronisation') }}
    </button>
    <p v-if="busy" role="status">{{ tx('Opération de sous-titres en cours…') }}</p>
  </details>
</template>

<script setup lang="ts">
import { computed, ref, onUnmounted } from 'vue'
import { api } from '@/api/client'
import { tx } from '@/utils/locale'
import type { DownloadTask, OutputMediaTrack } from '@/types'
import type {
  SubtitleImport,
  SubtitleProvider,
  SubtitleSyncCapabilities,
  SubtitleProviderStatus,
  SubtitleSearchQuery,
  SubtitleSearchResult,
} from '@/types/subtitles'
const props = withDefaults(
  defineProps<{ task: DownloadTask; referenceTracks?: OutputMediaTrack[] }>(),
  { referenceTracks: () => [] },
)
const emit = defineEmits<{ added: [trackId: string]; busy: [value: boolean] }>()
const providerStates = ref<Partial<Record<SubtitleProvider, SubtitleProviderStatus>>>({})
const providerName = ref<SubtitleProvider>('opensubtitles')
const provider = computed<SubtitleProviderStatus>(
  () =>
    providerStates.value[providerName.value] || {
      configured: false,
      authenticated: false,
      username: '',
      remember: false,
      secureStorageAvailable: false,
      quota: {},
      error: null,
      retryAfter: 0,
    },
)
const video = ref<{ fps: number | null; duration: number | null } | null>(null)
const searchErrors = ref<{ provider: SubtitleProvider; message: string }[]>([])
const alternatives = ref<Record<string, string>>({})
const syncCaps = ref<SubtitleSyncCapabilities | null>(null)
const syncBusy = ref(false),
  timingMethod = ref<'manual' | 'alass'>('manual'),
  timingOffset = ref<number | string>(0),
  sourceFps = ref<number | string>(''),
  targetFps = ref<number | string>(''),
  referenceId = ref(''),
  referenceConfirmed = ref(false),
  allowSplits = ref(false)
const originalId = ref(''),
  originalEntry = ref(''),
  comparison = ref<SubtitleImport['comparison']>()
function switchProvider() {
  apiKey.value = password.value = ''
  username.value = provider.value?.username || ''
  remember.value = provider.value?.remember || false
}
function setProviders(data: {
  provider: SubtitleProviderStatus
  providers?: Partial<Record<SubtitleProvider, SubtitleProviderStatus>>
}) {
  providerStates.value = {
    ...providerStates.value,
    opensubtitles: data.provider,
    ...data.providers,
  }
}
const busy = ref(false),
  error = ref(''),
  notice = ref(''),
  loaded = ref(false)
const encoding = ref('auto'),
  apiKey = ref(''),
  username = ref(''),
  password = ref(''),
  remember = ref(false)
const query = ref<SubtitleSearchQuery>({
  providers: ['opensubtitles'],
  query: props.task.animeName || '',
  languages: 'fr',
  idType: 'series',
  episode: Number(props.task.episodeNumber),
  page: 1,
})
const absolute = ref(false),
  results = ref<SubtitleSearchResult[]>([]),
  page = ref(1),
  totalPages = ref(1)
const expectedSeason = ref<number | null>(null)
const imported = ref<SubtitleImport | null>(null),
  entryId = ref(''),
  selectedLanguage = ref('fr'),
  selectedLabel = ref(''),
  confirmed = ref(false)
const entry = computed(() => imported.value?.entries.find((row) => row.id === entryId.value))
const wrongEpisode = computed(
  () =>
    !!entry.value?.numbering &&
    (entry.value.numbering.episode !== Number(props.task.episodeNumber) ||
      (expectedSeason.value != null && entry.value.numbering.season !== expectedSeason.value)),
)
let alive = true
onUnmounted(() => {
  alive = false
  apiKey.value = password.value = ''
})
async function perform(action: () => Promise<void>) {
  if (busy.value) return
  busy.value = true
  emit('busy', true)
  error.value = ''
  notice.value = ''
  try {
    await action()
  } catch (cause) {
    if (alive)
      error.value =
        cause instanceof Error ? cause.message : tx('Opération de sous-titres impossible')
  } finally {
    busy.value = false
    emit('busy', false)
  }
}
async function initialize(event: Event) {
  if (!(event.target as HTMLDetailsElement).open || loaded.value) return
  await perform(async () => {
    const context = await api.getSubtitleContext(props.task.id)
    setProviders(context)
    switchProvider()
    video.value = context.video || null
    try {
      syncCaps.value = await api.getSubtitleSyncCapabilities()
    } catch {
      /* Manual edits remain available without the optional tool. */
    }
    query.value.query = context.query
    query.value.season = context.season
    expectedSeason.value = context.season
    query.value.episode = context.episode
    loaded.value = true
  })
}
async function configure() {
  await perform(async () => {
    try {
      providerStates.value[providerName.value] = await api.configureSubtitleProvider(
        {
          apiKey: apiKey.value || undefined,
          username: providerName.value === 'subdl' ? '' : username.value,
          password: providerName.value === 'subdl' ? '' : password.value,
          remember: remember.value,
        },
        providerName.value,
      )
    } finally {
      apiKey.value = password.value = ''
    }
    notice.value = tx(
      providerName.value === 'subdl'
        ? 'Connexion SubDL enregistrée.'
        : 'Connexion OpenSubtitles enregistrée.',
    )
  })
}
async function forget() {
  await perform(async () => {
    providerStates.value[providerName.value] = await api.forgetSubtitleProvider(providerName.value)
    apiKey.value = password.value = username.value = ''
    remember.value = false
    results.value = []
  })
}
function number(value: unknown): number | null {
  return value === '' || value == null ? null : Number(value)
}
async function search(targetPage: number) {
  await perform(async () => {
    const body = {
      ...query.value,
      page: targetPage,
      tmdbId: number(query.value.tmdbId),
      expectedFps: number(query.value.expectedFps),
      expectedDuration: number(query.value.expectedDuration),
      season:
        query.value.idType === 'series' && !absolute.value ? number(query.value.season) : null,
      episode:
        query.value.idType === 'series' && !absolute.value ? number(query.value.episode) : null,
      absoluteEpisode:
        query.value.idType === 'series' && absolute.value
          ? number(query.value.absoluteEpisode)
          : null,
    }
    const data = await api.searchSubtitles(props.task.id, body)
    results.value = data.results
    page.value = data.page
    totalPages.value = data.totalPages
    setProviders(data)
    searchErrors.value = data.errors || []
    alternatives.value = Object.fromEntries(data.results.map((row) => [row.id, row.id]))
    if (!data.results.length) notice.value = tx('Aucun sous-titre trouvé avec ces critères.')
  })
}
function showImport(data: SubtitleImport) {
  imported.value = data
  originalId.value = data.originalImportId || ''
  originalEntry.value = data.originalEntryId || ''
  comparison.value = data.comparison
  entryId.value = data.entries.length === 1 ? data.entries[0].id : ''
  confirmed.value = false
  selectedLabel.value = data.entries.length === 1 ? data.entries[0].name : ''
}
async function upload(event: Event) {
  const input = event.target as HTMLInputElement,
    file = input.files?.[0]
  if (!file) return
  await perform(async () => {
    if (file.size > 10 * 1024 * 1024) throw new Error(tx('Import limité à 10 Mo compressés'))
    showImport(await api.uploadSubtitles(props.task.id, file, encoding.value))
  })
  input.value = ''
}
async function preview(result: SubtitleSearchResult) {
  await perform(async () => {
    showImport(
      await api.previewProviderSubtitle(props.task.id, alternatives.value[result.id] || result.id),
    )
    selectedLanguage.value = result.language
    selectedLabel.value = result.release || result.fileName
    const context = await api.getSubtitleContext(props.task.id)
    setProviders(context)
  })
}
async function correctTiming() {
  if (!imported.value || !entry.value) return
  await perform(async () => {
    syncBusy.value = true
    try {
      const data = await api.correctSubtitle(props.task.id, {
        importId: imported.value!.importId,
        entryId: entry.value!.id,
        method: timingMethod.value,
        offsetSeconds: timingMethod.value === 'manual' ? Number(timingOffset.value || 0) : 0,
        sourceFps: timingMethod.value === 'manual' ? number(sourceFps.value) : null,
        targetFps: timingMethod.value === 'manual' ? number(targetFps.value) : null,
        referenceTrackId: timingMethod.value === 'alass' ? referenceId.value : null,
        referenceConfirmed: referenceConfirmed.value,
        allowSplits: allowSplits.value,
      })
      showImport(data)
      timingOffset.value = 0
      sourceFps.value = targetFps.value = ''
    } finally {
      syncBusy.value = false
    }
  })
}
async function undoTiming() {
  await perform(async () => {
    const id = originalEntry.value
    showImport(await api.getSubtitleImport(props.task.id, originalId.value))
    entryId.value = id
  })
}
async function cancelTiming() {
  try {
    await api.cancelSubtitleSync(props.task.id)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : tx('Interruption impossible')
  }
}
async function attach() {
  if (!imported.value || !entry.value || !confirmed.value) return
  await perform(async () => {
    const result = await api.attachSubtitle(props.task.id, {
      importId: imported.value!.importId,
      entryId: entry.value!.id,
      language: selectedLanguage.value,
      label: selectedLabel.value || entry.value!.name,
      confirmedEpisode: true,
    })
    emit('added', result.trackId)
    imported.value = null
    notice.value = tx(
      'Piste ajoutée. Choisissez son format et son décalage, puis produisez le fichier.',
    )
  })
}
</script>

<style scoped>
.subtitle-sources {
  margin: 16px 0;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 12px;
  min-width: 0;
}
summary {
  cursor: pointer;
  font-weight: 600;
}
fieldset {
  border: 1px solid var(--line);
  border-radius: 8px;
  min-width: 0;
  margin: 12px 0;
  padding: 10px;
}
legend {
  max-width: 100%;
}
label {
  display: grid;
  gap: 4px;
  margin: 8px 0;
  min-width: 0;
}
input,
select {
  max-width: 100%;
  min-width: 0;
  width: 100%;
}
input[type='file'] {
  font-size: 12px;
}
.check-label {
  display: flex;
  align-items: start;
  gap: 8px;
}
input[type='checkbox'] {
  width: auto;
  flex-shrink: 0;
}
.subtitle-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}
.subtitle-results {
  max-height: 40vh;
  overflow: auto;
}
.subtitle-result {
  border-top: 1px solid var(--line);
  padding: 10px 0;
  overflow-wrap: anywhere;
}
.subtitle-preview {
  white-space: pre-wrap;
  overflow: auto;
  max-height: 180px;
  font-size: 12px;
  border: 1px solid var(--line);
  padding: 8px;
}
.subtitle-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin: 8px 0;
}
.subtitle-error {
  color: var(--danger, #f87171);
}
.subtitle-warning {
  color: var(--muted);
  font-weight: 600;
}
.provider-settings {
  margin-top: 12px;
}
</style>
