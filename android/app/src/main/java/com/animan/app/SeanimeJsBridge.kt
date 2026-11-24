package com.animan.app

import android.annotation.SuppressLint
import android.util.Log
import android.webkit.ConsoleMessage
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import com.chaquo.python.Python
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayInputStream
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CountDownLatch
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicReference

/**
 * Offscreen WebView V8 bridge executing Seanime JavaScript providers on Android
 * while routing all outbound HTTP calls through Python's SSRF-protected transport.
 */
object SeanimeJsBridge {
    private const val TAG = "SeanimeJsBridge"
    private const val SANDBOX_ORIGIN = "https://seanime.local/"

    private val execLock = Any()
    private val fetchExecutor: ExecutorService = Executors.newFixedThreadPool(4)
    private val pendingCalls = ConcurrentHashMap<String, PendingCall>()
    private val pageSequence = AtomicLong(0L)

    @Volatile
    private var sandboxView: WebView? = null

    @Volatile
    private var pendingPageToken: Long = 0L

    @Volatile
    private var pendingPageLatch: CountDownLatch? = null

    private data class PendingCall(
        val extensionId: String = "",
        val latch: CountDownLatch = CountDownLatch(1),
        val result: AtomicReference<String?> = AtomicReference(null),
        val verificationUrl: AtomicReference<String?> = AtomicReference(null),
        @Volatile var cancelled: Boolean = false,
    )

    @JvmStatic
    fun isAvailable(): Boolean =
        try {
            EngineHost.context
            true
        } catch (_: UninitializedPropertyAccessException) {
            false
        }

    @JvmStatic
    fun validateSyntax(shimJs: String, providerJs: String): String {
        synchronized(execLock) {
            return try {
                loadBlankPageAndWait(15_000L)
                val callId = UUID.randomUUID().toString()
                val pending = PendingCall()
                pendingCalls[callId] = pending
                try {
                    val validateScript = buildString {
                        append("(function(){\n")
                        append("  var __res;\n")
                        append("  try {\n")
                        append("    globalThis.__seanimeCompile(")
                        append(jsQuote(providerJs))
                        append(");\n")
                        append("    __res = 'ok';\n")
                        append("  } catch (e) {\n")
                        append("    __res = 'error:' + (e && e.message ? e.message : String(e));\n")
                        append("  }\n")
                        append("  window.__animelabSeanimeBridge.resolveCall(")
                        append(jsQuote(callId))
                        append(", String(__res));\n")
                        append("})();")
                    }
                    runJs(shimJs, validateScript)
                    if (!pending.latch.await(15_000L, TimeUnit.MILLISECONDS)) {
                        return "error:Timeout lors de la validation WebView"
                    }
                    pending.result.get() ?: "error:Réponse vide de WebView"
                } finally {
                    pending.cancelled = true
                    pendingCalls.remove(callId)
                }
            } catch (err: Exception) {
                Log.w(TAG, "validateSyntax failed", err)
                "error:${err.message ?: err.javaClass.simpleName}"
            }
        }
    }

    @JvmStatic
    fun invoke(invocationJson: String): String {
        synchronized(execLock) {
            val params = JSONObject(invocationJson)
            val extensionId = params.optString("extensionId", "")
            val shim = params.getString("shim")
            val code = params.getString("code")
            val method = params.getString("method")
            val argsJson = params.optString("argsJson", "[]")
            val userConfigJson = params.optString("userConfigJson", "{}")
            val defaultsJson = params.optString("defaultsJson", "{}")
            val storeJson = params.optString("storeJson", "{}")
            val timeoutMs = params.optLong("timeoutMs", 30_000L).coerceIn(3_000L, 120_000L)

            val callId = UUID.randomUUID().toString()
            val pending = PendingCall(extensionId = extensionId)
            pendingCalls[callId] = pending

            return try {
                loadBlankPageAndWait(10_000L)
                val bootstrap = buildString {
                    append("(function(){\n")
                    append("  var __callId = ").append(jsQuote(callId)).append(";\n")
                    append("  var __pendingFetches = Object.create(null);\n")
                    append("  var __seq = 0;\n")
                    append("  window.__animelabResolveFetch = function(targetCallId, reqId, respJson) {\n")
                    append("    if (targetCallId !== __callId) return;\n")
                    append("    var h = __pendingFetches[reqId];\n")
                    append("    if (h) { delete __pendingFetches[reqId]; h.resolve(respJson); }\n")
                    append("  };\n")
                    append("  globalThis.__seanimeHostFetch = function(reqJsonStr) {\n")
                    append("    return new Promise(function(resolve) {\n")
                    append("      var reqId = 'r' + (++__seq);\n")
                    append("      __pendingFetches[reqId] = { resolve: resolve };\n")
                    append("      window.__animelabSeanimeBridge.fetch(__callId, reqId, String(reqJsonStr || '{}'));\n")
                    append("    });\n")
                    append("  };\n")
                    append("  Promise.resolve().then(function() {\n")
                    append("    globalThis.__seanimeCompile(${jsQuote(code)});\n")
                    append("    return globalThis.__seanimeInvoke(")
                    append("${jsQuote(method)}, ${jsQuote(argsJson)}, ${jsQuote(userConfigJson)}, ${jsQuote(defaultsJson)}, ${jsQuote(storeJson)}")
                    append(");\n")
                    append("  }).then(function(resJson) {\n")
                    append("    window.__animelabSeanimeBridge.resolveCall(__callId, String(resJson));\n")
                    append("  }).catch(function(err) {\n")
                    append("    var payload = JSON.stringify({ ok: false, error: err && err.message ? String(err.message) : String(err), stack: err && err.stack ? String(err.stack) : '', store: {}, logs: [] });\n")
                    append("    window.__animelabSeanimeBridge.resolveCall(__callId, payload);\n")
                    append("  });\n")
                    append("})();")
                }
                runJs(shim, bootstrap)
                if (!pending.latch.await(timeoutMs, TimeUnit.MILLISECONDS)) {
                    return errorPayload(
                        "Délai d'exécution WebView Seanime dépassé (${timeoutMs / 1000}s)",
                        pending.verificationUrl.get(),
                    )
                }
                val raw = pending.result.get()
                if (raw.isNullOrBlank()) {
                    return errorPayload("Réponse vide du moteur WebView Seanime")
                }
                val capturedVerification = pending.verificationUrl.get()
                if (!capturedVerification.isNullOrBlank()) {
                    val parsed = JSONObject(raw)
                    if (!parsed.optBoolean("verificationRequired", false)) {
                        parsed.put("verificationRequired", true)
                        parsed.put("verificationUrl", capturedVerification)
                        return parsed.toString()
                    }
                }
                raw
            } catch (err: Exception) {
                Log.w(TAG, "invoke failed", err)
                errorPayload(err.message ?: err.javaClass.simpleName)
            } finally {
                pending.cancelled = true
                pendingCalls.remove(callId)
            }
        }
    }

    private fun errorPayload(error: String, verificationUrl: String? = null): String =
        JSONObject().apply {
            put("ok", false)
            put("error", error)
            put("store", JSONObject())
            put("logs", JSONArray())
            if (!verificationUrl.isNullOrBlank()) {
                put("verificationRequired", true)
                put("verificationUrl", verificationUrl)
            }
        }.toString()

    @SuppressLint("SetJavaScriptEnabled", "AddJavascriptInterface")
    private fun ensureWebView(): WebView {
        sandboxView?.let { existing ->
            existing.onResume()
            existing.resumeTimers()
            return existing
        }
        val context = EngineHost.context.applicationContext
        val view = WebView(context)
        view.setWillNotDraw(true)
        view.settings.javaScriptEnabled = true
        view.settings.domStorageEnabled = false
        view.settings.allowFileAccess = false
        view.settings.allowContentAccess = false
        view.settings.blockNetworkLoads = true
        view.addJavascriptInterface(HostJsBridge(), "__animelabSeanimeBridge")
        view.webChromeClient = object : WebChromeClient() {
            override fun onConsoleMessage(consoleMessage: ConsoleMessage?): Boolean {
                if (consoleMessage?.messageLevel() == ConsoleMessage.MessageLevel.ERROR) {
                    Log.d(TAG, "JS error: ${consoleMessage.message()}")
                }
                return true
            }
        }
        view.webViewClient = object : WebViewClient() {
            override fun shouldInterceptRequest(
                v: WebView?,
                request: WebResourceRequest?,
            ): WebResourceResponse {
                return WebResourceResponse(
                    "text/plain",
                    "utf-8",
                    403,
                    "Forbidden",
                    emptyMap(),
                    ByteArrayInputStream(ByteArray(0)),
                )
            }

            override fun onPageFinished(v: WebView?, url: String?) {
                val tag = v?.tag as? Long
                if (tag == null || tag == pendingPageToken) {
                    pendingPageLatch?.countDown()
                }
            }
        }
        view.onResume()
        view.resumeTimers()
        sandboxView = view
        return view
    }

    private fun loadBlankPageAndWait(timeoutMs: Long) {
        val token = pageSequence.incrementAndGet()
        val latch = CountDownLatch(1)
        pendingPageToken = token
        pendingPageLatch = latch
        EngineHost.main.post {
            try {
                val view = ensureWebView()
                view.stopLoading()
                view.tag = token
                view.loadDataWithBaseURL(
                    SANDBOX_ORIGIN,
                    "<!doctype html><html><body></body></html>",
                    "text/html",
                    "utf-8",
                    null,
                )
            } catch (err: Exception) {
                Log.e(TAG, "Failed to initialize offscreen WebView", err)
                latch.countDown()
            }
        }
        latch.await(timeoutMs, TimeUnit.MILLISECONDS)
        if (pendingPageToken == token) {
            pendingPageLatch = null
        }
    }

    private fun runJs(vararg scripts: String) {
        EngineHost.main.post {
            try {
                val view = ensureWebView()
                for (script in scripts) {
                    if (script.isNotBlank()) {
                        view.evaluateJavascript(script, null)
                    }
                }
            } catch (err: Exception) {
                Log.e(TAG, "evaluateJavascript failed", err)
            }
        }
    }

    private fun jsQuote(raw: String): String {
        return JSONObject.quote(raw)
            .replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029")
    }

    private class HostJsBridge {
        @JavascriptInterface
        fun fetch(callId: String, reqId: String, reqJson: String) {
            val pending = pendingCalls[callId]
            if (pending == null || pending.cancelled) return
            fetchExecutor.execute {
                if (pending.cancelled) return@execute
                val respJson = try {
                    Python.getInstance()
                        .getModule("android_runtime")
                        .callAttr("seanime_fetch", reqJson, pending.extensionId)
                        .toString()
                } catch (err: Exception) {
                    Log.w(TAG, "Python seanime_fetch failed", err)
                    JSONObject(mapOf("error" to (err.message ?: "Erreur réseau WebView"))).toString()
                }
                if (pending.cancelled) return@execute
                try {
                    val obj = JSONObject(respJson)
                    if (obj.optBoolean("verificationRequired", false)) {
                        val vUrl = obj.optString("verificationUrl", "")
                        if (vUrl.isNotBlank()) pending.verificationUrl.compareAndSet(null, vUrl)
                    }
                } catch (_: Exception) {
                }
                val callbackJs =
                    "window.__animelabResolveFetch && window.__animelabResolveFetch(${jsQuote(callId)}, ${jsQuote(reqId)}, ${jsQuote(respJson)});"
                EngineHost.main.post {
                    try {
                        sandboxView?.evaluateJavascript(callbackJs, null)
                    } catch (err: Exception) {
                        Log.w(TAG, "Failed to deliver fetch response to WebView", err)
                    }
                }
            }
        }

        @JavascriptInterface
        fun resolveCall(callId: String, resultJson: String) {
            pendingCalls[callId]?.let { pending ->
                pending.result.set(resultJson)
                pending.latch.countDown()
            }
        }
    }
}
