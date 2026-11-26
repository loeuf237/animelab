import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { test } from 'node:test'
import ts from 'typescript'

const inline = (value) => `data:text/javascript;base64,${Buffer.from(value).toString('base64')}`

const platformCode = ts
  .transpileModule(await readFile(new URL('../src/utils/platform.ts', import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  })
  .outputText.replace("'vue'", JSON.stringify(import.meta.resolve('vue')))

const {
  readAndroidEngineState,
  isAndroidEngineBooting,
  waitForAndroidEngine,
  openNativeExternalPlayer,
} = await import(inline(platformCode))

function setupMockWindow(t, initialState) {
  const originalWindow = Object.getOwnPropertyDescriptor(globalThis, 'window')
  const originalCustomEvent = Object.getOwnPropertyDescriptor(globalThis, 'CustomEvent')
  const target = new EventTarget()
  let state = initialState

  // Android WebView's Gin Java Bridge throws TypeError('Illegal invocation')
  // whenever a @JavascriptInterface method is called without the bridge object as `this`.
  const bridge =
    initialState === undefined
      ? {}
      : {
          getEngineState() {
            if (this !== bridge) throw new TypeError('Illegal invocation')
            return JSON.stringify(state)
          },
          openExternalPlayer(payloadJson) {
            if (this !== bridge) throw new TypeError('Illegal invocation')
            return JSON.stringify({ launched: Boolean(payloadJson) })
          },
        }

  const mockWindow = {
    addEventListener: target.addEventListener.bind(target),
    removeEventListener: target.removeEventListener.bind(target),
    dispatchEvent: target.dispatchEvent.bind(target),
    AnimeLabAndroid: bridge,
  }

  Object.defineProperty(globalThis, 'window', { configurable: true, value: mockWindow })
  if (!originalCustomEvent) {
    Object.defineProperty(globalThis, 'CustomEvent', {
      configurable: true,
      value: class CustomEvent extends Event {
        constructor(name, init = {}) {
          super(name)
          this.detail = init.detail
        }
      },
    })
  }

  t.after(() => {
    if (originalWindow) Object.defineProperty(globalThis, 'window', originalWindow)
    else delete globalThis.window
    if (originalCustomEvent) Object.defineProperty(globalThis, 'CustomEvent', originalCustomEvent)
    else if (!originalCustomEvent) delete globalThis.CustomEvent
  })

  return {
    mockWindow,
    setState: (next) => {
      state = next
    },
  }
}

test('returns ready immediately outside Android or when engine is already ready', async (t) => {
  setupMockWindow(t, undefined)
  assert.equal(readAndroidEngineState(), null)
  assert.equal(isAndroidEngineBooting(), false)
  assert.deepEqual(await waitForAndroidEngine(), { ready: true })

  const { setState } = setupMockWindow(t, { ready: true, fullyReady: false, error: null })
  assert.deepEqual(readAndroidEngineState(), { ready: true, fullyReady: false, error: null })
  assert.equal(isAndroidEngineBooting(), false)
  assert.deepEqual(await waitForAndroidEngine(), { ready: true })
  setState({ ready: false, fullyReady: false, error: 'Crash' })
  assert.deepEqual(await waitForAndroidEngine(), { ready: false, error: 'Crash' })
})

test('waits for animelab:engine-ready and animelab:engine-error events', async (t) => {
  const { mockWindow, setState } = setupMockWindow(t, {
    ready: false,
    fullyReady: false,
    error: null,
  })
  assert.equal(isAndroidEngineBooting(), true)

  const pendingReady = waitForAndroidEngine()
  setState({ ready: true, fullyReady: false, error: null })
  mockWindow.dispatchEvent(new CustomEvent('animelab:engine-ready'))
  assert.deepEqual(await pendingReady, { ready: true })

  setState({ ready: false, fullyReady: false, error: null })
  const pendingError = waitForAndroidEngine()
  setState({ ready: false, fullyReady: false, error: 'Python failed' })
  mockWindow.dispatchEvent(new CustomEvent('animelab:engine-error', { detail: 'Python failed' }))
  assert.deepEqual(await pendingError, { ready: false, error: 'Python failed' })
})

test('aborts cleanly when caller signal fires', async (t) => {
  setupMockWindow(t, { ready: false, fullyReady: false, error: null })
  const controller = new AbortController()
  const pending = waitForAndroidEngine(controller.signal)
  controller.abort()
  assert.deepEqual(await pending, { ready: false, error: 'Aborted' })
})

test('resolves via polling fallback when state changes without DOM event', async (t) => {
  const { setState } = setupMockWindow(t, {
    ready: false,
    fullyReady: false,
    error: null,
  })
  const pending = waitForAndroidEngine()
  setState({ ready: true, fullyReady: false, error: null })
  assert.deepEqual(await pending, { ready: true })
})

test('preserves Android WebView bridge receiver for JavascriptInterface methods', (t) => {
  setupMockWindow(t, { ready: false, fullyReady: false, error: null })
  assert.deepEqual(readAndroidEngineState(), { ready: false, fullyReady: false, error: null })
  assert.deepEqual(
    openNativeExternalPlayer({ kind: 'url', target: 'https://example.test/v.mp4' }),
    {
      launched: true,
      error: undefined,
    },
  )
})
