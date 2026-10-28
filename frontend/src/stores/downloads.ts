import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '@/api/client'
import type { DownloadTask, DownloadStats, OutputProfile } from '@/types'

function normalizeStatus(status: any): string {
  if (!status) return 'queued'
  const s = String(status).toUpperCase()
  if (s === 'DOWNLOADING' || s === 'MUXING') return 'downloading'
  if (s === 'PENDING' || s === 'SCHEDULED' || s === 'RETRYING') return 'queued'
  if (s === 'PAUSED') return 'paused'
  if (s === 'VERIFICATION_REQUIRED') return 'verification_required'
  if (s === 'COMPLETED') return 'completed'
  if (s === 'FAILED' || s === 'ERROR') return 'error'
  if (s === 'CANCELLED') return 'cancelled'
  return s.toLowerCase()
}

function normalizeTask(raw: any): DownloadTask {
  const normStatus = normalizeStatus(raw.status)
  const speed = raw.speedBytes ?? raw.downloadSpeed ?? raw.speed ?? 0
  return {
    ...raw,
    id: raw.id ?? raw.taskId,
    status: normStatus,
    rawStatus: String(raw.status || '').toUpperCase(),
    phase: raw.phase || (String(raw.status).toUpperCase() === 'MUXING' ? 'muxing' : null),
    downloadSpeed: typeof speed === 'number' ? speed : 0,
    bytesDownloaded: raw.downloadedBytes ?? raw.bytesDownloaded ?? 0,
    totalBytes: raw.totalBytes ?? 0,
    verificationStatus: raw.verificationStatus || 'UNVERIFIED',
    verificationError: raw.verificationError || null,
    videoDuration: raw.videoDuration || null,
    formattedDuration: raw.formattedDuration || null,
    maxSpeedLimit: raw.maxSpeedLimit || 0,
    scheduledStartTime: raw.scheduledStartTime || null,
  }
}

export const useDownloadStore = defineStore('downloads', () => {
  const tasks = ref<DownloadTask[]>([])
  const isDrawerOpen = ref(false)
  const isConnected = ref(false)
  let eventSource: EventSource | null = null
  let pollingTimer: any = null

  const stats = computed<DownloadStats>(() => {
    let active = 0
    let queued = 0
    let completed = 0
    let errCount = 0
    let speed = 0

    for (const t of tasks.value) {
      const s = normalizeStatus(t.status)
      if (s === 'downloading' || t.exportStatus === 'EXPORTING') {
        active++
        speed += t.downloadSpeed || 0
      } else if (s === 'queued') {
        queued++
      } else if (s === 'completed') {
        completed++
        if (t.exportStatus === 'EXPORT_FAILED' || t.exportStatus === 'PENDING') errCount++
      } else if (s === 'error') {
        errCount++
      }
    }

    return {
      activeCount: active,
      queuedCount: queued,
      completedCount: completed,
      errorCount: errCount,
      totalSpeed: speed,
    }
  })

  async function fetchTasks() {
    try {
      const res = await api.getDownloadTasks()
      const rawList = Array.isArray(res) ? res : (res as any)?.tasks || []
      tasks.value = rawList.map(normalizeTask)
    } catch (e) {
      console.warn('[DownloadStore] Error fetching tasks:', e)
    }
  }

  function handleSSEUpdate(payload: any) {
    if (!payload) return
    if (Array.isArray(payload)) {
      tasks.value = payload.map(normalizeTask)
      return
    }
    if (payload.tasks && Array.isArray(payload.tasks)) {
      tasks.value = payload.tasks.map(normalizeTask)
      return
    }

    const taskId = payload.taskId ?? payload.id
    if (taskId != null) {
      const idx = tasks.value.findIndex((t) => String(t.id) === String(taskId))
      const norm = normalizeTask(payload)
      if (idx !== -1) {
        tasks.value[idx] = { ...tasks.value[idx], ...norm }
      } else {
        tasks.value.push(norm)
      }
    }
  }

  function startSSE() {
    if (eventSource) return

    try {
      eventSource = new EventSource('/api/download/stream')

      eventSource.onopen = () => {
        isConnected.value = true
        if (pollingTimer) {
          clearInterval(pollingTimer)
          pollingTimer = null
        }
      }

      const onMessage = (event: MessageEvent) => {
        try {
          const payload = JSON.parse(event.data)
          handleSSEUpdate(payload)
        } catch (e) {
          console.debug('[DownloadStore] SSE parse error:', e)
        }
      }

      eventSource.addEventListener('download-update', onMessage as EventListener)
      eventSource.onmessage = onMessage

      eventSource.onerror = () => {
        isConnected.value = false
        if (eventSource) {
          eventSource.close()
          eventSource = null
        }
        if (!pollingTimer) {
          pollingTimer = setInterval(fetchTasks, 5000)
        }
      }
    } catch {
      if (!pollingTimer) {
        pollingTimer = setInterval(fetchTasks, 5000)
      }
    }
  }

  function stopSSE() {
    if (eventSource) {
      eventSource.close()
      eventSource = null
    }
    if (pollingTimer) {
      clearInterval(pollingTimer)
      pollingTimer = null
    }
    isConnected.value = false
  }

  async function startDownload(payload: {
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
  }) {
    const res = await api.startEpisodeDownload(payload)
    await fetchTasks()
    return res
  }

  async function startBatchDownload(payload: {
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
  }) {
    const res = await api.startBatchDownload(payload)
    await fetchTasks()
    return res
  }

  async function pauseDownload(taskId: number | string) {
    await api.pauseDownload(taskId)
    await fetchTasks()
  }

  async function resumeDownload(taskId: number | string) {
    await api.resumeDownload(taskId)
    await fetchTasks()
  }

  async function cancelDownload(taskId: number | string) {
    await api.cancelDownload(taskId)
    await fetchTasks()
  }

  async function removeTask(taskId: number | string) {
    await api.removeDownloadTask(taskId)
    await fetchTasks()
  }

  async function retryDownload(taskId: number | string) {
    await api.resumeDownload(taskId)
    await fetchTasks()
  }

  async function redownloadTask(taskId: number | string) {
    const res = await api.redownloadTask(taskId)
    await fetchTasks()
    return res
  }

  async function verifyTask(taskId: number | string) {
    const res = await api.verifyTask(taskId)
    await fetchTasks()
    return res
  }

  async function verifyAllTasks() {
    const res = await api.verifyAllTasks()
    await fetchTasks()
    return res
  }

  async function moveTaskToTop(taskId: number | string) {
    const res = await api.moveTaskToTop(taskId)
    await fetchTasks()
    return res
  }

  async function moveSeriesToTop(animeName: string) {
    const res = await api.moveSeriesToTop(animeName)
    await fetchTasks()
    return res
  }

  async function reorderTasks(orderedIds: (string | number)[]) {
    const res = await api.reorderTasks(orderedIds)
    await fetchTasks()
    return res
  }

  async function setTaskSpeedLimit(taskId: number | string, limitBytes: number) {
    const res = await api.setTaskSpeedLimit(taskId, limitBytes)
    await fetchTasks()
    return res
  }

  async function getQuickSettings() {
    return api.getDownloadSettings()
  }

  async function saveQuickSettings(settings: any) {
    return api.saveDownloadSettings(settings)
  }

  async function pauseAll() {
    await api.pauseAllDownloads()
    await fetchTasks()
  }

  async function resumeAll() {
    await api.resumeAllDownloads()
    await fetchTasks()
  }

  async function cancelAll() {
    await api.cancelAllDownloads()
    await fetchTasks()
  }

  async function cleanCompleted() {
    await api.cleanCompletedDownloads()
    await fetchTasks()
  }

  function toggleDrawer() {
    isDrawerOpen.value = !isDrawerOpen.value
  }

  return {
    tasks,
    stats,
    isDrawerOpen,
    isConnected,
    fetchTasks,
    startSSE,
    stopSSE,
    startDownload,
    startBatchDownload,
    pauseDownload,
    resumeDownload,
    cancelDownload,
    removeTask,
    retryDownload,
    redownloadTask,
    verifyTask,
    verifyAllTasks,
    moveTaskToTop,
    moveSeriesToTop,
    reorderTasks,
    setTaskSpeedLimit,
    getQuickSettings,
    saveQuickSettings,
    pauseAll,
    resumeAll,
    cancelAll,
    cleanCompleted,
    toggleDrawer,
  }
})
