import type {
  PlaybackState,
  PlaybackOpen,
  PlaybackTrack,
  PlaybackCheckpoint,
  ExternalPlayerSettings,
  ExternalPlayerLaunchResponse,
} from '@/types/api'
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '@/api/client'
import { episodeKey } from '@/utils/episodes'
import type { Episode, SubtitleTrack, SourceChallenge } from '@/types'
import { useVerificationStore, challengeFromError } from './verification'

export function playbackTrackKey(track: { kind?: string; srclang?: string; label?: string }) {
  return JSON.stringify([track.kind || 'subtitles', track.srclang || '', track.label || '']).slice(
    0,
    500,
  )
}

const LOCAL_PREF_LABELS = new Set(['Disque dur (Local)', 'Local (Disque)', 'Original (Local)'])

export function normalizeEpisodeVersion(version?: string | null): string {
  return (version || '').trim().toUpperCase()
}

export function episodeSeasonNumber(ep: Episode): number {
  const season = Number(ep.nativeMetadata?.season)
  return Number.isInteger(season) && season > 0 ? season : 0
}

export function sortEpisodesAscending(list: Episode[]): Episode[] {
  return [...list].sort((a, b) => {
    const seasonDiff = episodeSeasonNumber(a) - episodeSeasonNumber(b)
    if (seasonDiff !== 0) return seasonDiff
    const numA = Number(a.number)
    const numB = Number(b.number)
    if (Number.isFinite(numA) && Number.isFinite(numB) && numA !== numB) return numA - numB
    return String(a.number).localeCompare(String(b.number), undefined, {
      numeric: true,
      sensitivity: 'base',
    })
  })
}

export function findEpisodeIndex(list: Episode[], target: Episode | null): number {
  if (!target || !list.length) return -1
  if (target.downloadTaskId != null) {
    const targetId = String(target.downloadTaskId)
    const taskIdx = list.findIndex(
      (e) => e.downloadTaskId != null && String(e.downloadTaskId) === targetId,
    )
    if (taskIdx >= 0) return taskIdx
  }
  const key = episodeKey(target)
  const exactIdx = list.findIndex((e) => episodeKey(e) === key)
  if (exactIdx >= 0) return exactIdx
  const targetVer = normalizeEpisodeVersion(target.version)
  return list.findIndex(
    (e) =>
      String(e.number) === String(target.number) &&
      normalizeEpisodeVersion(e.version) === targetVer,
  )
}

export function sanitizeRemotePref(value: string | null | undefined, fallback: string): string {
  const cleaned = (value || '').trim()
  if (!cleaned || LOCAL_PREF_LABELS.has(cleaned)) return fallback
  return cleaned
}

export interface ExternalWatchPromptState {
  animeTitle: string
  animeUrl: string
  source: string
  episodeNumber: string | number
  version: string
  playerName: string
  fallback?: () => Promise<void>
}

export const usePlayerStore = defineStore('player', () => {
  const isOpen = ref(false)
  const animeTitle = ref('')
  const animeUrl = ref('')
  const source = ref('french-manga')
  const currentEpisode = ref<Episode | null>(null)
  const episodes = ref<Episode[]>([])

  const videoUrl = ref<string | null>(null)
  const subtitles = ref<SubtitleTrack[]>([])
  const selectedSubtitle = ref<string | null>(null)
  const isDownloaded = ref(false)
  const isHls = ref(false)
  const availableQualities = ref<Record<string, string>>({})
  const availableServers = ref<string[]>([])
  const selectedQuality = ref('HD')
  const selectedServer = ref('auto')
  const serverType = ref('En ligne')
  const isLoading = ref(false)
  const error = ref<string | null>(null)
  const challenges = ref<SourceChallenge[]>([])
  const externalPlayer = ref<ExternalPlayerSettings | null>(null)
  const externalLaunching = ref(false)
  const pendingExternalWatch = ref<ExternalWatchPromptState | null>(null)
  const canLaunchExternal = computed(() =>
    Boolean(externalPlayer.value?.available && externalPlayer.value?.configured),
  )
  const prefersExternal = computed(() =>
    Boolean(canLaunchExternal.value && externalPlayer.value?.preferExternal),
  )
  function clearVerification() {
    challenges.value = []
    useVerificationStore().clearPending('player-stream')
  }
  let requestVersion = 0

  const mediaEpoch = ref(0)
  const playback = ref<PlaybackState | null>(null)
  const resumePosition = ref<number | null>(null)
  const progressNotice = ref('')
  const audioTracks = ref<PlaybackTrack[]>([])
  const selectedAudio = ref<string | null>(null)
  let clock: { positionSeconds: number; durationSeconds: number } | null = null
  let lastSave = -Infinity,
    sequence = 0,
    lastFingerprint = ''

  function recordTime(position: number, duration: number) {
    if (!Number.isFinite(position) || !Number.isFinite(duration) || duration <= 0 || position < 0)
      return
    clock = {
      positionSeconds: Math.min(position, duration, 604800),
      durationSeconds: Math.min(duration, 604800),
    }
  }
  function selection() {
    const subtitle = subtitles.value.find((track) => track.src === selectedSubtitle.value)
    return {
      quality: selectedQuality.value,
      server: selectedServer.value,
      subtitle: subtitle ? playbackTrackKey(subtitle) : null,
      audio: selectedAudio.value,
    }
  }
  function savePlayback(final = false, ended = false): Promise<void> {
    const session = playback.value
    if (!session || !clock || !api.savePlaybackCheckpoint) return Promise.resolve()
    const fingerprint = JSON.stringify([session.sessionId, clock, selection(), ended])
    if (fingerprint === lastFingerprint || (!final && Date.now() - lastSave < 5000))
      return Promise.resolve()
    lastSave = Date.now()
    lastFingerprint = fingerprint
    const body: PlaybackCheckpoint = {
      sessionId: session.sessionId,
      sequence: ++sequence,
      ...clock,
      selection: selection(),
      final,
      ended,
    }
    return api
      .savePlaybackCheckpoint(body)
      .then((result) => {
        if (playback.value?.sessionId === session.sessionId)
          progressNotice.value =
            result?.reason === 'superseded'
              ? 'Une autre fenêtre a repris la lecture de cet épisode.'
              : ''
      })
      .catch(() => {
        if (playback.value?.sessionId === session.sessionId) {
          progressNotice.value = 'La progression n’a pas pu être enregistrée.'
          lastFingerprint = ''
        }
      })
  }
  async function loadPlayback(body: PlaybackOpen, request: number) {
    ++mediaEpoch.value
    playback.value = null
    resumePosition.value = null
    clock = null
    sequence = 0
    lastSave = -Infinity
    lastFingerprint = ''
    progressNotice.value = ''
    audioTracks.value = []
    selectedAudio.value = null
    if (!api.openPlaybackSession) return
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 2000)
    try {
      const result = await api.openPlaybackSession(body, controller.signal)
      if (request !== requestVersion) return
      playback.value = result
      resumePosition.value = result.positionSeconds
      selectedQuality.value = result.selection.quality
      selectedServer.value = result.selection.server
      selectedAudio.value = result.selection.audio
    } catch {
      if (request === requestVersion)
        progressNotice.value = 'La reprise de lecture est momentanément indisponible.'
    } finally {
      clearTimeout(timer)
    }
  }
  function chooseSubtitles() {
    const choice = playback.value?.selection.subtitle
    selectedSubtitle.value =
      choice === null
        ? null
        : choice && choice !== 'auto'
          ? subtitles.value.find((track) => playbackTrackKey(track) === choice)?.src || null
          : subtitles.value[0]?.src || null
  }

  const hasNext = computed(() => {
    const idx = findEpisodeIndex(episodes.value, currentEpisode.value)
    return idx >= 0 && idx < episodes.value.length - 1
  })

  const hasPrev = computed(() => {
    const idx = findEpisodeIndex(episodes.value, currentEpisode.value)
    return idx > 0
  })

  async function resolveStream() {
    if (!currentEpisode.value) return
    const request = ++requestVersion
    clearVerification()
    const targetUrl = currentEpisode.value.playerUrl || currentEpisode.value.downloadPageUrl
    if (!targetUrl) {
      error.value = 'Aucun lien de streaming disponible pour cet épisode.'
      isLoading.value = false
      return
    }

    const reqServer = sanitizeRemotePref(selectedServer.value, 'auto')
    const reqQuality = sanitizeRemotePref(selectedQuality.value, 'auto')
    selectedServer.value = reqServer
    selectedQuality.value = sanitizeRemotePref(selectedQuality.value, 'HD')

    isLoading.value = true
    error.value = null
    videoUrl.value = null
    isHls.value = false

    try {
      const res = await api.resolveVideoStream({
        animeName: animeTitle.value,
        episodeNumber: currentEpisode.value.number,
        episodeUrl: targetUrl,
        animeUrl: animeUrl.value,
        version: currentEpisode.value.version || '',
        source: source.value,
        server: reqServer !== 'auto' ? reqServer : undefined,
        quality: reqQuality !== 'auto' ? reqQuality : undefined,
      })
      if (request !== requestVersion) return

      const finalUrl = res.streamUrl || res.videoUrl
      if (res && finalUrl) {
        videoUrl.value = finalUrl
        subtitles.value = res.subtitles || []
        chooseSubtitles()
        const downloaded = Boolean(res.isDownloaded)
        isDownloaded.value = downloaded
        isHls.value = !downloaded && (Boolean(res.isHls) || finalUrl.includes('.m3u8'))

        const qMap = res.qualities || res.videoQualities || {}
        availableQualities.value = qMap

        if (res.availableServers) availableServers.value = res.availableServers
        if (res.selectedQuality) selectedQuality.value = res.selectedQuality
        if (res.serverType) {
          serverType.value = res.serverType
          if (
            !downloaded &&
            selectedServer.value === 'auto' &&
            sanitizeRemotePref(res.serverType, 'auto') !== 'auto'
          ) {
            selectedServer.value = res.serverType
          }
        }
      } else {
        error.value = res.error || "Impossible d'extraire la vidéo directe pour cet hébergeur."
      }
    } catch (e: any) {
      if (request !== requestVersion) return
      const challenge = challengeFromError(e)
      if (challenge) {
        challenges.value = [challenge]
        useVerificationStore().waitForVerification('player-stream', [challenge], async () => {
          if (request === requestVersion && isOpen.value) await resolveStream()
        })
      }
      error.value = e.message || 'Erreur lors de la résolution du flux vidéo.'
    } finally {
      if (request === requestVersion) isLoading.value = false
    }
  }

  async function openPlayer(
    title: string,
    url: string,
    src: string,
    episode: Episode,
    allEps: Episode[] = [],
  ) {
    void savePlayback(true)
    ++mediaEpoch.value
    clearVerification()
    videoUrl.value = null
    error.value = null
    availableQualities.value = {}
    availableServers.value = []
    isDownloaded.value = false
    isHls.value = false
    isLoading.value = true
    const openRequest = ++requestVersion
    animeTitle.value = title
    animeUrl.value = url
    source.value = src
    const targetVer = normalizeEpisodeVersion(episode.version)
    const matching = allEps.filter((e) => normalizeEpisodeVersion(e.version) === targetVer)
    if (findEpisodeIndex(matching, episode) < 0) matching.push(episode)
    const sorted = sortEpisodesAscending(matching)
    episodes.value = sorted
    const idx = findEpisodeIndex(sorted, episode)
    currentEpisode.value = idx >= 0 ? sorted[idx] : episode
    isOpen.value = true
    selectedServer.value = 'auto'
    selectedQuality.value = 'HD'
    subtitles.value = []
    selectedSubtitle.value = null
    await loadPlayback(
      {
        source: src,
        animeUrl: url,
        animeName: title,
        episodeNumber: Number(episode.number),
        version: episode.version || '',
      },
      openRequest,
    )
    if (openRequest !== requestVersion) return
    await resolveStream()
  }

  function closePlayer() {
    clearVerification()
    void savePlayback(true)
    ++mediaEpoch.value
    playback.value = null
    resumePosition.value = null
    clock = null
    ++requestVersion
    isOpen.value = false
    videoUrl.value = null
    currentEpisode.value = null
    error.value = null
    subtitles.value = []
    selectedSubtitle.value = null
    availableQualities.value = {}
    availableServers.value = []
    isDownloaded.value = false
    isHls.value = false
    isLoading.value = false
  }

  async function loadLocalEpisode(episode: Episode, request: number) {
    const taskId = episode.downloadTaskId
    if (taskId == null) return
    clearVerification()
    currentEpisode.value = episode
    isOpen.value = true
    isLoading.value = false
    error.value = null
    isDownloaded.value = true
    isHls.value = false
    videoUrl.value = `/api/media/stream/${encodeURIComponent(taskId)}`
    availableQualities.value = {}
    availableServers.value = []
    serverType.value = 'Local (Disque)'
    selectedServer.value = 'auto'
    selectedQuality.value = 'HD'
    subtitles.value = []
    selectedSubtitle.value = null
    await loadPlayback({ taskId: String(taskId) }, request)
    if (request !== requestVersion) return
    if (playback.value) {
      if (playback.value.animeUrl) animeUrl.value = playback.value.animeUrl
      if (playback.value.source) source.value = playback.value.source
      if (currentEpisode.value && typeof playback.value.version === 'string')
        currentEpisode.value.version = playback.value.version
      const listMatch = episodes.value.find(
        (e) => e.downloadTaskId != null && String(e.downloadTaskId) === String(taskId),
      )
      if (listMatch && typeof playback.value.version === 'string')
        listMatch.version = playback.value.version
    }
    try {
      const tracks = await api.getLocalSubtitles(taskId)
      if (request !== requestVersion) return
      subtitles.value = tracks
      chooseSubtitles()
    } catch {
      // Optional captions must never prevent the local video from playing.
    }
  }

  async function stepEpisode(delta: 1 | -1) {
    const idx = findEpisodeIndex(episodes.value, currentEpisode.value)
    const nextIdx = idx + delta
    if (idx < 0 || nextIdx < 0 || nextIdx >= episodes.value.length) return
    const target = episodes.value[nextIdx]
    void savePlayback(true)
    ++mediaEpoch.value
    const request = ++requestVersion
    clearVerification()
    error.value = null
    videoUrl.value = null
    subtitles.value = []
    selectedSubtitle.value = null
    availableQualities.value = {}
    availableServers.value = []
    isDownloaded.value = false
    isHls.value = false
    selectedServer.value = 'auto'
    selectedQuality.value = 'HD'

    if (target.downloadTaskId != null && !target.playerUrl && !target.downloadPageUrl) {
      await loadLocalEpisode(target, request)
      return
    }

    isLoading.value = true
    currentEpisode.value = target
    await loadPlayback(
      {
        source: source.value,
        animeUrl: animeUrl.value,
        animeName: animeTitle.value,
        episodeNumber: Number(target.number),
        version: target.version || '',
      },
      request,
    )
    selectedServer.value = sanitizeRemotePref(selectedServer.value, 'auto')
    selectedQuality.value = sanitizeRemotePref(selectedQuality.value, 'HD')
    if (request !== requestVersion) return
    await resolveStream()
  }

  async function playNext() {
    await stepEpisode(1)
  }

  async function playPrev() {
    await stepEpisode(-1)
  }

  async function changeServer(srv: string) {
    void savePlayback(true)
    resumePosition.value = clock?.positionSeconds ?? null
    selectedServer.value = srv
    await resolveStream()
  }

  async function changeQuality(q: string) {
    void savePlayback(true)
    resumePosition.value = clock?.positionSeconds ?? null
    selectedQuality.value = q
    if (availableQualities.value && availableQualities.value[q]) {
      videoUrl.value = availableQualities.value[q]
    } else {
      await resolveStream()
    }
  }

  function changeSubtitle(src: string | null) {
    selectedSubtitle.value = src
    if (playback.value) playback.value.selection.subtitle = selection().subtitle
    void savePlayback(true)
  }

  async function playLocalFile(
    taskId: string | number,
    title: string,
    epNum: number | string,
    fileName?: string,
    playlist: Episode[] = [],
    knownAnimeUrl = '',
  ) {
    void savePlayback(true)
    ++mediaEpoch.value
    const request = ++requestVersion
    animeTitle.value = title
    animeUrl.value = knownAnimeUrl
    source.value = 'local'
    const epObj: Episode = {
      number: epNum,
      title: fileName || `Épisode ${epNum}`,
      version: '',
      isDownloaded: true,
      downloadTaskId: taskId,
    }
    if (playlist.length) {
      const combined = playlist.map((item) => ({ ...item }))
      if (findEpisodeIndex(combined, epObj) < 0) combined.push(epObj)
      const sorted = sortEpisodesAscending(combined)
      episodes.value = sorted
      const activeIdx = findEpisodeIndex(sorted, epObj)
      await loadLocalEpisode(activeIdx >= 0 ? sorted[activeIdx] : epObj, request)
    } else {
      episodes.value = []
      await loadLocalEpisode(epObj, request)
    }
  }

  function setExternalPlayerConfig(config: ExternalPlayerSettings | null) {
    externalPlayer.value = config
  }

  async function loadExternalPlayerConfig(force = false) {
    if ((!force && externalPlayer.value) || !api.getExternalPlayerSettings) return
    try {
      externalPlayer.value = await api.getExternalPlayerSettings()
    } catch {
      // Leave null so the built-in player remains available seamlessly.
    }
  }

  function dismissExternalWatch() {
    pendingExternalWatch.value = null
  }

  function triggerAndroidExternalIntent(res: ExternalPlayerLaunchResponse) {
    if (res.mode !== 'android_intent' || !res.androidIntent) return
    if (typeof window === 'undefined') {
      throw new Error('Pont Android indisponible.')
    }
    const bridge = (
      window as Window & { AnimeLabAndroid?: { openExternalPlayer?: (payload: string) => string } }
    ).AnimeLabAndroid
    if (!bridge || typeof bridge.openExternalPlayer !== 'function') {
      throw new Error('Pont Android indisponible.')
    }
    const raw = bridge.openExternalPlayer(JSON.stringify(res.androidIntent))
    const parsed = raw ? (JSON.parse(raw) as { launched?: unknown; error?: string }) : null
    if (!parsed?.launched) {
      throw new Error(parsed?.error || 'Impossible d’ouvrir le lecteur externe.')
    }
  }

  async function launchCurrentInExternalPlayer(): Promise<ExternalPlayerLaunchResponse> {
    if (!currentEpisode.value || !api.launchExternalPlayer) {
      throw new Error('Aucun épisode prêt pour le lecteur externe.')
    }
    const title = `${animeTitle.value} - Épisode ${currentEpisode.value.number}`
    const taskId =
      isDownloaded.value && currentEpisode.value.downloadTaskId != null
        ? String(currentEpisode.value.downloadTaskId)
        : null
    const payload = taskId
      ? { taskId, title }
      : videoUrl.value
        ? {
            streamUrl: videoUrl.value,
            isHls: isHls.value,
            title,
            subtitles: subtitles.value,
          }
        : null
    if (!payload) {
      throw new Error('Aucun flux disponible pour le lecteur externe.')
    }

    externalLaunching.value = true
    try {
      const res = await api.launchExternalPlayer(payload)
      triggerAndroidExternalIntent(res)
      pendingExternalWatch.value = {
        animeTitle: animeTitle.value,
        animeUrl: animeUrl.value || playback.value?.animeUrl || '',
        source: source.value,
        episodeNumber: currentEpisode.value.number,
        version: currentEpisode.value.version || playback.value?.version || '',
        playerName: res.player,
      }
      return res
    } finally {
      externalLaunching.value = false
    }
  }

  async function launchEpisodeExternal(params: {
    title: string
    animeUrl: string
    source: string
    episode: Episode
    allEpisodes?: Episode[]
    taskId?: string | number | null
  }): Promise<ExternalPlayerLaunchResponse> {
    if (!api.launchExternalPlayer) {
      throw new Error('Lecteur externe indisponible.')
    }
    const displayTitle = `${params.title} - Épisode ${params.episode.number}`
    externalLaunching.value = true
    try {
      let launchPayload: {
        taskId?: string | null
        streamUrl?: string | null
        isHls?: boolean
        title?: string
        subtitles?: SubtitleTrack[]
      }
      let fallback: () => Promise<void>

      if (params.taskId != null) {
        launchPayload = { taskId: String(params.taskId), title: displayTitle }
        fallback = async () => {
          await playLocalFile(
            params.taskId!,
            params.title,
            params.episode.number,
            params.episode.title,
            params.allEpisodes || [],
          )
        }
      } else {
        const targetUrl = params.episode.playerUrl || params.episode.downloadPageUrl
        if (!targetUrl) {
          throw new Error('Aucun lien de streaming disponible pour cet épisode.')
        }
        const streamRes = await api.resolveVideoStream({
          animeName: params.title,
          episodeNumber: params.episode.number,
          episodeUrl: targetUrl,
          animeUrl: params.animeUrl,
          version: params.episode.version || '',
          source: params.source,
        })
        const finalUrl = streamRes.streamUrl || streamRes.videoUrl
        if (!finalUrl) {
          throw new Error(
            streamRes.error || "Impossible d'extraire la vidéo directe pour cet hébergeur.",
          )
        }
        const streamTaskId =
          streamRes.isDownloaded && (streamRes as { taskId?: string | number }).taskId != null
            ? String((streamRes as { taskId?: string | number }).taskId)
            : null
        launchPayload = streamTaskId
          ? { taskId: streamTaskId, title: displayTitle }
          : {
              streamUrl: finalUrl,
              isHls: Boolean(streamRes.isHls) || finalUrl.includes('.m3u8'),
              title: displayTitle,
              subtitles: streamRes.subtitles || [],
            }
        fallback = async () => {
          await openPlayer(
            params.title,
            params.animeUrl,
            params.source,
            params.episode,
            params.allEpisodes || [],
          )
        }
      }

      const res = await api.launchExternalPlayer(launchPayload)
      triggerAndroidExternalIntent(res)
      pendingExternalWatch.value = {
        animeTitle: params.title,
        animeUrl: params.animeUrl,
        source: params.source,
        episodeNumber: params.episode.number,
        version: params.episode.version || '',
        playerName: res.player,
        fallback,
      }
      return res
    } finally {
      externalLaunching.value = false
    }
  }

  return {
    mediaEpoch,
    playback,
    resumePosition,
    progressNotice,
    audioTracks,
    selectedAudio,
    recordTime,
    savePlayback,
    isOpen,
    animeTitle,
    animeUrl,
    source,
    currentEpisode,
    episodes,
    videoUrl,
    subtitles,
    selectedSubtitle,
    isDownloaded,
    isHls,
    availableQualities,
    availableServers,
    selectedQuality,
    selectedServer,
    serverType,
    isLoading,
    error,
    challenges,
    externalPlayer,
    externalLaunching,
    pendingExternalWatch,
    canLaunchExternal,
    prefersExternal,
    hasNext,
    hasPrev,
    openPlayer,
    playLocalFile,
    closePlayer,
    playNext,
    playPrev,
    changeServer,
    changeQuality,
    changeSubtitle,
    resolveStream,
    setExternalPlayerConfig,
    loadExternalPlayerConfig,
    dismissExternalWatch,
    launchCurrentInExternalPlayer,
    launchEpisodeExternal,
  }
})
