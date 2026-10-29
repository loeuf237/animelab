import { test, expect } from '@playwright/test'
import { mockApp } from './fixtures.mjs'

test('Android package trust is explicit and names both the version and signer', async ({
  page,
}) => {
  await mockApp(page)
  const identity = {
    pkg: 'fixture.one',
    name: 'Fixture APK',
    version: '17.1',
    versionCode: '1',
    api: 17,
    signer: 'a'.repeat(64),
    trusted: false,
    compatible: true,
    enabled: false,
    state: 'untrusted',
    extension_id: 1,
    sources: [],
  }
  await page.route('**/api/extensions/android', (route) =>
    route.fulfill({
      json: {
        available: true,
        packages: [identity],
        operations: [],
        securityBoundary: 'same-uid-worker',
      },
    }),
  )
  await page.route('**/api/extensions/repositories', (route) =>
    route.fulfill({ json: { repositories: [] } }),
  )
  const requests = []
  await page.route('**/api/extensions/android/fixture.one/trust', (route) => {
    requests.push(route.request().postDataJSON())
    identity.trusted = true
    identity.state = 'loaded'
    return route.fulfill({ json: { trusted: true } })
  })
  await page.goto('/app/extensions')
  await expect(page.getByRole('button', { name: 'Approuver cet APK' })).toBeVisible()
  page.once('dialog', async (dialog) => {
    expect(dialog.message()).toContain('accès aux données et au réseau')
    expect(dialog.message()).toContain(identity.signer)
    await dialog.dismiss()
  })
  await page.getByRole('button', { name: 'Approuver cet APK' }).click()
  expect(requests).toHaveLength(0)
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByRole('button', { name: 'Approuver cet APK' }).click()
  await expect.poll(() => requests.length).toBe(1)
  expect(requests[0]).toEqual({ approved: true, versionCode: '1', signer: identity.signer })
  await expect(page.getByRole('button', { name: 'Révoquer la confiance' })).toBeVisible()
})

test('Native filters retain 64 bit source IDs and nested states through navigation', async ({
  page,
}) => {
  await mockApp(page)
  const source = 'aniyomi:1152921504606846977'
  await page.route('**/api/sources', (route) =>
    route.fulfill({
      json: {
        sources: [
          {
            id: source,
            name: 'Fixture',
            type: 'imported',
            lang: 'fr',
            baseUrl: 'https://fixture.example',
            isEnabled: true,
            multiTags: true,
            views: [{ id: 'search', label: 'Recherche' }],
          },
        ],
      },
    }),
  )
  const schema = [
    {
      name: 'Options',
      type: 'group',
      children: [
        { name: 'Titre', type: 'text', state: '' },
        { name: 'Doublé', type: 'triState', state: 0 },
      ],
    },
  ]
  await page.route('**/api/sources/*/filters', (route) =>
    route.fulfill({
      json: {
        tags: [],
        orders: [{ id: 'source', label: 'Ordre de la source' }],
        nativeFilters: schema,
      },
    }),
  )
  const requests = []
  await page.route('**/api/sources/*/catalogue?**', (route) => {
    requests.push(new URL(route.request().url()))
    return route.fulfill({
      json: { source, results: [], queryScope: 'catalogue', nextCursor: null },
    })
  })
  await page.goto('/app/sources/' + encodeURIComponent(source) + '?mode=search')
  await page.getByRole('button', { name: 'Genres et filtres' }).click()
  await page.getByLabel('Titre', { exact: true }).fill('Naruto')
  await page.getByLabel('Doublé', { exact: true }).selectOption('2')
  await page.getByRole('button', { name: 'Appliquer les filtres' }).click()
  await expect
    .poll(() =>
      requests.some((url) => {
        const filters = JSON.parse(url.searchParams.get('nativeFilters') || '[]')
        return filters[0]?.children[0].state === 'Naruto' && filters[0]?.children[1].state === 2
      }),
    )
    .toBe(true)
  expect(decodeURIComponent(requests.at(-1).pathname)).toContain(source)
  await page.reload()
  await page.getByRole('button', { name: 'Genres et filtres' }).click()
  await expect(page.getByLabel('Titre', { exact: true })).toHaveValue('Naruto')
  await expect(page.getByLabel('Doublé', { exact: true })).toHaveValue('2')
})

test('A pending APK installation can be cancelled without affecting installed packages', async ({
  page,
}) => {
  await mockApp(page)
  const operation = {
    id: 'install-1',
    pkg: 'fixture.one',
    action: 'install',
    state: 'waiting_user',
  }
  await page.route('**/api/extensions/android', (route) =>
    route.fulfill({
      json: {
        available: true,
        packages: [],
        operations: [operation],
        securityBoundary: 'same-uid-worker',
      },
    }),
  )
  await page.route('**/api/extensions/repositories', (route) =>
    route.fulfill({ json: { repositories: [] } }),
  )
  const requests = []
  await page.route('**/api/extensions/android/operations/install-1/cancel', (route) => {
    requests.push(route.request().method())
    operation.state = 'cancelled'
    return route.fulfill({ json: { operation } })
  })
  await page.goto('/app/extensions')
  await expect(page.getByText('fixture.one — Confirmation Android attendue')).toBeVisible()
  await page.getByRole('button', { name: 'Annuler l’installation' }).click()
  await expect.poll(() => requests.length).toBe(1)
  expect(requests).toEqual(['POST'])
  await expect(page.getByText('fixture.one — Annulée')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Annuler l’installation' })).toHaveCount(0)
})
