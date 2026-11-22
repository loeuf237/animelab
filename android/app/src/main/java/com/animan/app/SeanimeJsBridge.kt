package com.animan.app

import android.annotation.SuppressLint
import android.util.Log
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import com.chaquo.python.Python
import org.json.JSONObject
import java.io.ByteArrayInputStream
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CountDownLatch
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
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

    @Volatile
    private var sandboxView: WebView? = null

    @Volatile
    private var pendingPageLatch: CountDownLatch? = null

    private data class PendingCall(
        val latch: CountDownLatch = CountDownLatch(1),
        val result: AtomicReference<String?> = AtomicReference(null),
    )

    fun isAvailable(): Boolean =
        try {
            EngineHost.context
            true
        } catch (_: UninitializedPropertyAccessException) {
            false
        }

    fun validateSyntax(shimJs: String, providerJs: String): String {
        synchronized(execLock) {
            return try {
                loadBlankPageAndWait(15_000L)
                val script = buildString {
                    append(shimJs)
                    append("\n;return (function(){ try { globalThis.__seanimeCompile(")
                    append(jsQuote(providerJs))
                    append("); return 'ok'; } catch(e) { return 'error:' + (e && e.message ? e.message : String(e)); } })();")
                }
                val callId = UUID.randomUUID().toString()
                val pending = PendingCall()
                pendingCalls[callId] = pending
                try {
                    runJs("(function(){ var __r = (function(){\n$script\n})(); window.__animelabSeanimeBridge.resolveCall(${jsQuote(callId)}, String(__r)); })();")
                    if (!pending.latch.await(15_000L, TimeUnit.MILLISECONDS)) {
                        return "error:Timeout lors de la validation WebView"
                    }
                    pending.result.get() ?: "error:Réponse vide de WebView"
                } finally {
                    pendingCalls.remove(callId)
                }
            } catch (err: Exception) {
                Log.w(TAG, "validateSyntax failed", err)
                "error:${err.message ?: err.javaClass.simpleName}"
            }
        }
    }

    fun invoke(invocationJson: String): String {
        synchronized(execLock) {
            val params = JSONObject(invocationJson)
            val shim = params.getString("shim")
            val code = params.getString("code")
            val method = params.getString("method")
            val argsJson = params.optString("argsJson", "[]")
            val userConfigJson = params.optString("userConfigJson", "{}")
            val defaultsJson = params.optString("defaultsJson", "{}")
            val storeJson = params.optString("storeJson", "{}")
            val timeoutMs = params.optLong("timeoutMs", 30_000L).coerceIn(3_000L, 120_000L)

            val callId = UUID.randomUUID().toString()
            val pending = PendingCall()
            pendingCalls[callId] = pending

            return try {
                loadBlankPageAndWait(10_000L)
                val bootstrap = buildString {
                    append("(function(){\n")
                    append("  var __pendingFetches = Object.create(null);\n")
                    append("  var __seq = 0;\n")
                    append("  window.__animelabResolveFetch = function(reqId, respJson) {\n")
                    append("    var h = __pendingFetches[reqId];\n")
                    append("    if (h) { delete __pendingFetches[reqId]; h.resolve(respJson); }\n")
                    append("  };\n")
                    append("  globalThis.__seanimeHostFetch = function(reqJsonStr) {\n")
                    append("    return new Promise(function(resolve) {\n")
                    append("      var reqId = 'r' + (++__seq);\n")
                    append("      __pendingFetches[reqId] = { resolve: resolve };\n")
                    append("      window.__animelabSeanimeBridge.fetch(reqId, String(reqJsonStr || '{}'));\n")
                    append("    });\n")
                    append("  };\n")
                    append(shim)
                    append("\n  Promise.resolve().then(function() {\n")
                    append("    globalThis.__seanimeCompile(${jsQuote(code)});\n")
                    append("    return globalThis.__seanimeInvoke(")
                    append("${jsQuote(method)}, ${jsQuote(argsJson)}, ${jsQuote(userConfigJson)}, ${jsQuote(defaultsJson)}, ${jsQuote(storeJson)}")
                    append(");\n")
                    append("  }).then(function(resJson) {\n")
                    append("    window.__animelabSeanimeBridge.resolveCall(${jsQuote(callId)}, String(resJson));\n")
                    append("  }).catch(function(err) {\n")
                    append("    var payload = JSON.stringify({ ok: false, error: err && err.message ? String(err.message) : String(err), stack: err && err.stack ? String(err.stack) : '', store: {}, logs: [] });\n")
                    append("    window.__animelabSeanimeBridge.resolveCall(${jsQuote(callId)}, payload);\n")
                    append("  });\n")
                    append("})();")
                }
                runJs(bootstrap)
                if (!pending.latch.await(timeoutMs, TimeUnit.MILLISECONDS)) {
                    return JSONObject(
                        mapOf(
                            "ok" to false,
                            "error" to "Délai d'exécution WebView Seanime dépassé (${timeoutMs / 1000}s)",
                            "store" to emptyMap<String, Any>(),
                            "logs" to emptyList<String>(),
                        )
                    ).toString()
                }
                pending.result.get() ?: JSONObject(
                    mapOf(
                        "ok" to false,
                        "error" to "Réponse vide du moteur WebView Seanime",
                        "store" to emptyMap<String, Any>(),
                        "logs" to emptyList<String>(),
                    )
                ).toString()
            } catch (err: Exception) {
                Log.w(TAG, "invoke failed", err)
                JSONObject(
                    mapOf(
                        "ok" to false,
                        "error" to (err.message ?: err.javaClass.simpleName),
                        "store" to emptyMap<String, Any>(),
                        "logs" to emptyList<String>(),
                    )
                ).toString()
            } finally {
                pendingCalls.remove(callId)
            }
        }
    }

    @SuppressLint("SetJavaScriptEnabled", "AddJavascriptInterface")
    private fun ensureWebView(): WebView {
        sandboxView?.let { return it }
        val context = EngineHost.context.applicationContext
        val view = WebView(context)
        view.settings.javaScriptEnabled = true
        view.settings.domStorageEnabled = false
        view.settings.allowFileAccess = false
        view.settings.allowContentAccess = false
        view.settings.blockNetworkLoads = true
        view.addJavascriptInterface(HostJsBridge(), "__animelabSeanimeBridge")
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
                pendingPageLatch?.countDown()
            }
        }
        sandboxView = view
        return view
    }

    private fun loadBlankPageAndWait(timeoutMs: Long) {
        val latch = CountDownLatch(1)
        pendingPageLatch = latch
        EngineHost.main.post {
            try {
                val view = ensureWebView()
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
        pendingPageLatch = null
    }

    private fun runJs(script: String) {
        EngineHost.main.post {
            try {
                ensureWebView().evaluateJavascript(script, null)
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
        fun fetch(reqId: String, reqJson: String) {
            fetchExecutor.execute {
                val respJson = try {
                    Python.getInstance()
                        .getModule("android_runtime")
                        .callAttr("seanime_fetch", reqJson)
                        .toString()
                } catch (err: Exception) {
                    Log.w(TAG, "Python seanime_fetch failed", err)
                    JSONObject(mapOf("error" to (err.message ?: "Erreur réseau WebView"))).toString()
                }
                val callbackJs =
                    "window.__animelabResolveFetch && window.__animelabResolveFetch(${jsQuote(reqId)}, ${jsQuote(respJson)});"
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
