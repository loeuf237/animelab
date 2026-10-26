<template>
  <section v-if="available" class="settings-card-pro">
    <div class="settings-card-header-pro">
      <div>
        <h2 class="settings-card-title-pro">{{ tx('Navigateur de vérification') }}</h2>
        <p class="settings-card-subtitle-pro">
          {{ tx('Utiliser Chromium installé lorsque la WebView système est indisponible.') }}
        </p>
      </div>
    </div>
    <div class="settings-card-body-pro browser-settings">
      <label class="setting-label-pro" for="verification-chromium-path">{{
        tx('Exécutable Chromium')
      }}</label>
      <input
        id="verification-chromium-path"
        v-model="values.chromiumPath"
        class="input-premium"
        :disabled="values.managed || busy"
        :placeholder="tx('Vide : détection automatique')"
        autocomplete="off"
      />
      <p class="setting-desc-pro">
        {{
          tx(
            "Indiquez le chemin sur la machine qui exécute le moteur AnimeLab, pas sur l'appareil du navigateur distant.",
          )
        }}
      </p>
      <label class="headless-option">
        <input v-model="values.headless" type="checkbox" :disabled="values.managed || busy" />
        {{ tx('Vérification sans fenêtre') }}
      </label>
      <p class="setting-desc-pro">
        {{
          tx(
            'Le mode sans fenêtre exécute JavaScript, mais ne permet pas de répondre à un CAPTCHA interactif.',
          )
        }}
      </p>
      <p v-if="values.managed" role="status">
        {{
          tx(
            'Réglages imposés au lancement : modifiez le launcher ou les options de démarrage, puis redémarrez.',
          )
        }}
      </p>
      <button class="btn btn-secondary" :disabled="busy || values.managed" @click="save">
        {{ tx('Enregistrer le navigateur') }}
      </button>
      <p v-if="message" role="status">{{ tx(message) }}</p>
    </div>
  </section>
</template>
<script setup lang="ts">
import { ref, watch } from 'vue'
import { api } from '@/api/client'
import { tx } from '@/utils/locale'
const props = defineProps<{ active: boolean }>()
const values = ref({ chromiumPath: '', headless: false, managed: false })
const available = ref(false)
const busy = ref(false)
const message = ref('')
watch(
  () => props.active,
  async (active) => {
    if (!active) return
    try {
      values.value = await api.getVerificationBrowserSettings()
      available.value = true
    } catch {
      available.value = false
    }
  },
  { immediate: true },
)
async function save() {
  busy.value = true
  message.value = ''
  try {
    values.value = await api.saveVerificationBrowserSettings({
      chromiumPath: values.value.chromiumPath,
      headless: values.value.headless,
    })
    message.value = 'Navigateur enregistré.'
  } catch (error) {
    message.value = error instanceof Error ? error.message : 'Enregistrement impossible.'
  } finally {
    busy.value = false
  }
}
</script>
<style scoped>
.browser-settings {
  display: grid;
  gap: 12px;
  padding: 20px;
  min-width: 0;
}
.browser-settings input[type='text'],
.browser-settings .input-premium {
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
}
.headless-option {
  display: flex;
  align-items: center;
  gap: 10px;
}
</style>
