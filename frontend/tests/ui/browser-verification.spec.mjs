import { test, expect } from '@playwright/test'
import { mockApp } from './fixtures.mjs'

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
