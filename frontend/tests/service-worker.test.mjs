import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { test } from 'node:test'
import vm from 'node:vm'

const source = await readFile(new URL('../../animelab/static/sw.js', import.meta.url), 'utf8')

function worker(fetchImpl, cached) {
  const handlers = new Map()
  const writes = []
  const cache = {
    match: async () => cached,
    put: async (request, response) => writes.push([request.url, await response.text()]),
  }
  vm.runInNewContext(source, {
    self: { addEventListener: (event, handler) => handlers.set(event, handler) },
    URL,
    Response,
    console,
    fetch: fetchImpl,
    caches: { open: async () => cache, match: async () => cached },
  })
  return {
    writes,
    request(path, options) {
      let result
      const request = new Request('http://localhost' + path, options)
      handlers.get('fetch')({
        request,
        respondWith: (value) => {
          result = value
        },
      })
      return result
    },
  }
}

test('an upgraded installation gets the new logo despite a cached old response', async () => {
  const requests = []
  const sw = worker(async (request, options) => {
    requests.push([request.url, options.cache])
    return new Response('new AnimeLab logo')
  }, new Response('old Animan logo'))
  const response = await sw.request('/img/icon-192.png')
  assert.equal(await response.text(), 'new AnimeLab logo')
  assert.equal(requests[0][1], 'no-cache')
  assert.deepEqual(sw.writes, [['http://localhost/img/icon-192.png', 'new AnimeLab logo']])
})

test('a fingerprinted PWA icon keeps its full URL and falls back offline', async () => {
  const sw = worker(async () => {
    throw new Error('offline')
  }, new Response('offline logo'))
  const response = await sw.request('/img/icon-512.png?v=new-artwork')
  assert.equal(await response.text(), 'offline logo')
  assert.deepEqual(sw.writes, [])
})

test('a failed icon response is never replaced with stale artwork or cached', async () => {
  const sw = worker(async () => new Response('missing', { status: 404 }), new Response('old logo'))
  assert.equal((await sw.request('/img/favicon.png')).status, 404)
  assert.deepEqual(sw.writes, [])
})

test('logo cache updates never intercept media ranges or download streams', () => {
  const sw = worker(() => {
    throw new Error('must not intercept')
  })
  assert.equal(sw.request('/api/media/stream/episode'), undefined)
  assert.equal(sw.request('/video.mp4', { headers: { Range: 'bytes=0-1023' } }), undefined)
})
