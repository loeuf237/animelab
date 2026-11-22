import { test, expect } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
import { mockApp } from './fixtures.mjs'

const PALETTE_CHROME = {
  dark: {
    classic: { bg: '#1b1b1f', nav: '#211f26' },
    teal: { bg: '#0b1517', nav: '#0f1b1e' },
    lavender: { bg: '#15121d', nav: '#191622' },
    ember: { bg: '#1c1510', nav: '#211913' },
    amoled: { bg: '#000000', nav: '#000000' },
  },
  light: {
    classic: { bg: '#fefbff', nav: '#f3edf7' },
    teal: { bg: '#f5fafb', nav: '#eaf2f3' },
    lavender: { bg: '#f8f6fc', nav: '#eee8f6' },
    ember: { bg: '#fcf7f4', nav: '#f2e7df' },
    amoled: { bg: '#ffffff', nav: '#f5f5f5' },
  },
}

const PALETTE_LABELS = {
  classic: 'Classique',
  teal: 'Turquoise',
  lavender: 'Violet',
  ember: 'Ambre',
  amoled: 'AMOLED',
}

test('design tokens override purple button defaults across all 5 palettes x dark/light', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.addInitScript(() => {
    window.__syncedSystemBars = []
    window.AnimeLabAndroid = {
      syncSystemBars(statusHex, navHex, lightIcons) {
        window.__syncedSystemBars.push({ statusHex, navHex, lightIcons })
      },
      getPlatformInfo() {
        return JSON.stringify({ os: 'android', runtime: 'android', sdk: 29, edgeToEdge: true })
      },
    }
  })
  await mockApp(page)
  await page.goto('/app/settings')
  await expect(page.locator('.settings-header-pro .btn-primary')).toBeVisible()

  const seenAccents = new Set()
  for (const theme of ['dark', 'light']) {
    await page
      .locator('.theme-modes')
      .getByRole('button', { name: theme === 'light' ? 'Clair' : 'Sombre' })
      .click()
    for (const palette of ['classic', 'teal', 'lavender', 'ember', 'amoled']) {
      await page
        .locator('.theme-variants')
        .getByRole('button', { name: PALETTE_LABELS[palette] })
        .click()

      await expect
        .poll(async () => {
          const result = await page.evaluate(() => {
            const btn = document.querySelector('.settings-header-pro .btn-primary')
            const probe = document.createElement('span')
            probe.style.backgroundColor = 'var(--accent)'
            document.body.appendChild(probe)
            const expected = getComputedStyle(probe).backgroundColor
            const actual = btn ? getComputedStyle(btn).backgroundColor : ''
            probe.remove()
            return { actual, expected }
          })
          return result.actual === result.expected ? result.actual : null
        })
        .not.toBeNull()

      const result = await page.evaluate(() => {
        const btn = document.querySelector('.settings-header-pro .btn-primary')
        const probe = document.createElement('span')
        probe.style.backgroundColor = 'var(--accent)'
        document.body.appendChild(probe)
        const expected = getComputedStyle(probe).backgroundColor
        const actual = btn ? getComputedStyle(btn).backgroundColor : ''
        probe.remove()
        const meta = document.querySelector('meta[name="theme-color"]')?.getAttribute('content')
        const topbar = document.querySelector('.app-topbar')
        const sidebar = document.querySelector('.app-sidebar')
        return {
          actual,
          expected,
          meta,
          bodyBg: getComputedStyle(document.body).backgroundColor,
          bodyColor: getComputedStyle(document.body).color,
          topbarBg: topbar ? getComputedStyle(topbar).backgroundColor : '',
          sidebarBg: sidebar ? getComputedStyle(sidebar).backgroundColor : '',
          lastBarSync: window.__syncedSystemBars.at(-1) || null,
        }
      })

      expect(result.actual).toBe(result.expected)
      if (palette !== 'lavender') {
        expect(result.actual).not.toBe('rgb(113, 53, 217)')
      }
      expect(result.meta).toBe(PALETTE_CHROME[theme][palette].bg)
      expect(result.lastBarSync).toEqual({
        statusHex: PALETTE_CHROME[theme][palette].bg,
        navHex: PALETTE_CHROME[theme][palette].nav,
        lightIcons: theme === 'light',
      })
      if (theme === 'dark' && palette === 'amoled') {
        expect(result.bodyBg).toBe('rgb(0, 0, 0)')
        expect(result.topbarBg).toBe('rgb(0, 0, 0)')
        expect(result.sidebarBg).toBe('rgb(0, 0, 0)')
        expect(result.bodyColor).toBe('rgb(255, 255, 255)')
      }
      if (theme === 'dark' && palette === 'classic') {
        expect(result.bodyBg).toBe('rgb(27, 27, 31)')
        expect(result.actual).toBe('rgb(176, 198, 255)')
      }
      if (theme === 'light' && palette === 'classic') {
        expect(result.bodyBg).toBe('rgb(254, 251, 255)')
        expect(result.actual).toBe('rgb(0, 88, 202)')
      }
      seenAccents.add(`${theme}:${palette}:${result.actual}`)
    }
  }
  expect(seenAccents.size).toBe(10)
})

test('platform attributes, desktop 2-col settings, collapsible rail, and back handler work', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await mockApp(page)
  await page.goto('/app/')
  await expect(page.locator('#main-content h1')).toBeVisible()
  await mkdir('../artifacts/mobile-ui', { recursive: true })
  await page.screenshot({ path: '../artifacts/mobile-ui/redesign-home-1440.png' })

  await page.goto('/app/settings')
  await expect(page.locator('.settings-layout-grid')).toBeVisible()

  const platform = await page.evaluate(() => ({
    os: document.documentElement.dataset.os,
    runtime: document.documentElement.dataset.runtime,
  }))
  expect(['linux', 'macos', 'windows', 'android', 'ios']).toContain(platform.os)
  expect(['web', 'desktop', 'android']).toContain(platform.runtime)

  const columns = await page.evaluate(() => {
    const grid = document.querySelector('.settings-layout-grid')
    return grid ? getComputedStyle(grid).gridTemplateColumns.trim().split(/\s+/) : []
  })
  expect(columns).toHaveLength(2)

  await page.locator('.sidebar-collapse-btn').click()
  await expect(page.locator('html')).toHaveClass(/sidebar-collapsed/)
  await page.locator('.sidebar-collapse-btn').click()
  await expect(page.locator('html')).not.toHaveClass(/sidebar-collapsed/)

  await page.keyboard.press('Control+k')
  await expect(page.locator('.palette-card')).toBeVisible()
  const handled = await page.evaluate(() => window.__animelabHandleBack?.())
  expect(handled).toBe(true)
  await expect(page.locator('.palette-card')).toBeHidden()
})

test('mobile 5-tab navigation, /more hub, and contextual sub-page back button work', async ({
  page,
}) => {
  await page.setViewportSize({ width: 360, height: 640 })
  await mockApp(page)
  await page.goto('/app/')

  const navLinks = page.locator('.bottom-nav-link')
  await expect(navLinks).toHaveCount(5)

  await mkdir('../artifacts/mobile-ui', { recursive: true })
  await navLinks.nth(4).click()
  await expect(page).toHaveURL(/\/app\/more/)
  await expect(page.locator('#main-content h1')).toHaveText('Plus')
  await page.screenshot({ path: '../artifacts/mobile-ui/redesign-more-360.png' })
  await expect(page.locator('.topbar-mobile-leading button')).toHaveCount(0)

  await expect(page.locator('a.more-list-row[href="/app/history"]')).toBeVisible()
  await expect(page.locator('a.more-list-row[href="/app/extensions"]')).toBeVisible()
  await expect(page.locator('a.more-list-row[href="/app/settings"]')).toBeVisible()

  await page.locator('a.more-list-row[href="/app/settings"]').click()
  await expect(page).toHaveURL(/\/app\/settings/)
  const backBtn = page.locator('.topbar-mobile-leading button')
  await expect(backBtn).toBeVisible()
  await backBtn.click()
  await expect(page).toHaveURL(/\/app\/more/)
})

test('settings AppUpdateSettings aligns with setting rows at desktop and mobile', async ({
  page,
}) => {
  await mkdir('../artifacts/mobile-ui', { recursive: true })
  for (const [width, height] of [
    [1440, 900],
    [360, 640],
  ]) {
    await page.setViewportSize({ width, height })
    await mockApp(page, { theme: 'light' })
    await page.goto('/app/settings')
    const updateHeading = page.locator('.app-update-settings h2')
    const firstRowLabel = page.locator('.setting-row-pro .setting-meta-pro').first()
    await expect(updateHeading).toBeVisible()
    await expect(firstRowLabel).toBeVisible()
    const [uBox, rBox] = await Promise.all([
      updateHeading.boundingBox(),
      firstRowLabel.boundingBox(),
    ])
    expect(Math.abs(uBox.x - rBox.x)).toBeLessThanOrEqual(2)
    if (width === 1440) {
      await page.screenshot({ path: '../artifacts/mobile-ui/redesign-settings-light-1440.png' })
    }
  }
})

test('progressive catalogue NDJSON streaming renders cards incrementally without overflow', async ({
  page,
}) => {
  await mkdir('../artifacts/mobile-ui', { recursive: true })
  await page.setViewportSize({ width: 1280, height: 800 })
  await mockApp(page)
  await page.route('**/api/sources/voir-anime/catalogue/stream?**', async (route) => {
    const chunks = [
      JSON.stringify({ type: 'meta', totalEstimate: 2 }),
      JSON.stringify({
        type: 'items',
        items: [
          {
            title: 'Frieren — Saison 1',
            url: 'https://voiranime.cx/anime/frieren/',
            imageUrl: '',
            source: 'voir-anime',
            version: 'VOSTFR',
            episodeInfo: 'Saison 1',
          },
          {
            title: 'Solo Leveling',
            url: 'https://voiranime.cx/anime/solo-leveling/',
            imageUrl: '',
            source: 'voir-anime',
            version: 'VF',
            episodeInfo: 'Épisode 12',
          },
        ],
      }),
      JSON.stringify({
        type: 'done',
        source: 'voir-anime',
        nextCursor: null,
        queryScope: 'catalogue',
      }),
    ].join('\n')
    await route.fulfill({
      status: 200,
      contentType: 'application/x-ndjson',
      body: chunks + '\n',
    })
  })
  await page.goto('/app/sources/voir-anime?mode=popular')
  await expect(page.locator('.anime-grid .poster-card')).toHaveCount(2)
  await expect(page.locator('.catalogue-result-heading')).toContainText('2 résultat(s) chargé(s)')
  await page.screenshot({ path: '../artifacts/mobile-ui/redesign-sources-stream-1280.png' })
})

test('diagnostics panel uses Android native export bridge and exposes copy and bug report actions', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockApp(page)
  await page.addInitScript(() => {
    window.__nativeDiagnosticsPayloads = []
    window.AnimeLabAndroid = {
      exportDiagnostics(payload) {
        window.__nativeDiagnosticsPayloads.push(payload)
        return 'Downloads/AnimeLab/animelab-diagnostics-test.json'
      },
    }
  })
  await page.route('**/api/diagnostics/export', (route) =>
    route.fulfill({
      json: {
        schemaVersion: 1,
        applicationVersion: '0.1.6-beta.5',
        platform: 'linux',
        recentErrorCount: 1,
        events: [{ event: 'client_error', code: 'TypeError' }],
      },
    }),
  )
  await page.goto('/app/settings?tab=storage')
  const exportBtn = page.getByRole('button', { name: 'Exporter les diagnostics' })
  await expect(exportBtn).toBeVisible()
  await expect(page.getByRole('button', { name: 'Copier le résumé' })).toBeVisible()
  const reportLink = page.getByRole('link', { name: 'Signaler un bug' })
  await expect(reportLink).toBeVisible()
  await expect(reportLink).toHaveAttribute('href', /issues\/new\/choose/)

  await exportBtn.click()
  await expect(page.locator('.diagnostics-status')).toContainText(
    'Downloads/AnimeLab/animelab-diagnostics-test.json',
  )
  const sent = await page.evaluate(() => window.__nativeDiagnosticsPayloads)
  expect(sent).toHaveLength(1)
  expect(sent[0]).toContain('"recentErrorCount": 1')
})

test('VoirAnime posters route through image-proxy and direct cover errors fall back to image-proxy', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await mockApp(page)

  // Valid 1x1 PNG so <img> fires load with naturalWidth === 1.
  const png = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
    'base64',
  )
  const proxiedUrls = []
  const vaPoster = 'https://voiranime.cx/wp-content/uploads/2026/09/frieren-460x630.jpg'
  const fallbackPoster = 'https://cdn.ext.invalid/cover.jpg'

  await page.route('https://cdn.ext.invalid/**', (route) => route.abort())
  await page.route('**/api/media/image-proxy*', async (route) => {
    const reqUrl = new URL(route.request().url())
    proxiedUrls.push(reqUrl.searchParams.get('url'))
    await route.fulfill({
      status: 200,
      contentType: 'image/png',
      body: png,
    })
  })
  await page.route('**/api/home/feed', (route) =>
    route.fulfill({
      json: {
        success: true,
        challenges: [],
        errors: [],
        latestReleases: {
          'voir-anime': [
            {
              id: 'frieren',
              title: 'Sousou no Frieren',
              imageUrl: vaPoster,
              url: 'https://voiranime.cx/anime/sousou-no-frieren/',
              version: 'VF',
              type: 'Anime',
              episodeInfo: 'Ep 28',
              source: 'voir-anime',
            },
            {
              id: 'ext-fallback',
              title: 'Fallback Show',
              imageUrl: fallbackPoster,
              url: 'https://example.test/anime/fallback',
              version: 'VOSTFR',
              type: 'Anime',
              episodeInfo: 'Ep 1',
              source: 'french-manga',
            },
          ],
        },
        favorites: [],
        recentHistory: [],
        enabledExtensions: [],
      },
    }),
  )

  await page.goto('/app/')
  await page.getByRole('tab', { name: 'VoirAnime' }).click()
  const imgs = page.locator('.poster-card-media img')
  await expect(imgs).toHaveCount(2)
  await expect(imgs.nth(0)).toHaveAttribute(
    'src',
    `/api/media/image-proxy?url=${encodeURIComponent(vaPoster)}`,
  )
  await expect(imgs.nth(0)).toHaveClass(/is-loaded/)
  await expect(imgs.nth(1)).toHaveAttribute(
    'src',
    `/api/media/image-proxy?url=${encodeURIComponent(fallbackPoster)}`,
  )
  await expect(imgs.nth(1)).toHaveClass(/is-loaded/)
  await expect(page.locator('.poster-card-fallback')).toHaveCount(0)
  expect(proxiedUrls).toContain(vaPoster)
  expect(proxiedUrls).toContain(fallbackPoster)

  // AnimeDetailView also resolves VoirAnime cover via image-proxy while preserving hero load.
  await page.route('**/api/anime/detail*', (route) =>
    route.fulfill({
      json: {
        success: true,
        source: 'voir-anime',
        sourceName: 'VoirAnime',
        isFavorite: false,
        autoDownload: false,
        watchedEpisodes: [],
        anime: {
          title: 'Sousou no Frieren',
          imageUrl: vaPoster,
          url: 'https://voiranime.cx/anime/sousou-no-frieren/',
          synopsis: 'Test synopsis',
          genres: ['Fantasy'],
          episodes: [],
          source: 'voir-anime',
        },
      },
    }),
  )
  await page.goto(
    '/app/anime?url=https%3A%2F%2Fvoiranime.cx%2Fanime%2Fsousou-no-frieren%2F&source=voir-anime',
  )
  const detailCover = page.locator('img.tachiyomi-cover')
  await expect(detailCover).toBeVisible()
  await expect(detailCover).toHaveAttribute(
    'src',
    `/api/media/image-proxy?url=${encodeURIComponent(vaPoster)}`,
  )
  await expect
    .poll(() => detailCover.evaluate((el) => el.complete && el.naturalWidth > 0))
    .toBe(true)
})
