import type { AndroidStorageState } from '@/api/client'
export type ThemeMode = 'system' | 'dark' | 'light'
export type Palette = 'classic' | 'teal' | 'lavender' | 'ember' | 'amoled'
export interface AppPreferences {
  onboardingCompleted: boolean
  theme: ThemeMode | null
  palette: Palette | null
  checkUpdates: boolean
  updateChannel: 'stable' | 'beta'
  lastSeenVersion?: string | null
}
export interface StartupSnapshot {
  preferences: AppPreferences
  currentVersion: string
  runtime: 'android' | 'desktop' | 'web'
  os: string
  architecture: string
  storageEditable: boolean
  native: AndroidStorageState | null
  downloadDirectory: string
}
export interface ReleaseAsset {
  name: string
  label: string
  url: string
  size: number | null
}
export interface AppRelease {
  version: string
  notes: string
  url: string
  assets: ReleaseAsset[]
}
export interface UpdateCheck {
  status: 'available' | 'current' | 'offline' | 'empty'
  currentVersion: string
  channel: 'stable' | 'beta'
  release: AppRelease | null
}
export interface UpdateInstallStatus {
  state:
    | 'idle'
    | 'downloading'
    | 'verifying'
    | 'installing'
    | 'permission_required'
    | 'waiting_user'
    | 'ready'
    | 'completed'
    | 'failed'
  version: string | null
  assetName: string | null
  downloadedBytes: number
  totalBytes: number
  percent: number
  filePath: string | null
  installDir: string | null
  executablePath: string | null
  restartRequired: boolean
  message: string | null
  error: string | null
}
