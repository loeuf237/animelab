import type {
  SubtitleProviderStatus,
  SubtitleSearchQuery,
  SubtitleSearchResult,
  SubtitleImport,
  SubtitleProvider,
  SubtitleSyncCapabilities,
  SubtitleTimingCorrection,
} from '@/types/subtitles'
import type { OutputProfile, OutputProfileCapability, OutputInventory } from '@/types'
import type { PlaybackOpen, PlaybackState, PlaybackCheckpoint, RecipeRevision } from '@/types/api'
import type {
  ErrorResponse,
  DownloadPreferences,
  ProxySettings,
  WatchProgress,
  ExtensionRepository,
  SourceSettingsResponse,
  SourcePreferences,
  NetworkOptions,
  VerificationMode,
  VerificationJob,
  VerificationResult,
} from '@/types/api'
import { language, tx } from '@/utils/locale'

export interface AndroidStorageState {
  android: boolean
  apiLevel: number
  mode: 'downloads' | 'directory'
  destination: string
  authorized: boolean
  selectionPending: boolean
  notificationsGranted: boolean
  subtitleDestination?: string | null
  error: string | null
  exportError: string | null
}

export interface ProxyPoolSnapshot {
  automatic: boolean
  refreshing: boolean
  checking: boolean
  lastRefresh: number | null
  total: number
  healthy: number
  importedCount: number
  providers: {
    id: string
    name: string
    website: string
    count?: number
    status?: string
    error?: string
  }[]
  entries: {
    url: string
    provider: string
    country: string
    status?: string
    latencyMs?: number
    usable: boolean
  }[]
}
import type {
  AnimeDetailResponse,
  AnimeResult,
  DownloadTask,
  ExtensionSource,
  FavoriteItem,
  HistoryItem,
  HomeFeedResponse,
  VideoStreamInfo,
  SearchResponse,
  CatalogueSource,
  CatalogueFilters,
  CataloguePage,
  AutoDownloadOptions,
  SubtitleTrack,
} from '@/types'

class ApiError extends Error {
  status: number
  data: ErrorResponse | null

  constructor(message: string, status: number, data: ErrorResponse | null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.data = data
  }
}

async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers || {})
  if (!headers.has('Content-Type') && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }
  headers.set('Accept', 'application/json')
  headers.set('Accept-Language', language.value)

  const config: RequestInit = {
    ...options,
    headers,
  }

  let response: Response
  try {
    response = await fetch(endpoint, config)
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw error
    throw new ApiError(tx('La connexion au site a échoué. Réessayez.'), 0, {
      problem: {
        code: 'client_network_error',
        category: 'network',
        messageKey: 'La connexion au site a échoué. Réessayez.',
        action: 'retry',
      },
    })
  }

  if (!response.ok) {
    if (response.status === 401 && response.headers.get('X-AnimeLab-Shared') === '1') {
      window.location.replace('/auth/login')
    }
    let errorDetail = response.statusText
    let data: ErrorResponse | null = null
    try {
      const raw: unknown = await response.json()
      data = raw && typeof raw === 'object' && !Array.isArray(raw) ? (raw as ErrorResponse) : null
      if (data?.problem) errorDetail = tx(data.problem.messageKey)
      else if (data && data.detail) {
        errorDetail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)
      } else if (data && data.error) {
        errorDetail = typeof data.error === 'string' ? data.error : JSON.stringify(data.error)
      }
    } catch {
      // Body not JSON
    }
    throw new ApiError(errorDetail, response.status, data)
  }

  return response.json() as Promise<T>
}

export const api = {
  openPlaybackSession(body: PlaybackOpen, signal?: AbortSignal) {
    return request<PlaybackState>('/api/playback/session', {
      method: 'POST',
      body: JSON.stringify(body),
      signal,
    })
  },
  savePlaybackCheckpoint(body: PlaybackCheckpoint) {
    return request<{ success: boolean; accepted: boolean; reason?: string }>(
      '/api/playback/checkpoint',
      { method: 'POST', body: JSON.stringify(body), keepalive: true },
    )
  },
  getRecipeHistory(id: string | number) {
    return request<{ revisions: RecipeRevision[] }>(
      `/api/extensions/${encodeURIComponent(id)}/recipe-history`,
    )
  },
  restoreRecipe(id: string | number, revision: number) {
    return request<{ success: boolean }>(
      `/api/extensions/${encodeURIComponent(id)}/recipe-restore`,
      { method: 'POST', body: JSON.stringify({ revision }) },
    )
  },
  getDiagnostics() {
    return request<Record<string, unknown>>('/api/diagnostics/export')
  },

  getProxyPool() {
    return request<ProxyPoolSnapshot>('/api/network/proxy-pool')
  },
  refreshProxyPool() {
    return request<ProxyPoolSnapshot>('/api/network/proxy-pool/refresh', { method: 'POST' })
  },
  checkProxyPool() {
    return request<ProxyPoolSnapshot>('/api/network/proxy-pool/check', { method: 'POST' })
  },
  saveProxyPool(automatic: boolean) {
    return request<ProxyPoolSnapshot>('/api/network/proxy-pool/settings', {
      method: 'POST',
      body: JSON.stringify({ automatic }),
    })
  },
  importProxyPool(data: unknown) {
    return request<{ imported: number; pool: ProxyPoolSnapshot }>(
      '/api/network/proxy-pool/import',
      { method: 'POST', body: JSON.stringify(data) },
    )
  },
  clearImportedProxies() {
    return request<ProxyPoolSnapshot>('/api/network/proxy-pool/import', { method: 'DELETE' })
  },
  rotateSourceProxy(domain: string) {
    return request<{ success: boolean; domain: string; resumed: number }>(
      '/api/network/proxy-pool/rotate',
      { method: 'POST', body: JSON.stringify({ domain }) },
    )
  },
  getVerificationBrowserSettings() {
    return request<{ chromiumPath: string; headless: boolean; managed: boolean }>(
      '/api/network/browser-settings',
    )
  },
  saveVerificationBrowserSettings(values: { chromiumPath: string; headless: boolean }) {
    return request<{ chromiumPath: string; headless: boolean; managed: boolean }>(
      '/api/network/browser-settings',
      {
        method: 'POST',
        body: JSON.stringify(values),
      },
    )
  },
  getVerificationStatus(id: string) {
    return request<{
      status: 'pending' | 'completed'
      domain: string
      resumed?: number
      error?: string
    }>(`/api/network/verification/${encodeURIComponent(id)}/status`)
  },
  getNetworkSessions() {
    return request<NetworkOptions>('/api/network/sessions')
  },
  recheckNetworkSource(domain: string) {
    return request<{ success: boolean; domain: string }>('/api/network/recheck', {
      method: 'POST',
      body: JSON.stringify({ domain }),
    })
  },
  startNetworkVerification(domain: string, browser: string, mode: VerificationMode) {
    return request<VerificationJob>('/api/network/verification', {
      method: 'POST',
      body: JSON.stringify({ domain, browser, mode }),
    })
  },
  completeNetworkVerification(id: string) {
    return request<VerificationResult>(
      `/api/network/verification/${encodeURIComponent(id)}/complete`,
      { method: 'POST' },
    )
  },
  cancelNetworkVerification(id: string) {
    return request<{ success: boolean }>(`/api/network/verification/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    })
  },
  // --- Feed & Home ---
  async getHomeFeed(): Promise<HomeFeedResponse> {
    return request<HomeFeedResponse>('/api/home/feed')
  },

  async getLatestReleases(
    source?: string,
  ): Promise<{ source?: string; releases: AnimeResult[] } | Record<string, AnimeResult[]>> {
    const q = source ? `?source=${encodeURIComponent(source)}` : ''
    return request(`/api/releases/latest${q}`)
  },

  async getSourceFeed(
    sourceId: string,
    page: number = 1,
  ): Promise<{ source: string; releases: AnimeResult[]; page: number }> {
    return request(`/api/sources/${encodeURIComponent(sourceId)}/feed?page=${page}`)
  },

  // --- Search & Details ---
  async searchAnime(query: string, source: string = 'all'): Promise<AnimeResult[]> {
    const q = `?q=${encodeURIComponent(query)}&source=${encodeURIComponent(source)}`
    return request<AnimeResult[]>(`/api/search${q}`)
  },

  searchAnimeDetailed(query: string, source = 'all') {
    return request<SearchResponse>(
      `/api/search?${new URLSearchParams({ q: query, source, include_challenges: 'true' })}`,
    )
  },
  getSources() {
    return request<{ sources: CatalogueSource[] }>('/api/sources')
  },
  getCatalogueFilters(source: string) {
    return request<CatalogueFilters>(`/api/sources/${encodeURIComponent(source)}/filters`)
  },
  browseCatalogue(
    source: string,
    params: { mode: string; q: string; tags: string[]; order: string; cursor?: string },
  ) {
    const query = new URLSearchParams({ mode: params.mode, q: params.q, order: params.order })
    params.tags.forEach((tag) => query.append('tags', tag))
    if (params.cursor) query.set('cursor', params.cursor)
    return request<CataloguePage>(`/api/sources/${encodeURIComponent(source)}/catalogue?${query}`)
  },

  async getAnimeDetail(url: string, source: string = 'french-manga'): Promise<AnimeDetailResponse> {
    const q = `?url=${encodeURIComponent(url)}&source=${encodeURIComponent(source)}`
    return request<AnimeDetailResponse>(`/api/anime/detail${q}`)
  },

  // --- Library & Favorites ---
  async getFavorites(): Promise<FavoriteItem[]> {
    return request<FavoriteItem[]>('/api/favorites')
  },

  async addFavorite(
    payload: {
      url: string
      title: string
      imageUrl: string
      source: string
      autoDownload?: boolean
    } & AutoDownloadOptions,
  ): Promise<{ success: boolean; id: number; favorite: FavoriteItem }> {
    return request('/api/favorites', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },

  async removeFavorite(url: string): Promise<{ success: boolean }> {
    return request('/api/favorites', {
      method: 'DELETE',
      body: JSON.stringify({ url }),
    })
  },

  async toggleAutoDownload(
    url: string,
    autoDownload: boolean,
    options: AutoDownloadOptions = {},
  ): Promise<{ success: boolean; favorite: FavoriteItem }> {
    return request('/api/favorites/auto-download', {
      method: 'PATCH',
      body: JSON.stringify({ url, autoDownload, ...options }),
    })
  },

  async clearAllFavorites(): Promise<{ success: boolean }> {
    return request('/api/favorites/all', { method: 'DELETE' })
  },

  // --- Watch Progress ---
  async markEpisodeWatched(payload: {
    animeUrl: string
    animeName?: string
    episodeNumber: string | number
    version?: string
    watched: boolean
  }): Promise<{ success: boolean }> {
    return request('/api/progress/watched', {
      method: 'POST',
      body: JSON.stringify({
        animeUrl: payload.animeUrl,
        animeName: payload.animeName || '',
        episodeNumber: parseInt(String(payload.episodeNumber), 10) || 0,
        version: payload.version || '',
        watched: payload.watched,
      }),
    })
  },

  async getProgress(animeUrl: string): Promise<WatchProgress[]> {
    return request(`/api/progress?animeUrl=${encodeURIComponent(animeUrl)}`)
  },

  async getDownloadedEpisodes(animeUrl: string): Promise<string[]> {
    return request(`/api/progress/downloaded?animeUrl=${encodeURIComponent(animeUrl)}`)
  },

  // --- History ---
  async getHistory(animeName?: string): Promise<HistoryItem[]> {
    const q = animeName ? `?animeName=${encodeURIComponent(animeName)}` : ''
    return request(`/api/history${q}`)
  },

  async deleteHistoryEntry(taskId: string | number): Promise<{ success: boolean }> {
    return request(`/api/history/${taskId}`, { method: 'DELETE' })
  },

  async clearHistory(): Promise<{ success: boolean }> {
    return request('/api/history', { method: 'DELETE' })
  },

  // --- Downloads ---
  async getOutputProfiles(): Promise<OutputProfileCapability[]> {
    return request('/api/download/output-profiles')
  },
  async getSubtitleContext(taskId: string | number): Promise<{
    query: string
    season: number | null
    episode: number
    provider: SubtitleProviderStatus
    providers?: Partial<Record<SubtitleProvider, SubtitleProviderStatus>>
    video?: { fps: number | null; duration: number | null }
  }> {
    return request(`/api/download/${encodeURIComponent(taskId)}/subtitles/context`)
  },
  async configureSubtitleProvider(
    credentials: {
      apiKey?: string
      username: string
      password: string
      remember: boolean
    },
    provider: SubtitleProvider = 'opensubtitles',
  ): Promise<SubtitleProviderStatus> {
    return request(
      '/api/download/subtitle-provider' + (provider === 'subdl' ? '?provider=subdl' : ''),
      {
        method: 'PUT',
        body: JSON.stringify(credentials),
      },
    )
  },
  async forgetSubtitleProvider(
    provider: SubtitleProvider = 'opensubtitles',
  ): Promise<SubtitleProviderStatus> {
    return request(
      '/api/download/subtitle-provider' + (provider === 'subdl' ? '?provider=subdl' : ''),
      { method: 'DELETE' },
    )
  },
  async searchSubtitles(
    taskId: string | number,
    query: SubtitleSearchQuery,
  ): Promise<{
    results: SubtitleSearchResult[]
    page: number
    totalPages: number
    provider: SubtitleProviderStatus
    providers?: Partial<Record<SubtitleProvider, SubtitleProviderStatus>>
    errors?: { provider: SubtitleProvider; message: string }[]
  }> {
    return request(`/api/download/${encodeURIComponent(taskId)}/subtitles/search`, {
      method: 'POST',
      body: JSON.stringify(query),
    })
  },
  async uploadSubtitles(
    taskId: string | number,
    file: File,
    encoding: string,
  ): Promise<SubtitleImport> {
    return request(
      `/api/download/${encodeURIComponent(taskId)}/subtitles/import?filename=${encodeURIComponent(file.name)}&encoding=${encodeURIComponent(encoding)}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/octet-stream' },
        body: await file.arrayBuffer(),
      },
    )
  },
  async previewProviderSubtitle(
    taskId: string | number,
    resultId: string,
  ): Promise<SubtitleImport> {
    return request(`/api/download/${encodeURIComponent(taskId)}/subtitles/provider-preview`, {
      method: 'POST',
      body: JSON.stringify({ resultId }),
    })
  },
  async attachSubtitle(
    taskId: string | number,
    selection: {
      importId: string
      entryId: string
      language: string
      label: string
      confirmedEpisode: boolean
    },
  ): Promise<{ trackId: string; duplicate: boolean }> {
    return request(`/api/download/${encodeURIComponent(taskId)}/subtitles/attach`, {
      method: 'POST',
      body: JSON.stringify(selection),
    })
  },
  async getOutputInventory(taskId: string | number): Promise<OutputInventory> {
    return request(`/api/download/${encodeURIComponent(taskId)}/media-inventory`)
  },
  async getSubtitleSyncCapabilities(): Promise<SubtitleSyncCapabilities> {
    return request('/api/download/subtitle-sync-capabilities')
  },
  async getSubtitleImport(taskId: string | number, importId: string): Promise<SubtitleImport> {
    return request(
      `/api/download/${encodeURIComponent(taskId)}/subtitles/imports/${encodeURIComponent(importId)}`,
    )
  },
  async correctSubtitle(
    taskId: string | number,
    body: SubtitleTimingCorrection,
  ): Promise<SubtitleImport> {
    return request(`/api/download/${encodeURIComponent(taskId)}/subtitles/transform`, {
      method: 'POST',
      body: JSON.stringify(body),
    })
  },
  async cancelSubtitleSync(taskId: string | number): Promise<{ cancelled: boolean }> {
    return request(`/api/download/${encodeURIComponent(taskId)}/subtitles/cancel-sync`, {
      method: 'POST',
    })
  },
  async restoreSubtitle(taskId: string | number, trackId: string): Promise<{ trackId: string }> {
    return request(
      `/api/download/${encodeURIComponent(taskId)}/subtitles/tracks/${encodeURIComponent(trackId)}/restore`,
      { method: 'POST' },
    )
  },
  async reprocessOutput(
    taskId: string | number,
    profile: OutputProfile,
  ): Promise<{ success: boolean }> {
    return request(`/api/download/${encodeURIComponent(taskId)}/output`, {
      method: 'POST',
      body: JSON.stringify(profile),
    })
  },
  async getDownloadTasks(): Promise<DownloadTask[]> {
    return request<DownloadTask[]>('/api/download/status')
  },

  async startEpisodeDownload(payload: {
    animeName: string
    episodeNumber: number | string
    version?: string
    animeUrl?: string
    url: string
    fileName?: string
    subtitleUrl?: string
    downloadSubtitles?: boolean
    outputProfile?: OutputProfile
    source?: string
    selectedServer?: string
    selectedQuality?: string
    scheduledTime?: string
    speedLimit?: number | string
  }): Promise<{ success: boolean; taskId?: number | string; message?: string }> {
    return request('/api/download', {
      method: 'POST',
      body: JSON.stringify({
        animeName: payload.animeName,
        episodeNumber: parseInt(String(payload.episodeNumber), 10) || 0,
        url: payload.url,
        version: payload.version || '',
        animeUrl: payload.animeUrl || '',
        fileName: payload.fileName,
        subtitleUrl: payload.subtitleUrl,
        downloadSubtitles: Boolean(payload.downloadSubtitles),
        outputProfile: payload.outputProfile,
        source: payload.source || 'french-manga',
        selectedServer: payload.selectedServer,
        selectedQuality: payload.selectedQuality,
        scheduledTime: payload.scheduledTime,
        speedLimit: payload.speedLimit,
      }),
    })
  },

  async startBatchDownload(payload: {
    animeName: string
    source: string
    episodes: {
      number: number | string
      version?: string
      animeUrl?: string
      url: string
      title?: string
      fileName?: string
      subtitleUrl?: string
      downloadSubtitles?: boolean
      outputProfile?: OutputProfile
    }[]
    preferredServer?: string
    preferredQuality?: string
  }): Promise<{
    success: boolean
    count?: number
    started?: number
    queued?: number
    message?: string
  }> {
    return request('/api/download/batch', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },

  async pauseDownload(taskId: number | string): Promise<{ success: boolean }> {
    return request(`/api/download/${taskId}/pause`, { method: 'POST' })
  },

  async resumeDownload(taskId: number | string): Promise<{ success: boolean }> {
    return request(`/api/download/${taskId}/resume`, { method: 'POST' })
  },

  async cancelDownload(taskId: number | string): Promise<{ success: boolean }> {
    return request(`/api/download/${taskId}`, { method: 'DELETE' })
  },

  async removeDownloadTask(taskId: number | string): Promise<{ success: boolean }> {
    return request(`/api/download/${taskId}/remove`, { method: 'DELETE' })
  },

  async redownloadTask(
    taskId: number | string,
  ): Promise<{ success: boolean; message?: string; task?: DownloadTask }> {
    return request(`/api/download/${taskId}/redownload`, { method: 'POST' })
  },

  async verifyTask(taskId: number | string): Promise<{
    success: boolean
    valid?: boolean
    status?: string
    duration?: number
    formattedDuration?: string
    formattedSize?: string
    error?: string
  }> {
    return request(`/api/download/${taskId}/verify`, { method: 'POST' })
  },

  async verifyAllTasks(): Promise<{
    success: boolean
    total?: number
    valid?: number
    invalid?: number
  }> {
    return request('/api/download/verify-all', { method: 'POST' })
  },

  async moveTaskToTop(taskId: number | string): Promise<{ success: boolean }> {
    return request(`/api/download/${taskId}/move-to-top`, { method: 'POST' })
  },

  async moveSeriesToTop(animeName: string): Promise<{ success: boolean; message?: string }> {
    return request('/api/download/move-series-to-top', {
      method: 'POST',
      body: JSON.stringify({ animeName }),
    })
  },

  async reorderTasks(orderedIds: (string | number)[]): Promise<{ success: boolean }> {
    return request('/api/download/reorder', {
      method: 'POST',
      body: JSON.stringify(orderedIds),
    })
  },

  async setTaskSpeedLimit(
    taskId: number | string,
    limitBytes: number,
  ): Promise<{ success: boolean }> {
    return request(`/api/download/${taskId}/speed-limit`, {
      method: 'POST',
      body: JSON.stringify({ limit: limitBytes }),
    })
  },

  async pauseAllDownloads(): Promise<{ success: boolean }> {
    return request('/api/download/pause-all', { method: 'POST' })
  },

  async resumeAllDownloads(): Promise<{ success: boolean }> {
    return request('/api/download/resume-all', { method: 'POST' })
  },

  async cancelAllDownloads(): Promise<{ success: boolean }> {
    return request('/api/download/cancel-all', { method: 'POST' })
  },

  async cleanCompletedDownloads(): Promise<{ success: boolean }> {
    return request('/api/download/clean', { method: 'POST' })
  },

  // --- Settings ---
  async getDownloadSettings(): Promise<DownloadPreferences> {
    return request('/api/download/settings')
  },

  async saveDownloadSettings(
    settings: Partial<DownloadPreferences>,
  ): Promise<{ success: boolean; message: string }> {
    return request('/api/download/settings', {
      method: 'POST',
      body: JSON.stringify(settings),
    })
  },

  async getProxySettings(): Promise<ProxySettings> {
    return request('/api/proxy/settings')
  },

  async saveProxySettings(
    settings: ProxySettings,
  ): Promise<{ success: boolean; settings: ProxySettings }> {
    return request('/api/proxy/settings', {
      method: 'POST',
      body: JSON.stringify(settings),
    })
  },

  async testProxy(
    proxyUrl?: string,
    settings?: ProxySettings,
  ): Promise<{ success: boolean; latencyMs?: number; ip?: string; error?: string }> {
    return request('/api/proxy/test', {
      method: 'POST',
      body: JSON.stringify({ proxyUrl: proxyUrl || '', settings }),
    })
  },

  async getSourcesSettings(): Promise<SourceSettingsResponse> {
    return request('/api/sources/settings')
  },

  async saveSourcesSettings(
    sourceId: string,
    settings: SourcePreferences,
  ): Promise<{ success: boolean; sourceId: string; settings: SourcePreferences }> {
    return request(`/api/sources/settings/${encodeURIComponent(sourceId)}`, {
      method: 'POST',
      body: JSON.stringify(settings),
    })
  },

  async getStorageInfo(): Promise<{
    totalBytes: number | null
    usedBytes: number | null
    freeBytes: number | null
    usedPercent: number | null
    downloadDir: string
    native?: AndroidStorageState | null
  }> {
    return request('/api/system/storage')
  },
  getAndroidStorage() {
    return request<AndroidStorageState | null>('/api/system/android/storage')
  },
  androidStorageAction(action: string) {
    return request<AndroidStorageState>('/api/system/android/storage', {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
  },
  exportAndroidDownload(taskId: string) {
    return request<{ success: boolean; destination: string; task: DownloadTask }>(
      '/api/system/android/export',
      { method: 'POST', body: JSON.stringify({ taskId }) },
    )
  },

  // --- i18n ---
  async getTranslations(lang?: string): Promise<{
    language: string
    supported: string[]
    translations: Record<string, string>
    all?: Record<string, Record<string, string>>
  }> {
    const q = lang ? `?lang=${encodeURIComponent(lang)}` : ''
    return request(`/api/i18n${q}`)
  },

  async setLanguage(language: string): Promise<{ success: boolean; language: string }> {
    return request('/api/i18n/set-language', {
      method: 'POST',
      body: JSON.stringify({ language }),
    })
  },

  // --- Streaming & Media Resolution ---
  async getLocalSubtitles(taskId: string | number): Promise<SubtitleTrack[]> {
    return request(`/api/media/subtitles/${encodeURIComponent(taskId)}`)
  },

  async resolveVideoStream(params: {
    animeName: string
    episodeNumber: number | string
    episodeUrl: string
    animeUrl?: string
    version?: string
    source?: string
    server?: string
    quality?: string
  }): Promise<VideoStreamInfo> {
    const search = new URLSearchParams()
    search.set('animeName', params.animeName)
    search.set('episodeNumber', String(params.episodeNumber))
    search.set('episodeUrl', params.episodeUrl)
    if (params.animeUrl) search.set('animeUrl', params.animeUrl)
    if (params.version) search.set('version', params.version)
    if (params.source) search.set('source', params.source)
    if (params.server && params.server !== 'auto') search.set('server', params.server)
    if (params.quality && params.quality !== 'auto') search.set('quality', params.quality)
    return request<VideoStreamInfo>(`/api/media/stream/resolve?${search.toString()}`)
  },

  async getEpisodeServers(
    episodeUrl: string,
    source: string,
  ): Promise<{ servers: string[]; qualities?: string[] }> {
    const search = new URLSearchParams()
    search.set('url', episodeUrl)
    search.set('source', source)
    return request(`/api/episode/servers?${search.toString()}`)
  },

  async getEpisodeSize(
    episodeUrl: string,
    source: string,
    server?: string,
  ): Promise<{ size: number; formattedSize: string }> {
    const search = new URLSearchParams()
    search.set('url', episodeUrl)
    search.set('source', source)
    if (server) search.set('server', server)
    return request(`/api/episode/size?${search.toString()}`)
  },

  // --- Extensions ---
  async getExtensions(
    q?: string,
    lang?: string,
  ): Promise<{
    active_repo?: ExtensionRepository | null
    count?: number
    updates_count?: number
    extensions?: ExtensionSource[]
    installed?: ExtensionSource[]
  }> {
    const params = new URLSearchParams()
    if (q) params.set('q', q)
    if (lang && lang !== 'all') params.set('lang', lang)
    const qs = params.toString() ? `?${params.toString()}` : ''
    return request(`/api/extensions/list${qs}`)
  },

  async toggleExtension(
    extId: number | string,
    enabled: boolean,
  ): Promise<{ success: boolean; is_enabled?: boolean }> {
    const numId = typeof extId === 'number' ? extId : parseInt(String(extId), 10)
    return request(`/api/extensions/${isNaN(numId) ? extId : numId}/toggle`, {
      method: 'POST',
      body: JSON.stringify({ enabled }),
    })
  },

  async configureExtension(
    id: number | string,
    recipe: Record<string, unknown>,
  ): Promise<{ success: boolean }> {
    return request(`/api/extensions/${id}/recipe`, { method: 'PUT', body: JSON.stringify(recipe) })
  },
  async diagnoseExtension(
    id: number | string,
  ): Promise<{ success: boolean; count: number; message: string }> {
    return request(`/api/extensions/${id}/diagnose`, { method: 'POST' })
  },
  async refreshExtensions(): Promise<{ success: boolean }> {
    return request('/api/extensions/refresh', { method: 'POST' })
  },
  async checkExtensionUpdates(): Promise<{
    success: boolean
    count?: number
    updates?: {
      id: number | string
      pkg: string
      name: string
      installed_version?: string
      available_version?: string
    }[]
    message?: string
  }> {
    return request('/api/extensions/check-updates', { method: 'POST' })
  },
  async updateExtension(id: number | string): Promise<{
    success: boolean
    id?: number | string
    version?: string
    installed_version?: string
    available_version?: string
    has_update?: boolean
    message?: string
  }> {
    return request(`/api/extensions/${encodeURIComponent(id)}/update`, { method: 'POST' })
  },
  async updateAllExtensions(): Promise<{
    success: boolean
    count?: number
    updated_ids?: (number | string)[]
    message?: string
  }> {
    return request('/api/extensions/update-all', { method: 'POST' })
  },
  async recompileExtension(id: number | string): Promise<{
    success: boolean
    id?: number | string
    message?: string
  }> {
    return request(`/api/extensions/${encodeURIComponent(id)}/recompile`, { method: 'POST' })
  },
  async importExtensionRepo(
    url: string,
  ): Promise<{ success: boolean; repo_name?: string; count?: number }> {
    return request('/api/extensions/import-repo', {
      method: 'POST',
      body: JSON.stringify({ url }),
    })
  },
}

export { ApiError }
