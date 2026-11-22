import { test, expect } from '@playwright/test'
import { mockApp } from './fixtures.mjs'

test('Seanime ecosystem tab manages marketplaces, streaming providers, config, diagnose and non-executable pills', async ({
  page,
}) => {
  await mockApp(page)

  let repositories = []
  let extensions = []
  let savedDomain = 'https://example.org'

  await page.route('**/api/extensions/seanime**', async (route) => {
    const req = route.request()
    const url = new URL(req.url())
    const path = url.pathname

    if (path === '/api/extensions/seanime' && req.method() === 'GET') {
      return route.fulfill({
        json: {
          runtime_available: true,
          engine: 'mini-racer',
          extensions,
          counts: {},
          repositories,
        },
      })
    }

    if (path === '/api/extensions/seanime/repositories' && req.method() === 'POST') {
      repositories = [
        {
          id: 1,
          url: 'https://raw.githubusercontent.com/Bas1874/Seanime-Marketplace/refs/heads/main/Marketplace/Main.json',
          name: 'Bas1874/Seanime-Marketplace',
          kind: 'marketplace',
          is_active: true,
          extension_count: 2,
          installed_count: 0,
        },
      ]
      extensions = [
        {
          id: 101,
          repo_id: 1,
          repo_name: 'Bas1874/Seanime-Marketplace',
          ext_id: 'demo-stream',
          source_id: null,
          name: 'Demo Stream FR',
          version: '1.2.0',
          installed_version: null,
          available_version: '1.2.0',
          has_update: false,
          ext_type: 'onlinestream-provider',
          supported: true,
          language: 'typescript',
          lang: 'fr',
          author: 'tester',
          description: 'Streaming provider de test',
          notes: '',
          icon_url: '',
          website: 'https://example.org',
          readme: '',
          manifest_uri: 'https://example.org/manifest.json',
          payload_uri: '',
          payload_sha256: '',
          user_config: {
            version: 1,
            requiresConfig: true,
            fields: [
              {
                type: 'text',
                name: 'domain',
                label: 'Domaine personnalisé',
                default: 'https://example.org',
              },
            ],
          },
          saved_config: { domain: savedDomain },
          needs_config: false,
          marketplace_meta: { workingTag: true },
          health: {},
          catalog_state: 'available',
          installed: false,
          enabled: false,
          last_error: null,
        },
        {
          id: 102,
          repo_id: 1,
          repo_name: 'Bas1874/Seanime-Marketplace',
          ext_id: 'demo-manga',
          source_id: null,
          name: 'Demo Manga Reader',
          version: '1.0.0',
          installed_version: null,
          available_version: '1.0.0',
          has_update: false,
          ext_type: 'manga-provider',
          supported: false,
          language: 'typescript',
          lang: 'en',
          author: 'tester',
          description: 'Lecteur manga non exécutable',
          notes: '',
          icon_url: '',
          website: '',
          readme: '',
          manifest_uri: 'https://example.org/manga.json',
          payload_uri: '',
          payload_sha256: '',
          user_config: {},
          saved_config: {},
          needs_config: false,
          marketplace_meta: {},
          health: {},
          catalog_state: 'available',
          installed: false,
          enabled: false,
          last_error: null,
        },
      ]
      return route.fulfill({
        json: {
          repo: repositories[0],
          count: 2,
          executable_count: 1,
          warnings: [],
        },
      })
    }

    if (path === '/api/extensions/seanime/demo-stream/install' && req.method() === 'POST') {
      extensions = extensions.map((item) =>
        item.ext_id === 'demo-stream'
          ? {
              ...item,
              installed: true,
              enabled: true,
              installed_version: item.version,
              source_id: 'seanime:demo-stream',
              catalog_state: 'installed',
            }
          : item,
      )
      return route.fulfill({ json: extensions[0] })
    }

    if (path === '/api/extensions/seanime/demo-stream/config') {
      if (req.method() === 'PUT') {
        const body = req.postDataJSON()
        savedDomain = body?.values?.domain || savedDomain
        extensions = extensions.map((item) =>
          item.ext_id === 'demo-stream' ? { ...item, saved_config: { domain: savedDomain } } : item,
        )
      }
      return route.fulfill({
        json: {
          ext_id: 'demo-stream',
          name: 'Demo Stream FR',
          schema: extensions[0].user_config,
          values: { domain: savedDomain },
          defaults: { domain: 'https://example.org' },
        },
      })
    }

    if (path === '/api/extensions/seanime/demo-stream/diagnose' && req.method() === 'POST') {
      return route.fulfill({
        json: {
          extension_id: 'demo-stream',
          source_id: 'seanime:demo-stream',
          engine: 'mini-racer',
          syntax_ok: true,
          syntax_error: null,
          settings: { episodeServers: ['vidcloud'], supportsDub: false },
          search_count: 2,
          sample_titles: ['Naruto Shippuden', 'Naruto'],
          episode_count: 24,
          stream_count: 1,
          ok: true,
          error: null,
          duration_ms: 42,
        },
      })
    }

    return route.fulfill({ json: {} })
  })

  await page.goto('/app/extensions')

  // Default tab stays Aniyomi for coexistence & backwards compatibility
  await expect(page.getByTestId('ecosystem-tab-aniyomi')).toHaveAttribute('aria-selected', 'true')
  await expect(
    page.getByRole('heading', {
      name: 'Aniyomi: Extension au nom particulièrement long 1',
      exact: true,
    }),
  ).toBeVisible()

  // Switch to Seanime ecosystem tab
  await page.getByTestId('ecosystem-tab-seanime').click()
  await expect(page).toHaveURL(/ecosystem=seanime/)
  await expect(page.getByTestId('seanime-engine-badge')).toContainText('mini-racer')

  // Import Bas1874 marketplace via 1-click preset button
  await page.getByTestId('seanime-import-bas1874-btn').click()
  await expect(page.getByTestId('seanime-ext-demo-stream')).toBeVisible()

  // Install streaming provider
  await page.getByTestId('seanime-install-demo-stream').click()
  await expect(page.getByTestId('seanime-toggle-demo-stream')).toContainText('Activée')

  // Open & save userConfig modal
  await page.getByTestId('seanime-config-demo-stream').click()
  await expect(page.getByTestId('seanime-config-modal')).toBeVisible()
  await page.locator('#cfg-domain').fill('https://mirror.example.org')
  await page.getByTestId('seanime-config-save').click()
  await expect(page.getByTestId('seanime-config-modal')).toBeHidden()

  // Run diagnose
  await page.getByTestId('seanime-diagnose-demo-stream').click()
  await expect(page.getByTestId('seanime-diagnose-modal')).toBeVisible()
  await expect(page.getByTestId('seanime-diagnose-modal')).toContainText('Naruto Shippuden')
  await page.getByTestId('seanime-diagnose-modal').getByRole('button', { name: 'Fermer' }).click()

  // Switch catalog view filter to All and verify non-executable badge on manga-provider
  await page.getByTestId('seanime-filter-all').click()
  const mangaCard = page.getByTestId('seanime-ext-demo-manga')
  await expect(mangaCard).toBeVisible()
  await expect(mangaCard.getByTestId('seanime-non-executable-badge')).toContainText(
    'Non exécutable (streaming uniquement)',
  )
})
