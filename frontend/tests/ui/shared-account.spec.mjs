import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'

const origin = 'http://127.0.0.1:41235'
const assets = Object.fromEntries(
  ['account.html', 'client.js', 'style.css'].map((name) => [
    name,
    readFileSync(new URL(`../../../animelab/shared/web/${name}`, import.meta.url)),
  ]),
)
async function accountPage(page, { admin = false, signedIn = true } = {}) {
  const calls = []
  const user = {
    id: 'a'.repeat(32),
    username: 'alice',
    admin,
    enabled: true,
    permissions: ['download'],
  }
  await page.route(`${origin}/**`, async (route) => {
    const request = route.request(),
      path = new URL(request.url()).pathname
    if (path.startsWith('/api/auth/')) {
      calls.push({ path, method: request.method(), body: request.postDataJSON() })
      if (path.endsWith('/me'))
        return route.fulfill({ status: signedIn ? 200 : 401, json: { user } })
      if (path.endsWith('/users')) return route.fulfill({ json: { users: [user], engines: [] } })
      if (path.endsWith('/codes') && request.method() === 'GET')
        return route.fulfill({ json: { codes: [] } })
      return route.fulfill({ json: { success: true, code: 'test-only-single-use-code' } })
    }
    if (path === '/app/')
      return route.fulfill({ contentType: 'text/html', body: '<h1>Private application</h1>' })
    const name = path.endsWith('client.js')
      ? 'client.js'
      : path.endsWith('style.css')
        ? 'style.css'
        : 'account.html'
    return route.fulfill({
      body: assets[name],
      contentType: {
        'account.html': 'text/html',
        'client.js': 'text/javascript',
        'style.css': 'text/css',
      }[name],
      headers: {
        'Content-Security-Policy':
          "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
      },
    })
  })
  await page.goto(`${origin}/auth/account`)
  return calls
}
for (const width of [360, 720, 1280]) {
  test(`shared account administration fits ${width}px in both languages`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    const calls = await accountPage(page, { admin: true })
    await expect(page.locator('#identity')).toHaveText('alice')
    await expect(page.locator('#admin-panel')).toBeVisible()
    await page.getByRole('button', { name: 'Français', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Administration des comptes' })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      width,
    )
    await page.getByRole('button', { name: 'Générer une invitation (7 jours)' }).click()
    await expect(page.locator('#generated-code')).toHaveValue('test-only-single-use-code')
    expect(
      calls.find((call) => call.path.endsWith('/codes') && call.method === 'POST').body,
    ).toEqual({ permissions: ['download'] })
    await page.screenshot({
      path: `../artifacts/shared-server/account-${width}.png`,
      fullPage: true,
    })
  })
}
test('signed-out users can log in and reach their application', async ({ page }) => {
  const calls = await accountPage(page, { signedIn: false })
  await page.locator('#login').getByLabel('Username', { exact: true }).fill('alice')
  await page
    .locator('#login')
    .getByLabel('Password', { exact: true })
    .fill('Test-only password 42!')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Private application' })).toBeVisible()
  expect(calls.find((call) => call.path.endsWith('/login')).body).toEqual({
    username: 'alice',
    password: 'Test-only password 42!',
  })
})
test('ordinary accounts do not see administrator controls or invitation codes', async ({
  page,
}) => {
  await accountPage(page)
  await expect(page.locator('#account-panel')).toBeVisible()
  await expect(page.locator('#admin-panel')).toBeHidden()
  await expect(page.locator('#generated')).toBeHidden()
})

test('authentication capacity and failure limits explain retrying in French', async ({ page }) => {
  await accountPage(page, { signedIn: false })
  await page.getByRole('button', { name: 'Français', exact: true }).click()
  await page.locator('#login input[name=username]').fill('alice')
  await page.locator('#login input[name=password]').fill('Test-only password 42!')
  let busy = true
  await page.route(`${origin}/api/auth/login`, (route) =>
    route.fulfill({
      status: busy ? 503 : 429,
      json: {
        detail: busy
          ? 'Password verification is busy; try shortly'
          : 'Too many authentication failures; try later',
      },
    }),
  )
  await page.getByRole('button', { name: 'Se connecter', exact: true }).click()
  await expect(page.locator('#message')).toHaveText(
    'Une vérification de mot de passe est en cours. Réessayez dans un instant.',
  )
  busy = false
  await page.getByRole('button', { name: 'Se connecter', exact: true }).click()
  await expect(page.locator('#message')).toHaveText(
    'Trop de tentatives échouées pour ce compte. Réessayez plus tard.',
  )
})

test('administrators create accounts with explicit permissions', async ({ page }) => {
  const calls = await accountPage(page, { admin: true })
  await page.getByText('Create an account', { exact: true }).first().click()
  const form = page.locator('#create')
  await form.getByLabel('Username', { exact: true }).fill('new-user')
  await form.getByLabel('Initial password (at least 12 characters)').fill('A test password 42!')
  await form.getByLabel('Manage extensions', { exact: true }).check()
  await form.getByRole('button', { name: 'Create an account', exact: true }).click()
  await expect(page.locator('#message')).toHaveText('Saved.')
  expect(calls.find((call) => call.path.endsWith('/users') && call.method === 'POST').body).toEqual(
    {
      username: 'new-user',
      password: 'A test password 42!',
      admin: false,
      permissions: ['download', 'extensions'],
    },
  )
})
