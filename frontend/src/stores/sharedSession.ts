import { ref } from 'vue'

export interface SharedUser {
  id: string
  username: string
  admin: boolean
  enabled: boolean
  permissions: string[]
}

export const sharedUser = ref<SharedUser | null>(null)
const identityKey = 'animelab_shared_identity'

export async function initializeSharedSession(): Promise<boolean> {
  let response: Response
  try {
    response = await fetch('/api/auth/me', { cache: 'no-store', credentials: 'same-origin' })
  } catch {
    // Personal-mode offline behavior stays available.
    return true
  }
  if (response.headers.get('X-AnimeLab-Shared') !== '1') return true
  if (!response.ok) {
    window.location.replace('/auth/login')
    return false
  }
  const data = (await response.json()) as { user: SharedUser }
  sharedUser.value = data.user
  const previous = localStorage.getItem(identityKey)
  if (previous !== data.user.id) {
    localStorage.clear()
    sessionStorage.clear()
    if ('caches' in window) {
      await Promise.all((await caches.keys()).map((key) => caches.delete(key)))
    }
  }
  localStorage.setItem(identityKey, data.user.id)
  if ('serviceWorker' in navigator) {
    await Promise.all(
      (await navigator.serviceWorker.getRegistrations()).map((item) => item.unregister()),
    )
  }
  window.addEventListener('storage', (event) => {
    if (event.key === null || event.key === identityKey) window.location.reload()
  })
  window.addEventListener('pageshow', (event) => {
    if (event.persisted) window.location.reload()
  })
  return true
}
