import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { test } from 'node:test'
import ts from 'typescript'
import { createPinia, setActivePinia } from 'pinia'
const inline = (code) => `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`
function compiled(source, imports) {
  let code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  }).outputText
  for (const [name, url] of Object.entries(imports))
    code = code
      .replaceAll(`'${name}'`, JSON.stringify(url))
      .replaceAll(`"${name}"`, JSON.stringify(url))
  return inline(code)
}
const clientUrl = compiled(
  await readFile(new URL('../src/api/client.ts', import.meta.url), 'utf8'),
  {
    '@/utils/locale': inline(
      "export const language={value:'en'}; export const tx=s=>s==='Autorisez le stockage dans les paramètres.'?'Allow storage access in Settings.':s;",
    ),
  },
)
const { api, ApiError } = await import(clientUrl)
const problem = {
  code: 'storage_permission_required',
  category: 'permission',
  messageKey: 'Autorisez le stockage dans les paramètres.',
  action: 'storage_settings',
}

test('API client uses translated structured errors and retains legacy details', async () => {
  const previous = globalThis.fetch
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ error: 'legacy error', problem }), { status: 409 })
  try {
    await assert.rejects(api.getDownloadTasks(), (error) => {
      assert(error instanceof ApiError)
      assert.equal(error.message, 'Allow storage access in Settings.')
      assert.equal(error.data.error, 'legacy error')
      assert.equal(error.data.problem.action, 'storage_settings')
      return true
    })
  } finally {
    globalThis.fetch = previous
  }
})

test('episode metadata uses the query parameter accepted by the server', async () => {
  const previous = globalThis.fetch
  const requests = []
  globalThis.fetch = async (url) => {
    requests.push(new URL(url, 'http://localhost'))
    return Response.json({ servers: [], size: 0 })
  }
  try {
    await api.getEpisodeServers('https://source.example/watch/1', 'source')
    await api.getEpisodeSize('https://source.example/watch/1', 'source')
    assert(
      requests.every((url) => url.searchParams.get('url') === 'https://source.example/watch/1'),
    )
  } finally {
    globalThis.fetch = previous
  }
})

const fakeApiUrl = inline('export class ApiError extends Error {} export const api={};')
const fake = (await import(fakeApiUrl)).api
const storeUrl = compiled(
  await readFile(new URL('../src/stores/verification.ts', import.meta.url), 'utf8'),
  {
    vue: import.meta.resolve('vue'),
    pinia: import.meta.resolve('pinia'),
    '@/api/client': fakeApiUrl,
    '@/utils/browser': inline('export const detectBrowser=()=>({installedHint:null});'),
  },
)
const { useVerificationStore } = await import(storeUrl)

test('verification retries only the latest still-active searches and retains cancelled-window requests', async () => {
  setActivePinia(createPinia())
  const store = useVerificationStore()
  fake.getNetworkSessions = async () => ({
    sessions: [],
    browsers: [],
    modes: [],
    webviewAvailable: false,
  })
  fake.completeNetworkVerification = async () => ({
    success: true,
    domain: 'source.example',
    resumed: 0,
  })
  fake.cancelNetworkVerification = async () => ({ success: true })
  const called = []
  store.waitForVerification('search', [{ domain: 'source.example' }], async () =>
    called.push('old'),
  )
  store.waitForVerification('search', [{ domain: 'source.example' }], async () =>
    called.push('new'),
  )
  store.waitForVerification('closed-view', [{ domain: 'source.example' }], async () =>
    called.push('closed'),
  )
  store.clearPending('closed-view')
  store.job = { id: 'first', domain: 'source.example', mode: 'webview' }
  await store.cancel()
  assert.deepEqual(called, [])
  store.job = { id: 'second', domain: 'source.example', mode: 'webview' }
  await store.complete()
  assert.deepEqual(called, ['new'])
})

test('automatic verification completion refreshes pending searches without a manual click', async () => {
  setActivePinia(createPinia())
  const store = useVerificationStore()
  const calls = []
  fake.getNetworkSessions = async () => ({
    sessions: [],
    browsers: [],
    modes: [],
    webviewAvailable: false,
  })
  fake.getVerificationStatus = async () => ({
    status: 'completed',
    domain: 'source.example',
    resumed: 2,
  })
  store.waitForVerification('auto-search', [{ domain: 'source.example' }], async () => {
    calls.push('retry')
  })
  store.job = { id: 'automatic', domain: 'source.example', mode: 'browser' }
  await new Promise((resolve) => setTimeout(resolve, 1300))
  assert.deepEqual(calls, ['retry'])
  assert.equal(store.job, null)
  store.$dispose()
})
