<template>
  <div class="history-container">
    <div class="page-header">
      <div>
        <h1 class="page-title">{{ tx('Historique de Visionnage & Téléchargements') }}</h1>
        <p class="page-sub">
          {{ tx('Retrouvez vos animés récemment visionnés et vos téléchargements passés.') }}
        </p>
      </div>

      <div style="display: flex; gap: 10px">
        <button v-if="historyItems.length > 0" class="btn btn-danger" @click="clearAllHistory">
          {{ tx("Effacer l'historique") }}
        </button>
        <button class="btn btn-primary" @click="fetchHistory">{{ tx('Actualiser') }}</button>
      </div>
    </div>

    <!-- Empty State -->
    <div v-if="!isLoading && historyItems.length === 0" class="empty-state">
      <h3>{{ tx('Aucun historique enregistré') }}</h3>
      <p>{{ tx('Vos épisodes regardés ou téléchargés apparaîtront ici.') }}</p>
      <router-link to="/" class="btn btn-primary" style="margin-top: 14px">{{
        tx("Retour à l'accueil")
      }}</router-link>
    </div>

    <!-- History List -->
    <div v-else class="history-list animate-fade-in">
      <div v-for="item in historyItems" :key="item.id" class="history-card">
        <div class="history-info">
          <strong class="history-anime">{{
            tx(item.animeName || item.animeTitle || 'Animé')
          }}</strong>
          <div class="history-meta">
            <span class="badge badge-source">{{ tx('Épisode') }} {{ tx(item.episodeNumber) }}</span>
            <span v-if="item.source" style="color: var(--muted); font-size: 13px"
              >{{ tx('Source :') }} {{ tx(item.source) }}</span
            >
            <span
              v-if="item.createdAt || item.updatedAt"
              style="color: var(--faint); font-size: 12px"
            >
              {{ tx(formatDate(item.createdAt || item.updatedAt)) }}
            </span>
          </div>
        </div>

        <div style="display: flex; gap: 8px; align-items: center">
          <span class="badge" :class="item.status === 'completed' ? 'badge-success' : ''">
            {{ tx(item.status || 'Terminé') }}
          </span>

          <button
            class="icon-button"
            :title="tx('Supprimer cette entrée')"
            :aria-label="tx('Supprimer cette entrée')"
            @click="deleteEntry(item.id)"
          >
            <Trash2 :size="16" aria-hidden="true" />
          </button>
        </div>
      </div>
    </div>

    <ConfirmDialog
      :open="clearConfirmOpen"
      :title="tx('Effacer l’historique ?')"
      :confirm-label="tx('Effacer')"
      :busy="clearingHistory"
      danger
      @cancel="clearConfirmOpen = false"
      @confirm="confirmClearAllHistory"
    >
      <p>{{ tx("Voulez-vous vraiment effacer l'ensemble de l'historique ?") }}</p>
    </ConfirmDialog>
  </div>
</template>

<script setup lang="ts">
import { Trash2 } from 'lucide-vue-next'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { language, tx } from '@/utils/locale'
import { ref, onMounted } from 'vue'
import { api } from '@/api/client'
import type { HistoryItem } from '@/types'

const historyItems = ref<HistoryItem[]>([])
const isLoading = ref(false)
const clearConfirmOpen = ref(false)
const clearingHistory = ref(false)

async function fetchHistory() {
  isLoading.value = true
  try {
    const res = await api.getHistory()
    if (Array.isArray(res)) {
      historyItems.value = res
    }
  } catch (e) {
    console.error('[HistoryView] Error fetching history:', e)
  } finally {
    isLoading.value = false
  }
}

async function deleteEntry(id?: string | number) {
  if (!id) return
  await api.deleteHistoryEntry(id)
  historyItems.value = historyItems.value.filter((h) => h.id !== id)
}

function clearAllHistory() {
  clearConfirmOpen.value = true
}

async function confirmClearAllHistory() {
  clearingHistory.value = true
  try {
    await api.clearHistory()
    historyItems.value = []
    clearConfirmOpen.value = false
  } finally {
    clearingHistory.value = false
  }
}

function formatDate(isoStr?: string): string {
  if (!isoStr) return ''
  try {
    const d = new Date(isoStr)
    return d.toLocaleDateString(language.value, {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return isoStr
  }
}

onMounted(() => {
  fetchHistory()
})
</script>

<style scoped>
.history-container {
  display: flex;
  flex-direction: column;
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.history-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  transition: all var(--transition);
}

.history-card:hover {
  border-color: var(--line-strong);
  background: var(--panel-strong);
}

.history-info {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.history-anime {
  font-size: 16px;
  font-weight: 700;
  color: var(--text);
}

.history-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80px 20px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  color: var(--muted);
  text-align: center;
}
</style>
