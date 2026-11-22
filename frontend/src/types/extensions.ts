export interface NativeSource {
  id: string
  name: string
  lang: string
  baseUrl: string
  supportsLatest: boolean
  configurable: boolean
  enabled?: boolean
  aliases?: string[]
}

export interface NativeExtension {
  pkg: string
  name: string
  version: string
  versionCode: string
  api: number
  signer: string
  trusted: boolean
  compatible: boolean
  enabled: boolean
  state: string
  error?: string
  extension_id: number
  sources: NativeSource[]
}

export interface ExtensionOperation {
  id: string
  pkg: string
  action: string
  state: string
  error?: string
  versionCode?: string
  createdAt?: number
  updatedAt?: number
  canConfirm?: boolean
}

export interface AndroidExtensionState {
  available: boolean
  packages: NativeExtension[]
  operations: ExtensionOperation[]
  securityBoundary: string
}

export interface NativePreference {
  summary?: string | null
  key?: string
  title: string
  type: 'group' | 'text' | 'boolean' | 'select' | 'multiSelect' | 'unsupported'
  enabled: boolean
  value?: string | boolean | string[] | null
  entries: string[]
  entryValues: string[]
  secret?: boolean
}

export interface NativeFilter {
  name: string
  type: 'header' | 'separator' | 'text' | 'checkbox' | 'select' | 'triState' | 'sort' | 'group'
  state?: string | number | boolean | { index: number; ascending: boolean } | null
  options?: string[]
  children?: NativeFilter[]
}

export type SeanimeExtensionType =
  'onlinestream-provider' | 'anime-torrent-provider' | 'manga-provider' | 'custom-source' | 'plugin'

export interface SeanimeConfigOption {
  value: string
  label: string
}

export interface SeanimeConfigField {
  type: 'text' | 'switch' | 'select'
  name: string
  label: string
  default: string
  options?: SeanimeConfigOption[]
}

export interface SeanimeUserConfigSchema {
  version?: number
  requiresConfig?: boolean
  fields?: SeanimeConfigField[]
}

export interface SeanimeRepository {
  id: number
  url: string
  name: string
  kind: 'marketplace' | 'repository' | 'direct' | string
  is_active: boolean
  last_error?: string | null
  checked_at?: string | null
  created_at?: string
  extension_count: number
  installed_count: number
}

export interface SeanimeExtension {
  id: number
  repo_id: number
  repo_name: string
  ext_id: string
  source_id: string | null
  name: string
  version: string
  installed_version: string | null
  available_version: string
  has_update: boolean
  ext_type: SeanimeExtensionType | string
  supported: boolean
  language: 'javascript' | 'typescript' | 'go' | string
  lang: string
  author: string
  description: string
  notes: string
  icon_url: string
  website: string
  readme: string
  manifest_uri: string
  payload_uri: string
  payload_sha256: string
  user_config: SeanimeUserConfigSchema
  saved_config: Record<string, string>
  needs_config: boolean
  marketplace_meta: {
    workingTag?: boolean
    brokenTag?: boolean
    deprecatedTag?: boolean
    stars?: number
    [key: string]: unknown
  }
  health: {
    last_diagnose?: SeanimeDiagnoseResult
    [key: string]: unknown
  }
  catalog_state: string
  installed: boolean
  enabled: boolean
  last_error?: string | null
  installed_at?: string | null
  updated_at?: string | null
}

export interface SeanimeTypeCounts {
  total: number
  installed: number
  enabled: number
  updates: number
}

export interface SeanimeCatalogResponse {
  runtime_available: boolean
  engine: string
  extensions: SeanimeExtension[]
  counts: Record<string, SeanimeTypeCounts>
  repositories: SeanimeRepository[]
}

export interface SeanimeConfigResponse {
  ext_id: string
  name: string
  schema: SeanimeUserConfigSchema
  values: Record<string, string>
  defaults: Record<string, string>
}

export interface SeanimeDiagnoseResult {
  extension_id: string
  source_id: string
  engine: string
  syntax_ok: boolean
  syntax_error?: string | null
  settings?: { episodeServers: string[]; supportsDub: boolean } | null
  search_count: number
  sample_titles: string[]
  episode_count: number
  stream_count: number
  ok?: boolean
  error?: string | null
  logs?: string[]
  duration_ms: number
}
