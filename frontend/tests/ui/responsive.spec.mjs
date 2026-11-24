import { test, expect } from '@playwright/test'
import { mockApp, tasks } from './fixtures.mjs'
import { mkdir } from 'node:fs/promises'

async function noOverflow(page) {
  const width = page.viewportSize().width
  // Resizing is acknowledged before media queries necessarily reach a layout frame.
  // Poll the rendered bounds, so assertions cover the settled UI without sleeps.
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

async function capture(page, name, width, lang, theme) {
  if (!(
    (width === 360 && lang === 'fr') ||
    (width === 390 && lang === 'en') ||
    (width === 1440 && lang === 'fr')
  ))
    return
  await mkdir('../artifacts/mobile-ui', { recursive: true })
  await page.screenshot({
    path: `../artifacts/mobile-ui/after-${lang}-${theme}-${width}-${name}.png`,
    fullPage: true,
  })
  await page.screenshot({ path: `../artifacts/mobile-ui/viewport-${lang}-${width}-${name}.png` })
}
for (const width of [320, 360, 390, 412, 768, 769, 900, 1024, 1440])
  for (const [lang, theme] of [
    ['fr', 'dark'],
    ['en', 'light'],
  ]) {
    test.describe(`${width}px ${lang} ${theme}`, () => {
      test.use({
        viewport: { width, height: 780 },
        isMobile: width <= 768,
        hasTouch: width <= 768,
        locale: lang,
      })
      test('download cards keep readable content and reachable actions in every state', async ({
        page,
      }) => {
        const errors = []
        page.on('pageerror', (error) => errors.push(error.message))
        await mockApp(page, {
          lang,
          theme,
          taskList: tasks.filter((t) => t.status !== 'VERIFICATION_REQUIRED'),
        })
        await page.goto('/app/downloads')
        await expect(page.locator('.task-row-card')).toHaveCount(3)
        await noOverflow(page)
        if (width <= 768) {
          expect((await page.locator('.task-row-card').first().boundingBox()).y).toBeLessThan(400)
          await expect(page.locator('.download-actions')).toBeHidden()
          await page.locator('.download-tools-toggle').click()
          await expect(page.locator('.download-actions')).toBeVisible()
          await page.locator('.download-tools-toggle').click()
        }
        for (const index of [0, 1, 2, 3]) {
          await page.locator('.download-tabs > button').nth(index).click()
          await noOverflow(page)
          for (const card of await page.locator('.task-row-card').all()) {
            const main = await card.locator('.task-col-main').boundingBox()
            const actions = await card.locator('.task-col-actions').boundingBox()
            expect(main.width).toBeGreaterThan(155)
            if (width <= 900) expect(actions.y).toBeGreaterThanOrEqual(main.y + main.height - 1)
            if (width <= 768) expect((await card.boundingBox()).height).toBeLessThan(470)
            for (const button of await card.locator('.task-col-actions button').all()) {
              const box = await button.boundingBox()
              if (width <= 768) {
                expect(box.height).toBeGreaterThanOrEqual(44)
                expect(box.width).toBeGreaterThanOrEqual(44)
              }
              expect(box.x).toBeGreaterThanOrEqual(0)
              expect(box.x + box.width).toBeLessThanOrEqual(width + 1)
            }
          }
          if (index === 0) await capture(page, 'downloads', width, lang, theme)
          if (index === 1) {
            await capture(page, 'completed', width, lang, theme)
            await page.locator('.export-notice summary').click()
            await expect(page.locator('.export-notice details')).toHaveAttribute('open', '')
            await noOverflow(page)
          }
        }
        if (width <= 768) {
          await page.evaluate(() => scrollTo(0, document.body.scrollHeight))
          const card = await page.locator('.task-row-card').last().boundingBox()
          const nav = await page.locator('.bottom-nav').boundingBox()
          expect(card.y + card.height).toBeLessThanOrEqual(nav.y)
          for (const label of await page
            .locator('.bottom-nav-link > span:not(.bottom-nav-badge)')
            .all())
            expect(await label.evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true)
        }
        expect(errors).toEqual([])
      })
      test('all settings sections remain accessible without clipped tabs', async ({ page }) => {
        const errors = []
        page.on('pageerror', (error) => errors.push(error.message))
        await mockApp(page, { lang, theme })
        await page.goto('/app/settings')
        for (const [index, section] of [
          'general',
          'downloads',
          'sources',
          'storage',
          'proxy',
          'about',
        ].entries()) {
          if (width <= 768)
            await page.locator('.settings-section-select select').selectOption(section)
          else await page.locator('.settings-nav-tab').nth(index).click()
          await expect(page.locator('.settings-tab-pane.active')).toBeVisible()
          await noOverflow(page)
          if (section === 'sources')
            for (const button of await page.locator('.source-tab-btn').all()) {
              await button.click()
              await noOverflow(page)
            }
          if (section === 'general' || section === 'sources')
            await capture(page, `settings-${section}`, width, lang, theme)
        }
        expect(errors).toEqual([])
      })
      test('sources and catalogues fit the viewport', async ({ page }) => {
        const errors = []
        page.on('pageerror', (error) => errors.push(error.message))
        await mockApp(page, { lang, theme })
        await page.goto('/app/sources')
        await expect(page.locator('.source-card')).toHaveCount(5)
        await noOverflow(page)
        await capture(page, 'sources', width, lang, theme)
        await page.locator('.source-view-menu > summary').first().click()
        await page.locator('.source-card-actions button').first().click()
        await expect(page).toHaveURL(/sources\/voir-anime/)
        await page.locator('.catalogue-tools > button').first().click()
        await expect(page.locator('.source-filters')).toBeVisible()
        await noOverflow(page)
        expect(errors).toEqual([])
      })
      test('home, library and history fit the viewport', async ({ page }) => {
        const errors = []
        page.on('pageerror', (error) => errors.push(error.message))
        await mockApp(page, { lang, theme })
        for (const view of ['', 'library', 'history']) {
          await page.goto('/app/' + view)
          await expect(page.locator('#main-content h1')).toBeVisible()
          await noOverflow(page)
        }
        expect(errors).toEqual([])
      })
      test('extensions and more pages fit the viewport', async ({ page }) => {
        const errors = []
        page.on('pageerror', (error) => errors.push(error.message))
        await mockApp(page, { lang, theme })
        await page.goto('/app/extensions')
        await expect(page.locator('#main-content h1')).toBeVisible()
        await expect(page.locator('.ext-card')).toHaveCount(12)
        await page.locator('.extension-management > summary').click()
        const input = await page.locator('.extension-repo-input').boundingBox()
        const container = await page.locator('.extension-repo-card').boundingBox()
        expect(input.x).toBeGreaterThanOrEqual(container.x)
        expect(input.x + input.width).toBeLessThanOrEqual(container.x + container.width)
        await capture(page, 'extensions', width, lang, theme)
        await noOverflow(page)
        await page.goto('/app/more')
        await expect(page.locator('#main-content h1')).toBeVisible()
        await noOverflow(page)
        expect(errors).toEqual([])
      })
    })
  }

test('mobile actions call the correct APIs, keyboard search and protection details remain usable', async ({
  page,
}) => {
  await page.setViewportSize({ width: 360, height: 780 })
  const requests = await mockApp(page)
  await page.goto('/app/downloads')
  await expect(page.locator('.task-row-card')).toHaveCount(4)
  await expect(page.locator('.download-verification')).toBeVisible()
  await page.locator('.download-verification > summary').click()
  await expect(page.locator('.verification-site-link')).toHaveAttribute(
    'href',
    'https://example.test/',
  )
  await noOverflow(page)
  await page.locator('.download-verification > summary').click()
  await page.locator('.task-row-card.status-downloading .task-col-actions button').first().click()
  await expect
    .poll(() => requests.some((r) => r.path === '/api/download/1/pause' && r.method === 'POST'))
    .toBe(true)
  await page.locator('.speed-limit-chip').first().click()
  await expect(page.locator('.confirmation-dialog')).toBeVisible()
  await noOverflow(page)
  await page.locator('.confirmation-actions button').first().click()
  await page.locator('.download-tabs > button').nth(1).click()
  await expect(page.locator('.download-verification')).toBeHidden()
  await page.getByRole('button', { name: 'Exporter vers le stockage', exact: true }).click()
  await expect
    .poll(() =>
      requests.some((r) => r.path === '/api/system/android/export' && r.body.taskId === '4'),
    )
    .toBe(true)
  await page.keyboard.press('Control+k')
  await expect(page.locator('.palette-card')).toBeVisible()
  await noOverflow(page)
  await page.screenshot({ path: '../artifacts/mobile-ui/after-search-360.png' })
  await page.keyboard.press('Escape')
  await expect(page.locator('.palette-card')).toBeHidden()
})

test('export failures and rotation preserve readable text, settings and working actions', async ({
  page,
}) => {
  const failedExport = {
    ...tasks[3],
    exportStatus: 'EXPORT_FAILED',
    exportError:
      'Accès refusé à /storage/emulated/0/Download/AnimeLab/une-serie-avec-un-tres-long-titre/episode.mp4',
  }
  const requests = await mockApp(page, { taskList: [failedExport] })
  await page.setViewportSize({ width: 360, height: 780 })
  await page.goto('/app/downloads')
  const card = page.locator('.task-row-card')
  await expect(card).toHaveCount(1)
  await expect(card.locator('.export-warning')).toBeVisible()
  await card.locator('.export-notice details').last().locator('summary').click()
  for (const width of [320, 740, 900, 1440, 360]) {
    await page.setViewportSize({ width, height: 780 })
    // Viewport acknowledgement precedes the browser's media-query layout frame.
    await page.evaluate(
      () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))),
    )
    await noOverflow(page)
    expect((await card.locator('.task-col-main').boundingBox()).width).toBeGreaterThan(155)
  }
  await card.getByRole('button', { name: 'Réessayer l’export' }).click()
  await expect.poll(() => requests.some((r) => r.path === '/api/system/android/export')).toBe(true)
  await page.locator('.download-tools-toggle').click()
  await page.getByRole('button', { name: 'Paramètres rapides de débit et téléchargement' }).click()
  await expect(page.locator('.quick-settings-panel')).toBeVisible()
  await noOverflow(page)
  await page.locator('.quick-settings-header button').click()
  await expect
    .poll(() => requests.some((r) => r.path === '/api/download/settings' && r.method === 'POST'))
    .toBe(true)
  await page.goto('/app/settings')
  await page.locator('.settings-section-select select').selectOption('sources')
  await page.locator('.source-tab-btn').nth(2).click()
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.evaluate(
    () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))),
  )
  await expect(page.locator('.settings-nav-tab.active')).toHaveText('Sources')
  await page.setViewportSize({ width: 360, height: 780 })
  await page.evaluate(
    () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))),
  )
  await expect(page.locator('.settings-section-select select')).toHaveValue('sources')
  await noOverflow(page)
})

for (const [width, height] of [
  [360, 640],
  [740, 360],
])
  test(`small or landscape viewport ${width}x${height} keeps dialogs reachable`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height })
    await mockApp(page)
    await page.goto('/app/downloads')
    await page.locator('.speed-limit-chip').first().click()
    const modal = page.locator('.confirmation-dialog')
    await expect(modal).toBeVisible()
    const bounds = await modal.boundingBox()
    expect(bounds.y).toBeGreaterThanOrEqual(0)
    expect(bounds.y + bounds.height).toBeLessThanOrEqual(height)
    await modal.locator('.confirmation-actions button').first().click()
    await page.keyboard.press('Control+k')
    const search = page.locator('.palette-card')
    await expect(search).toBeVisible()
    const searchBounds = await search.boundingBox()
    expect(searchBounds.y).toBeGreaterThanOrEqual(0)
    expect(searchBounds.y + searchBounds.height).toBeLessThanOrEqual(height + 1)
    await noOverflow(page)
    await mkdir('../artifacts/mobile-ui', { recursive: true })
    await page.screenshot({ path: `../artifacts/mobile-ui/search-${width}x${height}.png` })
    await page.keyboard.press('Escape')
    await expect(search).toBeHidden()
  })

for (const [width, height] of [
  [360, 780],
  [780, 360],
  [1440, 900],
]) {
  test(`player next/prev episode works for local downloads and fits ${width}x${height}`, async ({
    page,
  }) => {
    const completedTasks = [1, 2].map((ep) => ({
      id: 100 + ep,
      animeName: 'Sample Series',
      animeUrl: 'https://example.test/sample',
      episodeNumber: ep,
      fileName: `Sample Series - Episode ${ep} [VF].mp4`,
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
    }))
    await page.setViewportSize({ width, height })
    await mockApp(page, { taskList: completedTasks })
    await page.route('**/api/media/subtitles/**', (route) => route.fulfill({ json: [] }))
    await page.route('**/api/media/stream/*', (route) =>
      route.fulfill({ status: 200, contentType: 'video/mp4', body: '' }),
    )
    await page.goto('/app/downloads')
    await page.locator('.download-tabs > button').nth(1).click()
    await expect(page.locator('.task-row-card')).toHaveCount(2)
    await page.locator('.task-row-card').first().locator('button[title*="Lire"]').click()

    const modal = page.locator('.player-modal')
    await expect(modal).toBeVisible()
    await expect(modal.locator('.episode-title')).toContainText('Épisode 1')
    const nextBtn = modal.getByRole('button', { name: 'Épisode suivant' })
    const prevBtn = modal.getByRole('button', { name: 'Épisode précédent' })
    await expect(prevBtn).toBeDisabled()
    await expect(nextBtn).toBeEnabled()

    const bounds = await modal.boundingBox()
    expect(bounds.x).toBeGreaterThanOrEqual(0)
    expect(bounds.y).toBeGreaterThanOrEqual(0)
    expect(bounds.y + bounds.height).toBeLessThanOrEqual(height + 1)
    const nextBox = await nextBtn.boundingBox()
    expect(nextBox.y + nextBox.height).toBeLessThanOrEqual(height + 1)
    await noOverflow(page)

    await nextBtn.click()
    await expect(modal.locator('.episode-title')).toContainText('Épisode 2')
    await expect(modal.locator('video.video-element')).toHaveAttribute(
      'src',
      '/api/media/stream/102',
    )
    await expect(prevBtn).toBeEnabled()
    await expect(nextBtn).toBeDisabled()

    await prevBtn.click()
    await expect(modal.locator('.episode-title')).toContainText('Épisode 1')
    await expect(modal.locator('video.video-element')).toHaveAttribute(
      'src',
      '/api/media/stream/101',
    )
  })
}
