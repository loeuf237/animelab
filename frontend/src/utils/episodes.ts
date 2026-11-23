import type { Episode } from '@/types'

export function episodeKey(ep: Episode): string {
  return JSON.stringify([
    String(ep.number),
    ep.version || '',
    ep.downloadPageUrl || ep.playerUrl || '',
  ])
}

export function buildEpisodeRowKeys(episodes: Episode[]): WeakMap<Episode, string> {
  const counts = new Map<string, number>()
  const map = new WeakMap<Episode, string>()
  for (const ep of episodes) {
    const base = episodeKey(ep)
    const idx = counts.get(base) || 0
    counts.set(base, idx + 1)
    map.set(ep, idx === 0 ? base : `${base}#${idx}`)
  }
  return map
}

export function episodeFileName(title: string, ep: Episode): string {
  const season = Number(ep.nativeMetadata?.season)
  const label =
    Number.isInteger(season) && season > 0
      ? `S${String(season).padStart(2, '0')}E${String(ep.number).padStart(2, '0')}`
      : `Episode ${ep.number}`
  return `${title} - ${label}${ep.version ? ` [${ep.version}]` : ''}.mp4`
}
