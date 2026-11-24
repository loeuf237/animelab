import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { test } from 'node:test'
import { parse, compileScript } from '@vue/compiler-sfc'
import ts from 'typescript'
import { createRenderer, nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
const inline = (code) => `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`
const vue = import.meta.resolve('vue')
function moduleUrl(source, imports) {
  let code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  }).outputText
  for (const [name, url] of Object.entries(imports))
    code = code
      .replaceAll(`'${name}'`, JSON.stringify(url))
      .replaceAll(`"${name}"`, JSON.stringify(url))
  return inline(code)
}
const apiUrl = inline('export const api={};')
const { api } = await import(apiUrl)
const storeUrl = moduleUrl(
  await readFile(new URL('../src/stores/player.ts', import.meta.url), 'utf8'),
  {
    './verification': inline(
      'export const useVerificationStore=()=>({clearPending(){},waitForVerification(){}}); export const challengeFromError=()=>null;',
    ),
    vue,
    pinia: import.meta.resolve('pinia'),
    '@/api/client': apiUrl,
    '@/utils/episodes': inline(
      'export const episodeKey=e=>JSON.stringify([e.number,e.version,e.playerUrl]);',
    ),
  },
)
const { usePlayerStore } = await import(storeUrl)
const { descriptor } = parse(
  await readFile(new URL('../src/components/VideoPlayerModal.vue', import.meta.url), 'utf8'),
)
const component = (
  await import(
    moduleUrl(
      compileScript(descriptor, { id: 'playback-regression', inlineTemplate: true }).content,
      {
        vue,
        '@/stores/player': storeUrl,
        '@/components/VerificationPrompt.vue': inline(
          'export default {props:["challenges"],render(){return null}};',
        ),
        '@/utils/locale': inline('export const tx=v=>String(v??"");'),
        '@/stores/library': inline('export const useLibraryStore=()=>({markWatched(){}});'),
        'lucide-vue-next': inline(
          'const Icon=()=>null; export const HardDrive=Icon, SkipBack=Icon, SkipForward=Icon, Subtitles=Icon, X=Icon;',
        ),
        'hls.js': inline(`export default class Hls {
 static Events={MANIFEST_PARSED:'manifest',ERROR:'error'};
 static isSupported(){return Boolean(globalThis.__hlsTest);}
 constructor(){this.audioTracks=[{lang:'en',name:'English'},{lang:'ja',name:'Japanese'}];this.audioTrack=0;this.handlers={};globalThis.__hlsInstance=this;}
 on(event,callback){this.handlers[event]=callback;}loadSource(){}attachMedia(){}destroy(){}
}`),
      },
    )
  )
).default
function mountPlayer() {
  const videos = []
  const node = (type, text = '') => ({ type, text, children: [], parent: null, props: {} })
  const renderer = createRenderer({
    createElement(type) {
      const el = node(type)
      if (type === 'video') {
        Object.assign(el, {
          textTracks: [],
          src: '',
          plays: 0,
          pauses: 0,
          loads: 0,
          error: null,
          play() {
            this.plays++
            return Promise.resolve()
          },
          pause() {
            this.pauses++
          },
          load() {
            this.loads++
          },
          removeAttribute(name) {
            if (name === 'src') this.src = ''
          },
        })
        videos.push(el)
      }
      return el
    },
    createText: (text) => node('text', text),
    createComment: (text) => node('comment', text),
    setText: (el, text) => (el.text = text),
    setElementText: (el, text) => (el.text = text),
    parentNode: (el) => el.parent,
    nextSibling: (el) => el.parent?.children[el.parent.children.indexOf(el) + 1] || null,
    patchProp: (el, key, old, value) => (el.props[key] = value),
    insert(el, parent, anchor = null) {
      if (el.parent) {
        const i = el.parent.children.indexOf(el)
        if (i >= 0) el.parent.children.splice(i, 1)
      }
      el.parent = parent
      const i = anchor ? parent.children.indexOf(anchor) : -1
      parent.children.splice(i < 0 ? parent.children.length : i, 0, el)
    },
    remove(el) {
      if (el.parent) {
        const i = el.parent.children.indexOf(el)
        if (i >= 0) el.parent.children.splice(i, 1)
      }
      el.parent = null
    },
  })
  const root = node('root'),
    app = renderer.createApp(component)
  app.mount(root)
  return { videos, app, root }
}
test('local video loads on opening, stops on close, reloads the same file, and exposes media errors', async (t) => {
  globalThis.window = { addEventListener() {}, removeEventListener() {} }
  setActivePinia(createPinia())
  api.getLocalSubtitles = async () => []
  const player = usePlayerStore()
  const { videos, app, root } = mountPlayer()
  t.after(() => {
    app.unmount()
    delete globalThis.window
  })
  await player.playLocalFile('task', 'Anime', 160, 'video.mp4')
  await nextTick()
  assert.equal(videos.length, 1)
  assert.equal(videos[0].src, '/api/media/stream/task')
  assert.ok(videos[0].plays > 0, 'the video ref must exist before loading the URL')
  player.closePlayer()
  await nextTick()
  assert.equal(videos[0].src, '')
  assert.ok(videos[0].pauses > 0)
  await player.playLocalFile('task', 'Anime', 160, 'video.mp4')
  await nextTick()
  assert.equal(videos.length, 2)
  assert.equal(videos[1].src, '/api/media/stream/task')
  videos[1].error = { code: 4 }
  videos[1].props.onError()
  await nextTick()
  assert.match(player.error, /format vidéo/)
  const buttons = []
  function walk(el) {
    if (el.type === 'button') buttons.push(el)
    for (const c of el.children) walk(c)
  }
  walk(root)
  const retry = buttons.find((b) => b.text === 'Réessayer')
  assert.ok(retry)
  const loads = videos[1].loads
  retry.props.onClick()
  await nextTick()
  assert.equal(player.error, null)
  assert.ok(videos[1].loads > loads)
})
test('subtitle tracks use the real file list and stale responses cannot replace a local video', async () => {
  setActivePinia(createPinia())
  const player = usePlayerStore()
  let finishRemote, finishOld
  api.resolveVideoStream = () => new Promise((resolve) => (finishRemote = resolve))
  const remote = player.openPlayer('Remote', 'remote', 'french-manga', {
    number: 1,
    playerUrl: 'https://example.org/1',
  })
  await Promise.resolve()
  api.getLocalSubtitles = () => new Promise((resolve) => (finishOld = resolve))
  const old = player.playLocalFile('old', 'Old', 1)
  await Promise.resolve()
  api.getLocalSubtitles = async () => [
    { src: '/api/media/subtitle/new/0', srclang: 'fr', label: 'French' },
  ]
  await player.playLocalFile('new', 'New', 2)
  finishOld([{ src: '/api/media/subtitle/old/0' }])
  await old
  finishRemote({ streamUrl: 'https://example.org/remote.mp4' })
  await remote
  assert.equal(player.videoUrl, '/api/media/stream/new')
  assert.equal(player.selectedSubtitle, '/api/media/subtitle/new/0')
  assert.equal(player.isDownloaded, true)
  player.closePlayer()
  api.getLocalSubtitles = async () => {
    throw new Error('optional subtitles failed')
  }
  await player.playLocalFile('none', 'No captions', 1)
  assert.equal(player.error, null)
  assert.deepEqual(player.subtitles, [])
  assert.equal(player.videoUrl, '/api/media/stream/none')
})

test('resume uses stable task identity, restores the time and preserves it through quality changes', async (t) => {
  globalThis.window = { addEventListener() {}, removeEventListener() {} }
  setActivePinia(createPinia())
  const writes = [],
    opens = []
  api.openPlaybackSession = async (body) => {
    opens.push(body)
    return {
      sessionId: 'a'.repeat(32),
      source: 'source',
      animeUrl: 'https://example.org/series',
      episodeNumber: 3,
      version: 'VF',
      positionSeconds: 130,
      durationSeconds: 1500,
      selection: { quality: '720p', server: 'auto', subtitle: null, audio: null },
    }
  }
  api.savePlaybackCheckpoint = async (body) => {
    writes.push(body)
    return { success: true, accepted: true }
  }
  api.getLocalSubtitles = async () => []
  const player = usePlayerStore(),
    { videos, app } = mountPlayer()
  t.after(() => {
    app.unmount()
    delete api.openPlaybackSession
    delete api.savePlaybackCheckpoint
    delete globalThis.window
  })
  await player.playLocalFile('downloaded-task', 'Series', 3)
  await nextTick()
  assert.deepEqual(opens, [{ taskId: 'downloaded-task' }])
  assert.equal(player.currentEpisode.version, 'VF')
  const video = videos[0]
  video.duration = 1500
  video.currentTime = 0
  video.readyState = 1
  video.props.onLoadedmetadata()
  assert.equal(video.currentTime, 130)
  video.currentTime = 225
  video.props.onTimeupdate()
  await Promise.resolve()
  const writeCount = writes.length
  video.currentTime = 226
  video.props.onTimeupdate()
  await Promise.resolve()
  assert.equal(writes.length, writeCount, 'timeupdates must be throttled')
  player.availableQualities = { '1080p': '/quality.mp4' }
  await player.changeQuality('1080p')
  await nextTick()
  video.currentTime = 0
  video.props.onLoadedmetadata()
  assert.equal(video.currentTime, 226)
  assert.equal(opens.length, 1, 'quality must keep the same session')
  video.currentTime = 240
  video.props.onPause()
  await Promise.resolve()
  assert.equal(writes.at(-1).selection.quality, '1080p')
  assert.equal(writes.at(-1).positionSeconds, 240)
  player.closePlayer()
  await nextTick()
})

test('an old video cannot save its clock in a new episode while resume is loading', async (t) => {
  globalThis.window = { addEventListener() {}, removeEventListener() {} }
  setActivePinia(createPinia())
  const writes = []
  let finish
  const state = (id) => ({
    sessionId: id.repeat(32),
    source: 'source',
    animeUrl: 'series',
    episodeNumber: id === 'a' ? 1 : 2,
    version: 'VF',
    positionSeconds: 0,
    durationSeconds: 1000,
    selection: { quality: 'HD', server: 'auto', subtitle: 'auto', audio: null },
  })
  api.openPlaybackSession = async () => state('a')
  api.savePlaybackCheckpoint = async (b) => {
    writes.push(b)
    return { success: true }
  }
  api.getLocalSubtitles = async () => []
  const player = usePlayerStore(),
    { videos, app } = mountPlayer()
  t.after(() => {
    app.unmount()
    delete api.openPlaybackSession
    delete api.savePlaybackCheckpoint
    delete globalThis.window
  })
  await player.playLocalFile('first', 'Series', 1)
  await nextTick()
  const old = videos[0]
  old.currentTime = 150
  old.duration = 1000
  old.props.onTimeupdate()
  api.openPlaybackSession = () => new Promise((resolve) => (finish = resolve))
  const opening = player.playLocalFile('second', 'Series', 2)
  old.currentTime = 700
  old.props.onTimeupdate()
  old.props.onPause()
  finish(state('b'))
  await opening
  await nextTick()
  assert.ok(writes.every((b) => b.sessionId === 'a'.repeat(32) && b.positionSeconds === 150))
  player.closePlayer()
  await nextTick()
})

test('HLS audio selection restores by language and label, then saves the new choice', async (t) => {
  globalThis.window = { addEventListener() {}, removeEventListener() {} }
  globalThis.__hlsTest = true
  setActivePinia(createPinia())
  const writes = []
  const english = JSON.stringify(['audio', 'en', 'English']),
    japanese = JSON.stringify(['audio', 'ja', 'Japanese'])
  api.openPlaybackSession = async () => ({
    sessionId: 'a'.repeat(32),
    source: 'source',
    animeUrl: 'series',
    episodeNumber: 1,
    version: 'VO',
    positionSeconds: 25,
    durationSeconds: 1000,
    selection: { quality: 'HD', server: 'auto', subtitle: null, audio: japanese },
  })
  api.savePlaybackCheckpoint = async (b) => {
    writes.push(b)
    return { success: true }
  }
  api.getLocalSubtitles = async () => []
  const player = usePlayerStore(),
    { videos, app, root } = mountPlayer()
  t.after(() => {
    app.unmount()
    delete api.openPlaybackSession
    delete api.savePlaybackCheckpoint
    delete globalThis.window
    delete globalThis.__hlsTest
    delete globalThis.__hlsInstance
  })
  await player.playLocalFile('task', 'Series', 1)
  await nextTick()
  player.videoUrl = '/api/media/hls-proxy/playlist.m3u8'
  await nextTick()
  const hls = globalThis.__hlsInstance
  hls.handlers.manifest()
  await nextTick()
  assert.equal(hls.audioTrack, 1)
  assert.equal(player.audioTracks.length, 2)
  const selectors = []
  function walk(el) {
    if (el.type === 'select') selectors.push(el)
    for (const c of el.children) walk(c)
  }
  walk(root)
  selectors.find((el) => el.props.value === japanese).props.onChange({ target: { value: english } })
  assert.equal(hls.audioTrack, 0)
  const video = videos[0]
  video.currentTime = 80
  video.duration = 1000
  video.props.onPause()
  await Promise.resolve()
  assert.equal(writes.at(-1).selection.audio, english)
  player.closePlayer()
  await nextTick()
})

test('local playlist enables next and previous episode navigation across downloads', async (t) => {
  globalThis.window = { addEventListener() {}, removeEventListener() {} }
  setActivePinia(createPinia())
  const opened = []
  let resolveCalls = 0
  api.openPlaybackSession = async (body) => {
    opened.push(body)
    return {
      sessionId: String(body.taskId).padEnd(32, '0').slice(0, 32),
      source: 'french-manga',
      animeUrl: 'https://example.org/series',
      episodeNumber: body.taskId === 'task-1' ? 1 : 2,
      version: 'VF',
      positionSeconds: 0,
      durationSeconds: 1400,
      selection: {
        quality: 'Original (Local)',
        server: 'Disque dur (Local)',
        subtitle: 'auto',
        audio: null,
      },
    }
  }
  api.resolveVideoStream = async () => {
    resolveCalls++
    return {}
  }
  api.getLocalSubtitles = async (taskId) => [
    { src: `/api/media/subtitle/${taskId}/0`, srclang: 'fr', label: 'Français' },
  ]
  const player = usePlayerStore()
  const { videos, app } = mountPlayer()
  t.after(() => {
    app.unmount()
    delete api.openPlaybackSession
    delete api.resolveVideoStream
    delete api.getLocalSubtitles
    delete globalThis.window
  })

  const playlist = [
    { number: 2, title: 'Ep 2.mp4', version: 'VF', isDownloaded: true, downloadTaskId: 'task-2' },
    { number: 1, title: 'Ep 1.mp4', version: 'VF', isDownloaded: true, downloadTaskId: 'task-1' },
  ]
  await player.playLocalFile('task-1', 'My Series', 1, 'Ep 1.mp4', playlist)
  await nextTick()
  assert.equal(player.hasPrev, false)
  assert.equal(player.hasNext, true)
  assert.equal(videos.at(-1).src, '/api/media/stream/task-1')

  await player.playNext()
  await nextTick()
  assert.equal(player.currentEpisode.number, 2)
  assert.equal(player.hasPrev, true)
  assert.equal(player.hasNext, false)
  assert.equal(videos.at(-1).src, '/api/media/stream/task-2')
  assert.equal(player.selectedSubtitle, '/api/media/subtitle/task-2/0')
  assert.equal(resolveCalls, 0)
  assert.deepEqual(opened, [{ taskId: 'task-1' }, { taskId: 'task-2' }])

  await player.playPrev()
  await nextTick()
  assert.equal(player.currentEpisode.number, 1)
  assert.equal(videos.at(-1).src, '/api/media/stream/task-1')
  player.closePlayer()
  await nextTick()
})

test('descending source episodes sort ascending, sanitize local prefs, and honor backend isHls flag', async (t) => {
  globalThis.window = { addEventListener() {}, removeEventListener() {} }
  globalThis.__hlsTest = true
  setActivePinia(createPinia())
  const resolveParams = []
  api.openPlaybackSession = async (body) => ({
    sessionId: 'b'.repeat(32),
    source: 'ext-source',
    animeUrl: body.animeUrl,
    episodeNumber: body.episodeNumber,
    version: body.version,
    positionSeconds: 0,
    durationSeconds: 1400,
    selection: {
      quality: 'Original (Local)',
      server: 'Disque dur (Local)',
      subtitle: null,
      audio: null,
    },
  })
  api.resolveVideoStream = async (params) => {
    resolveParams.push(params)
    return {
      streamUrl: `/api/media/extension-resource/tok-${params.episodeNumber}`,
      isHls: true,
      isDownloaded: false,
      serverType: 'StreamSB',
      selectedQuality: '1080p',
      subtitles: [],
    }
  }
  const player = usePlayerStore()
  const { app } = mountPlayer()
  t.after(() => {
    app.unmount()
    delete api.openPlaybackSession
    delete api.resolveVideoStream
    delete globalThis.window
    delete globalThis.__hlsTest
    delete globalThis.__hlsInstance
  })

  const rawDescending = [
    { number: 3, title: 'Ep 3', playerUrl: 'https://example.org/ep3', version: 'VOSTFR' },
    { number: 1, title: 'Ep 1', playerUrl: 'https://example.org/ep1', version: 'VOSTFR' },
    { number: 2, title: 'Ep 2', playerUrl: 'https://example.org/ep2', version: 'VOSTFR' },
  ]
  await player.openPlayer(
    'Test Anime',
    'https://example.org/anime',
    'ext-source',
    rawDescending[1],
    rawDescending,
  )
  await nextTick()
  assert.equal(player.episodes.map((e) => e.number).join(','), '1,2,3')
  assert.equal(player.hasPrev, false)
  assert.equal(player.hasNext, true)
  assert.equal(player.isHls, true)
  assert.equal(resolveParams[0].server, undefined)
  assert.equal(resolveParams[0].quality, undefined)
  assert.ok(globalThis.__hlsInstance)

  await player.playNext()
  await nextTick()
  assert.equal(player.currentEpisode.number, 2)
  assert.equal(player.hasPrev, true)
  assert.equal(player.hasNext, true)
  assert.equal(resolveParams[1].episodeUrl, 'https://example.org/ep2')
  player.closePlayer()
  await nextTick()
})
