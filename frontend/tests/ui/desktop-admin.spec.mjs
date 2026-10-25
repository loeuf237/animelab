import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'

const origin = 'http://127.0.0.1:41234'
const token = 'desktop-test-capability-never-a-real-secret'
const assets = Object.fromEntries(
  ['html', 'js', 'css'].map((extension) => [
    extension,
    readFileSync(new URL(`../../../animelab/desktop/panel.${extension}`, import.meta.url)),
  ]),
)

async function panel(page, { unauthorized = false } = {}) {
  let saved = null
  const actions = []
  await page.route(`${origin}/**`, async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.startsWith('/api/')) {
      expect(route.request().headers().authorization).toBe(`Bearer ${token}`)
      if (unauthorized) return route.fulfill({ status: 401, json: { error: 'Unauthorized' } })
      if (path === '/api/action') {
        actions.push(route.request().postDataJSON().action)
        return route.fulfill({ status: 202, json: { accepted: true } })
      }
      if (path === '/api/diagnostics') {
        return route.fulfill({
          json: {
            ok: false,
            checks: [
              { name: 'database', ok: true, detail: 'OK' },
              { name: 'backend', ok: false, detail: '<b>Engine unavailable</b>' },
            ],
          },
        })
      }
      if (path === '/api/status' && actions.includes('stop'))
        return route.abort('connectionrefused')
      if (path === '/api/config') saved = route.request().postDataJSON()
      return route.fulfill({
        json: {
          ready: true,
          running: true,
          busy: false,
          port: 8091,
          configuredPort: saved?.port ?? 8080,
          browser: saved?.browser ?? false,
          url: 'http://127.0.0.1:8091/spa/',
          portFallback: true,
          nativeError: 'Native window unavailable',
        },
      })
    }
    const extension = path === '/' ? 'html' : path.split('.').at(-1)
    return route.fulfill({
      body: assets[extension] || '',
      contentType: { html: 'text/html', js: 'text/javascript', css: 'text/css' }[extension],
      headers: {
        'Content-Security-Policy':
          "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
      },
    })
  })
  await page.goto(`${origin}/#${token}`)
  return { actions, saved: () => saved }
}

for (const width of [360, 720, 1280]) {
  test(`desktop administration remains usable at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    const controller = await panel(page)
    await page.locator('#language').selectOption('fr')
    await expect(page.locator('#state')).toHaveText('Prêt')
    await expect(page.locator('#warning')).toContainText('port demandé est occupé')
    await expect(page.locator('#open-app')).toHaveAttribute('href', 'http://127.0.0.1:8091/spa/')
    expect(page.url()).not.toContain(token)
    await page.getByLabel('Port de l’application').fill('9092')
    await page.getByLabel('Ouvrir dans mon navigateur').check()
    await page.getByRole('button', { name: 'Enregistrer', exact: true }).click()
    await expect(page.locator('#notice')).toContainText('Paramètres enregistrés')
    expect(controller.saved()).toEqual({ port: 9092, browser: true })
    await page.getByRole('button', { name: 'Lancer le diagnostic rapide' }).click()
    await expect(page.locator('#results li')).toHaveCount(2)
    await expect(page.locator('#results')).toContainText('<b>Engine unavailable</b>')
    await expect(page.locator('#results b')).toHaveCount(0)
    const download = page.waitForEvent('download')
    await page.getByRole('button', { name: 'Télécharger le rapport de diagnostic' }).click()
    expect((await download).suggestedFilename()).toBe('animelab-desktop-diagnostics.json')
    const fits = await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    )
    expect(fits).toBe(true)
    await page.screenshot({
      path: `../artifacts/mobile-ui/desktop-admin-${width}.png`,
      fullPage: true,
    })
    page.once('dialog', (dialog) => dialog.accept())
    await page.getByRole('button', { name: 'Redémarrer le serveur' }).click()
    await expect(page.locator('#notice')).toContainText('Redémarrage demandé')
    expect(controller.actions).toEqual(['restart'])
    page.once('dialog', (dialog) => dialog.dismiss())
    await page.getByRole('button', { name: 'Quitter AnimeLab' }).click()
    expect(controller.actions).toEqual(['restart'])
    page.once('dialog', (dialog) => dialog.accept())
    await page.getByRole('button', { name: 'Quitter AnimeLab' }).click()
    await expect(page.locator('#notice')).toContainText('AnimeLab est arrêté')
    await expect(page.locator('#open-app')).toBeHidden()
    expect(controller.actions).toEqual(['restart', 'stop'])
  })
}

test('administration explains a missing authorization in English', async ({ page }) => {
  await panel(page, { unauthorized: true })
  await page.locator('#language').selectOption('en')
  // Trigger a new status poll so its error follows the selected language.
  await expect(page.locator('#notice')).toContainText(
    'Reopen Administration from the AnimeLab launcher',
  )
  await expect(page.getByRole('heading', { name: 'Startup settings' })).toBeVisible()
  await expect(page.locator('#open-app')).toBeHidden()
})
