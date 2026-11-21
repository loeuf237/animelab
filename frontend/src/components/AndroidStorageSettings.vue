<template>
  <section v-if="state?.android" class="android-storage settings-card-pro" aria-live="polite">
    <h2>{{ tx('Autorisations Android') }}</h2>
    <p>
      {{
        tx(
          'Les vidéos terminées sont exportées vers le stockage partagé, puis la copie temporaire privée est libérée automatiquement. Sur Android 10+, AnimeLab utilise l’accès ciblé par dossier (SAF/MediaStore) sans demander l’autorisation globale « Stockage ».',
        )
      }}
    </p>
    <div class="storage-access-row">
      <div>
        <strong>{{ tx('Dossier de destination') }}</strong>
        <p>{{ state.destination }}</p>
      </div>
      <span :class="state.authorized ? 'badge-ok' : 'badge-err'">{{
        tx(state.authorized ? 'Accès autorisé' : 'Autorisation requise')
      }}</span>
    </div>
    <p>
      {{
        tx(
          'Downloads/AnimeLab fonctionne sans accès global au stockage. Pour un autre dossier ou une carte SD, utilisez le sélecteur Android pour autoriser l’accès.',
        )
      }}
    </p>
    <p v-if="state.subtitleDestination">
      {{ tx('Sous-titres séparés :') }} {{ state.subtitleDestination }}.
      {{
        tx(
          'Un dossier autorisé avec le sélecteur Android conserve la vidéo et les sous-titres au même endroit.',
        )
      }}
    </p>
    <div class="storage-access-actions">
      <button
        type="button"
        class="btn btn-primary"
        :disabled="busy || state.selectionPending"
        @click="act('choose_directory')"
      >
        {{ tx('Choisir et autoriser un dossier') }}
      </button>
      <button
        type="button"
        class="btn btn-secondary"
        :disabled="busy || state.selectionPending"
        @click="act('use_downloads')"
      >
        {{ tx('Utiliser Downloads/AnimeLab') }}
      </button>
      <button
        type="button"
        class="btn btn-secondary"
        :disabled="busy"
        @click="act('open_downloads')"
      >
        {{ tx('Ouvrir le dossier') }}
      </button>
    </div>
    <p v-if="state.selectionPending">
      {{ tx('Choisissez un sous-dossier dans la fenêtre Android, puis confirmez l’accès.') }}
    </p>
    <p v-if="error || state.error || state.exportError" class="storage-access-error" role="alert">
      {{ tx(error || state.error || state.exportError || '') }}
    </p>
    <div class="storage-access-row">
      <div>
        <strong>{{ tx('Notifications de téléchargement') }}</strong>
        <p>{{ tx(state.notificationsGranted ? 'Accès autorisé' : 'Autorisation requise') }}</p>
      </div>
      <button
        v-if="!state.notificationsGranted"
        type="button"
        class="btn btn-secondary"
        :disabled="busy"
        @click="act('notifications')"
      >
        {{ tx('Autoriser les notifications') }}
      </button>
    </div>
    <div class="storage-access-row">
      <div>
        <strong>{{ tx('Installation d’extensions APK') }}</strong>
        <p>{{ tx(state.installAppsGranted ? 'Accès autorisé' : 'Autorisation requise') }}</p>
      </div>
      <button
        v-if="!state.installAppsGranted"
        type="button"
        class="btn btn-secondary"
        :disabled="busy"
        @click="act('install_apps')"
      >
        {{ tx('Autoriser') }}
      </button>
    </div>
    <div class="storage-access-row">
      <div>
        <strong>{{ tx('Téléchargements en arrière-plan') }}</strong>
        <p>{{ tx(state.batteryUnrestricted ? 'Sans restriction' : 'Optimisée par Android') }}</p>
      </div>
      <button
        v-if="!state.batteryUnrestricted"
        type="button"
        class="btn btn-secondary"
        :disabled="busy"
        @click="act('battery')"
      >
        {{ tx('Configurer la batterie') }}
      </button>
    </div>
    <div class="storage-access-row storage-private-box">
      <div class="storage-private-meta">
        <strong>{{ tx('Stockage privé de l’application') }}</strong>
        <p>{{ reclaimableSummary }}</p>
        <p class="storage-reassurance">
          {{
            tx(
              'Vos vidéos déjà exportées dans Downloads/AnimeLab, votre bibliothèque et vos réglages sont conservés.',
            )
          }}
        </p>
      </div>
      <button
        type="button"
        class="btn btn-secondary"
        :disabled="busy || cleaning || (state.reclaimableBytes ?? 0) === 0"
        @click="cleanupPrivateStorage"
      >
        {{ tx(cleaning ? 'Nettoyage…' : 'Libérer le stockage privé') }}
      </button>
    </div>
    <p v-if="cleanupNotice" class="storage-cleanup-notice" role="status">{{ cleanupNotice }}</p>
    <div class="storage-access-actions">
      <button type="button" class="btn btn-secondary" :disabled="busy" @click="act('app_settings')">
        {{ tx('Permissions dans les paramètres Android') }}
      </button>
      <button type="button" class="btn btn-secondary" :disabled="busy" @click="refresh">
        {{ tx('Actualiser les accès') }}
      </button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api, type AndroidStorageState } from '@/api/client'
import { tx } from '@/utils/locale'

const state = ref<AndroidStorageState | null>(null)
const busy = ref(false)
const cleaning = ref(false)
const error = ref('')
const cleanupNotice = ref('')
let timer: ReturnType<typeof setInterval> | undefined
let refreshing = false

function formatMb(bytes: number): string {
  return (bytes / (1024 * 1024)).toFixed(1)
}

const reclaimableSummary = computed(() => {
  const reclaimable = state.value?.reclaimableBytes ?? 0
  if (reclaimable <= 0) return tx('Aucun fichier temporaire à nettoyer')
  return `${formatMb(reclaimable)} ${tx('Mo récupérables')}`
})

async function refresh() {
  if (refreshing) return
  refreshing = true
  try {
    state.value = await api.getAndroidStorage()
  } catch (failure) {
    error.value = failure instanceof Error ? failure.message : String(failure)
  } finally {
    refreshing = false
  }
}

async function act(action: string) {
  busy.value = true
  error.value = ''
  try {
    state.value = await api.androidStorageAction(action)
  } catch (failure) {
    error.value = failure instanceof Error ? failure.message : String(failure)
  } finally {
    busy.value = false
  }
}

async function cleanupPrivateStorage() {
  if (busy.value || cleaning.value) return
  cleaning.value = true
  error.value = ''
  cleanupNotice.value = ''
  try {
    const res = await api.androidCleanupPrivateStorage()
    if (res.storage) state.value = res.storage
    else await refresh()
    cleanupNotice.value = tx('{0} Mo libérés dans le stockage privé.').replace(
      '{0}',
      formatMb(res.freedBytes || 0),
    )
  } catch (failure) {
    error.value = failure instanceof Error ? failure.message : String(failure)
  } finally {
    cleaning.value = false
  }
}

function handleVisibility() {
  if (!document.hidden) void refresh()
}

onMounted(async () => {
  await refresh()
  if (state.value?.android) {
    window.addEventListener('focus', refresh)
    document.addEventListener('visibilitychange', handleVisibility)
    timer = setInterval(() => {
      if (!document.hidden) void refresh()
    }, 4000)
  }
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
  window.removeEventListener('focus', refresh)
  document.removeEventListener('visibilitychange', handleVisibility)
})
</script>

<style scoped>
.android-storage {
  padding: 16px;
}
.android-storage h2 {
  margin: 0 0 12px;
  font-size: 1.15rem;
}
.android-storage p {
  color: var(--text-secondary);
  line-height: 1.55;
  overflow-wrap: anywhere;
}
.storage-access-row {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin: 20px 0 12px;
}
.storage-access-row p {
  margin: 6px 0;
}
.storage-private-box {
  padding-top: 14px;
  border-top: 1px solid var(--line);
}
.storage-private-meta {
  flex: 1;
  min-width: min(240px, 100%);
}
.storage-reassurance {
  font-size: 0.82rem;
  color: var(--muted);
}
.storage-cleanup-notice {
  color: #34d399 !important;
  font-size: 0.88rem;
  font-weight: 500;
}
.storage-access-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin: 16px 0;
}
.storage-access-actions .btn {
  max-width: 100%;
  white-space: normal;
  text-align: center;
}
.storage-access-error {
  color: var(--danger, #ef4444) !important;
}
</style>
