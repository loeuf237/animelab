import { test, expect } from '@playwright/test'
import { mockApp, tasks } from './fixtures.mjs'

for (const width of [360, 1280]) {
  test(`local output dialog selects tracks and offsets at ${width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 })
    await mockApp(page, {
      taskList: [{ ...tasks[3], id: 'local', savePath: '/downloads/reference.mkv' }],
    })
    const profiles = ['ORIGINAL', 'MKV_SOFT', 'SIDECAR', 'MP4_HARD'].map((mode) => ({
      mode,
      available: true,
      reason: '',
      trackSelectionAvailable: true,
    }))
    const tracks = [
      { id: 'v0', kind: 'video', label: 'Image', lang: 'und', default: true },
      { id: 'a0', kind: 'audio', label: 'Japonais', lang: 'jpn', default: true },
      { id: 'a1', kind: 'audio', label: 'English', lang: 'eng', default: false },
      { id: 's0', kind: 'subtitle', label: 'Français', lang: 'fra', default: true },
      { id: 's1', kind: 'subtitle', label: 'English CC', lang: 'eng', default: false },
    ].map((track) => ({
      ...track,
      format: 'test',
      automatic: false,
      forced: false,
      embedded: true,
    }))
    await page.route('**/api/download/local/media-inventory', (route) =>
      route.fulfill({
        json: {
          tracks,
          profiles,
          warnings: [],
          duration: 1200,
          outputProfile: { version: 1, mode: 'MKV_SOFT', keepOriginals: true },
        },
      }),
    )
    const requests = []
    await page.route('**/api/download/local/output', (route) => {
      requests.push(route.request().postDataJSON())
      return route.fulfill({ json: { success: true } })
    })
    await page.goto('/app/downloads')
    await page.getByRole('button', { name: 'Terminés 1', exact: true }).click()
    await page.getByRole('button', { name: 'Pistes et format', exact: true }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    expect(await page.locator('#app').evaluate((element) => element.inert)).toBe(true)
    await dialog.getByLabel('Format de sortie').selectOption('MP4_HARD')
    const english = dialog.locator('.output-track').filter({ hasText: 'Audio · English' })
    await english.getByRole('radio').check()
    const french = dialog.locator('.output-track').filter({ hasText: 'Français' })
    await expect(french.getByRole('radio')).toBeChecked()
    await french.getByRole('spinbutton').fill('0.5')
    await dialog.screenshot({ path: testInfo.outputPath('selected-tracks.png') })
    await dialog.getByRole('button', { name: 'Produire le fichier' }).click()
    await expect.poll(() => requests.length).toBe(1)
    expect(requests[0].mode).toBe('MP4_HARD')
    expect(requests[0].burnTrackId).toBe('s0')
    expect(
      requests[0].selections
        .filter((track) => track.trackId.startsWith('a'))
        .map((track) => track.trackId),
    ).toEqual(['a1'])
    expect(requests[0].selections.find((track) => track.trackId === 's0').offsetSeconds).toBe(0.5)
    await expect(dialog).not.toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      width,
    )
  })
}
