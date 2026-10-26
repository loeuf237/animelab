import type { DownloadTask, FavoriteItem } from './index'
export type ErrorCategory =
  | 'protection'
  | 'network'
  | 'rate_limit'
  | 'media'
  | 'permission'
  | 'export'
  | 'validation'
  | 'conflict'
  | 'not_found'
  | 'internal'
export interface APIProblem {
  code: string
  category: ErrorCategory
  messageKey: string
  action: 'verify' | 'retry' | 'wait' | 'storage_settings' | 'retry_export' | 'open_site' | 'none'
  retryAfter?: number | null
  domain?: string | null
  url?: string | null
}
export interface ErrorResponse {
  code?: string
  error?: string
  detail?: string | { loc: (string | number)[]; msg: string; type: string }[]
  problem?: APIProblem
  domain?: string
  url?: string
  task?: DownloadTask
}
export interface Result {
  success: boolean
  message?: string
  error?: string
  problem?: APIProblem
}
export interface ProxySettings {
  enabled: boolean
  proxy_type: string
  host: string
  port: number
  username: string
  password: string
  custom_url: string
  customUrl?: string
  proxyType?: string
  effectiveUrl?: string | null
  effective_url?: string | null
  effective_url_masked?: string | null
  effectiveUrlMasked?: string | null
  hasPassword?: boolean
  has_password?: boolean
}
export interface DownloadPreferences {
  maxConcurrentDownloads: number
  globalSpeedLimit: number
  plexOrganization: boolean
  selectedUserAgent?: string
  voiranimeDefaultServer?: string
  networkProfile?: string
  ffmpegAvailable?: boolean
  proxy?: ProxySettings
}
export interface WatchProgress {
  episode_number?: number
  isWatched?: boolean
  animeUrl: string
  animeName: string
  episodeNumber: number
  version: string
  watched: boolean
  downloaded: boolean
}
export interface ExtensionRepository {
  id: number
  name: string
  url: string
  is_active: number | boolean
  created_at: string
}
export interface SourcePreferences {
  quality_strategy?: string
  default_server?: string
}
export interface SourceSettingsEntry {
  id: string
  name: string
  settings: SourcePreferences
  [key: string]: unknown
}
export interface SourceSettingsResponse extends Result {
  sources: SourceSettingsEntry[]
}
export type VerificationMode = 'browser' | 'webview'
export interface VerificationCapability {
  id: VerificationMode | 'manual'
  available: boolean
  capturesCookies: boolean
  headless?: boolean
  reason:
    | 'client_remote'
    | 'android_webview'
    | 'no_display'
    | 'no_browser'
    | 'authenticated_proxy'
    | 'no_webview'
    | 'webview_proxy'
    | null
}
export interface NetworkSession {
  domain: string
  verificationRequired: boolean
  usesProxy: boolean
  modes: VerificationCapability[]
}
export interface NetworkOptions {
  browsers: { name: string }[]
  webviewAvailable: boolean
  platform: 'desktop' | 'android'
  clientLocal: boolean
  modes: VerificationCapability[]
  sessions: NetworkSession[]
}
export interface VerificationJob {
  id: string
  domain: string
  mode: VerificationMode
}
export interface VerificationResult extends Result {
  domain: string
  resumed: number
}
export interface DownloadResult extends Result {
  taskId?: string
  task?: DownloadTask
}
export interface BatchDownloadResult extends Result {
  count?: number
  started?: number
  queued?: number
}
export interface FavoriteResult extends Result {
  id?: number
  favorite: FavoriteItem
}
export interface PlaybackSelection {
  quality: string
  server: string
  subtitle: string | null
  audio: string | null
}
export interface PlaybackState {
  sessionId: string
  source: string
  animeUrl: string
  episodeNumber: number
  version: string
  positionSeconds: number
  durationSeconds: number
  selection: PlaybackSelection
}
export interface PlaybackOpen {
  taskId?: string
  source?: string
  animeUrl?: string
  animeName?: string
  episodeNumber?: number
  version?: string
}
export interface PlaybackCheckpoint {
  sessionId: string
  sequence: number
  positionSeconds: number
  durationSeconds: number
  selection: PlaybackSelection
  final: boolean
  ended: boolean
}
export interface PlaybackTrack {
  kind: string
  srclang: string
  label: string
}
export interface ExtensionHealth {
  operation: string
  status: string
  code: string
  messageKey: string
  checked_at: string
  success_at: string | null
  failure_streak: number
  duration_ms: number
  result_count: number
  recipe_revision: number
}
export interface RecipeRevision {
  revision: number
  schema_version: number
  fingerprint: string
  reason: string
  created_at: string
}
