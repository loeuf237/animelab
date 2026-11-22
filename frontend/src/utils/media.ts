export const PROXIED_IMAGE_HOSTS = [
  'voiranime.cx',
  'voir-anime.to',
  'voiranime.to',
  'voiranime.io',
  'voiranime.homes',
  'animepahe.com',
  'animepahe.org',
  'animepahe.pw',
  'animepahe.ru',
  'animepahe.si',
  'animepahe.su',
  'kwik.cx',
  'kwik.si',
  'kwik.link',
  'kwik.top',
  'pahe.win',
  'owocdn.top',
  'kwikcdn.com',
] as const

export function isRemoteHttpUrl(url?: string | null): boolean {
  const trimmed = (url || '').trim()
  return /^https?:\/\//i.test(trimmed)
}

export function proxyImageUrl(url?: string | null): string {
  const trimmed = (url || '').trim()
  if (!trimmed) return ''
  if (trimmed.startsWith('/api/media/image-proxy')) return trimmed
  if (!isRemoteHttpUrl(trimmed)) return trimmed
  return `/api/media/image-proxy?url=${encodeURIComponent(trimmed)}`
}

export function needsImageProxy(url?: string | null): boolean {
  if (!isRemoteHttpUrl(url)) return false
  try {
    const host = new URL((url || '').trim()).hostname.toLowerCase()
    return PROXIED_IMAGE_HOSTS.some((domain) => host === domain || host.endsWith('.' + domain))
  } catch {
    return false
  }
}

export function resolveImageUrl(url?: string | null): string {
  const trimmed = (url || '').trim()
  if (!trimmed) return ''
  if (trimmed.startsWith('/api/media/image-proxy')) return trimmed
  return needsImageProxy(trimmed) ? proxyImageUrl(trimmed) : trimmed
}

export function canFallbackToImageProxy(
  rawUrl?: string | null,
  currentSrc?: string | null,
): boolean {
  return isRemoteHttpUrl(rawUrl) && !(currentSrc || '').trim().startsWith('/api/media/image-proxy')
}
