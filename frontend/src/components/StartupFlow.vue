<template>
  <div v-if="flow.screen !== 'app'" class="startup-page">
    <aside class="startup-intro" aria-hidden="true">
      <img :src="brandIcon" alt="" />
      <span class="intro-eyebrow">ANIMELAB</span>
      <h2>{{ tx('Votre bibliothèque. Votre rythme.') }}</h2>
      <p>{{ tx('Un espace pour vos séries, vos téléchargements et vos prochains épisodes.') }}</p>
      <span class="intro-caption">{{ tx('Android · Ordinateur · Navigateur') }}</span>
    </aside>
    <section
      class="setup-window"
      :aria-label="tx('Configuration d’AnimeLab')"
      :aria-busy="flow.saving"
    >
      <header class="setup-top">
        <button
          v-if="canGoBack"
          class="setup-back"
          type="button"
          :aria-label="tx('Retour')"
          @click="back"
        >
          <ArrowLeft />
        </button>
        <span v-else class="setup-wordmark">AnimeLab</span>
        <span v-if="stepIndex >= 0" class="setup-step-label">{{
          tx('Étape {0} sur {1}')
            .replace('{0}', String(stepIndex + 1))
            .replace('{1}', String(steps.length))
        }}</span>
        <span v-else class="setup-step-label">{{ flow.snapshot?.currentVersion }}</span>
      </header>
      <main class="setup-content" id="setup-content" tabindex="-1">
        <template v-if="flow.screen === 'loading'">
          <RefreshCw class="setup-hero-icon checking-icon" aria-hidden="true" />
          <h1>{{ tx('Un instant…') }}</h1>
          <p class="setup-description" role="status">
            {{
              tx(
                flow.checking
                  ? 'Recherche d’une nouvelle version…'
                  : 'Préparation de votre espace…',
              )
            }}
          </p>
          <div class="setup-card">
            <p>
              {{
                tx(
                  'La vérification ne télécharge que les informations de version. Aucun fichier d’installation n’est téléchargé sans votre accord.',
                )
              }}
            </p>
          </div>
        </template>
        <template v-else-if="flow.screen === 'update' || flow.screen === 'updated'">
          <BadgeInfo class="setup-hero-icon" aria-hidden="true" />
          <h1>
            {{
              flow.screen === 'update'
                ? tx('Nouvelle version disponible !')
                : tx('Version {0} installée').replace('{0}', flow.snapshot?.currentVersion || '')
            }}
          </h1>
          <p class="setup-description">
            {{ displayRelease?.version }}
            <span class="release-chip">{{
              tx(
                flow.snapshot?.preferences.updateChannel === 'beta' ? 'Canal bêta' : 'Canal stable',
              )
            }}</span>
          </p>
          <div class="release-notes">
            <h2>AnimeLab {{ displayRelease?.version }}</h2>
            <p
              v-for="(line, index) in releaseNotes"
              :key="index"
              :class="{ 'note-heading': line.heading, 'note-item': line.item }"
            >
              {{ line.text }}
            </p>
            <a
              v-if="displayRelease"
              class="setup-text-link"
              :href="displayRelease.url"
              target="_blank"
              rel="noopener noreferrer"
              >{{ tx('Voir les nouveautés') }} <ExternalLink
            /></a>
          </div>
          <label v-if="flow.screen === 'update' && downloadLinks.length > 1" class="setup-field"
            >{{ tx('Choisir un téléchargement')
            }}<select v-model="selectedAsset">
              <option v-for="asset in downloadLinks" :key="asset.url" :value="asset.url">
                {{ asset.label }}
              </option>
            </select></label
          >
          <p v-if="flow.screen === 'update'" class="setup-fine-print">
            {{
              tx(
                'Téléchargez la version, puis suivez les étapes d’installation de votre système. Votre bibliothèque est conservée.',
              )
            }}
          </p>
        </template>
        <template v-else>
          <Rocket class="setup-hero-icon" aria-hidden="true" />
          <h1>{{ tx('Bienvenue !') }}</h1>
          <p class="setup-description">
            {{
              tx(
                'Commençons par quelques réglages. Vous pourrez les modifier plus tard dans les paramètres.',
              )
            }}
          </p>
          <div v-if="flow.screen === 'theme'" class="setup-card appearance-card">
            <h2>{{ tx('À votre image') }}</h2>
            <ThemePicker />
            <label class="setup-field language-field"
              >{{ tx('Langue de l’interface')
              }}<select :value="i18n.currentLang" @change="changeLanguage">
                <option value="fr">Français</option>
                <option value="en">English</option>
              </select></label
            >
          </div>
          <div v-else-if="flow.screen === 'storage'" class="setup-card">
            <FolderOpen class="setup-card-icon" aria-hidden="true" />
            <h2>{{ tx('Un dossier pour vos épisodes') }}</h2>
            <p>
              {{
                tx(
                  native?.android
                    ? 'Choisissez où enregistrer vos vidéos terminées et leurs sous-titres. Un dossier dédié est recommandé.'
                    : 'Choisissez le dossier où le moteur AnimeLab enregistrera vos téléchargements.',
                )
              }}
            </p>
            <div class="chosen-folder">
              <Folder /><span>{{ native?.android ? native.destination : directory }}</span
              ><Check v-if="storageReady" />
            </div>
            <template v-if="native?.android">
              <button
                class="setup-primary"
                :disabled="busy || native.selectionPending"
                @click="nativeAction('choose_directory')"
              >
                {{
                  tx(native.selectionPending ? 'Sélection en cours…' : 'Sélectionner un dossier')
                }}
              </button>
              <button
                class="setup-outlined"
                :disabled="busy || native.selectionPending"
                @click="nativeAction('use_downloads')"
              >
                {{ tx('Utiliser Downloads/AnimeLab') }}
              </button>
              <p v-if="native.selectionPending" role="status">
                {{
                  tx('Choisissez un sous-dossier dans la fenêtre Android, puis confirmez l’accès.')
                }}
              </p>
            </template>
            <template v-else-if="flow.snapshot?.storageEditable">
              <label class="setup-field"
                >{{ tx('Dossier des téléchargements')
                }}<input
                  v-model="directory"
                  type="text"
                  autocomplete="off"
                  spellcheck="false"
                  @input="storageConfirmed = false"
              /></label>
              <button
                v-if="hasNativePicker"
                class="setup-outlined"
                :disabled="busy"
                @click="chooseDesktopDirectory"
              >
                {{ tx('Sélectionner un dossier') }}
              </button>
              <button class="setup-primary" :disabled="busy" @click="confirmDirectory">
                {{ tx('Utiliser ce dossier') }}
              </button>
            </template>
            <template v-else>
              <p>
                {{
                  tx(
                    'Le stockage est géré par le serveur. Ce navigateur ne peut pas choisir un dossier sur la machine distante.',
                  )
                }}
              </p>
              <button class="setup-primary" @click="storageConfirmed = true">
                {{ tx('Utiliser le dossier du serveur') }}
              </button>
            </template>
            <details class="storage-guide">
              <summary>{{ tx('Guide du stockage') }}</summary>
              <p>
                {{
                  tx(
                    'Sur Android, choisissez un sous-dossier comme Documents/AnimeLab ou une carte SD. Certaines racines sont interdites par Android. La bibliothèque et les fichiers en cours restent privés ; les vidéos terminées sont exportées dans le dossier choisi.',
                  )
                }}
              </p>
              <p>{{ tx('Changer de dossier ne déplace ni ne supprime vos anciens fichiers.') }}</p>
            </details>
            <p v-if="native?.error" role="alert">{{ tx(native.error) }}</p>
          </div>
          <div v-else-if="flow.screen === 'permissions'" class="setup-card permission-card">
            <div v-for="permission in permissions" :key="permission.action" class="permission-row">
              <component :is="permission.icon" aria-hidden="true" />
              <div>
                <h2>{{ tx(permission.title) }}</h2>
                <p>{{ tx(permission.description) }}</p>
              </div>
              <span v-if="permission.granted" class="permission-granted"
                ><Check />{{ tx('Autorisé') }}</span
              >
              <button
                v-else
                class="setup-grant"
                :disabled="busy"
                @click="nativeAction(permission.action)"
              >
                {{ tx('Autoriser') }}
              </button>
            </div>
            <p class="setup-fine-print">
              {{
                tx(
                  'Ces autorisations sont facultatives. Vous pourrez les accorder plus tard selon vos besoins.',
                )
              }}
            </p>
          </div>
        </template>
        <p v-if="error || flow.error" class="setup-error" role="alert">
          {{ tx(error || flow.error) }}
        </p>
        <p
          v-if="flow.screen === 'theme' && flow.update?.status === 'offline'"
          class="setup-fine-print"
          role="status"
        >
          {{ tx('Vérification des mises à jour indisponible. Vous pouvez continuer hors ligne.') }}
        </p>
      </main>
      <footer class="setup-footer">
        <template v-if="flow.screen === 'loading'">
          <button v-if="flow.error" class="setup-primary" @click="flow.initialize()">
            {{ tx('Réessayer') }}
          </button>
          <button class="setup-outlined" @click="flow.skipCheck()">
            {{ tx('Continuer sans vérifier') }}
          </button>
        </template>
        <template v-else-if="flow.screen === 'updated'">
          <button class="setup-primary" :disabled="flow.saving" @click="flow.acknowledgeUpdate()">
            {{ tx('Continuer') }}
          </button>
        </template>
        <template v-else-if="flow.screen === 'update'">
          <a
            class="setup-primary"
            :href="selectedAsset || flow.update?.release?.url"
            target="_blank"
            rel="noopener noreferrer"
            @click="downloadStarted = true"
            ><Download />{{ tx('Télécharger') }}</a
          >
          <button class="setup-outlined" @click="flow.continueStartup()">
            {{ tx(downloadStarted ? 'Continuer la configuration' : 'Pas maintenant') }}
          </button>
        </template>
        <template v-else>
          <div class="setup-dots" aria-hidden="true">
            <i
              v-for="(step, index) in steps"
              :key="step"
              :class="{ active: index === stepIndex, complete: index < stepIndex }"
            ></i>
          </div>
          <button
            class="setup-primary"
            :disabled="busy || flow.saving || (flow.screen === 'storage' && !storageReady)"
            @click="next"
          >
            {{ tx(flow.saving ? 'Enregistrement…' : isLastStep ? 'Commencer' : 'Suivant')
            }}<ArrowRight v-if="!isLastStep" />
          </button>
        </template>
      </footer>
    </section>
  </div>
</template>
<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  ArrowLeft,
  ArrowRight,
  BadgeInfo,
  BatteryCharging,
  Bell,
  Check,
  Download,
  ExternalLink,
  Folder,
  FolderOpen,
  PackageOpen,
  RefreshCw,
  Rocket,
} from 'lucide-vue-next'
import brandIcon from '@/assets/brand-icon.png'
import ThemePicker from './ThemePicker.vue'
import { useStartupStore } from '@/stores/startup'
import { useI18nStore } from '@/stores/i18n'
import { api, type AndroidStorageState } from '@/api/client'
import { tx } from '@/utils/locale'
const flow = useStartupStore()
const i18n = useI18nStore()
const router = useRouter()
const native = ref<AndroidStorageState | null>(null)
const directory = ref('')
const storageConfirmed = ref(false)
const busy = ref(false)
const error = ref('')
const downloadStarted = ref(false)
const selectedAsset = ref('')
type PickerWindow = Window & {
  pywebview?: { api?: { choose_download_directory?: () => Promise<string | null> } }
}
const hasNativePicker = ref(false)
const steps = computed(() =>
  native.value?.android ? ['theme', 'storage', 'permissions'] : ['theme', 'storage'],
)
const stepIndex = computed(() => steps.value.indexOf(flow.screen))
const canGoBack = computed(() => stepIndex.value > 0)
const isLastStep = computed(() => stepIndex.value === steps.value.length - 1)
const storageReady = computed(() =>
  native.value?.android
    ? native.value.authorized &&
      !native.value.selectionPending &&
      (native.value.storageChosen || storageConfirmed.value)
    : storageConfirmed.value,
)
const permissions = computed(() => [
  {
    action: 'install_apps',
    title: 'Installation des extensions',
    description: 'Pour installer les extensions APK depuis AnimeLab.',
    icon: PackageOpen,
    granted: native.value?.installAppsGranted,
  },
  {
    action: 'notifications',
    title: 'Notifications',
    description: 'Pour suivre vos téléchargements et les nouveaux épisodes.',
    icon: Bell,
    granted: native.value?.notificationsGranted,
  },
  {
    action: 'battery',
    title: 'Activité en arrière-plan',
    description:
      'Pour limiter les interruptions pendant les longs téléchargements et les mises à jour de la bibliothèque.',
    icon: BatteryCharging,
    granted: native.value?.batteryUnrestricted,
  },
])
const downloadLinks = computed(() => {
  const assets = flow.update?.release?.assets || []
  if (flow.snapshot?.runtime === 'android')
    return assets.filter((a) => a.name.toLowerCase().endsWith('.apk'))
  if (flow.snapshot?.runtime !== 'desktop') return assets
  const os = flow.snapshot.os
  const arch = flow.snapshot.architecture
  return assets.filter((a) => {
    const name = a.name.toLowerCase()
    if (os === 'windows') return name.includes('windows')
    if (os === 'darwin')
      return name.includes('macos') && (arch === 'arm64') === name.includes('arm64')
    return name.includes('linux')
  })
})
const displayRelease = computed(() => {
  const release = flow.update?.release
  if (
    flow.screen === 'updated' &&
    release?.version.replace(/^(?:android-)?v/, '') !==
      flow.snapshot?.currentVersion.replace(/^(?:android-)?v/, '')
  )
    return null
  return release
})
const releaseNotes = computed(() =>
  (displayRelease.value?.notes || tx('Consultez la page de version pour découvrir les nouveautés.'))
    .split('\n')
    .filter(Boolean)
    .slice(0, 140)
    .map((line) => ({
      heading: /^#{1,6}\s/.test(line),
      item: /^[-*]\s/.test(line),
      text: line.replace(/^#{1,6}\s+|^[-*]\s+/g, '').replace(/\*\*/g, ''),
    })),
)
watch(downloadLinks, (assets) => {
  selectedAsset.value = assets[0]?.url || ''
})
watch(
  () => flow.snapshot,
  (state) => {
    if (state) {
      native.value = state.native
      directory.value = state.downloadDirectory
    }
  },
)
watch(
  () => flow.screen,
  async () => {
    error.value = ''
    await nextTick()
    document.getElementById('setup-content')?.focus()
  },
)
function back() {
  flow.screen = steps.value[stepIndex.value - 1] as 'theme' | 'storage'
}
async function next() {
  if (isLastStep.value) {
    if (await flow.finish()) {
      await router.replace('/library')
      flow.screen = 'app'
    }
  } else flow.screen = steps.value[stepIndex.value + 1] as 'storage' | 'permissions'
}
async function changeLanguage(event: Event) {
  await i18n.changeLanguage((event.target as HTMLSelectElement).value as 'fr' | 'en')
}
let refreshingNative = false
async function refreshNative() {
  if (!native.value?.android || !['storage', 'permissions'].includes(flow.screen)) return
  if (refreshingNative) return
  refreshingNative = true
  try {
    native.value = await api.getAndroidStorage()
  } catch {
    /* The next user action reports transport errors. */
  } finally {
    refreshingNative = false
  }
}
async function nativeAction(action: string) {
  busy.value = true
  error.value = ''
  try {
    native.value = await api.androidStorageAction(action)
    if (action === 'use_downloads') storageConfirmed.value = true
  } catch (failure) {
    error.value = failure instanceof Error ? failure.message : String(failure)
  } finally {
    busy.value = false
  }
}
async function confirmDirectory() {
  busy.value = true
  error.value = ''
  try {
    directory.value = (await api.saveDownloadDirectory(directory.value)).downloadDirectory
    storageConfirmed.value = true
  } catch (failure) {
    error.value = failure instanceof Error ? failure.message : String(failure)
  } finally {
    busy.value = false
  }
}
async function chooseDesktopDirectory() {
  error.value = ''
  try {
    const selected = await (window as PickerWindow).pywebview?.api?.choose_download_directory?.()
    if (selected) {
      directory.value = selected
      storageConfirmed.value = false
      await confirmDirectory()
    }
  } catch (failure) {
    error.value = failure instanceof Error ? failure.message : String(failure)
  }
}
function pickerReady() {
  hasNativePicker.value = !!(window as PickerWindow).pywebview?.api?.choose_download_directory
}
let timer: ReturnType<typeof setInterval> | undefined
onMounted(() => {
  void flow.initialize()
  pickerReady()
  window.addEventListener('pywebviewready', pickerReady)
  window.addEventListener('focus', refreshNative)
  timer = setInterval(refreshNative, 2500)
})
onUnmounted(() => {
  if (timer) clearInterval(timer)
  window.removeEventListener('focus', refreshNative)
  window.removeEventListener('pywebviewready', pickerReady)
})
</script>
<style scoped src="./startup-flow.css"></style>
