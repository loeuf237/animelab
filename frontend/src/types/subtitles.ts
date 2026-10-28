export type SubtitleProvider = 'opensubtitles' | 'subdl'
export interface SubtitleProviderStatus {
  configured: boolean
  authenticated: boolean
  username: string
  remember: boolean
  secureStorageAvailable: boolean
  quota: {
    allowed_downloads?: number
    remaining?: number
    requests?: number
    reset_time_utc?: string
    search?: { remaining?: number; limit?: number }
    downloads?: { remaining?: number; limit?: number }
  }
  error: string | null
  retryAfter: number
}
export interface SubtitleSearchQuery {
  providers?: SubtitleProvider[]
  expectedRelease?: string
  expectedFps?: number | null
  expectedDuration?: number | null
  query: string
  languages: string
  imdbId?: string
  tmdbId?: number | null
  idType: 'series' | 'episode' | 'movie'
  season?: number | null
  episode?: number | null
  absoluteEpisode?: number | null
  page: number
}
export interface SubtitleSearchResult {
  provider?: SubtitleProvider
  alternatives?: { id: string; provider: SubtitleProvider }[]
  duration?: number | null
  id: string
  fileName: string
  language: string
  release: string
  fps?: number
  hearingImpaired: boolean
  forced: boolean
  feature: {
    title?: string
    parent_title?: string
    season_number?: number
    episode_number?: number
  }
  checks: {
    field: string
    expected: string | number
    actual?: string | number | null
    state: string
  }[]
  warnings: string[]
}
export interface SubtitleImport {
  importId: string
  entries: {
    id: string
    name: string
    format: string
    size: number
    cues: number
    firstCue: number
    lastCue: number
    preview: string
    numbering?: { season: number; episode: number } | null
  }[]
  provenance: { provider: string; release?: string; fileId?: number | string }
  originalImportId?: string
  originalEntryId?: string
  comparison?: { kind: string; factor?: number; overlapAfter?: number; correctedCues: number }
}
export interface SubtitleSyncCapabilities {
  manual: boolean
  alass: boolean
  version: string | null
  reason: string
}
export interface SubtitleTimingCorrection {
  importId: string
  entryId: string
  method: 'manual' | 'alass'
  offsetSeconds?: number
  sourceFps?: number | null
  targetFps?: number | null
  referenceTrackId?: string | null
  referenceConfirmed?: boolean
  allowSplits?: boolean
}
