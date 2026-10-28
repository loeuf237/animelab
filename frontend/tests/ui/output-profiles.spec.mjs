import { test, expect } from '@playwright/test'
import { mockApp } from './fixtures.mjs'

for (const width of [360, 1280]) {
  test(`output profile is snapshotted and unavailable modes disabled at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 })
    await mockApp(page)
    await page.route('**/api/anime/detail?*', (route) =>
      route.fulfill({
        json: {
          success: true,
          source: 'voir-anime',
          isFavorite: false,
          autoDownload: false,
          downloadedEpisodes: [],
          watchedEpisodes: [],
          totalEpisodes: 1,
          downloadedCount: 0,
          watchedCount: 0,
          anime: {
            title: 'Test',
            url: 'https://example.test/anime',
            imageUrl: '',
            genres: [],
            episodes: [
              { number: 1, title: 'Episode 1', downloadPageUrl: 'https://example.test/episode' },
            ],
          },
        },
      }),
    )
    await page.route('**/api/download/output-profiles', (route) =>
      route.fulfill({
        json: [
          { mode: 'ORIGINAL', available: true, reason: '' },
          { mode: 'MKV_SOFT', available: true, reason: '' },
          { mode: 'MP4_HARD', available: false, reason: 'Ce format n’est pas encore disponible' },
        ],
      }),
    )
    const queued = []
    await page.route('**/api/download', async (route) => {
      queued.push(route.request().postDataJSON())
      await route.fulfill({ json: { success: true, taskId: 'test' } })
    })
    await page.goto('/app/anime?url=https%3A%2F%2Fexample.test%2Fanime&source=voir-anime')
    const picker = page.getByLabel('Format de sortie')
    await expect(picker.locator('option[value="MP4_HARD"]')).toHaveJSProperty('disabled', true)
    await picker.selectOption('MKV_SOFT')
    await page.getByTitle("Télécharger l'épisode", { exact: true }).click()
    await expect.poll(() => queued.length).toBe(1)
    expect(queued[0].outputProfile).toEqual({ version: 1, mode: 'MKV_SOFT', keepOriginals: true })
    expect(queued[0].downloadSubtitles).toBe(true)
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      width,
    )
  })
}
