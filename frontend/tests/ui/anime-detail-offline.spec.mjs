import { test, expect } from '@playwright/test'
import { mockApp } from './fixtures.mjs'

const PNG_1X1 = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+X2Z0AAAAASUVORK5CYII=',
  'base64',
)

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
  test(`library anime opens from offline snapshot, keeps downloaded episodes playable, and updates on refresh at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 820 })
    const animeUrl = 'https://voiranime.cx/anime/frieren/'
    const coverUrl = 'https://voiranime.cx/posters/frieren.png'
    let onlineNow = false

    await mockApp(page, { taskList: [] })

    await page.route('**/api/media/image-proxy*', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'image/png',
        body: PNG_1X1,
      }),
    )

    await page.route('**/api/anime/detail*', (route) => {
      const reqUrl = new URL(route.request().url())
      const refresh = reqUrl.searchParams.get('refresh') === 'true'

      if (refresh && !onlineNow) {
        return route.fulfill({
          status: 503,
          json: {
            detail: 'Connexion Internet indisponible pour actualiser la fiche.',
          },
        })
      }

      if (refresh && onlineNow) {
        return route.fulfill({
          json: {
            success: true,
            source: 'voir-anime',
            sourceName: 'VoirAnime',
            isFavorite: true,
            autoDownload: false,
            fromCache: false,
            cachedAt: '2026-11-24T12:00:00Z',
            downloadedEpisodes: [1],
            watchedEpisodes: [],
            totalEpisodes: 2,
            downloadedCount: 1,
            watchedCount: 0,
            anime: {
              title: 'Frieren',
              url: animeUrl,
              imageUrl: coverUrl,
              source: 'voir-anime',
              version: 'VF',
              synopsis: 'Voyage après la quête du héros.',
              genres: ['Aventure'],
              episodes: [
                {
                  number: 1,
                  title: 'Épisode 1',
                  version: 'VF',
                  playerUrl: `${animeUrl}ep-1/`,
                  downloadPageUrl: `${animeUrl}ep-1/`,
                  isDownloaded: true,
                  isWatched: false,
                  downloadTaskId: 'local-frieren-1',
                },
                {
                  number: 2,
                  title: 'Épisode 2',
                  version: 'VF',
                  playerUrl: `${animeUrl}ep-2/`,
                  downloadPageUrl: `${animeUrl}ep-2/`,
                  isDownloaded: false,
                  isWatched: false,
                  downloadTaskId: null,
                },
              ],
            },
          },
        })
      }

      return route.fulfill({
        json: {
          success: true,
          source: 'voir-anime',
          sourceName: 'VoirAnime',
          isFavorite: true,
          autoDownload: false,
          fromCache: true,
          cachedAt: '2026-11-24T10:00:00Z',
          downloadedEpisodes: [1],
          watchedEpisodes: [],
          totalEpisodes: 1,
          downloadedCount: 1,
          watchedCount: 0,
          anime: {
            title: 'Frieren',
            url: animeUrl,
            imageUrl: coverUrl,
            source: 'voir-anime',
            version: 'VF',
            synopsis: 'Voyage après la quête du héros.',
            genres: ['Aventure'],
            episodes: [
              {
                number: 1,
                title: 'Épisode 1',
                version: 'VF',
                playerUrl: `${animeUrl}ep-1/`,
                downloadPageUrl: `${animeUrl}ep-1/`,
                isDownloaded: true,
                isWatched: false,
                downloadTaskId: 'local-frieren-1',
              },
            ],
          },
        },
      })
    })

    await page.goto(`/app/anime?url=${encodeURIComponent(animeUrl)}&source=voir-anime`)

    await expect(page.locator('.tachiyomi-main-title')).toHaveText('Frieren')
    await expect(page.locator('.error-state')).toHaveCount(0)
    await expect(page.locator('.tachiyomi-episode-item')).toHaveCount(1)
    await expect(page.locator('.tachiyomi-cache-line')).toContainText('Hors ligne · fiche locale')
    await expect(page.locator('img.tachiyomi-cover')).toHaveAttribute(
      'src',
      `/api/media/image-proxy?url=${encodeURIComponent(coverUrl)}`,
    )

    // Restore connectivity and manually refresh like Mihon.
    onlineNow = true
    await page.getByRole('button', { name: 'Actualiser la fiche' }).click()

    await expect(page.locator('.tachiyomi-episode-item')).toHaveCount(2)
    await expect(page.locator('.tachiyomi-cache-line')).toHaveCount(0)
    await expect(page.locator('body')).toContainText('Fiche mise à jour (+1 épisode(s)).')
    await noOverflow(page)
  })
}
