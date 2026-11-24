package com.animan.app

import android.content.Intent
import android.os.Looper
import android.webkit.CookieManager
import android.webkit.WebSettings
import org.json.JSONArray
import java.net.URI
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

object VerificationBridge {
    const val EXTRA_AUTO_CLOSE = "auto_close"

    private fun <T> runOnMainSync(timeoutError: String, block: () -> T): T {
        if (Looper.myLooper() == Looper.getMainLooper()) {
            return block()
        }
        val ready = CountDownLatch(1)
        val result = AtomicReference<T?>(null)
        val failure = AtomicReference<Throwable?>(null)
        EngineHost.main.post {
            try {
                result.set(block())
            } catch (err: Throwable) {
                failure.set(err)
            } finally {
                ready.countDown()
            }
        }
        check(ready.await(5, TimeUnit.SECONDS)) { timeoutError }
        failure.get()?.let { throw it }
        @Suppress("UNCHECKED_CAST")
        return result.get() as T
    }

    @JvmStatic fun userAgent(): String =
        runOnMainSync("WebView did not provide its user agent") {
            val raw = WebSettings.getDefaultUserAgent(EngineHost.context)
            raw.replace("; wv)", ")").replace("Version/4.0 ", "")
        }

    @Volatile var activity: VerificationActivity? = null
    @Volatile private var openedUrl: String? = null
    private val currentUrlRef = AtomicReference("")

    @JvmStatic fun updateCurrentUrl(url: String) {
        if (url.isNotBlank()) currentUrlRef.set(url)
    }

    @JvmStatic fun open(url: String, userAgent: String) {
        open(url, userAgent, true)
    }

    @JvmStatic fun open(url: String, userAgent: String, autoClose: Boolean) {
        openedUrl = url
        currentUrlRef.set(url)
        EngineHost.main.post {
            try {
                EngineHost.context.startActivity(
                    Intent(EngineHost.context, VerificationActivity::class.java)
                        .putExtra("url", url)
                        .putExtra("user_agent", userAgent)
                        .putExtra(EXTRA_AUTO_CLOSE, autoClose)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                )
            } catch (_: Exception) {
                didClose(url)
            }
        }
    }

    @JvmStatic fun isOpen(url: String): Boolean = openedUrl == url

    fun didClose(url: String) {
        if (openedUrl == url) openedUrl = null
    }

    private fun apexUrl(targetUrl: String): String? =
        try {
            val host = URI(targetUrl).host?.lowercase() ?: ""
            val labels = host.split(".").filter { it.isNotBlank() }
            if (labels.size >= 2) "https://${labels.takeLast(2).joinToString(".")}/" else null
        } catch (_: Exception) {
            null
        }

    @JvmStatic fun cookies(url: String): String {
        val current = currentUrlRef.get()
        return runOnMainSync("CookieManager did not respond") {
            val manager = CookieManager.getInstance()
            manager.flush()
            val urls = linkedSetOf<String>()
            apexUrl(url)?.let { urls.add(it) }
            if (current.isNotBlank()) urls.add(current)
            urls.add(url)
            val merged = LinkedHashMap<String, String>()
            for (candidate in urls) {
                val raw = manager.getCookie(candidate) ?: continue
                for (segment in raw.split(";")) {
                    val trimmed = segment.trim()
                    if (trimmed.isEmpty()) continue
                    val name = trimmed.substringBefore("=").trim()
                    if (name.isNotEmpty()) merged[name] = trimmed
                }
            }
            merged.values.joinToString("; ")
        }
    }

    /** Applied before source navigation; callbacks finish before Python continues. */
    @JvmStatic fun setCookies(url: String, headersJson: String) {
        val ready = CountDownLatch(1)
        val failure = AtomicReference<Exception?>(null)
        EngineHost.main.post {
            try {
                val headers = JSONArray(headersJson)
                val manager = CookieManager.getInstance()
                manager.setAcceptCookie(true)
                var remaining = headers.length()
                if (remaining == 0) ready.countDown()
                for (index in 0 until headers.length()) {
                    manager.setCookie(url, headers.getString(index)) { accepted ->
                        if (!accepted) failure.set(IllegalStateException("WebView refused a source cookie"))
                        remaining -= 1
                        if (remaining == 0) {
                            manager.flush()
                            ready.countDown()
                        }
                    }
                }
            } catch (error: Exception) {
                failure.set(error)
                ready.countDown()
            }
        }
        check(ready.await(5, TimeUnit.SECONDS)) { "CookieManager did not finish updating cookies" }
        failure.get()?.let { throw it }
    }

    @JvmStatic fun close(url: String) {
        runOnMainSync("Verification browser did not stop") {
            activity?.let {
                if (it.verificationUrl == url) {
                    it.shutdownBrowser()
                    it.finish()
                }
            }
            didClose(url)
        }
    }
}
