<template>
  <div v-if="playerStore.isOpen" class="player-overlay" @click.self="playerStore.closePlayer">
    <div class="player-modal glass-panel">
      <!-- Player Header -->
      <div class="player-header">
        <div class="header-info">
          <div style="display: flex; align-items: center; gap: 8px">
            <h2 class="anime-title">{{ tx(playerStore.animeTitle) }}</h2>
            <span
              v-if="playerStore.isDownloaded"
              class="local-badge"
              :title="tx('Fichier disponible sur le disque dur')"
            >
              <HardDrive :size="13" aria-hidden="true" />
              <span>Local</span>
            </span>
          </div>
          <span class="episode-title">
            {{ tx('Épisode') }} {{ tx(playerStore.currentEpisode?.number) }} -
            {{ tx(playerStore.currentEpisode?.title || 'Streaming') }}
          </span>
        </div>

        <!-- Controls: Server, Quality, Subtitles & Close -->
        <div class="header-actions">
          <!-- Subtitle Selector -->
          <div v-if="playerStore.subtitles.length > 0" class="select-group">
            <label style="display: inline-flex; align-items: center; gap: 5px">
              <Subtitles :size="15" aria-hidden="true" />
              <span>{{ tx('Sous-titres :') }}</span>
            </label>
            <select
              :value="playerStore.selectedSubtitle || ''"
              class="header-select"
              @change="onSubtitleChange($event)"
            >
              <option value="">{{ tx('Désactivés') }}</option>
              <option v-for="sub in playerStore.subtitles" :key="sub.src" :value="sub.src">
                {{ tx(sub.label || 'Français') }}
              </option>
            </select>
          </div>

          <div v-if="playerStore.audioTracks.length > 1" class="select-group">
            <label>{{ tx('Audio :') }}</label>
            <select
              class="header-select"
              :value="playerStore.selectedAudio || ''"
              @change="onAudioChange"
            >
              <option
                v-for="track in playerStore.audioTracks"
                :key="playbackTrackKey(track)"
                :value="playbackTrackKey(track)"
              >
                {{ track.label || track.srclang }}
              </option>
            </select>
          </div>
          <!-- Server Selector -->
          <div v-if="playerStore.availableServers.length > 1" class="select-group">
            <label>{{ tx('Serveur :') }}</label>
            <select
              :value="playerStore.selectedServer"
              class="header-select"
              @change="onServerChange($event)"
            >
              <option v-for="srv in playerStore.availableServers" :key="srv" :value="srv">
                {{ tx(srv) }}
              </option>
            </select>
          </div>

          <!-- Quality Selector -->
          <div v-if="hasQualities" class="select-group">
            <label>{{ tx('Qualité :') }}</label>
            <select
              :value="playerStore.selectedQuality"
              class="header-select"
              @change="onQualityChange($event)"
            >
              <option v-for="q in Object.keys(playerStore.availableQualities)" :key="q" :value="q">
                {{ tx(q) }}
              </option>
            </select>
          </div>

          <button
            v-if="
              playerStore.canLaunchExternal && (playerStore.videoUrl || playerStore.isDownloaded)
            "
            type="button"
            class="btn btn-secondary btn-sm player-external-btn"
            :disabled="playerStore.externalLaunching"
            :title="tx('Ouvrir dans un lecteur externe')"
            @click="openInExternalPlayer"
          >
            <ExternalLink :size="15" aria-hidden="true" />
            <span class="player-external-label">{{ tx('Lecteur externe') }}</span>
          </button>

          <button
            type="button"
            class="btn-icon player-close-btn"
            :title="tx('Fermer (Échap)')"
            :aria-label="tx('Fermer (Échap)')"
            @click="playerStore.closePlayer"
          >
            <X :size="18" aria-hidden="true" />
          </button>
        </div>
      </div>

      <!-- Player Body -->
      <div class="player-body">
        <!-- Video element -->
        <video
          ref="videoRef"
          class="video-element"
          controls
          autoplay
          playsinline
          webkit-playsinline
          :crossorigin="videoCrossOrigin"
          @play="onPlay"
          @timeupdate="onTimeUpdate"
          @loadedmetadata="onMetadataLoaded"
          @pause="checkpoint"
          @ended="onEnded"
          @error="onMediaError"
        >
          <track
            v-for="(sub, i) in playerStore.subtitles"
            :key="sub.src || i"
            :kind="sub.kind || 'captions'"
            :label="tx(sub.label || 'Français')"
            :srclang="sub.srclang || 'fr'"
            :src="sub.src"
            :default="playerStore.selectedSubtitle === sub.src"
            @load="syncSubtitleTracks"
          />
        </video>

        <!-- Loading overlay -->
        <div v-if="playerStore.isLoading" class="player-state-overlay">
          <div class="spinner"></div>
          <p>{{ tx('Résolution du flux vidéo...') }}</p>
        </div>

        <!-- Error overlay -->
        <div v-if="playerStore.error" class="player-state-overlay error">
          <svg
            viewBox="0 0 24 24"
            width="48"
            height="48"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
          >
            <circle cx="12" cy="12" r="10"></circle>
            <line x1="12" y1="8" x2="12" y2="12"></line>
            <line x1="12" y1="16" x2="12.01" y2="16"></line>
          </svg>
          <p>{{ tx(playerStore.error) }}</p>
          <div class="player-error-actions">
            <button type="button" class="btn btn-primary" @click="retryPlayback">
              {{ tx('Réessayer') }}
            </button>
            <button
              v-if="
                playerStore.canLaunchExternal && (playerStore.videoUrl || playerStore.isDownloaded)
              "
              type="button"
              class="btn btn-secondary"
              :disabled="playerStore.externalLaunching"
              @click="openInExternalPlayer"
            >
              <ExternalLink :size="15" aria-hidden="true" />
              {{ tx('Ouvrir dans le lecteur externe') }}
            </button>
          </div>
        </div>
      </div>

      <p v-if="externalError" role="status" class="playback-notice playback-notice-error">
        {{ tx(externalError) }}
      </p>
      <div v-if="playerStore.pendingExternalWatch" class="external-watch-bar" role="status">
        <span>
          {{ tx('Lecture dans le lecteur externe') }} ({{
            tx(playerStore.pendingExternalWatch.playerName)
          }})
        </span>
        <div class="external-watch-bar-actions">
          <button
            v-if="playerStore.pendingExternalWatch.animeUrl || playerStore.animeUrl"
            type="button"
            class="btn btn-primary btn-sm"
            @click="markExternalEpisodeWatched"
          >
            <Check :size="14" aria-hidden="true" />
            {{ tx('Marquer comme vu') }}
          </button>
          <button
            type="button"
            class="btn btn-secondary btn-sm"
            @click="playerStore.dismissExternalWatch"
          >
            {{ tx('Fermer') }}
          </button>
        </div>
      </div>
      <p v-if="playerStore.progressNotice" role="status" class="playback-notice">
        {{ tx(playerStore.progressNotice) }}
      </p>
      <!-- Player Footer (Episode Navigation) -->
      <div v-if="playerStore.challenges.length" class="player-verification">
        <VerificationPrompt :challenges="playerStore.challenges" />
      </div>
      <div class="player-footer">
        <button
          type="button"
          class="btn btn-secondary"
          :disabled="!playerStore.hasPrev"
          @click="playerStore.playPrev"
        >
          <SkipBack :size="15" aria-hidden="true" />
          {{ tx('Épisode précédent') }}
        </button>

        <span class="source-tag">
          {{ tx('Source :') }} {{ tx(playerStore.source) }} •
          {{ tx(playerStore.serverType || 'Direct') }}
        </span>

        <button
          type="button"
          class="btn btn-primary"
          :disabled="!playerStore.hasNext"
          @click="playerStore.playNext"
        >
          {{ tx('Épisode suivant') }}
          <SkipForward :size="15" aria-hidden="true" />
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { tx } from '@/utils/locale'
import { ref, watch, onMounted, onUnmounted, computed } from 'vue'
import {
  Check,
  ExternalLink,
  HardDrive,
  SkipBack,
  SkipForward,
  Subtitles,
  X,
} from 'lucide-vue-next'
import Hls from 'hls.js'
import { usePlayerStore, playbackTrackKey } from '@/stores/player'
import { useLibraryStore } from '@/stores/library'
import VerificationPrompt from '@/components/VerificationPrompt.vue'

const playerStore = usePlayerStore()
const libraryStore = useLibraryStore()

const videoRef = ref<HTMLVideoElement | null>(null)
let hlsInstance: Hls | null = null
let attachedVideo: HTMLVideoElement | null = null
let markedWatched = false
let attachedEpoch = -1
let attachedUrl: string | null = null
const externalError = ref('')
function ownsMedia() {
  return (
    !!attachedVideo &&
    attachedVideo === videoRef.value &&
    attachedEpoch === playerStore.mediaEpoch &&
    attachedUrl === playerStore.videoUrl
  )
}

const hasQualities = computed(() => {
  return Object.keys(playerStore.availableQualities || {}).length > 1
})

const videoCrossOrigin = computed(() =>
  playerStore.videoUrl?.startsWith('/') || playerStore.subtitles.length > 0
    ? 'anonymous'
    : undefined,
)

function setKeepScreenOn(enabled: boolean) {
  if (typeof window === 'undefined') return
  try {
    ;(
      window as Window & { AnimeLabAndroid?: { setKeepScreenOn?: (value: boolean) => void } }
    ).AnimeLabAndroid?.setKeepScreenOn?.(enabled)
  } catch {
    /* ignore unavailable Android hook */
  }
}

function onPlay() {
  setKeepScreenOn(true)
}

function syncSubtitleTracks() {
  if (!videoRef.value) return
  const tracks = videoRef.value.textTracks
  const targetSrc = playerStore.selectedSubtitle

  for (let i = 0; i < tracks.length; i++) {
    const track = tracks[i]
    if (!targetSrc) {
      track.mode = 'disabled'
    } else {
      const sub = playerStore.subtitles[i]
      if (sub && sub.src === targetSrc) {
        track.mode = 'showing'
      } else {
        track.mode = 'disabled'
      }
    }
  }
}

function onSubtitleChange(e: Event) {
  const target = e.target as HTMLSelectElement
  playerStore.changeSubtitle(target.value || null)
  syncSubtitleTracks()
}

type NativeAudioTrack = { language: string; label: string; enabled: boolean }
function nativeAudio(): NativeAudioTrack[] {
  const tracks = (
    videoRef.value as (HTMLVideoElement & { audioTracks?: ArrayLike<NativeAudioTrack> }) | null
  )?.audioTracks
  return tracks ? Array.from(tracks) : []
}
function syncAudio() {
  if (hlsInstance?.audioTracks.length) {
    const index = hlsInstance.audioTracks.findIndex(
      (track) =>
        playbackTrackKey({ kind: 'audio', srclang: track.lang || '', label: track.name }) ===
        playerStore.selectedAudio,
    )
    if (index >= 0) hlsInstance.audioTrack = index
    return
  }
  const tracks = nativeAudio()
  if (
    !tracks.some(
      (track) =>
        playbackTrackKey({ kind: 'audio', srclang: track.language, label: track.label }) ===
        playerStore.selectedAudio,
    )
  )
    return
  for (const track of tracks)
    track.enabled =
      playbackTrackKey({ kind: 'audio', srclang: track.language, label: track.label }) ===
      playerStore.selectedAudio
}
function onAudioChange(event: Event) {
  playerStore.selectedAudio = (event.target as HTMLSelectElement).value || null
  syncAudio()
  void playerStore.savePlayback(true)
}
function applyResume() {
  const video = videoRef.value,
    position = playerStore.resumePosition
  if (
    !ownsMedia() ||
    !video ||
    position === null ||
    !Number.isFinite(video.duration) ||
    video.duration <= 0
  )
    return
  if (position > 0 && position < video.duration - 5) video.currentTime = position
  playerStore.resumePosition = null
}
function onMetadataLoaded() {
  if (!ownsMedia()) return
  applyResume()
  refreshAudioTracks()
  syncSubtitleTracks()
}
function refreshAudioTracks() {
  const tracks = nativeAudio()
  playerStore.audioTracks = hlsInstance?.audioTracks.length
    ? hlsInstance.audioTracks.map((track) => ({
        kind: 'audio',
        srclang: track.lang || '',
        label: track.name,
      }))
    : tracks.map((track) => ({ kind: 'audio', srclang: track.language, label: track.label }))
  if (
    playerStore.audioTracks.some((track) => playbackTrackKey(track) === playerStore.selectedAudio)
  )
    syncAudio()
  else {
    const active = tracks.find((track) => track.enabled)
    const selected =
      hlsInstance && hlsInstance.audioTrack >= 0
        ? playerStore.audioTracks[hlsInstance.audioTrack]
        : active
          ? { kind: 'audio', srclang: active.language, label: active.label }
          : undefined
    playerStore.selectedAudio = selected ? playbackTrackKey(selected) : null
  }
}
function checkpoint() {
  setKeepScreenOn(false)
  if (!videoRef.value || !ownsMedia()) return
  playerStore.recordTime(videoRef.value.currentTime, videoRef.value.duration)
  void playerStore.savePlayback(true)
}
function onEnded() {
  setKeepScreenOn(false)
  if (!ownsMedia()) return
  if (videoRef.value) playerStore.recordTime(videoRef.value.currentTime, videoRef.value.duration)
  void playerStore.savePlayback(true, true)
}
watch(
  () => playerStore.resumePosition,
  () => {
    if ((videoRef.value?.readyState || 0) >= 1) applyResume()
  },
)

function releaseVideo() {
  setKeepScreenOn(false)
  attachedUrl = null
  attachedEpoch = -1
  if (hlsInstance) {
    hlsInstance.destroy()
    hlsInstance = null
  }
  if (attachedVideo) {
    attachedVideo.pause()
    attachedVideo.removeAttribute('src')
    attachedVideo.load()
    attachedVideo = null
  }
}

function setupVideo(url: string | null) {
  releaseVideo()
  externalError.value = ''
  if (!url || !videoRef.value) return
  markedWatched = false
  playerStore.error = null
  attachedVideo = videoRef.value
  attachedUrl = url
  attachedEpoch = playerStore.mediaEpoch
  const owner = attachedVideo,
    epoch = attachedEpoch

  const isHls = playerStore.isHls || url.includes('.m3u8')
  let networkRetries = 0
  let mediaRetries = 0

  if (isHls && Hls.isSupported()) {
    hlsInstance = new Hls({
      enableWorker: true,
      lowLatencyMode: true,
    })
    hlsInstance.loadSource(url)
    hlsInstance.attachMedia(videoRef.value)
    hlsInstance.on(Hls.Events.MANIFEST_PARSED, () => {
      if (owner !== attachedVideo || epoch !== attachedEpoch || url !== attachedUrl) return
      videoRef.value?.play().catch(() => {})
      syncSubtitleTracks()
      refreshAudioTracks()
    })
    hlsInstance.on(Hls.Events.ERROR, (_event, data) => {
      if (owner !== attachedVideo || epoch !== attachedEpoch || url !== attachedUrl) return
      if (!data.fatal) return
      if (
        hlsInstance &&
        Hls.ErrorTypes?.NETWORK_ERROR &&
        data.type === Hls.ErrorTypes.NETWORK_ERROR &&
        networkRetries < 1
      ) {
        networkRetries++
        hlsInstance.startLoad()
        return
      }
      if (
        hlsInstance &&
        Hls.ErrorTypes?.MEDIA_ERROR &&
        data.type === Hls.ErrorTypes.MEDIA_ERROR &&
        mediaRetries < 1
      ) {
        mediaRetries++
        hlsInstance.recoverMediaError()
        return
      }
      setKeepScreenOn(false)
      playerStore.error =
        'Impossible de lire ce flux vidéo. Réessayez ou choisissez un autre serveur.'
    })
  } else {
    videoRef.value.src = url
    videoRef.value.load()
    videoRef.value.play().catch(() => {})
    syncSubtitleTracks()
  }
}

watch(
  [videoRef, () => playerStore.videoUrl],
  ([, newUrl]) => {
    setupVideo(newUrl)
  },
  // Opening the modal and setting its URL happen in the same render cycle.
  // Wait for the <video> ref; also reload when reopening the very same file.
  { flush: 'post', immediate: true },
)

watch(
  () => playerStore.subtitles,
  () => {
    syncSubtitleTracks()
  },
  { deep: true, flush: 'post' },
)

function onMediaError() {
  const error = videoRef.value?.error
  if (!ownsMedia() || !playerStore.videoUrl || !error || error.code === 1) return
  playerStore.error =
    error.code === 2
      ? 'Impossible de charger la vidéo. Vérifiez que le fichier existe et que le serveur est accessible.'
      : error.code === 3
        ? 'Le navigateur ne peut pas décoder cette vidéo. Le fichier peut être endommagé ou utiliser un codec non pris en charge.'
        : 'Ce format vidéo ne peut pas être lu dans ce navigateur, ou le fichier est inaccessible. Essayez de l’ouvrir avec un lecteur comme VLC.'
}

function retryPlayback() {
  if (playerStore.isDownloaded && playerStore.videoUrl) {
    setupVideo(playerStore.videoUrl)
  } else {
    void playerStore.resolveStream()
  }
}

async function openInExternalPlayer() {
  externalError.value = ''
  if (videoRef.value && !videoRef.value.paused) {
    checkpoint()
    videoRef.value.pause()
  }
  try {
    await playerStore.launchCurrentInExternalPlayer()
  } catch (err) {
    externalError.value =
      err instanceof Error ? err.message : 'Impossible d’ouvrir le lecteur externe.'
  }
}

function markExternalEpisodeWatched() {
  const prompt = playerStore.pendingExternalWatch
  const animeUrl = prompt?.animeUrl || playerStore.animeUrl
  const epNum = prompt?.episodeNumber ?? playerStore.currentEpisode?.number
  if (!animeUrl || epNum == null) {
    playerStore.dismissExternalWatch()
    return
  }
  markedWatched = true
  void libraryStore.markWatched(
    animeUrl,
    epNum,
    true,
    prompt?.version || playerStore.currentEpisode?.version || '',
    prompt?.animeTitle || playerStore.animeTitle,
  )
  playerStore.dismissExternalWatch()
}

function onServerChange(e: Event) {
  const target = e.target as HTMLSelectElement
  playerStore.changeServer(target.value)
}

function onQualityChange(e: Event) {
  const target = e.target as HTMLSelectElement
  playerStore.changeQuality(target.value)
}

function onTimeUpdate() {
  if (!videoRef.value || !ownsMedia()) return
  playerStore.recordTime(videoRef.value.currentTime, videoRef.value.duration)
  void playerStore.savePlayback()
  if (markedWatched) return
  const current = videoRef.value.currentTime
  const total = videoRef.value.duration
  if (total > 0 && current / total >= 0.85) {
    markedWatched = true
    if (playerStore.currentEpisode && playerStore.animeUrl) {
      libraryStore.markWatched(
        playerStore.animeUrl,
        playerStore.currentEpisode.number,
        true,
        playerStore.currentEpisode.version || '',
        playerStore.animeTitle,
      )
    }
  }
}

function onKeyDown(e: KeyboardEvent) {
  if (!playerStore.isOpen) return
  if (e.key === 'Escape') {
    playerStore.closePlayer()
  } else if (e.key === ' ' && e.target === document.body) {
    e.preventDefault()
    if (videoRef.value) {
      if (videoRef.value.paused) videoRef.value.play().catch(() => {})
      else videoRef.value.pause()
    }
  }
}

watch(
  () => playerStore.isOpen,
  (open) => {
    if (open && !playerStore.externalPlayer) {
      void playerStore.loadExternalPlayerConfig()
    }
  },
  { immediate: true },
)

onMounted(() => {
  window.addEventListener('keydown', onKeyDown)
  window.addEventListener('pagehide', checkpoint)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeyDown)
  window.removeEventListener('pagehide', checkpoint)
  checkpoint()
  releaseVideo()
  setKeepScreenOn(false)
})
</script>

<style scoped>
.playback-notice {
  margin: 0;
  padding: 6px 20px;
  color: #cbd5e1;
  font-size: 0.85rem;
  flex-shrink: 0;
}
.playback-notice-error {
  color: #fda4af;
}
.player-error-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 10px;
}
.player-external-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.16);
  color: #f8fafc;
}
.player-external-btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.15);
}
.external-watch-bar {
  flex-shrink: 0;
  padding: 8px 18px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  font-size: 0.84rem;
  color: #e2e8f0;
  background: rgba(255, 255, 255, 0.05);
  border-top: 1px solid rgba(255, 255, 255, 0.1);
}
.external-watch-bar-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.player-overlay {
  position: fixed;
  inset: 0;
  height: 100dvh;
  background: rgba(0, 0, 0, 0.88);
  backdrop-filter: blur(10px);
  z-index: 300;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: max(16px, env(safe-area-inset-top, 0px)) max(16px, env(safe-area-inset-right, 0px))
    max(16px, env(safe-area-inset-bottom, 0px)) max(16px, env(safe-area-inset-left, 0px));
  animation: fadeIn 0.25s ease;
}

.player-modal {
  color-scheme: dark;
  width: 100%;
  max-width: 1100px;
  max-height: 94dvh;
  display: flex;
  flex-direction: column;
  background: rgba(14, 18, 30, 0.96);
  color: #f8fafc;
  border: 1px solid rgba(255, 255, 255, 0.14);
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.8);
  border-radius: var(--radius, 12px);
  overflow: hidden;
}

.player-header {
  flex-shrink: 0;
  padding: 12px 18px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid rgba(255, 255, 255, 0.12);
  flex-wrap: wrap;
  gap: 10px;
}

.header-info {
  flex: 1 1 200px;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  overflow: hidden;
}

.anime-title {
  margin: 0;
  color: #f8fafc;
  font-size: 1.1rem;
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.local-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
  font-size: 0.72rem;
  background: rgba(16, 185, 129, 0.2);
  color: #34d399;
  border: 1px solid rgba(16, 185, 129, 0.3);
  padding: 2px 7px;
  border-radius: 9999px;
  font-weight: 600;
}

.episode-title {
  font-size: 0.85rem;
  color: #93c5fd;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.player-close-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 9999px;
  border: 1px solid rgba(255, 255, 255, 0.16);
  background: rgba(255, 255, 255, 0.08);
  color: #f8fafc;
  cursor: pointer;
}

.player-close-btn:hover {
  background: rgba(255, 255, 255, 0.16);
}

.select-group {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.82rem;
  color: #cbd5e1;
}

.header-select {
  background: #171c2c;
  border: 1px solid rgba(255, 255, 255, 0.16);
  border-radius: var(--radius-sm, 8px);
  color: #f8fafc;
  padding: 6px 10px;
  font-size: 0.82rem;
  outline: none;
}

.header-select option {
  background: #171c2c;
  color: #f8fafc;
}

.player-body {
  position: relative;
  flex: 1 1 auto;
  min-height: 0;
  width: 100%;
  max-height: 70dvh;
  aspect-ratio: 16 / 9;
  background: #000;
  display: flex;
  align-items: center;
  justify-content: center;
}

.video-element {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.player-state-overlay {
  position: absolute;
  inset: 0;
  padding: 20px;
  text-align: center;
  background: rgba(10, 13, 20, 0.9);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  color: #f8fafc;
}

.player-state-overlay.error {
  color: #fda4af;
}

.spinner {
  width: 44px;
  height: 44px;
  border: 3px solid rgba(var(--accent-rgb, 56, 189, 248), 0.22);
  border-top-color: var(--accent, #38bdf8);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.player-footer {
  flex-shrink: 0;
  padding: 12px 18px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-top: 1px solid rgba(255, 255, 255, 0.12);
  flex-wrap: wrap;
  gap: 10px;
}

.player-footer .btn-secondary {
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.16);
  color: #f8fafc;
}

.player-footer .btn-secondary:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.15);
}

.player-footer button:disabled {
  opacity: 0.4 !important;
  cursor: not-allowed;
  pointer-events: none;
}

.source-tag {
  font-size: 0.82rem;
  color: #94a3b8;
  text-align: center;
}

.player-verification {
  flex-shrink: 0;
  max-height: 35dvh;
  overflow: auto;
  padding: 0.75rem;
}

@media (max-width: 768px) {
  .player-overlay {
    padding: max(8px, env(safe-area-inset-top, 0px)) max(8px, env(safe-area-inset-right, 0px))
      max(8px, env(safe-area-inset-bottom, 0px)) max(8px, env(safe-area-inset-left, 0px));
  }

  .player-modal {
    max-height: 96dvh;
  }

  .player-header {
    padding: 10px 12px;
    gap: 8px;
  }

  .anime-title {
    font-size: 1rem;
  }

  .header-actions {
    width: 100%;
    justify-content: flex-end;
    gap: 8px;
  }

  .select-group {
    flex: 1 1 130px;
    min-width: 0;
  }

  .header-select {
    flex: 1;
    min-width: 0;
    min-height: 40px;
  }

  .player-close-btn {
    min-width: 44px;
    min-height: 44px;
  }

  .player-external-btn {
    min-height: 40px;
  }

  .external-watch-bar {
    padding: 8px 12px;
  }

  .player-footer {
    padding: 10px 12px;
    gap: 8px;
  }

  .source-tag {
    order: -1;
    flex: 1 0 100%;
    font-size: 0.78rem;
  }

  .player-footer button {
    flex: 1 1 0;
    min-width: 0;
    min-height: 44px;
    padding: 8px 10px;
    font-size: 13px;
  }
}

@media (max-height: 520px) and (orientation: landscape) {
  .player-overlay {
    padding: 0;
  }

  .player-modal {
    max-width: none;
    height: 100dvh;
    max-height: 100dvh;
    border-radius: 0;
    border: 0;
  }

  .player-header {
    padding: 6px 12px;
    gap: 8px;
    flex-wrap: nowrap;
  }

  .anime-title {
    font-size: 0.95rem;
  }

  .player-body {
    flex: 1 1 0;
    max-height: none;
    aspect-ratio: auto;
  }

  .player-footer {
    padding: 6px 12px;
    flex-wrap: nowrap;
  }

  .source-tag {
    display: none;
  }

  .player-footer button {
    min-height: 36px;
    padding: 4px 12px;
    font-size: 13px;
  }
}
</style>
