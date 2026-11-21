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
