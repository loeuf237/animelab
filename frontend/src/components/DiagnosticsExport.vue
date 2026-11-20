<template>
  <section class="settings-card-pro diagnostics-card">
    <h2>{{ tx('Diagnostics') }}</h2>
    <p>
      {{
        tx(
          'Exportez les événements récents et les durées des opérations pour comprendre un problème. Les cookies, mots de passe et adresses vidéo ne sont pas inclus.',
        )
      }}
    </p>
    <div class="diagnostics-actions">
      <button type="button" class="btn btn-primary" :disabled="busy" @click="download">
        <Download :size="15" aria-hidden="true" />
        <span>{{ tx(busy ? 'Export en cours…' : 'Exporter les diagnostics') }}</span>
      </button>
      <button type="button" class="btn btn-secondary" :disabled="busy" @click="copySummary">
        <Copy :size="15" aria-hidden="true" />
        <span>{{ tx('Copier le résumé') }}</span>
      </button>
      <a
        class="btn btn-secondary diagnostics-report-link"
        href="https://github.com/loeuf237/animelab/issues/new/choose"
        target="_blank"
        rel="noopener noreferrer"
      >
        <Bug :size="15" aria-hidden="true" />
        <span>{{ tx('Signaler un bug') }}</span>
      </a>
    </div>
    <p v-if="message" role="status" class="diagnostics-status">{{ message }}</p>
  </section>
</template>
<script setup lang="ts">
import { ref } from 'vue'
import { Bug, Copy, Download } from 'lucide-vue-next'
import { api } from '@/api/client'
import { tx } from '@/utils/locale'
import { exportNativeDiagnostics, platformOs, platformRuntime } from '@/utils/platform'

const busy = ref(false),
  message = ref('')

async function download() {
  busy.value = true
  message.value = ''
  let url: string | null = null
  try {
    const report = await api.getDiagnostics()
    const payload = JSON.stringify(report, null, 2)
    const nativePath = exportNativeDiagnostics(payload)
    if (nativePath) {
      message.value = tx('Diagnostics enregistrés dans {0}.').replace('{0}', nativePath)
      return
    }
    url = URL.createObjectURL(new Blob([payload], { type: 'application/json' }))
    const link = document.createElement('a')
    link.href = url
    link.download = 'animelab-diagnostics.json'
    document.body.appendChild(link)
    link.click()
    link.remove()
    message.value = tx('Diagnostics exportés.')
  } catch {
    message.value = tx(
      'Impossible d’exporter les diagnostics. Ouvrez AnimeLab sur l’appareil qui exécute le serveur.',
    )
  } finally {
    busy.value = false
    if (url) setTimeout(() => URL.revokeObjectURL(url!), 1000)
  }
}

async function copySummary() {
  busy.value = true
  message.value = ''
  try {
    const report = await api.getDiagnostics()
    const events = Array.isArray(report.events) ? report.events : []
    const lastCrash =
      report.lastCrash && typeof report.lastCrash === 'object' ? report.lastCrash : null
    const summaryLines = [
      `AnimeLab ${String(report.applicationVersion || '?')} (${platformRuntime.value}/${platformOs.value})`,
      `Erreurs récentes : ${String(report.recentErrorCount ?? 0)}`,
      `Événements : ${events.length}`,
      lastCrash
        ? `Dernier incident : ${String((lastCrash as Record<string, unknown>).kind || '')} — ${String((lastCrash as Record<string, unknown>).exception || '')}`
        : 'Dernier incident : aucun',
    ]
    await navigator.clipboard.writeText(summaryLines.join('\n'))
    message.value = tx('Résumé copié dans le presse-papiers.')
  } catch {
    message.value = tx('Impossible de copier le résumé.')
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.diagnostics-card {
  padding: 24px;
}
.diagnostics-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  margin-top: 12px;
}
.diagnostics-report-link {
  text-decoration: none;
}
.diagnostics-status {
  margin-top: 12px;
  font-size: 0.9rem;
  color: var(--muted);
}
@media (max-width: 768px) {
  .diagnostics-card {
    padding: 14px;
  }
}
</style>
