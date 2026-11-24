import { test, expect } from '@playwright/test'
import { mockApp } from './fixtures.mjs'

for (const lastError of ['network', 'geo_blocked']) {
  test(`proxy rotation requires explicit geography: ${lastError}`, async ({ page }) => {
    await mockApp(page)
    await page.route('**/api/sources/aniyomi-long/catalogue?**', (route) =>
      route.fulfill({
        status: 502,
        json: { code: lastError, error: 'Source unavailable', domain: 'example.test' },
      }),
    )
    await page.route('**/api/network/sessions', (route) =>
      route.fulfill({
        json: {
          browsers: [],
          modes: [],
          webviewAvailable: false,
          platform: 'desktop',
          clientLocal: true,
          sessions: [
            {
              domain: 'example.test',
              lastError,
              modes: [],
              verificationRequired: false,
              usesProxy: false,
            },
          ],
        },
      }),
    )
    await page.goto('/app/sources/aniyomi-long?mode=catalogue')
    await expect(page.locator('.catalogue-error')).toBeVisible()
    const button = page.getByRole('button', { name: 'Changer de proxy et réessayer' })
    if (lastError === 'geo_blocked') await expect(button).toBeVisible()
    else await expect(button).toHaveCount(0)
  })
}

test('a returned WebView session retries once without claiming verified access', async ({
  page,
}) => {
  await mockApp(page)
  let catalogueCalls = 0
  let completed = false
  let rechecks = 0
  await page.route('**/api/sources/aniyomi-long/catalogue?**', (route) => {
    catalogueCalls++
    return completed
      ? route.fulfill({
          json: { source: 'aniyomi-long', results: [], nextCursor: null, queryScope: 'catalogue' },
        })
      : route.fulfill({
          status: 409,
          json: {
            code: 'verification_required',
            error: 'Vérification nécessaire',
            domain: 'example.test',
            url: 'https://example.test/',
          },
        })
  })
  await page.route('**/api/network/**', (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/network/sessions')
      return route.fulfill({
        json: {
          platform: 'android',
          clientLocal: true,
          webviewAvailable: true,
          browsers: [],
          modes: [{ id: 'webview', available: true, capturesCookies: true, reason: null }],
          sessions: [],
        },
      })
    if (path === '/api/network/verification')
      return route.fulfill({
        json: { id: 'webview-test', domain: 'example.test', mode: 'webview' },
      })
    if (path === '/api/network/webview/open')
      return route.fulfill({
        json: { id: 'webview-manual', domain: 'aniyomi-long.test', mode: 'webview' },
      })
    if (path.endsWith('/complete')) {
      completed = true
      return route.fulfill({
        json: {
          success: true,
          domain: 'example.test',
          resumed: 0,
          sessionImported: true,
          accessVerified: false,
        },
      })
    }
    if (path.endsWith('/status')) return route.fulfill({ json: { status: 'pending' } })
    rechecks++
    return route.fulfill({ json: {} })
  })
  await page.goto('/app/sources/aniyomi-long?mode=catalogue')
  await expect(page.getByRole('button', { name: 'Changer de proxy et réessayer' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Ouvrir en WebView', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Vérifier dans la WebView', exact: true }).click()
  await page.getByRole('button', { name: 'J’ai terminé la vérification', exact: true }).click()
  const notice = page.locator('.verification-notice')
  await expect(notice).toContainText('Session WebView récupérée')
  await expect(notice).not.toContainText('Accès vérifié')
  await expect.poll(() => catalogueCalls).toBe(2)
  expect(rechecks).toBe(0)
})

for (const [width, lang] of [
  [360, 'fr'],
  [1280, 'en'],
]) {
  test(`verification browser can be configured at ${width}px (${lang})`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await mockApp(page, { lang })
    const saved = []
    let values = { chromiumPath: '', headless: false, managed: false }
    await page.route('**/api/network/browser-settings', async (route) => {
      if (route.request().method() === 'POST') {
        saved.push(route.request().postDataJSON())
        values = { ...values, ...saved.at(-1) }
      }
      return route.fulfill({ json: values })
    })
    await page.goto(`/app/settings?tab=proxy&lang=${lang}`)
    const path = page.locator('#verification-chromium-path')
    await expect(path).toBeVisible()
    await path.fill('/opt/My Browser/chromium')
    const section = path.locator('xpath=ancestor::section')
    await section.getByRole('checkbox').check()
    await section.getByRole('button').click()
    await expect.poll(() => saved.length).toBe(1)
    expect(saved[0]).toEqual({ chromiumPath: '/opt/My Browser/chromium', headless: true })
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      width,
    )
    await page.screenshot({
      path: `../artifacts/mobile-ui/browser-verification-${width}-${lang}.png`,
      fullPage: true,
    })
    values.managed = true
    await page.reload()
    await expect(path).toBeDisabled()
    await expect(section.getByRole('button')).toBeDisabled()
  })
}
