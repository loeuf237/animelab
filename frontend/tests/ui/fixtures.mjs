// All browser tests are offline: no requests reach user data or remote sources.
export const sources = [
  ['voir-anime', 'VoirAnime', 'fr', 'https://voiranime.cx/'],
  ['animepahe', 'AnimePahe', 'en', 'https://animepahe.pw/'],
  ['french-manga', 'French-Manga', 'fr', 'https://w16.french-manga.net/'],
  ['french-stream', 'French-Stream', 'fr', 'https://fs016.lol/'],
  [
    'aniyomi-long',
    'Aniyomi: Une extension avec un nom particulièrement long',
    'fr',
    'https://example.test/',
  ],
].map(([id, name, lang, baseUrl], i) => ({
  id,
  name,
  lang,
  baseUrl,
  type: i < 4 ? 'native' : 'imported',
  isEnabled: true,
  views: [
    { id: 'latest', label: 'Dernières sorties' },
    { id: 'popular', label: 'Populaires' },
    { id: 'catalogue', label: 'Catalogue' },
    { id: 'search', label: 'Recherche' },
  ],
  multiTags: true,
}))
export const tasks = [
  'DOWNLOADING',
  'PENDING',
  'PAUSED',
  'COMPLETED',
  'FAILED',
  'VERIFICATION_REQUIRED',
].map((status, i) => ({
  id: i + 1,
  animeName: 'Shokugeki no Sōma — Une série au titre particulièrement long',
  animeUrl: 'https://example.test/anime',
  episodeNumber: i + 1,
  fileName: `Shokugeki no Soma - Episode ${i + 1} [VF].mp4`,
  source: 'voir-anime',
  version: 'VF',
  selectedQuality: '480p',
  status,
  totalBytes: status === 'PENDING' ? 0 : 100000000,
  downloadedBytes: status === 'COMPLETED' ? 100000000 : 12000000,
  speedBytes: status === 'DOWNLOADING' ? 62000 : 0,
  progress: status === 'COMPLETED' ? 100 : 12,
  verificationStatus: status === 'COMPLETED' ? 'VALID' : 'UNVERIFIED',
  formattedDuration: '25m 07s',
  exportStatus: status === 'COMPLETED' ? 'EXPORTED' : 'NOT_REQUESTED',
  exportDestination:
    status === 'COMPLETED'
      ? 'Download/AnimeLab/Shokugeki no Soma/Un très long nom de fichier exporté.mp4'
      : null,
  error:
    status === 'FAILED'
      ? 'La connexion a été interrompue pendant le téléchargement. Réessayez.'
      : null,
  verificationDomain: status === 'VERIFICATION_REQUIRED' ? 'example.test' : null,
  verificationUrl: status === 'VERIFICATION_REQUIRED' ? 'https://example.test/' : null,
}))
export async function mockApp(
  page,
  {
    lang = 'fr',
    theme = 'dark',
    taskList = tasks,
    origin = 'http://127.0.0.1:5179',
    externalPlayerSettings = {
      available: true,
      platform: 'desktop',
      clientLocal: true,
      preset: 'none',
      customPath: '',
      preferExternal: false,
      configured: false,
      resolvedPath: null,
      detected: [{ id: 'mpv', label: 'mpv', path: '/usr/bin/mpv' }],
    },
  } = {},
) {
  const requests = []
  await page.addInitScript(
    ({ lang, theme }) => {
      localStorage.setItem('animan_lang', lang)
      localStorage.setItem('animan_theme', theme)
    },
    { lang, theme },
  )
  await page.route('**/*', async (route) => {
    const url = new URL(route.request().url())
    if (url.origin !== origin) return route.abort()
    if (!url.pathname.startsWith('/api/')) return route.continue()
    requests.push({
      path: url.pathname,
      method: route.request().method(),
      body: route.request().postDataJSON(),
    })
    let data = {}
    switch (url.pathname) {
      case '/api/extensions/android':
        data = { available: false, packages: [], operations: [] }
        break
      case '/api/extensions/seanime':
        data = {
          runtime_available: true,
          engine: 'mini-racer',
          extensions: [],
          counts: {},
          repositories: [],
        }
        break
      case '/api/extensions/seanime/repositories':
        data = { repositories: [] }
        break
      case '/api/extensions/repositories':
        data = { repositories: [] }
        break
      case '/api/app/startup':
        data = {
          preferences: {
            onboardingCompleted: true,
            theme,
            palette: 'teal',
            checkUpdates: true,
            updateChannel: 'beta',
          },
          currentVersion: '0.1.6-beta.3',
          runtime: 'web',
          os: 'linux',
          architecture: 'x86_64',
          storageEditable: false,
          native: null,
          downloadDirectory: '/downloads/AnimeLab',
        }
        break
      case '/api/app/updates':
        data = { status: 'current', currentVersion: '0.1.6-beta.3', channel: 'beta', release: null }
        break
      case '/api/app/preferences':
        data = {
          onboardingCompleted: true,
          theme,
          palette: 'teal',
          checkUpdates: true,
          updateChannel: 'beta',
          ...route.request().postDataJSON(),
        }
        break
      case '/api/download/status':
        data = taskList
        break
      case '/api/download/stream':
        return route.fulfill({
          status: 200,
          contentType: 'text/event-stream',
          body: `data: ${JSON.stringify({ tasks: taskList })}\n\n`,
        })
      case '/api/sources':
        data = { sources }
        break
      case '/api/favorites':
      case '/api/history':
        data = []
        break
      case '/api/download/settings':
        data = {
          maxConcurrentDownloads: 3,
          globalSpeedLimit: 0,
          selectedUserAgent: 'Chrome',
          ffmpegAvailable: true,
        }
        break
      case '/api/proxy/settings':
        data = { enabled: false }
        break
      case '/api/system/android/export':
        data = { success: true, destination: 'Download/AnimeLab', task: taskList[0] }
        break
      case '/api/system/android/storage':
        data = {
          android: true,
          apiLevel: 29,
          authorized: true,
          destination: 'Download/AnimeLab',
          notificationsGranted: true,
          exportSupported: true,
          exportConfigured: true,
          permissionGranted: true,
        }
        break
      case '/api/system/storage':
        data = {
          totalBytes: 100000000000,
          usedBytes: 30000000000,
          freeBytes: 70000000000,
          usedPercent: 30,
          downloadDir: '/downloads/AnimeLab',
        }
        break
      case '/api/i18n':
        data = { language: lang, supported: ['fr', 'en'], translations: {} }
        break
      case '/api/network/sessions':
        data = { sessions: [], browsers: [] }
        break
      case '/api/home/feed':
        data = { favorites: [], releases: {}, latestFrenchStream: [], sources: [] }
        break
      case '/api/releases/latest':
        data = { releases: [] }
        break
      case '/api/search':
        data = { results: [], challenges: [], errors: [] }
        break
      case '/api/network/proxy-pool':
        data = { automatic: false, entries: [], providers: [] }
        break
      case '/api/media/external-player/settings':
        if (route.request().method() === 'POST') {
          const posted = route.request().postDataJSON() || {}
          const detectedMatch = (externalPlayerSettings.detected || []).find(
            (item) => item.id === posted.preset,
          )
          const resolvedPath =
            posted.preset === 'none'
              ? externalPlayerSettings.detected?.[0]?.path || null
              : posted.preset === 'custom'
                ? posted.customPath || '/usr/bin/custom-player'
                : detectedMatch?.path ||
                  (posted.preset === 'mpv'
                    ? '/usr/bin/mpv'
                    : posted.preset === 'vlc'
                      ? '/usr/bin/vlc'
                      : posted.preset === 'system'
                        ? '/usr/bin/xdg-open'
                        : null)
          data = {
            ...externalPlayerSettings,
            ...posted,
            configured: Boolean(
              (posted.preset && posted.preset !== 'none') ||
              (externalPlayerSettings.detected || []).length > 0,
            ),
            resolvedPath,
          }
        } else {
          data = externalPlayerSettings
        }
        break
      case '/api/media/external-player/launch':
        data = {
          success: true,
          mode:
            externalPlayerSettings.platform === 'android' ? 'android_intent' : 'desktop_process',
          player: externalPlayerSettings.platform === 'android' ? 'Android' : 'mpv',
          targetKind: 'file',
        }
        break
      default:
        if (url.pathname.endsWith('/filters'))
          data = {
            tags: [{ id: 'action', label: 'Action', group: 'Genres' }],
            orders: [{ id: 'source', label: 'Ordre de la source' }],
          }
        else if (url.pathname.endsWith('/catalogue'))
          data = { results: [], nextCursor: null, queryScope: 'catalogue' }
        else if (url.pathname.startsWith('/api/extensions/seanime')) data = {}
        else if (url.pathname.startsWith('/api/extensions'))
          data = {
            active_repo: 'example/test-repo',
            extensions: Array.from({ length: 12 }, (_, i) => ({
              id: i + 1,
              name: 'Aniyomi: Extension au nom particulièrement long ' + (i + 1),
              lang: i % 2 ? 'en' : 'fr',
              version: '14.42',
              base_url: 'https://example.test/',
              is_enabled: true,
            })),
          }
    }
    return route.fulfill({ json: data })
  })
  return requests
}
