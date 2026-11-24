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
  test(`downloaded episode hides subtitle toggle, blocks re-download, and plays locally at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 820 })
    const resolveCalls = []

    await mockApp(page, { taskList: [] })

    await page.route('**/api/anime/detail*', (route) =>
      route.fulfill({
        json: {
          success: true,
          source: 'voir-anime',
          sourceName: 'VoirAnime',
          isFavorite: false,
          autoDownload: false,
          downloadedEpisodes: [1],
          watchedEpisodes: [],
          totalEpisodes: 2,
          downloadedCount: 1,
          watchedCount: 0,
          anime: {
            title: 'One Punch Man (VF)',
            url: 'https://voiranime.cx/anime/one-punch-man-vf/',
            imageUrl: '',
            source: 'voir-anime',
            version: 'VF',
            genres: ['Action'],
            episodes: [
              {
                number: 1,
                title: 'Épisode 1',
                version: 'VF',
                playerUrl: 'https://voiranime.cx/anime/one-punch-man-vf/ep-1/',
                downloadPageUrl: 'https://voiranime.cx/anime/one-punch-man-vf/ep-1/',
                isDownloaded: true,
                isWatched: false,
                downloadTaskId: 'local-abc123',
              },
              {
                number: 2,
                title: 'Épisode 2',
                version: 'VF',
                playerUrl: 'https://voiranime.cx/anime/one-punch-man-vf/ep-2/',
                downloadPageUrl: 'https://voiranime.cx/anime/one-punch-man-vf/ep-2/',
                isDownloaded: false,
                isWatched: false,
                downloadTaskId: null,
              },
            ],
          },
        },
      }),
    )

    await page.route('**/api/playback/session', (route) =>
      route.fulfill({
        json: {
          sessionId: 'd'.repeat(32),
          source: 'voir-anime',
          animeUrl: 'https://voiranime.cx/anime/one-punch-man-vf/',
          episodeNumber: 1,
          version: 'VF',
          positionSeconds: 0,
          durationSeconds: 0,
          selection: { quality: 'HD', server: 'auto', subtitle: null, audio: null },
        },
      }),
    )

    await page.route('**/api/media/stream/resolve*', (route) => {
      const u = new URL(route.request().url())
      resolveCalls.push(Object.fromEntries(u.searchParams.entries()))
      return route.fulfill({
        json: {
          success: true,
          isDownloaded: true,
          isHls: false,
          sourceType: 'local',
          taskId: 'local-abc123',
          streamUrl: '/api/media/stream/local-abc123',
          title: 'One Punch Man (VF) - Épisode 1',
          subtitles: [],
          serverType: 'Disque dur (Local)',
          selectedQuality: 'Original (Local)',
          qualities: {},
        },
      })
    })

    await page.route('**/api/media/stream/local-abc123*', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'video/mp4',
        body: '',
      }),
    )

    await page.goto(
      '/app/anime?url=' +
        encodeURIComponent('https://voiranime.cx/anime/one-punch-man-vf/') +
        '&source=voir-anime',
    )

    const rows = page.locator('.tachiyomi-episode-item')
    await expect(rows).toHaveCount(2)

    const ep1Row = rows.nth(0)
    const ep2Row = rows.nth(1)

    await expect(ep1Row.locator('.ep-done-badge')).toBeVisible()
    await expect(ep1Row.locator('.ep-sub-control')).toHaveCount(0)
    await expect(ep1Row.locator('.btn-download-ep')).toHaveCount(0)
    await expect(ep1Row.locator('span.tachiyomi-circle-btn.is-downloaded')).toBeVisible()
    await expect(ep1Row.locator('.episode-check')).toBeDisabled()

    await expect(ep2Row.locator('.ep-sub-control')).toHaveCount(1)
    await expect(ep2Row.locator('.btn-download-ep')).toHaveCount(1)
    await expect(ep2Row.locator('.episode-check')).toBeEnabled()

    // Batch selection buttons never select Ep 1.
    await page.getByRole('button', { name: 'Tout', exact: true }).click()
    await expect(ep1Row.locator('.episode-check')).not.toBeChecked()
    await expect(ep2Row.locator('.episode-check')).toBeChecked()

    await page.getByRole('button', { name: 'Inverser', exact: true }).click()
    await expect(ep1Row.locator('.episode-check')).not.toBeChecked()
    await expect(ep2Row.locator('.episode-check')).not.toBeChecked()

    await page.getByRole('button', { name: 'Non vus', exact: true }).click()
    await expect(ep1Row.locator('.episode-check')).not.toBeChecked()
    await expect(ep2Row.locator('.episode-check')).toBeChecked()

    // Clicking Play on Ep 1 resolves with taskId and displays the local badge.
    await ep1Row.locator('.btn-play-ep').click()
    await expect.poll(() => resolveCalls.length).toBe(1)
    expect(resolveCalls[0].taskId).toBe('local-abc123')
    await expect(page.locator('.local-badge')).toBeVisible()
    await expect(page.locator('video.video-element')).toHaveAttribute(
      'src',
      '/api/media/stream/local-abc123',
    )

    await page.locator('.player-close-btn').click()
    await noOverflow(page)

    // Deleting a downloaded episode asks confirmation, calls API, and reverts row to downloadable.
    let deletePayload = null
    await page.route('**/api/media/downloaded/delete', async (route) => {
      deletePayload = route.request().postDataJSON()
      await route.fulfill({
        json: { success: true, deletedFiles: 1, removedTaskIds: ['local-abc123'] },
      })
    })
    await ep1Row.locator('.btn-delete-ep').click()
    const dialog = page.locator('.confirmation-dialog')
    await expect(dialog).toBeVisible()
    await dialog.getByRole('button', { name: 'Supprimer', exact: true }).click()

    await expect.poll(() => deletePayload).not.toBeNull()
    expect(deletePayload.taskId).toBe('local-abc123')
    expect(deletePayload.episodeNumber).toBe(1)
    expect(deletePayload.version).toBe('VF')

    await expect(dialog).toBeHidden()
    await expect(ep1Row.locator('.ep-done-badge')).toHaveCount(0)
    await expect(ep1Row.locator('.btn-delete-ep')).toHaveCount(0)
    await expect(ep1Row.locator('.btn-download-ep')).toHaveCount(1)
    await expect(ep1Row.locator('.ep-sub-control')).toHaveCount(1)
    await expect(ep1Row.locator('.episode-check')).toBeEnabled()
    await noOverflow(page)
  })
}
