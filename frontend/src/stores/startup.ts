import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/client'
import { palette, setAppearance, themeMode } from './appearance'
import { useNotifications } from './notifications'
import { readPreference, writePreference } from '@/utils/locale'
import { applyStartupPlatform } from '@/utils/platform'
import type {
  AppPreferences,
  StartupSnapshot,
  UpdateCheck,
  UpdateInstallStatus,
} from '@/types/startup'

const BUSY_INSTALL_STATES = ['downloading', 'verifying', 'installing']
const WAITING_INSTALL_STATES = ['waiting_user', 'permission_required']

export function getUpdateApplyActionLabel(
  status: UpdateInstallStatus | null | undefined,
): string | null {
  if (!status) return null
  if (status.state === 'ready' && status.restartRequired) {
    return 'Lancer la nouvelle version'
  }
  if (status.state === 'permission_required') {
    return 'Autoriser l’installation'
  }
  if (status.state === 'waiting_user') {
    return 'Ouvrir l’installeur'
  }
  if ((status.state === 'failed' || status.state === 'cancelled') && status.filePath) {
    return 'Réessayer l’installation'
  }
  return null
}

export const useStartupStore = defineStore('startup', () => {
  const screen = ref<
    'loading' | 'update' | 'updated' | 'theme' | 'storage' | 'permissions' | 'app'
  >('loading')
  const snapshot = ref<StartupSnapshot | null>(null)
  const update = ref<UpdateCheck | null>(null)
  const installStatus = ref<UpdateInstallStatus | null>(null)
  const installing = ref(false)
  const error = ref('')
  const saving = ref(false)
  const checking = ref(false)
  let generation = 0
  let pollTimer: ReturnType<typeof setTimeout> | null = null
  function continueStartup() {
    const state = snapshot.value
    screen.value = state?.preferences.onboardingCompleted
      ? state.preferences.lastSeenVersion &&
        state.preferences.lastSeenVersion !== state.currentVersion
        ? 'updated'
        : 'app'
      : 'theme'
  }
  async function initialize() {
    const current = ++generation
    screen.value = 'loading'
    error.value = ''
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 5000)
    try {
      const state = await api.getStartup(controller.signal)
      if (current !== generation) return
      snapshot.value = state
      applyStartupPlatform(state.runtime, state.os)
      // Shared browsers keep their own appearance; a changing Android origin
      // can restore installation preferences from the engine instead.
      setAppearance(
        (readPreference('theme') ? themeMode.value : state.preferences.theme) || themeMode.value,
        (readPreference('palette') ? palette.value : state.preferences.palette) || palette.value,
      )
      if (state.preferences.checkUpdates) {
        if (!state.preferences.onboardingCompleted) {
          await checkUpdates()
          if (current !== generation) return
          if (update.value?.status === 'available') {
            screen.value = 'update'
            return
          }
        } else {
          continueStartup()
          void checkUpdates().then(() => {
            if (current === generation && update.value?.status === 'available') {
              useNotifications().notify('Une nouvelle version est disponible.', 'info', {
                label: 'Mettre à jour',
                run: () => {
                  screen.value = 'update'
                },
              })
            }
          })
          return
        }
      }
      continueStartup()
    } catch {
      if (snapshot.value === null) {
        setAppearance(themeMode.value, palette.value)
      }
      if (current === generation)
        error.value = 'Impossible de joindre le serveur. Vous pouvez réessayer ou continuer.'
    } finally {
      clearTimeout(timer)
    }
  }
  async function checkUpdates(refresh = false) {
    checking.value = true
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 14000)
    try {
      update.value = await api.checkApplicationUpdates(controller.signal, refresh)
    } catch {
      update.value = {
        status: 'offline',
        currentVersion: snapshot.value?.currentVersion || '',
        channel: snapshot.value?.preferences.updateChannel || 'beta',
        release: null,
      }
    } finally {
      clearTimeout(timer)
      checking.value = false
    }
  }
  function skipCheck() {
    generation++
    if (snapshot.value) continueStartup()
    else screen.value = 'app'
  }
  async function save(changes: Partial<AppPreferences>) {
    const prefs = await api.saveAppPreferences(changes)
    if (snapshot.value) snapshot.value.preferences = prefs
  }
  async function finish() {
    saving.value = true
    error.value = ''
    try {
      await save({
        onboardingCompleted: true,
        theme: themeMode.value,
        palette: palette.value,
        lastSeenVersion: snapshot.value?.currentVersion,
      })
      writePreference('onboarding_completed', '1')
      return true
    } catch (failure) {
      error.value = failure instanceof Error ? failure.message : String(failure)
      return false
    } finally {
      saving.value = false
    }
  }
  async function acknowledgeUpdate() {
    saving.value = true
    error.value = ''
    try {
      await save({ lastSeenVersion: snapshot.value?.currentVersion })
      screen.value = 'app'
    } catch {
      error.value = 'Impossible d’enregistrer les préférences.'
    } finally {
      saving.value = false
    }
  }
  function schedulePollIfActive(status: UpdateInstallStatus | null | undefined) {
    if (pollTimer) {
      clearTimeout(pollTimer)
      pollTimer = null
    }
    if (!status) {
      installing.value = false
      return
    }
    if (BUSY_INSTALL_STATES.includes(status.state)) {
      installing.value = true
      pollTimer = setTimeout(() => {
        void pollInstallStatus()
      }, 650)
    } else if (WAITING_INSTALL_STATES.includes(status.state)) {
      installing.value = false
      pollTimer = setTimeout(() => {
        void pollInstallStatus()
      }, 1500)
    } else {
      installing.value = false
    }
  }
  async function pollInstallStatus() {
    if (pollTimer) {
      clearTimeout(pollTimer)
      pollTimer = null
    }
    try {
      const current = await api.getUpdateInstallStatus()
      installStatus.value = current
      schedulePollIfActive(current)
    } catch {
      installing.value = false
    }
  }
  async function installUpdate(url?: string) {
    installing.value = true
    error.value = ''
    try {
      const status = await api.installApplicationUpdate(url)
      installStatus.value = status
      schedulePollIfActive(status)
    } catch (failure) {
      installing.value = false
      error.value =
        failure instanceof Error
          ? failure.message
          : 'Impossible de télécharger ou d’installer la mise à jour.'
    }
  }
  async function applyInstalledUpdate() {
    installing.value = true
    error.value = ''
    try {
      const status = await api.applyApplicationUpdate()
      installStatus.value = status
      schedulePollIfActive(status)
    } catch (failure) {
      installing.value = false
      error.value =
        failure instanceof Error ? failure.message : 'Impossible de lancer la nouvelle version.'
    }
  }
  return {
    screen,
    snapshot,
    update,
    installStatus,
    installing,
    error,
    saving,
    checking,
    initialize,
    checkUpdates,
    continueStartup,
    skipCheck,
    save,
    finish,
    acknowledgeUpdate,
    installUpdate,
    applyInstalledUpdate,
    refreshInstallStatus: pollInstallStatus,
  }
})
