import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { test } from 'node:test'
import ts from 'typescript'

const mediaSource = await readFile(new URL('../src/utils/media.ts', import.meta.url), 'utf8')
const transpiled = ts.transpileModule(mediaSource, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
}).outputText
const mediaMod = await import(
  `data:text/javascript;base64,${Buffer.from(transpiled).toString('base64')}`
)

const {
  isRemoteHttpUrl,
  proxyImageUrl,
  needsImageProxy,
  resolveImageUrl,
  canFallbackToImageProxy,
} = mediaMod

test('resolveImageUrl proxies hotlink-protected VoirAnime and AnimePahe hosts', () => {
  const cx = 'https://voiranime.cx/wp-content/uploads/2026/09/poster-460x630.jpg'
  assert.equal(needsImageProxy(cx), true)
  assert.equal(resolveImageUrl(cx), `/api/media/image-proxy?url=${encodeURIComponent(cx)}`)

  const legacy = 'https://voir-anime.to/wp-content/uploads/poster.jpg'
  assert.equal(needsImageProxy(legacy), true)
  assert.equal(resolveImageUrl(legacy), `/api/media/image-proxy?url=${encodeURIComponent(legacy)}`)

  const pahe = 'https://i.animepahe.ru/snapshots/abc.jpg'
  assert.equal(needsImageProxy(pahe), true)
  assert.equal(resolveImageUrl(pahe), `/api/media/image-proxy?url=${encodeURIComponent(pahe)}`)
})

test('resolveImageUrl leaves TMDB, local, data, empty and already-proxied URLs intact', () => {
  const tmdb = 'https://image.tmdb.org/t/p/w500/poster.jpg'
  assert.equal(needsImageProxy(tmdb), false)
  assert.equal(resolveImageUrl(tmdb), tmdb)
  assert.equal(resolveImageUrl('/static/placeholder.jpg'), '/static/placeholder.jpg')
  assert.equal(resolveImageUrl('data:image/png;base64,AAA'), 'data:image/png;base64,AAA')
  assert.equal(resolveImageUrl(''), '')
  assert.equal(resolveImageUrl(null), '')

  const proxied = proxyImageUrl('https://voiranime.cx/cover.jpg')
  assert.equal(proxyImageUrl(proxied), proxied)
  assert.equal(resolveImageUrl(proxied), proxied)
})

test('canFallbackToImageProxy only permits one proxy retry for non-proxied http(s) URLs', () => {
  const extUrl = 'https://cdn.example.invalid/poster.jpg'
  assert.equal(isRemoteHttpUrl(extUrl), true)
  assert.equal(canFallbackToImageProxy(extUrl, extUrl), true)
  assert.equal(canFallbackToImageProxy(extUrl, proxyImageUrl(extUrl)), false)
  assert.equal(canFallbackToImageProxy('/static/placeholder.jpg', '/static/placeholder.jpg'), false)
  assert.equal(canFallbackToImageProxy('', ''), false)
})
