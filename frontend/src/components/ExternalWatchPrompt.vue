<template>
  <aside
    v-if="prompt && !playerStore.isOpen"
    class="external-watch-prompt glass-panel"
    role="status"
    aria-live="polite"
  >
    <div class="external-watch-head">
      <div class="external-watch-title-wrap">
        <ExternalLink :size="16" aria-hidden="true" />
        <strong>{{ tx('Lecture dans le lecteur externe') }} ({{ tx(prompt.playerName) }})</strong>
      </div>
      <button
        type="button"
        class="external-watch-close"
        :aria-label="tx('Fermer')"
        :title="tx('Fermer')"
        @click="playerStore.dismissExternalWatch"
      >
        <X :size="15" aria-hidden="true" />
      </button>
    </div>

    <p class="external-watch-sub">
      {{ tx(prompt.animeTitle) }} — {{ tx('Épisode') }} {{ tx(prompt.episodeNumber) }}
    </p>

    <div class="external-watch-actions">
      <button
        v-if="prompt.animeUrl"
        type="button"
        class="btn btn-primary btn-sm"
        :disabled="marking"
        @click="markAsWatched"
      >
        <Check :size="14" aria-hidden="true" />
        <span>{{ tx('Marquer comme vu') }}</span>
      </button>
      <button
        v-if="prompt.fallback"
        type="button"
        class="btn btn-secondary btn-sm"
        @click="openBuiltinFallback"
      >
        <span>{{ tx('Lecteur intégré') }}</span>
      </button>
      <button type="button" class="btn btn-sm" @click="playerStore.dismissExternalWatch">
        {{ tx('Fermer') }}
      </button>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { Check, ExternalLink, X } from 'lucide-vue-next'
import { useLibraryStore } from '@/stores/library'
import { useNotifications } from '@/stores/notifications'
import { usePlayerStore } from '@/stores/player'
import { tx } from '@/utils/locale'

const playerStore = usePlayerStore()
const libraryStore = useLibraryStore()
const notifications = useNotifications()
const marking = ref(false)

const prompt = computed(() => playerStore.pendingExternalWatch)

async function markAsWatched() {
  const current = prompt.value
  if (!current || !current.animeUrl || marking.value) return
  marking.value = true
  try {
    await libraryStore.markWatched(
      current.animeUrl,
      current.episodeNumber,
      true,
      current.version || '',
      current.animeTitle,
    )
    notifications.notify(
      `${current.animeTitle} — ${tx('Épisode')} ${current.episodeNumber} ${tx('marqué comme vu.')}`,
      'success',
    )
    playerStore.dismissExternalWatch()
  } catch (err) {
    notifications.notify(
      err instanceof Error ? err.message : 'Impossible de marquer l’épisode comme vu.',
      'error',
    )
  } finally {
    marking.value = false
  }
}

async function openBuiltinFallback() {
  const current = prompt.value
  const fn = current?.fallback
  playerStore.dismissExternalWatch()
  if (fn) await fn()
}
</script>

<style scoped>
.external-watch-prompt {
  position: fixed;
  right: max(16px, env(safe-area-inset-right, 0px));
  bottom: max(18px, env(safe-area-inset-bottom, 0px));
  z-index: 260;
  width: min(400px, calc(100vw - 24px));
  padding: 14px 16px;
  border-radius: var(--radius, 12px);
  background: var(--panel, rgba(14, 18, 30, 0.96));
  border: 1px solid var(--border-highlight, var(--line));
  box-shadow: 0 14px 36px rgba(0, 0, 0, 0.4);
  display: grid;
  gap: 8px;
}

.external-watch-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.external-watch-title-wrap {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
  font-size: 0.9rem;
  color: var(--text);
}

.external-watch-close {
  border: none;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  padding: 4px;
  border-radius: 6px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.external-watch-close:hover {
  color: var(--text);
}

.external-watch-sub {
  margin: 0;
  font-size: 0.84rem;
  color: var(--muted);
  word-break: break-word;
}

.external-watch-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

@media (max-width: 768px) {
  .external-watch-prompt {
    left: max(12px, env(safe-area-inset-left, 0px));
    right: max(12px, env(safe-area-inset-right, 0px));
    bottom: calc(74px + env(safe-area-inset-bottom, 0px));
    width: auto;
  }
}
</style>
