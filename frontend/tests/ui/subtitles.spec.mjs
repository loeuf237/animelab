import { test, expect } from '@playwright/test'
import { mockApp, tasks } from './fixtures.mjs'

const importId = 'a'.repeat(32),
  firstId = 'b'.repeat(32),
  secondId = 'c'.repeat(32)
const resultId = 'd'.repeat(32),
  trackId = 'local:' + 'e'.repeat(32)
const status = {
  configured: true,
  authenticated: true,
  username: '',
  remember: false,
  secureStorageAvailable: false,
  quota: { remaining: 5 },
  error: null,
  retryAfter: 0,
}
const entries = [firstId, secondId].map((id, i) => ({
  id,
  name: `One.Piece.S01E0${i + 2}.srt`,
  format: 'srt',
  size: 100,
  cues: 2,
  firstCue: 0.5,
  lastCue: 3,
  preview: `Bonjour épisode ${i + 2}\n<script>window.subtitleInjected=true</script>`,
  numbering: { season: 1, episode: i + 2 },
}))
const pack = { importId, entries, provenance: { provider: 'local' } }

async function setup(page, width) {
  await page.setViewportSize({ width, height: 1000 })
  await mockApp(page, {
    taskList: [
      { ...tasks[3], id: 'local', episodeNumber: 2, savePath: '/downloads/reference.mkv' },
    ],
  })
  let attached = false
  const writes = []
  await page.route('**/api/download/local/media-inventory', (route) =>
    route.fulfill({
      json: {
        tracks: [
          { id: 'v0', kind: 'video', label: 'Image', lang: 'und', default: true },
          { id: 'a0', kind: 'audio', label: 'Japanese', lang: 'jpn', default: true },
          ...(attached
            ? [
                {
                  id: trackId,
                  kind: 'subtitle',
                  label: 'Import français',
                  lang: 'fr',
                  default: false,
                },
              ]
            : []),
        ].map((row) => ({
          ...row,
          format: 'test',
          automatic: false,
          forced: false,
          embedded: !row.id.startsWith('local:'),
        })),
        profiles: ['ORIGINAL', 'SIDECAR', 'MKV_SOFT', 'MP4_HARD'].map((mode) => ({
          mode,
          available: true,
          reason: '',
          trackSelectionAvailable: true,
        })),
        warnings: [],
        duration: 1200,
        outputProfile: { version: 1, mode: 'MKV_SOFT', keepOriginals: true },
      },
    }),
  )
  await page.route('**/api/download/local/subtitles/context', (route) =>
    route.fulfill({ json: { query: 'One Piece', episode: 2, season: 1, provider: status } }),
  )
  await page.route('**/api/download/local/subtitles/attach', (route) => {
    attached = true
    writes.push(route.request().postDataJSON())
    return route.fulfill({ json: { trackId, duplicate: false } })
  })
  await page.goto('/app/downloads')
  await page.getByRole('button', { name: 'Terminés 1', exact: true }).click()
  await page.getByRole('button', { name: 'Pistes et format', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByText('Ajouter des sous-titres', { exact: true }).click()
  await expect(dialog.getByLabel('Titre de la série ou du film')).toHaveValue('One Piece')
  return { dialog, writes }
}

for (const width of [360, 1280]) {
  test(`local archive preview and explicit episode selection at ${width}px`, async ({
    page,
  }, testInfo) => {
    const { dialog, writes } = await setup(page, width)
    await page.route('**/api/download/local/subtitles/import?*', (route) => {
      expect(route.request().headers()['content-type']).toBe('application/octet-stream')
      return route.fulfill({ json: pack })
    })
    await dialog.getByLabel('Fichier de sous-titres ou archive').setInputFiles({
      name: 'season.zip',
      mimeType: 'application/zip',
      buffer: Buffer.from('mock bounded ZIP'),
    })
    const choose = dialog.getByLabel('Fichier dans l’import')
    await expect(choose).toHaveValue('')
    await choose.selectOption(secondId)
    await expect(
      dialog.getByText('Attention : le numéro du fichier diffère de celui de la tâche.'),
    ).toBeVisible()
    await expect(dialog.locator('.subtitle-preview')).toContainText('Bonjour épisode 3')
    expect(await page.evaluate(() => window.subtitleInjected)).toBeUndefined()
    const add = dialog.getByRole('button', { name: 'Ajouter cette piste', exact: true })
    await expect(add).toBeDisabled()
    await dialog
      .getByLabel('Je confirme que ce fichier correspond au bon épisode et à cette vidéo.')
      .check()
    await dialog.getByLabel('Nom de la piste', { exact: true }).fill('Import français')
    await dialog.screenshot({ path: testInfo.outputPath('subtitle-import.png') })
    await add.click()
    await expect.poll(() => writes.length).toBe(1)
    expect(writes[0].entryId).toBe(secondId)
    const track = dialog.locator('.output-track').filter({ hasText: 'Import français' })
    await expect(track.getByRole('checkbox').first()).toBeChecked()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      width,
    )
  })

  test(`OpenSubtitles configuration search and manual quota preview at ${width}px`, async ({
    page,
  }) => {
    const { dialog } = await setup(page, width)
    const calls = []
    await page.route('**/api/download/subtitle-provider', (route) => {
      const body = route.request().postDataJSON()
      expect(body.apiKey).toBe('test-key')
      expect(body.password).toBe('test-password')
      return route.fulfill({ json: status })
    })
    await page.route('**/api/download/local/subtitles/search', (route) => {
      expect(route.request().postDataJSON()).toMatchObject({
        imdbId: 'tt100',
        season: 1,
        episode: 2,
      })
      return route.fulfill({
        json: {
          results: [
            {
              id: resultId,
              fileName: entries[1].name,
              language: 'fr',
              release: 'WEB 1080p',
              fps: 23.976,
              feature: { title: 'Episode', season_number: 1, episode_number: 3 },
              checks: [],
              hearingImpaired: false,
              forced: false,
              warnings: ['Les identifiants ou la numérotation ne correspondent pas à la recherche'],
            },
          ],
          page: 1,
          totalPages: 1,
          provider: status,
        },
      })
    })
    await page.route('**/api/download/local/subtitles/provider-preview', (route) => {
      calls.push(route.request().postDataJSON())
      return route.fulfill({
        json: { ...pack, entries: [entries[1]], provenance: { provider: 'opensubtitles' } },
      })
    })
    await dialog.getByText('Compte OpenSubtitles', { exact: true }).click()
    await dialog.getByLabel('Clé API OpenSubtitles', { exact: true }).fill('test-key')
    await dialog.getByLabel('Nom d’utilisateur OpenSubtitles (facultatif)').fill('tester')
    await dialog.getByLabel('Mot de passe OpenSubtitles', { exact: true }).fill('test-password')
    await expect(dialog.getByLabel('Mémoriser les identifiants chiffrés')).toBeDisabled()
    await dialog.getByRole('button', { name: 'Connecter OpenSubtitles', exact: true }).click()
    await expect(dialog.getByLabel('Mot de passe OpenSubtitles', { exact: true })).toHaveValue('')
    await expect(dialog.getByLabel('Clé API OpenSubtitles', { exact: true })).toHaveValue('')
    expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain('test-key')
    await dialog.getByLabel('IMDb', { exact: true }).fill('tt100')
    await dialog.getByRole('button', { name: 'Rechercher les sous-titres', exact: true }).click()
    await expect(dialog.locator('.subtitle-result')).toHaveCount(1)
    expect(calls).toHaveLength(0)
    await dialog.getByRole('button', { name: 'Télécharger et prévisualiser', exact: true }).click()
    await expect(dialog.locator('.subtitle-preview')).toContainText('Bonjour épisode 3')
    expect(calls).toEqual([{ resultId }])
    await expect(
      dialog.getByRole('button', { name: 'Ajouter cette piste', exact: true }),
    ).toBeDisabled()
  })
}

for (const width of [360, 1280]) {
  test(`SubDL v2 configuration combined search and reversible timing at ${width}px`, async ({
    page,
  }) => {
    await page.route('**/api/download/subtitle-sync-capabilities', (route) =>
      route.fulfill({ json: { manual: true, alass: true, version: '2.0.0', reason: '' } }),
    )
    const { dialog } = await setup(page, width)
    await page.route('**/api/download/subtitle-provider?provider=subdl', (route) => {
      expect(route.request().postDataJSON()).toMatchObject({
        apiKey: 'subdl-test-key',
        username: '',
        password: '',
      })
      return route.fulfill({ json: { ...status, quota: { downloads: { remaining: 47 } } } })
    })
    await dialog.getByText('Compte OpenSubtitles', { exact: true }).click()
    await dialog.getByLabel('Fournisseur à configurer').selectOption('subdl')
    // Older contexts omit the provider registry; configure status is refreshed below.
    await page.route('**/api/download/local/subtitles/context', (route) =>
      route.fulfill({
        json: {
          query: 'One Piece',
          season: 1,
          episode: 2,
          provider: status,
          providers: { opensubtitles: status, subdl: status },
          video: { fps: 25, duration: 1400 },
        },
      }),
    )
    // Trigger a context refresh through preview after search; the key form remains usable before it.
    await dialog.getByLabel('Clé API SubDL', { exact: true }).fill('subdl-test-key')
    await expect(dialog.getByLabel('Mot de passe OpenSubtitles', { exact: true })).toHaveCount(0)
    await dialog.getByRole('button', { name: 'Connecter SubDL', exact: true }).click()
    await expect(dialog.getByLabel('Clé API SubDL', { exact: true })).toHaveValue('')
    await dialog.getByLabel('SubDL v2', { exact: true }).check()
    await page.route('**/api/download/local/subtitles/search', (route) => {
      expect(route.request().postDataJSON().providers).toEqual(['opensubtitles', 'subdl'])
      return route.fulfill({
        json: {
          results: [
            {
              id: resultId,
              fileName: 'Show.srt',
              release: 'WEB',
              language: 'fr',
              provider: 'subdl',
              feature: {},
              fps: 25,
              checks: [{ field: 'fps', actual: 25, expected: 23.976, state: 'mismatch' }],
              warnings: [],
              alternatives: [{ id: resultId, provider: 'subdl' }],
            },
          ],
          errors: [{ provider: 'opensubtitles', message: 'Clé refusée' }],
          page: 1,
          totalPages: 1,
          provider: status,
          providers: { subdl: status },
        },
      })
    })
    await dialog.getByRole('button', { name: 'Rechercher les sous-titres', exact: true }).click()
    await expect(dialog.getByText('opensubtitles : Clé refusée')).toBeVisible()
    await expect(dialog.getByText('Différent de la recherche', { exact: false })).toBeVisible()
    await page.route('**/api/download/local/subtitles/provider-preview', (route) =>
      route.fulfill({
        json: { ...pack, entries: [entries[0]], provenance: { provider: 'subdl' } },
      }),
    )
    await dialog.getByRole('button', { name: 'Télécharger et prévisualiser', exact: true }).click()
    await dialog.getByText('Corriger la synchronisation', { exact: true }).click()
    await dialog.getByLabel('Décalage à appliquer (secondes)').fill('2.5')
    const correctedId = 'f'.repeat(32)
    await page.route('**/api/download/local/subtitles/transform', (route) => {
      expect(route.request().postDataJSON()).toMatchObject({
        importId,
        entryId: firstId,
        method: 'manual',
        offsetSeconds: 2.5,
        sourceFps: null,
        targetFps: null,
      })
      return route.fulfill({
        json: {
          ...pack,
          importId: correctedId,
          entries: [{ ...entries[0], preview: 'Copie corrigée' }],
          originalImportId: importId,
          originalEntryId: firstId,
          comparison: { kind: 'offset', correctedCues: 2 },
        },
      })
    })
    await dialog.getByRole('button', { name: 'Créer une copie corrigée', exact: true }).click()
    await expect(dialog.locator('.subtitle-preview')).toHaveText('Copie corrigée')
    await expect(
      dialog.getByRole('button', { name: 'Ajouter cette piste', exact: true }),
    ).toBeDisabled()
    await page.route(`**/api/download/local/subtitles/imports/${importId}`, (route) =>
      route.fulfill({ json: { ...pack, entries: [entries[0]] } }),
    )
    await dialog
      .getByRole('button', { name: 'Revenir au sous-titre original', exact: true })
      .click()
    await expect(dialog.locator('.subtitle-preview')).toContainText('Bonjour épisode 2')
    expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain('subdl-test-key')
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      width,
    )
  })
}

test('automatic synchronization requires reference confirmation and can be cancelled', async ({
  page,
}) => {
  await page.route('**/api/download/subtitle-sync-capabilities', (route) =>
    route.fulfill({ json: { manual: true, alass: true, version: '2.0.0', reason: '' } }),
  )
  const { dialog } = await setup(page, 1280)
  await page.route('**/api/download/local/subtitles/import?*', (route) =>
    route.fulfill({ json: { ...pack, entries: [entries[0]] } }),
  )
  await dialog.getByLabel('Fichier de sous-titres ou archive').setInputFiles({
    name: 'x.srt',
    mimeType: 'text/plain',
    buffer: Buffer.from('bounded fixture'),
  })
  await dialog.getByText('Corriger la synchronisation', { exact: true }).click()
  await dialog.getByLabel('Méthode de correction').selectOption('alass')
  const create = dialog.getByRole('button', { name: 'Créer une copie corrigée', exact: true })
  await expect(create).toBeDisabled()
  await expect(dialog.getByLabel('Piste locale de référence').locator('option')).toHaveCount(1)
  await dialog.getByLabel('Méthode de correction').selectOption('manual')
  let finish
  const pending = new Promise((resolve) => {
    finish = resolve
  })
  await page.route('**/api/download/local/subtitles/transform', async (route) => {
    await pending
    return route.fulfill({
      status: 409,
      json: { error: 'Synchronisation interrompue ; l’original est conservé' },
    })
  })
  await page.route('**/api/download/local/subtitles/cancel-sync', async (route) => {
    finish()
    return route.fulfill({ json: { cancelled: true } })
  })
  await create.click()
  await dialog.getByRole('button', { name: 'Interrompre la synchronisation', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText('original est conservé')
  await expect(dialog.locator('.subtitle-preview')).toContainText('Bonjour épisode 2')
  await expect(create).toBeEnabled()
})
