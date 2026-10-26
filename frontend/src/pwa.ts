/** The personal SPA owns PWA registration; shared accounts disable offline caching. */
export function initializePwa(): void {
  if (!('serviceWorker' in navigator)) return
  const register = () => {
    navigator.serviceWorker
      .register('/sw.js', { scope: '/', updateViaCache: 'none' })
      .catch((error) => console.warn('[AnimeLab] Service worker registration failed', error))
  }
  if (document.readyState === 'complete') register()
  else window.addEventListener('load', register, { once: true })
}
