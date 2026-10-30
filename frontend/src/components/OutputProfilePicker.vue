<template>
  <div class="output-profile">
    <label class="output-profile-choice">
      <span>{{ tx('Format de sortie') }}</span>
      <select class="input-premium" :value="modelValue?.mode || ''" @change="change">
        <option value="">{{ tx('Selon le choix de sous-titres') }}</option>
        <option
          v-for="profile in profiles"
          :key="profile.mode"
          :value="profile.mode"
          :disabled="!profile.available"
          :title="tx(profile.reason)"
        >
          {{ tx(labels[profile.mode]) }}{{ profile.available ? '' : ` — ${tx(profile.reason)}` }}
        </option>
      </select>
    </label>
    <label v-if="modelValue && modelValue.mode !== 'ORIGINAL'" class="output-retention">
      <input type="checkbox" :checked="modelValue.keepOriginals" @change="retention" />
      <span>{{ tx('Conserver les originaux et la copie de travail') }}</span>
    </label>
    <small v-if="error" role="status">{{ error }}</small>
    <small v-if="modelValue?.mode === 'MP4_HARD'">{{
      tx('Réencodage complet ; une interruption recommence la conversion.')
    }}</small>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '@/api/client'
import type { OutputProfile, OutputProfileCapability } from '@/types'
import { tx } from '@/utils/locale'

const props = defineProps<{ modelValue?: OutputProfile }>()
const emit = defineEmits<{ 'update:modelValue': [value: OutputProfile | undefined] }>()
const profiles = ref<OutputProfileCapability[]>([])
const error = ref('')
const labels = {
  ORIGINAL: 'Vidéo originale',
  SIDECAR: 'Sous-titres séparés',
  MKV_SOFT: 'MKV avec sous-titres',
  MP4_HARD: 'MP4 avec sous-titres incrustés',
}
onMounted(async () => {
  try {
    profiles.value = await api.getOutputProfiles()
  } catch {
    error.value = tx('Les formats disponibles ne peuvent pas être vérifiés pour le moment.')
  }
})
function change(event: Event) {
  const mode = (event.target as HTMLSelectElement).value
  const profile = profiles.value.find((item) => item.mode === mode && item.available)
  emit(
    'update:modelValue',
    profile
      ? { version: 1, mode: profile.mode, keepOriginals: props.modelValue?.keepOriginals ?? false }
      : undefined,
  )
}
function retention(event: Event) {
  if (props.modelValue) {
    emit('update:modelValue', {
      ...props.modelValue,
      keepOriginals: (event.target as HTMLInputElement).checked,
    })
  }
}
</script>

<style scoped>
.output-profile,
.output-profile-choice {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 4px;
  width: 240px;
  min-width: 0;
  max-width: 100%;
  font-size: 12px;
}
.output-retention {
  display: flex;
  align-items: center;
  gap: 6px;
}
.output-profile select {
  width: 100%;
  min-width: 0;
  max-width: 100%;
  min-height: 36px;
}
</style>
