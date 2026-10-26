import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { test } from 'node:test'
import ts from 'typescript'
import { createPinia, setActivePinia } from 'pinia'
const inline = (value) => `data:text/javascript;base64,${Buffer.from(value).toString('base64')}`
const english = JSON.parse(await readFile(new URL('../src/locales/en.json', import.meta.url)))
async function load(path, replacements = {}) {
  let code = ts.transpileModule(await readFile(new URL(path, import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  }).outputText
  for (const [name, value] of Object.entries(replacements))
    code = code.replaceAll(`'${name}'`, JSON.stringify(value))
  return inline(code)
}
const jsonUrl = inline(`export default ${JSON.stringify(english)};`)
const localeUrl = await load('../src/utils/locale.ts', {
  vue: import.meta.resolve('vue'),
  '@/locales/en.json': jsonUrl,
})
const locale = await import(localeUrl)
const preferencesUrl = await load('../src/stores/sourcePreferences.ts', {
  vue: import.meta.resolve('vue'),
  pinia: import.meta.resolve('pinia'),
  '@/utils/locale': localeUrl,
})
const { useSourcePreferences } = await import(preferencesUrl)

test('browser language detection respects explicit preferences and restricted storage', (t) => {
  const originals = Object.fromEntries(
    ['document', 'location', 'navigator', 'localStorage'].map((key) => [
      key,
      Object.getOwnPropertyDescriptor(globalThis, key),
    ]),
  )
  t.after(() => {
    for (const [key, value] of Object.entries(originals))
      if (value) Object.defineProperty(globalThis, key, value)
      else delete globalThis[key]
  })
  const values = new Map()
  for (const [key, value] of Object.entries({
    document: { cookie: '' },
    location: { search: '' },
    navigator: { languages: ['en-GB', 'fr'], language: 'en-GB' },
    localStorage: { getItem: (key) => values.get(key) || null },
  }))
    Object.defineProperty(globalThis, key, { configurable: true, value })
  assert.equal(locale.resolveClientLanguage(), 'en')
  globalThis.navigator.languages = ['fr-CA', 'en']
  assert.equal(locale.resolveClientLanguage(), 'fr')
  values.set('animan_lang', 'en')
  assert.equal(locale.resolveClientLanguage(), 'en')
  globalThis.document.cookie = 'animan_lang=fr'
  assert.equal(locale.resolveClientLanguage(), 'fr')
  globalThis.location.search = '?lang=en'
  assert.equal(locale.resolveClientLanguage(), 'en')
  globalThis.location.search = '?lang=invalid'
  globalThis.localStorage.getItem = () => {
    throw new Error('blocked')
  }
  assert.equal(locale.resolveClientLanguage(), 'fr')
})

test('default source follows language until an explicit choice is saved', (t) => {
  const original = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  const values = new Map()
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: {
      getItem: (key) => values.get(key) || null,
      setItem: (key, value) => values.set(key, value),
    },
  })
  t.after(() => {
    if (original) Object.defineProperty(globalThis, 'localStorage', original)
    else delete globalThis.localStorage
    locale.language.value = 'fr'
  })
  locale.language.value = 'en'
  setActivePinia(createPinia())
  const prefs = useSourcePreferences()
  assert.equal(prefs.defaultSource, 'animepahe')
  locale.language.value = 'fr'
  assert.equal(prefs.defaultSource, 'french-manga')
  prefs.setDefault('voir-anime')
  locale.language.value = 'en'
  assert.equal(prefs.defaultSource, 'voir-anime')
  setActivePinia(createPinia())
  assert.equal(useSourcePreferences().defaultSource, 'voir-anime')
})

test('English covers labels, parameterized notifications and genuine decoder failures', () => {
  locale.language.value = 'en'
  assert.equal(locale.tx('Ouvrir la recherche'), 'Open search')
  assert.equal(locale.tx('Épisode 9 VF ajouté à la file.'), 'Episode 9 VF added to queue.')
  assert.equal(locale.tx('Bibliothèque vidée.'), 'Library cleared.')
  assert.equal(
    locale.tx(
      'Échec du téléchargement des sous-titres : Sous-titres 1: Délai réseau dépassé après 3 tentatives',
    ),
    'Subtitle download failed: Subtitles 1: Network timeout after 3 attempts',
  )
  assert.equal(locale.tx('One Piece - Saison 23'), 'One Piece - Saison 23')
  locale.language.value = 'fr'
  assert.equal(locale.tx('Ouvrir la recherche'), 'Ouvrir la recherche')
})

test('legacy browser preferences migrate once without replacing modern choices', (t) => {
  const original = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  const values = new Map([
    ['animan_theme', 'dark'],
    ['animan_pinned_sources', '["voir-anime"]'],
    ['animan_default_source', 'voir-anime'],
  ])
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: {
      getItem: (key) => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, value),
    },
  })
  t.after(() => {
    if (original) Object.defineProperty(globalThis, 'localStorage', original)
    else delete globalThis.localStorage
  })
  assert.equal(locale.readPreference('theme'), 'dark')
  assert.equal(values.get('animelab_theme'), 'dark')
  values.set('animelab_theme', 'light')
  assert.equal(locale.readPreference('theme'), 'light')
  setActivePinia(createPinia())
  const prefs = useSourcePreferences()
  assert.deepEqual(prefs.pinned, ['voir-anime'])
  assert.equal(prefs.defaultSource, 'voir-anime')
  prefs.setDefault('animepahe')
  assert.equal(values.get('animelab_default_source'), 'animepahe')
  assert.equal(values.get('animan_default_source'), 'voir-anime')
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: {
      getItem: (key) => (key === 'animan_theme' ? 'dark' : null),
      setItem: () => {
        throw new Error('Read only')
      },
    },
  })
  assert.equal(locale.readPreference('theme'), 'dark')
})
