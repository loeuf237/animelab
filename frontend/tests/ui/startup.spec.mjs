import { test, expect } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
import { mockApp } from './fixtures.mjs'
await mkdir('/tmp/animelab-onboarding', { recursive: true })

async function installation(
  page,
  { android = false, completed = false, update = 'current', lang = 'fr' } = {},
) {
  const requests = await mockApp(page, { lang })
  const state = {
    preferences: {
      onboardingCompleted: completed,
      theme: 'dark',
      palette: 'teal',
      checkUpdates: true,
      updateChannel: 'beta',
    },
    currentVersion: '0.1.6-beta.3',
    runtime: android ? 'android' : 'web',
    os: android ? 'android' : 'linux',
    architecture: 'arm64',
    storageEditable: false,
    downloadDirectory: '/downloads/AnimeLab',
    native: android
      ? {
          android: true,
          apiLevel: 33,
          mode: 'downloads',
          authorized: true,
          destination: 'Downloads/AnimeLab',
          selectionPending: false,
          storageChosen: false,
          notificationsGranted: false,
          installAppsGranted: false,
          batteryUnrestricted: false,
          error: null,
        }
      : null,
  }
  await page.route('**/api/app/startup', (route) => route.fulfill({ json: state }))
  await page.route('**/api/app/preferences', (route) => {
    const changes = route.request().postDataJSON()
    requests.push({ path: '/api/app/preferences', body: changes })
    Object.assign(state.preferences, changes)
    return route.fulfill({ json: state.preferences })
  })
  await page.route('**/api/app/updates', (route) =>
    route.fulfill({
      json: {
        status: update,
        currentVersion: state.currentVersion,
        channel: 'beta',
        release:
          update === 'available'
            ? {
                version: '0.1.7-beta.1',
                notes: '# Changes\n- Offline improvements\n<script>window.injected = true</script>',
                url: 'https://github.com/loeuf237/animelab/releases/tag/v0.1.7-beta.1',
                assets: [
                  {
                    name: 'AnimeLab-Android-arm64.apk',
                    label: 'Android',
                    url: 'https://github.com/loeuf237/animelab/releases/download/v0.1.7-beta.1/AnimeLab.apk',
                    size: 120,
                  },
                ],
              }
            : null,
      },
    }),
  )
  await page.route('**/api/system/android/storage', (route) => {
    const action = route.request().postDataJSON()?.action
    if (action === 'choose_directory') state.native.selectionPending = true
    if (action === 'use_downloads') {
      state.native.storageChosen = true
      state.native.selectionPending = false
    }
    if (action === 'notifications') state.native.notificationsGranted = true
    if (action === 'install_apps') state.native.installAppsGranted = true
    if (action === 'battery') state.native.batteryUnrestricted = true
    if (action) requests.push({ path: '/api/system/android/storage', body: { action } })
    return route.fulfill({ json: state.native })
  })
  return { state, requests }
}

for (const width of [320, 390, 1440]) {
  test(`first run follows appearance, folder, permissions and library at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 850 })
    const { state, requests } = await installation(page, { android: true })
    await page.goto('/app/')
    await expect(page.getByRole('heading', { name: 'Bienvenue !' })).toBeVisible()
    if (width === 390)
      await page.screenshot({ path: '/tmp/animelab-onboarding/theme-teal-390.png' })
    await page.getByRole('button', { name: 'Ambre', exact: true }).click()
    await expect(page.locator('html')).toHaveAttribute('data-palette', 'ember')
    await mkdir('/tmp/animelab-onboarding', { recursive: true })
    await page.screenshot({ path: `/tmp/animelab-onboarding/theme-${width}.png` })
    await page.getByRole('button', { name: 'Suivant', exact: true }).click()
    await expect(page.getByRole('button', { name: 'Suivant', exact: true })).toBeDisabled()
    await page.getByRole('button', { name: 'Sélectionner un dossier', exact: true }).click()
    await expect(page.getByRole('button', { name: 'Suivant', exact: true })).toBeDisabled()
    state.native.selectionPending = false // User cancels the system picker.
    await expect(
      page.getByRole('button', { name: 'Utiliser Downloads/AnimeLab', exact: true }),
    ).toBeEnabled()
    await page.getByRole('button', { name: 'Utiliser Downloads/AnimeLab', exact: true }).click()
    await page.getByRole('button', { name: 'Suivant', exact: true }).click()
    await expect(
      page.getByText('Ces autorisations sont facultatives.', { exact: false }),
    ).toBeVisible()
    await page.screenshot({ path: `/tmp/animelab-onboarding/permissions-${width}.png` })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    expect(
      requests.filter(
        (r) =>
          r.path === '/api/system/android/storage' &&
          ['notifications', 'battery', 'install_apps'].includes(r.body?.action),
      ),
    ).toHaveLength(0)
    await page.getByRole('button', { name: 'Commencer', exact: true }).click()
    await expect(page).toHaveURL(/\/library$/)
    expect(state.preferences.onboardingCompleted).toBe(true)
    expect(state.preferences.palette).toBe('ember')
    await page.reload()
    await expect(page.getByRole('heading', { name: 'Ma Bibliothèque' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Bienvenue !' })).toHaveCount(0)
  })
}

test('new version appears before setup without downloading a binary automatically', async ({
  page,
}) => {
  const binaries = []
  page.on('request', (request) => {
    if (request.url().endsWith('.apk')) binaries.push(request.url())
  })
  await installation(page, { update: 'available', android: true, lang: 'en' })
  await page.goto('/app/')
  await expect(page.getByRole('heading', { name: 'New version available!' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Download', exact: true })).toHaveAttribute(
    'href',
    /AnimeLab\.apk$/,
  )
  expect(await page.evaluate(() => window.injected)).toBeUndefined()
  expect(binaries).toHaveLength(0)
  await page.screenshot({ path: '/tmp/animelab-onboarding/update-en.png' })
  await page.getByRole('button', { name: 'Not now', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Welcome!' })).toBeVisible()
})

test('offline update checks do not block setup and remote browsers cannot change server storage', async ({
  page,
}) => {
  const { requests } = await installation(page, { update: 'offline' })
  await page.goto('/app/')
  await expect(
    page.getByText('Vérification des mises à jour indisponible.', { exact: false }),
  ).toBeVisible()
  await page.getByRole('button', { name: 'Suivant', exact: true }).click()
  await expect(
    page.getByText('Le stockage est géré par le serveur.', { exact: false }),
  ).toBeVisible()
  await page.getByRole('button', { name: 'Utiliser le dossier du serveur' }).click()
  await page.getByRole('button', { name: 'Commencer', exact: true }).click()
  await expect(page).toHaveURL(/\/library$/)
  expect(requests.filter((r) => r.path === '/api/app/directory')).toHaveLength(0)
})

test('permission buttons invoke the actual native actions only on explicit clicks', async ({
  page,
}) => {
  const { requests } = await installation(page, { android: true })
  await page.goto('/app/')
  await page.getByRole('button', { name: 'Suivant', exact: true }).click()
  await page.getByRole('button', { name: 'Utiliser Downloads/AnimeLab', exact: true }).click()
  await page.getByRole('button', { name: 'Suivant', exact: true }).click()
  await page.getByRole('button', { name: 'Autoriser', exact: true }).first().click()
  await page.getByRole('button', { name: 'Autoriser', exact: true }).first().click()
  await page.getByRole('button', { name: 'Autoriser', exact: true }).first().click()
  expect(
    requests
      .filter((r) => ['install_apps', 'notifications', 'battery'].includes(r.body?.action))
      .map((r) => r.body.action),
  ).toEqual(['install_apps', 'notifications', 'battery'])
})

test('system theme follows OS changes and preserves an explicit override', async ({ page }) => {
  await installation(page)
  await page.emulateMedia({ colorScheme: 'dark' })
  await page.goto('/app/')
  await page.getByRole('button', { name: 'Système', exact: true }).click()
  await page.emulateMedia({ colorScheme: 'light' })
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
  await page.getByRole('button', { name: 'Sombre', exact: true }).click()
  await page.emulateMedia({ colorScheme: 'dark' })
  await page.emulateMedia({ colorScheme: 'light' })
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
})

test('an installed update is acknowledged once without resetting setup', async ({ page }) => {
  const { state } = await installation(page, { completed: true })
  state.preferences.lastSeenVersion = '0.1.6-beta.2'
  await page.goto('/app/library')
  await expect(page.getByRole('heading', { name: 'Version 0.1.6-beta.3 installée' })).toBeVisible()
  await page.getByRole('button', { name: 'Continuer', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Ma Bibliothèque' })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Ma Bibliothèque' })).toBeVisible()
  await expect(page.getByRole('heading', { name: /installée$/ })).toHaveCount(0)
})

test('returning users enter immediately without waiting on update checks', async ({ page }) => {
  await installation(page, { completed: true })
  let releaseUpdateCheck
  const updateRequested = new Promise((resolve) => {
    releaseUpdateCheck = resolve
  })
  await page.route('**/api/app/updates', async (route) => {
    releaseUpdateCheck()
    await new Promise((resolve) => setTimeout(resolve, 600))
    return route.fulfill({
      json: {
        status: 'available',
        currentVersion: '0.1.6-beta.3',
        channel: 'beta',
        release: {
          version: '0.1.7-beta.1',
          notes: '# Changes\n- Faster startup',
          url: 'https://github.com/loeuf237/animelab/releases/tag/v0.1.7-beta.1',
          assets: [
            {
              name: 'AnimeLab-Linux-x64.tar.gz',
              label: 'Linux',
              url: 'https://github.com/loeuf237/animelab/releases/download/v0.1.7-beta.1/AnimeLab.tar.gz',
              size: 120,
            },
          ],
        },
      },
    })
  })

  await page.goto('/app/library')
  await expect(page.getByRole('heading', { name: 'Ma Bibliothèque' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Nouvelle version disponible !' })).toHaveCount(0)

  await updateRequested
  const updateNotifBtn = page
    .locator('.notification-region')
    .getByRole('button', { name: 'Mettre à jour', exact: true })
  await expect(updateNotifBtn).toBeVisible()
  await updateNotifBtn.click()
  await expect(page.getByRole('heading', { name: 'Nouvelle version disponible !' })).toBeVisible()
})

test('a failed preferences save keeps setup open and reports the error', async ({ page }) => {
  const { state } = await installation(page)
  await page.route('**/api/app/preferences', (route) =>
    route.fulfill({ status: 503, json: { error: 'Temporary storage failure' } }),
  )
  await page.goto('/app/')
  await page.getByRole('button', { name: 'Suivant', exact: true }).click()
  await page.getByRole('button', { name: 'Utiliser le dossier du serveur' }).click()
  await page.getByRole('button', { name: 'Commencer', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Temporary storage failure')
  expect(state.preferences.onboardingCompleted).toBe(false)
  await expect(page.getByRole('button', { name: 'Commencer', exact: true })).toBeEnabled()
})

test('a desktop folder is saved only after a successful validation', async ({ page }) => {
  const { state } = await installation(page)
  state.runtime = 'desktop'
  state.storageEditable = true
  const saved = []
  await page.route('**/api/app/directory', (route) => {
    saved.push(route.request().postDataJSON().path)
    return route.fulfill({ json: { downloadDirectory: saved.at(-1) } })
  })
  await page.goto('/app/')
  await page.getByRole('button', { name: 'Suivant', exact: true }).click()
  await page
    .getByRole('textbox', { name: 'Dossier des téléchargements' })
    .fill('/home/test/Videos/AnimeLab')
  await expect(page.getByRole('button', { name: 'Commencer', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: 'Utiliser ce dossier', exact: true }).click()
  expect(saved).toEqual(['/home/test/Videos/AnimeLab'])
  await expect(page.getByRole('button', { name: 'Commencer', exact: true })).toBeEnabled()
})

for (const width of [320, 1440]) {
  test(`Telegram group invitation appears in onboarding and Settings About at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 850 })
    const { state } = await installation(page, { lang: 'fr' })
    await page.goto('/app/')
    await page.getByRole('button', { name: 'Suivant', exact: true }).click()
    await page.getByRole('button', { name: 'Utiliser le dossier du serveur' }).click()

    const onboardingLink = page.locator('a[href="https://t.me/AnimeLabGroup"]')
    await expect(onboardingLink).toBeVisible()
    await expect(onboardingLink).toHaveAttribute('target', '_blank')
    await expect(onboardingLink).toHaveAttribute('rel', 'noopener noreferrer')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    )

    // Onboarding remains non-blocking: clicking Get started completes setup directly.
    await page.getByRole('button', { name: 'Commencer', exact: true }).click()
    await expect(page).toHaveURL(/\/library$/)
    expect(state.preferences.onboardingCompleted).toBe(true)

    await page.goto('/app/settings?tab=about')
    const aboutLink = page.locator('a[href="https://t.me/AnimeLabGroup"]')
    await expect(aboutLink).toBeVisible()
    await expect(aboutLink).toHaveAttribute('target', '_blank')
    await expect(aboutLink).toHaveAttribute('rel', 'noopener noreferrer')
    await expect(page.getByText('0.1.6-beta.3', { exact: true })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    )
  })
}

test('English Settings About section shows translated labels and Telegram link', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await installation(page, { completed: true, lang: 'en' })
  await page.goto('/app/settings')
  await page.locator('.settings-nav-tab', { hasText: 'About' }).click()
  await expect(page.getByRole('heading', { name: 'About AnimeLab' })).toBeVisible()
  const tgLink = page.getByRole('link', { name: 'Join the Telegram group' })
  await expect(tgLink).toBeVisible()
  await expect(tgLink).toHaveAttribute('href', 'https://t.me/AnimeLabGroup')
})
