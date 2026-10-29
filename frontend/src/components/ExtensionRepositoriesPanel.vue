<template>
  <section v-if="repositories.length" class="repositories">
    <h2>{{ tx('Dépôts d’extensions') }}</h2>
    <p>{{ tx('Les dépôts coexistent. Les désactiver ne désinstalle pas leurs extensions.') }}</p>
    <article v-for="repository in repositories" :key="repository.id">
      <label>
        <input
          type="checkbox"
          :checked="!!repository.is_active"
          :disabled="busy"
          @change="toggle(repository.id, ($event.target as HTMLInputElement).checked)"
        />
        {{ repository.name }}
      </label>
      <p>{{ repository.url }}</p>
      <p v-if="repository.last_error" role="alert">
        {{ tx('Le dernier rafraîchissement a échoué :') }} {{ repository.last_error }}
      </p>
      <div v-if="repository.pending_signing_key">
        <p>
          {{ tx('Le signataire annoncé a changé. Les nouvelles installations sont suspendues.') }}
        </p>
        <p>{{ repository.signing_key }} → {{ repository.pending_signing_key }}</p>
        <button class="btn btn-secondary" :disabled="busy" @click="approve(repository)">
          {{ tx('Examiner et approuver la nouvelle clé') }}
        </button>
      </div>
    </article>
    <p v-if="error" role="alert">{{ error }}</p>
  </section>
</template>
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '@/api/client'
import { tx } from '@/utils/locale'
import type { ExtensionRepository } from '@/types/api'
const emit = defineEmits<{ changed: [] }>()
const repositories = ref<ExtensionRepository[]>([])
const busy = ref(false),
  error = ref('')
async function reload() {
  repositories.value = (await api.extensionRepositories()).repositories.filter((r) =>
    /^https?:/.test(r.url),
  )
}
async function toggle(id: number, enabled: boolean) {
  busy.value = true
  error.value = ''
  try {
    await api.setExtensionRepository(id, enabled)
    await reload()
    emit('changed')
  } catch (failure) {
    error.value = failure instanceof Error ? failure.message : tx('Échec de l’opération.')
  } finally {
    busy.value = false
  }
}
async function approve(repository: ExtensionRepository) {
  const key = repository.pending_signing_key
  if (
    !key ||
    !window.confirm(
      `${tx('Approuver ce changement de signataire du dépôt ?')}\n${repository.name}\n${repository.signing_key}\n→ ${key}`,
    )
  )
    return
  busy.value = true
  try {
    await api.approveExtensionRepositoryKey(repository.id, key)
    await reload()
    emit('changed')
  } catch (failure) {
    error.value = failure instanceof Error ? failure.message : tx('Échec de l’opération.')
  } finally {
    busy.value = false
  }
}
onMounted(() => {
  void reload().catch(() => {
    repositories.value = []
  })
})
defineExpose({ reload })
</script>
<style scoped>
.repositories {
  border: 1px solid var(--border-color, #666);
  border-radius: 14px;
  padding: 1.25rem;
  margin-bottom: 1.5rem;
}
article {
  padding: 0.75rem 0;
  border-top: 1px solid var(--border-color, #666);
}
p {
  overflow-wrap: anywhere;
}
</style>
