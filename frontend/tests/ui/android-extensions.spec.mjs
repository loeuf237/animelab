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
  await page.getByRole('button', { name: 'Approuver cet APK' }).click()
  const dialog = page.locator('.confirmation-dialog')
  await expect(dialog).toBeVisible()
  await expect(dialog).toContainText('accès aux données et au réseau')
  await expect(dialog).toContainText(identity.signer)
  await dialog.getByRole('button', { name: 'Annuler' }).click()
  await expect(dialog).toBeHidden()
  expect(requests).toHaveLength(0)
  await page.getByRole('button', { name: 'Approuver cet APK' }).click()
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: 'Approuver' }).click()
  await expect(dialog).toBeHidden()
  await expect.poll(() => requests.length).toBe(1)
  expect(requests[0]).toEqual({ approved: true, versionCode: '1', signer: identity.signer })
  await page.locator('.apk-details > summary').click()
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

test('active APK operation polling stays silent without flickering or unmounting extensions', async ({
  page,
}) => {
  await mockApp(page)
  let androidCalls = 0
  let listCalls = 0
  const state = {
    available: true,
    packages: [
      {
        pkg: 'fixture.installed',
        name: 'Installed Fixture',
        version: '1.0',
        versionCode: '1',
        api: 17,
        signer: 'a'.repeat(64),
        trusted: true,
        compatible: true,
        enabled: true,
        state: 'loaded',
        extension_id: 1,
        sources: [],
      },
    ],
    operations: [
      {
        id: 'op-poll-1',
        pkg: 'fixture.candidate',
        action: 'install',
        state: 'waiting_user',
        canConfirm: true,
      },
    ],
    securityBoundary: 'same-uid-worker',
  }
  await page.route('**/api/extensions/android', (route) => {
    androidCalls += 1
    return route.fulfill({ json: JSON.parse(JSON.stringify(state)) })
  })
  await page.route('**/api/extensions/list**', (route) => {
    listCalls += 1
    return route.fulfill({
      json: {
        active_repo: { id: 1, name: 'Repo', url: 'https://repo.example/index.min.json' },
        extensions: [
          {
            id: 2,
            pkg: 'fixture.candidate',
            name: 'Candidate Source',
            lang: 'fr',
            version: '1.2',
            is_enabled: false,
            is_installed: false,
          },
        ],
      },
    })
  })
  await page.route('**/api/extensions/repositories', (route) =>
    route.fulfill({ json: { repositories: [] } }),
  )

  await page.goto('/app/extensions')
  await expect(page.locator('.apk-item')).toHaveCount(1)
  await expect(page.locator('.ext-card')).toHaveCount(1)

  await page.evaluate(() => {
    window.__flickerEvents = 0
    const root = document.querySelector('#main-content')
    const observer = new MutationObserver((mutations) => {
      for (const m of mutations) {
        if (document.querySelector('.loading-state')) window.__flickerEvents += 1
        for (const node of m.removedNodes) {
          if (
            node instanceof HTMLElement &&
            (node.matches('.ext-card,.apk-item') || node.querySelector?.('.ext-card,.apk-item'))
          ) {
            window.__flickerEvents += 1
          }
        }
      }
    })
    observer.observe(root, { childList: true, subtree: true })
  })

  const baselineAndroidCalls = androidCalls
  const baselineListCalls = listCalls
  await expect.poll(() => androidCalls, { timeout: 6000 }).toBeGreaterThan(baselineAndroidCalls)
  expect(listCalls).toBe(baselineListCalls)
  await expect(page.getByText('Opération en cours…')).toHaveCount(0)
  expect(await page.evaluate(() => window.__flickerEvents)).toBe(0)

  state.operations[0] = {
    id: 'op-poll-1',
    pkg: 'fixture.candidate',
    action: 'install',
    state: 'installed',
  }
  state.packages.push({
    pkg: 'fixture.candidate',
    name: 'Candidate Source',
    version: '1.2',
    versionCode: '2',
    api: 17,
    signer: 'b'.repeat(64),
    trusted: false,
    compatible: true,
    enabled: false,
    state: 'untrusted',
    extension_id: 2,
    sources: [],
  })

  await expect(page.getByRole('button', { name: 'Approuver cet APK' })).toBeVisible({
    timeout: 6000,
  })
  await expect.poll(() => listCalls, { timeout: 5000 }).toBe(baselineListCalls + 1)
  await expect(page.locator('.loading-state')).toHaveCount(0)
})

test('Mihon-style Android catalogue offers Installer, confirm retry, conflict uninstall and fits 360px', async ({
  page,
}) => {
  await mockApp(page)
  await page.setViewportSize({ width: 360, height: 780 })
  const confirmed = []
  const toggled = []
  const operations = [
    {
      id: 'op-wait',
      pkg: 'fixture.pending',
      action: 'install',
      state: 'waiting_user',
      canConfirm: true,
    },
    {
      id: 'op-conflict',
      pkg: 'fixture.installed',
      action: 'install',
      state: 'failed',
      error: 'package_installer_conflict',
    },
  ]
  const packages = [
    {
      pkg: 'fixture.installed',
      name: 'Installed Conflict APK',
      version: '1.0',
      versionCode: '1',
      api: 17,
      signer: 'a'.repeat(64),
      trusted: true,
      compatible: true,
      enabled: true,
      state: 'loaded',
      extension_id: 1,
      sources: [],
    },
  ]
  await page.route('**/api/extensions/android', (route) =>
    route.fulfill({
      json: { available: true, packages, operations, securityBoundary: 'same-uid-worker' },
    }),
  )
  await page.route('**/api/extensions/list**', (route) =>
    route.fulfill({
      json: {
        active_repo: { id: 1, name: 'Repo', url: 'https://repo.example/index.min.json' },
        extensions: [
          {
            id: 1,
            pkg: 'fixture.installed',
            name: 'Installed Conflict APK',
            lang: 'fr',
            version: '1.0',
            is_installed: true,
            is_enabled: true,
          },
          {
            id: 2,
            pkg: 'fixture.catalogue',
            name: 'Catalogue Anime Source',
            lang: 'fr',
            version: '2.0',
            is_installed: false,
            is_enabled: false,
          },
        ],
      },
    }),
  )
  await page.route('**/api/extensions/repositories', (route) =>
    route.fulfill({ json: { repositories: [] } }),
  )
  await page.route('**/api/extensions/2/toggle', (route) => {
    toggled.push(route.request().postDataJSON())
    operations.push({
      id: 'op-cat',
      pkg: 'fixture.catalogue',
      action: 'install',
      state: 'waiting_user',
      canConfirm: true,
    })
    return route.fulfill({ json: { success: true, pending: true } })
  })
  await page.route('**/api/extensions/android/operations/op-wait/confirm', (route) => {
    confirmed.push(route.request().method())
    return route.fulfill({ json: { operation: operations[0] } })
  })

  await page.goto('/app/extensions')
  await expect(page.locator('.ext-card .toggle-switch')).toHaveCount(0)

  await page.getByRole('button', { name: 'Ouvrir la confirmation' }).click()
  await expect.poll(() => confirmed).toEqual(['POST'])

  const installBtn = page.locator('.ext-card').getByRole('button', { name: 'Installer' })
  await expect(installBtn).toBeVisible()
  await installBtn.click()
  await expect.poll(() => toggled.length).toBe(1)
  expect(toggled[0]).toEqual({ enabled: true })
  await expect(page.locator('.ext-card').getByText('En attente…')).toBeVisible()

  await page.getByRole('button', { name: 'Désinstaller l’ancienne version' }).click()
  const dialog = page.locator('.confirmation-dialog')
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: 'Annuler' }).click()
  await expect(dialog).toBeHidden()

  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
    true,
  )
})
