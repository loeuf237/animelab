import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { test } from 'node:test'
import ts from 'typescript'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'

// Load the actual TypeScript modules with the same dependencies as the app.
async function moduleUrl(path, replacements = {}, transform = (s) => s) {
  const source = transform(await readFile(new URL(path, import.meta.url), 'utf8'))
  let code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  }).outputText
  for (const [name, url] of Object.entries(replacements)) {
    code = code.replaceAll(`'${name}'`, JSON.stringify(url))
    code = code.replaceAll(`"${name}"`, JSON.stringify(url))
  }
  code = code
    .replaceAll("'@/utils/locale'", JSON.stringify(localeUrl))
    .replaceAll("'@/stores/sourcePreferences'", JSON.stringify(sourcePreferencesUrl))
    .replaceAll("'@/utils/media'", JSON.stringify(mediaUtilsUrl))
    .replaceAll('"@/utils/media"', JSON.stringify(mediaUtilsUrl))
  return `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`
}

const localeSource = await readFile(new URL('../src/utils/locale.ts', import.meta.url), 'utf8')
const english = JSON.parse(
  await readFile(new URL('../src/locales/en.json', import.meta.url), 'utf8'),
)
const localeCode = ts
  .transpileModule(localeSource, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  })
  .outputText.replace("'vue'", JSON.stringify(import.meta.resolve('vue')))
  .replace("import english from '@/locales/en.json';", `const english=${JSON.stringify(english)};`)
const localeUrl = `data:text/javascript;base64,${Buffer.from(localeCode).toString('base64')}`
// The preference module needs only the already initialized locale.
let sourcePreferencesUrl = ''
let mediaUtilsUrl = ''
sourcePreferencesUrl = await moduleUrl('../src/stores/sourcePreferences.ts', {
  vue: import.meta.resolve('vue'),
  pinia: import.meta.resolve('pinia'),
})
mediaUtilsUrl = await moduleUrl('../src/utils/media.ts')

const notificationsUrl = await moduleUrl('../src/stores/notifications.ts', {
  vue: import.meta.resolve('vue'),
  pinia: import.meta.resolve('pinia'),
})
const { useNotifications } = await import(notificationsUrl)
const apiUrl = await moduleUrl('../src/api/client.ts')
const { api } = await import(apiUrl)
const { useLibraryStore } = await import(
  await moduleUrl('../src/stores/library.ts', {
    '@/api/client': apiUrl,
    '@/stores/notifications': notificationsUrl,
    vue: import.meta.resolve('vue'),
    pinia: import.meta.resolve('pinia'),
  })
)
const { getRouterBase } = await import(await moduleUrl('../src/router/base.ts'))

test('navigation keeps the SPA prefix on entry and deep links', async () => {
  for (const [pathname, expected] of [
    ['/spa', '/spa/'],
    ['/spa/anime', '/spa/'],
    ['/app', '/app/'],
    ['/app/library', '/app/'],
    ['/', '/'],
    ['/spa-other', '/'],
  ]) {
    const base = getRouterBase(pathname)
    assert.equal(base, expected)
    const router = createRouter({
      history: createMemoryHistory(base),
      routes: [{ path: '/downloads', component: {} }],
    })
    await router.push('/downloads')
    assert.equal(router.resolve('/downloads').href, `${base}downloads`)
  }
})

test('unwatch sends false and keeps separate VF/VOSTFR state', async () => {
  const previousFetch = globalThis.fetch
  const bodies = []
  globalThis.fetch = async (url, config) => {
    bodies.push(JSON.parse(config.body))
    return new Response(JSON.stringify({ success: true }))
  }
  try {
    await api.markEpisodeWatched({ animeUrl: 'anime', episodeNumber: 1, watched: false })
    assert.equal(bodies[0].watched, false)
    setActivePinia(createPinia())
    const library = useLibraryStore()
    assert.equal(library.isWatched('anime', 1, 'VF'), undefined)
    await library.markWatched('anime', 1, true, 'VF')
    await library.markWatched('anime', 1, true, 'VOSTFR')
    await library.markWatched('anime', 1, false, 'VF')
    assert.equal(library.isWatched('anime', 1, 'VF'), false)
    assert.equal(library.isWatched('anime', 1, 'VOSTFR'), true)
    assert.equal(bodies.at(-1).version, 'VF')
    assert.equal(bodies.at(-1).watched, false)
  } finally {
    globalThis.fetch = previousFetch
  }
})

const episodeUtilsUrl = await moduleUrl('../src/utils/episodes.ts')
const { buildEpisodeRowKeys, episodeKey, episodeFileName } = await import(episodeUtilsUrl)
const { usePlayerStore } = await import(
  await moduleUrl('../src/stores/player.ts', {
    './verification': `data:text/javascript;base64,${Buffer.from('export const useVerificationStore=()=>({clearPending(){},waitForVerification(){}}); export const challengeFromError=()=>null;').toString('base64')}`,
    '@/api/client': apiUrl,
    '@/utils/episodes': episodeUtilsUrl,
    vue: import.meta.resolve('vue'),
    pinia: import.meta.resolve('pinia'),
  })
)

test('VF selection and subtitle overrides do not include the VOSTFR counterpart', () => {
  const vf = { number: 1, version: 'VF', playerUrl: 'https://anime/vf/1' }
  const vo = { number: 1, version: 'VOSTFR', playerUrl: 'https://anime/vo/1' }
  const selected = new Set([episodeKey(vf)])
  assert.deepEqual(
    [vf, vo].filter((ep) => selected.has(episodeKey(ep))),
    [vf],
  )
  assert.notEqual(episodeFileName('Anime', vf), episodeFileName('Anime', vo))
  assert.notEqual(episodeKey(vf), episodeKey({ ...vf, playerUrl: 'https://other/vf/1' }))
})

test('player next and previous stay in the selected language', async () => {
  setActivePinia(createPinia())
  const player = usePlayerStore()
  const previous = api.resolveVideoStream
  api.resolveVideoStream = async () => ({ streamUrl: 'https://cdn/video.mp4' })
  try {
    const episodes = [
      { number: 1, version: 'VF', playerUrl: 'https://vf/1' },
      { number: 1, version: 'VOSTFR', playerUrl: 'https://vo/1' },
      { number: 2, version: 'VF', playerUrl: 'https://vf/2' },
      { number: 2, version: 'VOSTFR', playerUrl: 'https://vo/2' },
    ]
    await player.openPlayer('Anime', 'anime', 'french-manga', episodes[0], episodes)
    await player.playNext()
    assert.equal(player.currentEpisode.version, 'VF')
    assert.equal(player.currentEpisode.number, 2)
    assert.equal(player.hasNext, false)
    await player.playPrev()
    assert.equal(player.currentEpisode.playerUrl, 'https://vf/1')
    assert.equal(player.hasPrev, false)
  } finally {
    api.resolveVideoStream = previous
  }
})

test('single download sends the selected language and parent anime URL', async () => {
  const previousFetch = globalThis.fetch
  let body
  globalThis.fetch = async (url, config) => {
    body = JSON.parse(config.body)
    return new Response(JSON.stringify({ success: true }))
  }
  try {
    await api.startEpisodeDownload({
      animeName: 'Anime',
      animeUrl: 'anime',
      episodeNumber: 1,
      version: 'VF',
      url: 'https://vf/1',
    })
    assert.equal(body.version, 'VF')
    assert.equal(body.animeUrl, 'anime')
  } finally {
    globalThis.fetch = previousFetch
  }
})

test('the actual detail view queues only the checked VF episode', async () => {
  const detail = {
    anime: {
      title: 'Anime',
      url: 'https://anime/title',
      episodes: [
        { number: 1, version: 'VF', playerUrl: 'https://anime/vf/1' },
        { number: 1, version: 'VOSTFR', playerUrl: 'https://anime/vo/1' },
      ],
    },
    source: 'french-manga',
    watchedEpisodes: [],
  }
  const captured = []
  globalThis.__episodeTest = { detail, captured }
  const inline = (source) => `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`
  const code = await moduleUrl(
    '../src/views/AnimeDetailView.vue',
    {
      '@/utils/episodes': episodeUtilsUrl,
      '@/stores/notifications': inline('export const useNotifications=()=>({notify:()=>{}});'),
      '@/stores/searchContext': inline('export const useSearchContext=()=>({restore:()=>{}});'),
      vue: inline(
        `export {ref,computed} from '${import.meta.resolve('vue')}'; export const onMounted=()=>{}; export const onUnmounted=()=>{}; export const watch=()=>{};`,
      ),
      'vue-router': inline(
        `export const useRouter=()=>({push:()=>{}}); export const useRoute=()=>({query:{}});`,
      ),
      '@/stores/anime': inline(
        `export const useAnimeStore=()=>({currentDetail:globalThis.__episodeTest.detail});`,
      ),
      '@/stores/player': inline(`export const usePlayerStore=()=>({});`),
      '@/stores/library': inline(
        `export const useLibraryStore=()=>({favorites:[],isWatched:()=>undefined});`,
      ),
      '@/stores/downloads': inline(
        `export const useDownloadStore=()=>({startBatchDownload:async p=>{globalThis.__episodeTest.captured.push(p);return {success:true};}});`,
      ),
    },
    (s) =>
      s
        .split('<script setup lang="ts">')[1]
        .split('</script>')[0]
        .replace("import ConfirmDialog from '@/components/ConfirmDialog.vue';", '')
        .replace(
          "const emit = defineEmits<{(event: 'open-palette'): void}>();",
          'const emit=()=>{};',
        ) +
      '\nexport {toggleEpisodeSelection, downloadSelectedEpisodes, confirmBatchDownload, triggerBatchPreset, toggleEpSub, epSubtitles, pendingBatch, batchQuality};',
  )
  const view = await import(code)
  view.toggleEpisodeSelection(episodeKey(detail.anime.episodes[0]))
  view.toggleEpSub(detail.anime.episodes[0])
  view.downloadSelectedEpisodes()
  assert.equal(captured.length, 0, 'preview must never start a download')
  assert.equal(view.pendingBatch.value.episodes[0].version, 'VF')
  view.batchQuality.value = '480p'
  view.toggleEpSub(detail.anime.episodes[0])
  await view.confirmBatchDownload()
  assert.equal(captured.length, 1)
  assert.equal(captured[0].episodes.length, 1)
  assert.equal(
    captured[0].preferredQuality,
    undefined,
    'the confirmed request must use the previewed quality',
  )
  assert.equal(captured[0].episodes[0].version, 'VF')
  assert.equal(captured[0].episodes[0].url, 'https://anime/vf/1')
  assert.equal(captured[0].episodes[0].downloadSubtitles, true)
  assert.equal(view.epSubtitles.value[episodeKey(detail.anime.episodes[1])], undefined)
  delete globalThis.__episodeTest
})

test('duplicate episode rows receive distinct row keys and toggling one selects only that row', async () => {
  const dupA = {
    number: 1,
    title: 'Episode 1',
    version: 'VOSTFR',
    playerUrl: 'https://on.jetanimes.com/episodes/dup-1/',
  }
  const dupB = {
    number: 1,
    title: 'Episode 1',
    version: 'VOSTFR',
    playerUrl: 'https://on.jetanimes.com/episodes/dup-1/',
  }
  const season2 = {
    number: 1,
    title: 'S02E01 — Episode 1',
    version: 'VOSTFR',
    playerUrl: 'https://on.jetanimes.com/episodes/s2-1/',
    nativeMetadata: { season: 2 },
  }
  const rowMap = buildEpisodeRowKeys([dupA, dupB, season2])
  assert.notEqual(rowMap.get(dupA), rowMap.get(dupB))
  assert.equal(
    episodeFileName('The Ramparts of Ice', season2),
    'The Ramparts of Ice - S02E01 [VOSTFR].mp4',
  )

  const detail = {
    anime: {
      title: 'The Ramparts of Ice',
      url: 'https://on.jetanimes.com/serie/the-ramparts-of-ice/',
      episodes: [dupA, dupB, season2],
    },
    source: 'eu.kanade.tachiyomi.animeextension.fr.jetanime',
    watchedEpisodes: [],
  }
  const captured = []
  globalThis.__episodeTest = { detail, captured }
  const inline = (source) => `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`
  const code = await moduleUrl(
    '../src/views/AnimeDetailView.vue',
    {
      '@/utils/episodes': episodeUtilsUrl,
      '@/stores/notifications': inline('export const useNotifications=()=>({notify:()=>{}});'),
      '@/stores/searchContext': inline('export const useSearchContext=()=>({restore:()=>{}});'),
      vue: inline(
        `export {ref,computed} from '${import.meta.resolve('vue')}'; export const onMounted=()=>{}; export const onUnmounted=()=>{}; export const watch=()=>{};`,
      ),
      'vue-router': inline(
        `export const useRouter=()=>({push:()=>{}}); export const useRoute=()=>({query:{}});`,
      ),
      '@/stores/anime': inline(
        `export const useAnimeStore=()=>({currentDetail:globalThis.__episodeTest.detail});`,
      ),
      '@/stores/player': inline(`export const usePlayerStore=()=>({});`),
      '@/stores/library': inline(
        `export const useLibraryStore=()=>({favorites:[],isWatched:()=>undefined});`,
      ),
      '@/stores/downloads': inline(
        `export const useDownloadStore=()=>({startBatchDownload:async p=>{globalThis.__episodeTest.captured.push(p);return {success:true};}});`,
      ),
    },
    (s) =>
      s
        .split('<script setup lang="ts">')[1]
        .split('</script>')[0]
        .replace("import ConfirmDialog from '@/components/ConfirmDialog.vue';", '')
        .replace(
          "const emit = defineEmits<{(event: 'open-palette'): void}>();",
          'const emit=()=>{};',
        ) +
      '\nexport {rowKey, selectedEpisodes, toggleEpisodeSelection, downloadSelectedEpisodes, pendingBatch};',
  )
  const view = await import(code)
  view.toggleEpisodeSelection(view.rowKey(dupA))
  assert.equal(view.selectedEpisodes.value.has(view.rowKey(dupA)), true)
  assert.equal(view.selectedEpisodes.value.has(view.rowKey(dupB)), false)
  assert.equal(view.selectedEpisodes.value.size, 1)
  view.downloadSelectedEpisodes()
  assert.equal(view.pendingBatch.value.episodes.length, 1)
  delete globalThis.__episodeTest
})

test('favorite removal can be undone without losing automatic download preferences', async (t) => {
  setActivePinia(createPinia())
  const original = { ...api }
  const saved = {
    url: 'anime',
    title: 'Anime',
    imageUrl: 'cover',
    source: 'french-manga',
    autoDownload: true,
  }
  let records = [{ ...saved }],
    additions = 0
  api.getFavorites = async () => records.map((item) => ({ ...item }))
  api.removeFavorite = async () => {
    records = []
    return { success: true }
  }
  api.addFavorite = async (item) => {
    additions++
    records.push({ ...item })
    return { success: true }
  }
  const notifications = useNotifications()
  t.after(() => {
    Object.assign(api, original)
    for (const item of [...notifications.items]) notifications.dismiss(item.id)
  })
  const library = useLibraryStore()
  await library.fetchFavorites()
  await library.toggleFavorite(saved)
  assert.equal(library.favorites.length, 0)
  const undo = notifications.items[0]
  assert.equal(undo.action.label, 'Annuler')
  await undo.action.run()
  await undo.action.run()
  assert.equal(additions, 1, 'restoring twice must not create a duplicate')
  assert.equal(library.favorites[0].autoDownload, true)
})

const downloadsUrl = await moduleUrl('../src/stores/downloads.ts', {
  '@/api/client': apiUrl,
  vue: import.meta.resolve('vue'),
  pinia: import.meta.resolve('pinia'),
})
const { useDownloadStore } = await import(downloadsUrl)

test('download display distinguishes finalization and unknown sizes without inventing progress', async (t) => {
  setActivePinia(createPinia())
  const original = { ...api }
  t.after(() => Object.assign(api, original))
  api.getDownloadTasks = async () => [
    { id: 1, status: 'MUXING', downloadedBytes: 123, totalBytes: 0, progress: 100 },
    {
      id: 2,
      status: 'DOWNLOADING',
      phase: 'subtitles',
      downloadedBytes: 321,
      totalBytes: 0,
      progress: 0,
    },
  ]
  const store = useDownloadStore()
  await store.fetchTasks()
  assert.equal(store.tasks[0].phase, 'muxing')
  assert.equal(store.tasks[0].rawStatus, 'MUXING')
  assert.equal(store.stats.activeCount, 2)
  const inline = (source) => `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`
  const view = await import(
    await moduleUrl(
      '../src/views/DownloadsView.vue',
      {
        '@/api/client': apiUrl,
        '@/stores/downloads': downloadsUrl,
        '@/stores/notifications': notificationsUrl,
        '@/stores/library': inline('export const useLibraryStore=()=>({favorites:[]});'),
        '@/stores/player': inline('export const usePlayerStore=()=>({});'),
        vue: inline(
          `export {ref,computed} from '${import.meta.resolve('vue')}'; export const onMounted=()=>{}; export const onActivated=()=>{};`,
        ),
      },
      (s) =>
        s
          .split('<script setup lang="ts">')[1]
          .split('</script>')[0]
          .replace(/defineOptions\(\{\s*name:\s*'DownloadsView'\s*\}\);?/, '') +
        '\nexport {getStatusLabel,progressText,getVisualProgress,filteredTasks,tab,errorTasksCount};',
    )
  )
  assert.equal(view.getStatusLabel(store.tasks[0]), 'Fusion des sous-titres')
  assert.equal(view.getStatusLabel(store.tasks[1]), 'Sous-titres')
  assert.match(view.progressText(store.tasks[0]), /taille totale inconnue/)
  assert.doesNotMatch(view.progressText(store.tasks[0]), /0 %|100 %/)
  assert.equal(view.getVisualProgress({ status: 'failed', progress: 0 }), 0)
  assert.equal(view.getVisualProgress({ status: 'downloading', progress: 100 }), 99)
  assert.equal(view.getVisualProgress({ status: 'completed', progress: 100 }), 100)
  store.tasks = [
    { id: 3, status: 'completed', progress: 100, exportStatus: 'EXPORT_FAILED' },
    { id: 4, status: 'completed', progress: 100, exportStatus: 'EXPORTED' },
  ]
  assert.equal(store.stats.completedCount, 2)
  assert.equal(store.stats.errorCount, 1)
  assert.equal(view.getStatusLabel(store.tasks[0]), 'Vidéo vérifiée')
  assert.deepEqual(
    view.filteredTasks.value.map((t) => t.id),
    [3],
    'failed exports remain visible in the default queue',
  )
  view.tab.value = 'errors'
  assert.deepEqual(
    view.filteredTasks.value.map((t) => t.id),
    [3],
  )
  assert.equal(view.errorTasksCount.value, 1)
})

const searchContextUrl = await moduleUrl('../src/stores/searchContext.ts', {
  vue: import.meta.resolve('vue'),
  pinia: import.meta.resolve('pinia'),
})
const { useSearchContext } = await import(searchContextUrl)
test('only the detail opened from search can request restoration of its results', () => {
  setActivePinia(createPinia())
  const context = useSearchContext()
  context.markDetail('naruto')
  assert.equal(context.restore('other'), false)
  assert.equal(context.restoreSequence, 0)
  assert.equal(context.restore('naruto'), true)
  assert.equal(context.restoreSequence, 1)
})

test('tracking options reach the API and server-confirmed preferences survive toggling', async (t) => {
  setActivePinia(createPinia())
  const original = { ...api }
  const saved = {
    url: 'anime',
    title: 'Anime',
    source: 'animepahe',
    imageUrl: '',
    autoDownload: true,
    autoDownloadVersion: 'VF',
    autoDownloadSubtitles: true,
  }
  const calls = []
  api.getFavorites = async () => [{ ...saved }]
  api.toggleAutoDownload = async (url, enabled, options) => {
    calls.push({ url, enabled, options })
    Object.assign(saved, options, { autoDownload: enabled })
    return { success: true, favorite: { ...saved } }
  }
  const notifications = useNotifications()
  t.after(() => {
    Object.assign(api, original)
    for (const item of [...notifications.items]) notifications.dismiss(item.id)
  })
  const store = useLibraryStore()
  await store.fetchFavorites()
  await store.saveAutoDownload(store.favorites[0], {
    autoDownloadVersion: 'VOSTFR',
    autoDownloadQuality: '720p',
    autoDownloadSubtitles: true,
  })
  assert.equal(calls[0].options.autoDownloadVersion, 'VOSTFR')
  await store.toggleAutoDownload(saved.url, true)
  assert.equal(store.favorites[0].autoDownload, false)
  assert.equal(store.favorites[0].autoDownloadVersion, 'VOSTFR')
  assert.equal(store.favorites[0].autoDownloadQuality, '720p')
})

test('verified media and failed exports retain independent display states', async (t) => {
  const locale = await import(localeUrl)
  const previousLanguage = locale.language.value
  locale.applyLanguage('fr')
  t.after(() => locale.applyLanguage(previousLanguage))
  setActivePinia(createPinia())
  const original = { ...api }
  t.after(() => Object.assign(api, original))
  api.getDownloadTasks = async () => [
    {
      id: 7,
      status: 'COMPLETED',
      progress: 100,
      exportStatus: 'EXPORT_FAILED',
      exportError: 'Folder revoked',
      exportAttempts: 2,
      exportUris: [],
    },
  ]
  const store = useDownloadStore()
  await store.fetchTasks()
  assert.equal(store.tasks[0].status, 'completed')
  assert.equal(store.tasks[0].exportStatus, 'EXPORT_FAILED')
  assert.equal(store.tasks[0].exportAttempts, 2)
  const { parse, compileScript } = await import('@vue/compiler-sfc')
  const component = await import(
    await moduleUrl(
      '../src/components/ExportStatusNotice.vue',
      { vue: import.meta.resolve('vue') },
      (source) => {
        const { descriptor } = parse(source)
        return compileScript(descriptor, { id: 'export-status-test', inlineTemplate: true }).content
      },
    )
  )
  const { createSSRApp } = await import('vue')
  const { renderToString } = await import('vue/server-renderer')
  const failed = await renderToString(
    createSSRApp(component.default, { task: store.tasks[0], native: true }),
  )
  assert.match(failed, /Export à reprendre/)
  assert.match(failed, /vidéo vérifiée reste disponible/)
  assert.doesNotMatch(failed, /Exporté vers le stockage/)
  const unknown = await renderToString(
    createSSRApp(component.default, {
      task: { status: 'completed', exportStatus: 'NOT_REQUESTED' },
      native: true,
    }),
  )
  assert.match(unknown, /Export non renseigné/)
  const done = await renderToString(
    createSSRApp(component.default, {
      task: {
        status: 'completed',
        exportStatus: 'EXPORTED',
        exportDestination: 'Downloads/AnimeLab',
      },
      native: true,
    }),
  )
  assert.match(done, /Exporté vers le stockage/)
  assert.match(done, /Downloads\/AnimeLab/)
})
