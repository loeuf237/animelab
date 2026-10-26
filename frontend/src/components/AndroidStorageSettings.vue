<template>
  <section v-if="state?.android" class="android-storage settings-card-pro" aria-live="polite">
    <h2>{{ tx('Autorisations Android') }}</h2>
    <p>
      {{
        tx(
          'Les fichiers terminés sont copiés dans le stockage partagé. Les téléchargements en cours restent privés.',
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
        class="btn btn-primary"
        :disabled="busy || state.selectionPending"
        @click="act('choose_directory')"
      >
        {{ tx('Choisir et autoriser un dossier') }}
      </button>
      <button
        class="btn btn-secondary"
        :disabled="busy || state.selectionPending"
        @click="act('use_downloads')"
      >
        {{ tx('Utiliser Downloads/AnimeLab') }}
      </button>
      <button class="btn btn-secondary" :disabled="busy" @click="act('open_downloads')">
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
        class="btn btn-secondary"
        :disabled="busy"
        @click="act('notifications')"
      >
        {{ tx('Autoriser les notifications') }}
      </button>
    </div>
    <div class="storage-access-actions">
      <button class="btn btn-secondary" :disabled="busy" @click="act('app_settings')">
        {{ tx('Permissions dans les paramètres Android') }}
      </button>
      <button class="btn btn-secondary" :disabled="busy" @click="refresh">
        {{ tx('Actualiser les accès') }}
      </button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { api, type AndroidStorageState } from '@/api/client'
import { tx } from '@/utils/locale'
const state = ref<AndroidStorageState | null>(null)
const busy = ref(false)
const error = ref('')
let timer: ReturnType<typeof setInterval> | undefined
let refreshing = false
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
onMounted(async () => {
  await refresh()
  if (state.value?.android) {
    window.addEventListener('focus', refresh)
    timer = setInterval(refresh, 4000)
  }
})
onUnmounted(() => {
  if (timer) clearInterval(timer)
  window.removeEventListener('focus', refresh)
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
