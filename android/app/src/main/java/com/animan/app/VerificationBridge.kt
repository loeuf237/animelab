package com.animan.app

import android.content.Intent
import android.webkit.CookieManager
import org.json.JSONArray
import java.util.concurrent.atomic.AtomicReference
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

object VerificationBridge {
    @Volatile var activity: VerificationActivity? = null
    @Volatile private var openedUrl: String? = null
    @JvmStatic fun open(url: String, userAgent: String) {
        openedUrl = url
        EngineHost.main.post {
            try {
                EngineHost.context.startActivity(Intent(EngineHost.context, VerificationActivity::class.java)
                    .putExtra("url", url).putExtra("user_agent", userAgent).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            } catch (_: Exception) { didClose(url) }
        }
    }
    @JvmStatic fun isOpen(url: String): Boolean = openedUrl == url
    fun didClose(url: String) { if (openedUrl == url) openedUrl = null }
    @JvmStatic fun cookies(url: String): String {
        val ready = CountDownLatch(1)
        var result = ""
        EngineHost.main.post {
            try { result = CookieManager.getInstance().getCookie(url) ?: "" }
            finally { ready.countDown() }
        }
        check(ready.await(5, TimeUnit.SECONDS)) { "CookieManager did not respond" }
        return result
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
                        if (remaining == 0) { manager.flush(); ready.countDown() }
                    }
                }
            } catch (error: Exception) { failure.set(error); ready.countDown() }
        }
        check(ready.await(5, TimeUnit.SECONDS)) { "CookieManager did not finish updating cookies" }
        failure.get()?.let { throw it }
    }
    @JvmStatic fun close(url: String) {
        val ready = CountDownLatch(1)
        EngineHost.main.post {
            try {
                activity?.let { if (it.verificationUrl == url) { it.shutdownBrowser(); it.finish() } }
                didClose(url)
            } finally { ready.countDown() }
        }
        check(ready.await(5, TimeUnit.SECONDS)) { "Verification browser did not stop" }
    }
}
