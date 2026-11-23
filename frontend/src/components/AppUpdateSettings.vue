<template>
  <section class="app-update-settings">
    <h2>{{ tx('Application et mises à jour') }}</h2>
    <p>{{ tx('Version installée : {0}').replace('{0}', flow.snapshot?.currentVersion || '—') }}</p>
    <label class="update-switch"
      ><input
        type="checkbox"
        :checked="flow.snapshot?.preferences.checkUpdates ?? true"
        @change="changeAutomatic"
      />{{ tx('Vérifier les mises à jour au démarrage') }}</label
    >
    <label class="update-channel"
      >{{ tx('Canal des mises à jour')
      }}<select
        class="input-premium"
        :value="flow.snapshot?.preferences.updateChannel || 'beta'"
        @change="changeChannel"
      >
        <option value="stable">{{ tx('Stable') }}</option>
        <option value="beta">{{ tx('Bêta') }}</option>
      </select></label
    >
    <div class="update-actions">
      <button class="btn btn-primary" :disabled="flow.checking" @click="check">
        {{ tx(flow.checking ? 'Vérification…' : 'Vérifier maintenant') }}
      </button>
      <button class="btn btn-secondary" @click="flow.screen = 'theme'">
        {{ tx('Reprendre la configuration') }}
      </button>
    </div>
    <p v-if="status" role="status">{{ tx(status) }}</p>
    <div v-if="flow.update?.status === 'available'" class="update-actions" style="margin-top: 10px">
      <button
        v-if="flow.installStatus?.state === 'ready' && flow.installStatus?.restartRequired"
        class="btn btn-primary"
        :disabled="flow.installing"
        @click="flow.applyInstalledUpdate()"
      >
        {{ tx('Lancer la nouvelle version') }}
      </button>
      <button
        v-else
        class="btn btn-primary"
        :disabled="flow.installing"
        @click="flow.installUpdate()"
      >
        {{ tx(flow.installing ? 'Installation en cours…' : 'Télécharger et installer') }}
        {{ flow.update.release?.version }}
      </button>
      <button class="btn btn-secondary" @click="flow.screen = 'update'">
        {{ tx('Voir la nouvelle version') }} {{ flow.update.release?.version }}
      </button>
    </div>
    <p
      v-if="flow.installStatus && flow.installStatus.state !== 'idle'"
      role="status"
      style="margin-top: 8px"
    >
      {{ tx(flow.installStatus.message || 'Installation en cours…') }}
      <span v-if="flow.installStatus.percent > 0">({{ flow.installStatus.percent }}%)</span>
    </p>
    <p v-if="error || flow.error" role="alert">{{ tx(error || flow.error) }}</p>
  </section>
</template>
<script setup lang="ts">
import { ref } from 'vue'
import { useStartupStore } from '@/stores/startup'
import { tx } from '@/utils/locale'
const flow = useStartupStore()
const status = ref('')
const error = ref('')
async function check() {
  await flow.checkUpdates(true)
  status.value =
    flow.update?.status === 'available'
      ? 'Une nouvelle version est disponible.'
      : flow.update?.status === 'current'
        ? 'Votre version est à jour.'
        : flow.update?.status === 'empty'
          ? 'Aucune version disponible sur ce canal.'
          : 'Vérification indisponible. Réessayez plus tard.'
}
async function changeAutomatic(event: Event) {
  error.value = ''
  try {
    await flow.save({ checkUpdates: (event.target as HTMLInputElement).checked })
  } catch {
    error.value = tx('Impossible d’enregistrer les préférences.')
  }
}
async function changeChannel(event: Event) {
  error.value = ''
  try {
    await flow.save({
      updateChannel: (event.target as HTMLSelectElement).value as 'stable' | 'beta',
    })
    await check()
  } catch {
    error.value = tx('Impossible d’enregistrer les préférences.')
  }
}
</script>
<style scoped>
.app-update-settings {
  padding: 22px 24px;
  border-bottom: 1px solid var(--line);
}
@media (max-width: 768px) {
  .app-update-settings {
    padding: 14px;
  }
}
.app-update-settings h2 {
  font-size: 18px;
  margin: 0 0 12px;
  font-weight: 600;
}
.app-update-settings p {
  color: var(--muted);
  font-size: 13px;
}
.update-switch,
.update-channel {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin: 18px 0;
  font-size: 14px;
}
.update-switch input {
  accent-color: var(--accent);
}
.update-channel select {
  color: var(--text);
  background: var(--panel);
  padding: 10px;
  border: 1px solid var(--line-strong);
  border-radius: 12px;
}
.update-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.update-actions .btn {
  white-space: normal;
}
</style>
