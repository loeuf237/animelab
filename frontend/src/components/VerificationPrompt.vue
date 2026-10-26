<template>
  <section
    v-if="challenges.length"
    class="verification-prompt"
    :aria-label="tx('Accès au site bloqué')"
  >
    <strong>{{ tx('Le site demande une vérification ou bloque l’accès') }}</strong>
    <p>
      {{
        tx(
          'Ouvrez le site, effectuez la vérification si elle est proposée, puis revenez dans AnimeLab pour réessayer. Une visite manuelle ne transfère pas automatiquement les cookies à l’application.',
        )
      }}
    </p>
    <div v-for="challenge in unique" :key="challenge.domain" class="verification-actions">
      <a
        class="verification-site-link"
        :href="siteUrl(challenge)"
        target="_blank"
        rel="noopener noreferrer"
        >{{ tx('Ouvrir dans un nouvel onglet')
        }}<template v-if="currentBrowser.name"> ({{ currentBrowser.name }})</template> :
        {{ siteUrl(challenge) }}</a
      >
      <button
        class="btn btn-secondary"
        :disabled="verification.busy"
        @click="verification.retry(challenge.domain)"
      >
        {{ tx('Je suis revenu, réessayer') }}
      </button>
      <ProxyRotationButton
        :domain="challenge.domain"
        :retry="() => verification.retry(challenge.domain)"
      />
      <template v-if="verification.job?.domain === challenge.domain">
        <button
          class="btn btn-primary"
          :disabled="verification.busy"
          @click="verification.complete"
        >
          {{ tx('J’ai terminé la vérification') }}
        </button>
        <button
          class="btn btn-secondary"
          :disabled="verification.busy"
          @click="verification.cancel"
        >
          {{ tx('Fermer la fenêtre') }}
        </button>
      </template>
      <details v-else class="managed-verification">
        <summary>{{ tx('Modes de vérification disponibles') }}</summary>
        <div class="verification-actions">
          <template
            v-for="mode in verification.modes(challenge.domain).filter((m) => m.id !== 'manual')"
            :key="mode.id"
          >
            <div class="verification-mode">
              <strong>{{
                tx(
                  mode.id === 'browser'
                    ? 'Navigateur installé sur le serveur'
                    : 'WebView de l’application',
                )
              }}</strong>
              <span v-if="!mode.available">{{ tx(modeReason(mode.reason)) }}</span>
              <template v-else>
                <select
                  v-if="mode.id === 'browser'"
                  v-model="verification.browser"
                  :aria-label="tx('Navigateur installé pour la vérification')"
                >
                  <option v-for="item in verification.browsers" :key="item.name" :value="item.name">
                    {{ item.name }}
                  </option>
                </select>
                <button
                  class="btn btn-primary"
                  :disabled="verification.busy || !!verification.job"
                  @click="
                    verification.start(
                      challenge.domain,
                      mode.id === 'webview' ? 'webview' : 'browser',
                    )
                  "
                >
                  {{
                    tx(
                      mode.headless
                        ? 'Démarrer la vérification sans fenêtre'
                        : 'Ouvrir une fenêtre de vérification',
                    )
                  }}
                </button>
              </template>
            </div>
          </template>
        </div>
      </details>
    </div>

    <p v-if="verification.error" role="alert">{{ tx(verification.error) }}</p>
    <p v-if="verification.job && !unique.some((c) => c.domain === verification.job?.domain)">
      {{ tx('Une vérification est déjà ouverte pour') }} {{ tx(verification.job.domain) }}.
      <button class="btn btn-secondary" :disabled="verification.busy" @click="verification.cancel">
        {{ tx('Fermer cette vérification') }}
      </button>
    </p>
  </section>
</template>
<script setup lang="ts">
import { tx } from '@/utils/locale'
import { computed, onMounted } from 'vue'
import { useVerificationStore } from '@/stores/verification'
import type { VerificationCapability } from '@/types/api'
import type { SourceChallenge } from '@/types'
import ProxyRotationButton from './ProxyRotationButton.vue'
import { detectBrowser } from '@/utils/browser'
const currentBrowser = detectBrowser(navigator.userAgent)
const props = defineProps<{ challenges: SourceChallenge[] }>()
const verification = useVerificationStore()
function modeReason(reason: VerificationCapability['reason']) {
  const reasons = {
    client_remote:
      'Cette fenêtre doit être ouverte depuis la machine du serveur. Utilisez le lien manuel depuis ce client.',
    android_webview: 'Sur Android, utilisez la WebView de l’application.',
    no_display: 'Le serveur ne dispose pas d’une session graphique.',
    no_browser: 'Aucun navigateur compatible détecté sur la machine du serveur.',
    authenticated_proxy:
      'La capture de cookies ne prend pas en charge les proxys avec authentification.',
    no_webview: 'La WebView est disponible dans l’application native.',
    webview_proxy:
      'La WebView ne peut pas utiliser le proxy de cette source. Choisissez un autre mode.',
  }
  return reason ? reasons[reason] : ''
}
function siteUrl(challenge: SourceChallenge) {
  try {
    const url = new URL(challenge.url || `https://${challenge.domain}/`)
    if (
      ['http:', 'https:'].includes(url.protocol) &&
      url.hostname === challenge.domain &&
      !url.username &&
      !url.password
    )
      return url.href
  } catch {
    /* Use the known source domain. */
  }
  return `https://${challenge.domain}/`
}
const unique = computed(() =>
  props.challenges.filter((c, i, all) => all.findIndex((x) => x.domain === c.domain) === i),
)
onMounted(() => {
  void verification.refresh()
})
</script>
<style scoped>
.verification-prompt {
  padding: 16px;
  border: 1px solid var(--yellow, #d9a441);
  border-radius: var(--radius, 12px);
  background: var(--panel);
}
.verification-prompt p {
  margin: 10px 0;
  color: var(--muted);
  line-height: 1.5;
}
.verification-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 12px;
}
.verification-site-link {
  width: 100%;
  overflow-wrap: anywhere;
}
.verification-actions select {
  max-width: 200px;
}
.managed-verification {
  width: 100%;
  color: var(--muted);
}
.verification-mode {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 100%;
}
.managed-verification summary {
  cursor: pointer;
}
</style>
