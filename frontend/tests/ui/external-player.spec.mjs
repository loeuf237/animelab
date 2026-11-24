import { test, expect } from '@playwright/test'
import { mockApp } from './fixtures.mjs'

async function noOverflow(page) {
  const width = page.viewportSize().width
  await expect
    .poll(async () => {
      const size = await page.evaluate(() => ({
        viewport: innerWidth,
        document: document.documentElement.scrollWidth,
        body: document.body.scrollWidth,
      }))
      return size.viewport === width && size.document <= width + 1 && size.body <= width + 1
        ? null
        : size
    })
    .toBeNull()
}

for (const width of [360, 1440]) {
  test(`external player settings render cleanly and save preset at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 820 })
    const requests = await mockApp(page, {
      externalPlayerSettings: {
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
    })

    await page.goto('/app/settings')
    const card = page.locator('.ext-player-card')
    await expect(card).toBeVisible()
    await card.locator('#external-player-preset').selectOption('mpv')
    await card.getByRole('button', { name: 'Enregistrer le lecteur' }).click()

    await expect(card.locator('[role="status"]')).toContainText('Lecteur externe enregistré.')
    await expect
      .poll(() =>
        requests.some(
          (r) =>
            r.path === '/api/media/external-player/settings' &&
            r.method === 'POST' &&
            r.body?.preset === 'mpv',
        ),
      )
      .toBe(true)
    await noOverflow(page)
  })
}

test('launching an external player from downloads and player modal shows watch prompt and marks watched', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 820 })
  const completedTask = {
    id: 301,
    animeName: 'Sample External Series',
    animeUrl: 'https://example.test/external-series',
    episodeNumber: 4,
    fileName: 'Sample External Series - Episode 4 [VF].mp4',
    source: 'french-manga',
    version: 'VF',
    selectedQuality: '1080p',
    status: 'COMPLETED',
    totalBytes: 100000000,
    downloadedBytes: 100000000,
    speedBytes: 0,
    progress: 100,
    verificationStatus: 'VALID',
    formattedDuration: '24m 00s',
    exportStatus: 'NOT_REQUESTED',
  }
  const requests = await mockApp(page, {
    taskList: [completedTask],
    externalPlayerSettings: {
      available: true,
      platform: 'desktop',
      clientLocal: true,
      preset: 'mpv',
      customPath: '',
      preferExternal: false,
      configured: true,
      resolvedPath: '/usr/bin/mpv',
      detected: [{ id: 'mpv', label: 'mpv', path: '/usr/bin/mpv' }],
    },
  })
  await page.route('**/api/media/subtitles/**', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/media/stream/*', (route) =>
    route.fulfill({ status: 200, contentType: 'video/mp4', body: '' }),
  )

  await page.goto('/app/downloads')
  await page.locator('.download-tabs > button').nth(1).click()
  const card = page.locator('.task-row-card').first()
  await expect(card).toBeVisible()

  await card.getByRole('button', { name: 'Ouvrir dans un lecteur externe' }).click()
  await expect
    .poll(() =>
      requests.some(
        (r) =>
          r.path === '/api/media/external-player/launch' &&
          r.method === 'POST' &&
          r.body?.taskId === '301',
      ),
    )
    .toBe(true)

  const prompt = page.locator('.external-watch-prompt')
  await expect(prompt).toBeVisible()
  await expect(prompt).toContainText('Épisode 4')
  await noOverflow(page)

  await prompt.getByRole('button', { name: 'Marquer comme vu' }).click()
  await expect
    .poll(() =>
      requests.some(
        (r) =>
          r.path === '/api/progress/watched' &&
          r.method === 'POST' &&
          r.body?.animeUrl === 'https://example.test/external-series' &&
          r.body?.episodeNumber === 4 &&
          r.body?.watched === true,
      ),
    )
    .toBe(true)
  await expect(prompt).toBeHidden()

  await card.locator('button[title*="Lire"]').click()
  const modal = page.locator('.player-modal')
  await expect(modal).toBeVisible()
  await modal.locator('.player-external-btn').click()
  const inlineBar = modal.locator('.external-watch-bar')
  await expect(inlineBar).toBeVisible()
  await inlineBar.getByRole('button', { name: 'Marquer comme vu' }).click()
  await expect(inlineBar).toBeHidden()
})

test('external player button appears automatically on Linux/Desktop when players are detected even with preset none', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 820 })
  const completedTask = {
    id: 302,
    animeName: 'Auto Detected External Show',
    animeUrl: 'https://example.test/auto-detected',
    episodeNumber: 1,
    fileName: 'Auto Detected External Show - Episode 1 [VF].mp4',
    source: 'french-manga',
    version: 'VF',
    selectedQuality: '1080p',
    status: 'COMPLETED',
    totalBytes: 100000000,
    downloadedBytes: 100000000,
    speedBytes: 0,
    progress: 100,
    verificationStatus: 'VALID',
    formattedDuration: '24m 00s',
    exportStatus: 'NOT_REQUESTED',
  }
  await mockApp(page, {
    taskList: [completedTask],
    externalPlayerSettings: {
      available: true,
      platform: 'desktop',
      clientLocal: true,
      preset: 'none',
      customPath: '',
      preferExternal: false,
      configured: true,
      resolvedPath: '/usr/bin/mpv',
      detected: [
        { id: 'mpv', label: 'mpv', path: '/usr/bin/mpv' },
        { id: 'system', label: 'Lecteur par défaut du système', path: '/usr/bin/xdg-open' },
      ],
    },
  })
  await page.route('**/api/media/subtitles/**', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/media/stream/*', (route) =>
    route.fulfill({ status: 200, contentType: 'video/mp4', body: '' }),
  )
  await page.route('**/api/media/stream/resolve*', (route) =>
    route.fulfill({
      json: {
        success: true,
        isDownloaded: true,
        isHls: false,
        sourceType: 'local',
        taskId: '302',
        videoUrl: '/api/media/stream/302',
        quality: 'Local',
        qualities: {},
      },
    }),
  )
  await page.route('**/api/playback/session', (route) =>
    route.fulfill({
      json: {
        sessionId: 'e'.repeat(32),
        source: 'french-manga',
        animeUrl: 'https://example.test/auto-detected',
        episodeNumber: 1,
        version: 'VF',
        positionSeconds: 0,
        durationSeconds: 0,
        selection: { quality: 'HD', server: 'auto', subtitle: null, audio: null },
      },
    }),
  )
  await page.route('**/api/anime/detail*', (route) =>
    route.fulfill({
      json: {
        success: true,
        source: 'french-manga',
        sourceName: 'French-Manga',
        isFavorite: false,
        autoDownload: false,
        downloadedEpisodes: [1],
        watchedEpisodes: [],
        totalEpisodes: 1,
        downloadedCount: 1,
        watchedCount: 0,
        anime: {
          title: 'Auto Detected External Show',
          url: 'https://example.test/auto-detected',
          imageUrl: '',
          source: 'french-manga',
          version: 'VF',
          genres: [],
          episodes: [
            {
              number: 1,
              title: 'Épisode 1',
              version: 'VF',
              playerUrl: 'https://vidzy.org/embed-abc.html',
              downloadPageUrl: 'https://vidzy.org/d/abc_n',
              isDownloaded: true,
              isWatched: false,
              downloadTaskId: 302,
            },
          ],
        },
      },
    }),
  )

  await page.goto('/app/downloads')
  await page.locator('.download-tabs > button').nth(1).click()
  const card = page.locator('.task-row-card').first()
  await expect(card.getByRole('button', { name: 'Ouvrir dans un lecteur externe' })).toBeVisible()

  await page.goto(
    '/app/anime?url=' +
      encodeURIComponent('https://example.test/auto-detected') +
      '&source=french-manga',
  )
  const epRow = page.locator('.tachiyomi-episode-item').first()
  await expect(epRow.getByRole('button', { name: /lecteur externe/i })).toBeVisible()
  await epRow.locator('.btn-play-ep').click()
  await expect(page.locator('.player-modal .player-external-btn')).toBeVisible()
  await noOverflow(page)
})
