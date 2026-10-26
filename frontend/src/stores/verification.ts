import { defineStore } from 'pinia'
import { ref, watch, onScopeDispose } from 'vue'
import { api, ApiError } from '@/api/client'
import type { NetworkSession, NetworkOptions, VerificationMode, VerificationJob } from '@/types/api'
import type { SourceChallenge } from '@/types'
import { detectBrowser } from '@/utils/browser'

export function challengeFromError(error: unknown): SourceChallenge | null {
  if (
    error instanceof ApiError &&
    error.data?.code === 'verification_required' &&
    error.data.domain
  )
    return {
      domain: error.data.domain,
      url: error.data.url,
      code: error.data.code,
      error: error.data.error || error.message,
    }
  return null
}

export const useVerificationStore = defineStore('verification', () => {
  const sessions = ref<NetworkSession[]>([])
  const browsers = ref<{ name: string }[]>([])
  const webviewAvailable = ref(false)
  const browser = ref('')
  const options = ref<NetworkOptions | null>(null)
  function modes(domain: string) {
    return sessions.value.find((s) => s.domain === domain)?.modes || options.value?.modes || []
  }
  const job = ref<VerificationJob | null>(null)
  const busy = ref(false)
  const error = ref('')
  const notice = ref('')
  const pending = new Map<string, { domains: Set<string>; retry: () => Promise<void> }>()
  let refreshing: Promise<void> | null = null

  function waitForVerification(
    key: string,
    challenges: Pick<SourceChallenge, 'domain'>[],
    retry: () => Promise<void>,
  ) {
    if (challenges.length)
      pending.set(key, { domains: new Set(challenges.map((c) => c.domain)), retry })
    else pending.delete(key)
    if (challenges.length) void refresh()
  }
  function clearPending(key: string) {
    pending.delete(key)
  }
  async function refresh() {
    if (refreshing) return refreshing
    refreshing = (async () => {
      try {
        const result = await api.getNetworkSessions()
        options.value = result
        sessions.value = result.sessions
        browsers.value = result.browsers
        webviewAvailable.value = result.webviewAvailable
        if (!browsers.value.some((b) => b.name === browser.value)) {
          const hint = detectBrowser(navigator.userAgent).installedHint
          browser.value =
            (hint ? browsers.value.find((b) => b.name.toLowerCase().includes(hint)) : null)?.name ||
            browsers.value[0]?.name ||
            ''
        }
      } catch {
        /* Retry on the next poll if the server is restarting. */
      }
    })()
    try {
      await refreshing
    } finally {
      refreshing = null
    }
  }
  async function start(domain: string, mode: VerificationMode = 'browser') {
    if (busy.value || job.value) return
    busy.value = true
    error.value = ''
    notice.value = ''
    try {
      job.value = await api.startNetworkVerification(domain, browser.value, mode)
    } catch (exc) {
      error.value = exc instanceof Error ? exc.message : 'Impossible d’ouvrir la vérification.'
    } finally {
      busy.value = false
    }
  }
  let timer: ReturnType<typeof setTimeout> | null = null
  async function verified(result: { domain: string; resumed?: number }) {
    job.value = null
    const retries = [...pending.entries()].filter(([, request]) =>
      request.domains.has(result.domain),
    )
    for (const [key] of retries) pending.delete(key)
    await Promise.allSettled(retries.map(([, request]) => request.retry()))
    notice.value = retries.length
      ? 'Accès vérifié. La recherche ou le catalogue a été actualisé.'
      : `Accès vérifié. ${result.resumed || 0} téléchargement(s) repris.`
    await refresh()
  }
  async function poll(id: string) {
    if (job.value?.id !== id) return
    if (!busy.value) {
      try {
        const result = await api.getVerificationStatus(id)
        if (job.value?.id !== id) return
        if (result.status === 'completed') {
          busy.value = true
          try {
            await verified(result)
          } finally {
            busy.value = false
          }
          return
        }
      } catch (exc) {
        if (exc instanceof ApiError && exc.status === 404 && job.value?.id === id) job.value = null
      }
    }
    if (job.value?.id === id)
      timer = setTimeout(() => {
        void poll(id)
      }, 2000)
  }
  watch(job, (value) => {
    if (timer) clearTimeout(timer)
    timer = value
      ? setTimeout(() => {
          void poll(value.id)
        }, 1000)
      : null
  })
  onScopeDispose(() => {
    if (timer) clearTimeout(timer)
  })
  async function complete() {
    if (!job.value || busy.value) return
    busy.value = true
    error.value = ''
    try {
      const result = await api.completeNetworkVerification(job.value.id)
      await verified(result)
    } catch (exc) {
      error.value = exc instanceof Error ? exc.message : 'Le site demande encore une vérification.'
      if (
        exc instanceof ApiError &&
        exc.status === 400 &&
        /expir|introuvable|fermé/.test(exc.message)
      )
        job.value = null
    } finally {
      busy.value = false
    }
  }
  async function retry(domain: string) {
    if (busy.value) return
    busy.value = true
    error.value = ''
    try {
      await api.recheckNetworkSource(domain)
      const retries = [...pending.entries()].filter(([, request]) => request.domains.has(domain))
      for (const [key] of retries) pending.delete(key)
      await Promise.allSettled(retries.map(([, request]) => request.retry()))
      await refresh()
    } catch (exc) {
      error.value = exc instanceof Error ? exc.message : 'Le site demande encore une vérification.'
    } finally {
      busy.value = false
    }
  }
  async function cancel() {
    if (!job.value || busy.value) return
    busy.value = true
    try {
      await api.cancelNetworkVerification(job.value.id)
      job.value = null
      error.value = ''
    } catch (exc) {
      error.value = exc instanceof Error ? exc.message : 'Impossible de fermer la vérification.'
    } finally {
      busy.value = false
    }
  }
  return {
    options,
    modes,
    sessions,
    browsers,
    browser,
    job,
    busy,
    error,
    notice,
    webviewAvailable,
    waitForVerification,
    clearPending,
    refresh,
    start,
    complete,
    cancel,
    retry,
  }
})
