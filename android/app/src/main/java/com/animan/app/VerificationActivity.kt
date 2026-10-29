package com.animan.app

import android.annotation.SuppressLint
import android.os.Bundle
import android.webkit.WebView
import android.webkit.WebViewClient
import android.webkit.WebResourceRequest
import android.webkit.CookieManager
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import java.net.URI

/** Source pages never receive a JavaScript bridge or the engine's session token. */
class VerificationActivity : AppCompatActivity() {
    var verificationUrl = ""
        private set
    private lateinit var browser: WebView
    private var browserStopped = false
    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        verificationUrl = intent.getStringExtra("url") ?: ""
        if (!VerificationBridge.isOpen(verificationUrl)) { finish(); return }
        val parsed = try { URI(verificationUrl) } catch (_: Exception) { finish(); return }
        if (parsed.scheme != "https" || parsed.host == null || parsed.userInfo != null) { finish(); return }
        VerificationBridge.activity = this
        val layout = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        layout.addView(TextView(this).apply { text = parsed.host; setPadding(16, 12, 16, 12) })
        browser = WebView(this).apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.allowFileAccess = false
            settings.allowContentAccess = false
            settings.userAgentString = intent.getStringExtra("user_agent") ?: settings.userAgentString
            webViewClient = object : WebViewClient() {
                override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                    val uri = request.url
                    return uri.scheme != "https" || uri.host == "127.0.0.1" || uri.host == "localhost" || uri.host == "::1"
                }
            }
        }
        layout.addView(browser, LinearLayout.LayoutParams(-1, 0, 1f))
        layout.addView(Button(this).apply {
            text = getString(R.string.return_to_animan)
            setOnClickListener { shutdownBrowser(); finish() }
        })
        setContentView(layout)
        browser.loadUrl(verificationUrl)
    }
    fun shutdownBrowser() {
        if (::browser.isInitialized && !browserStopped) {
            browserStopped = true
            browser.stopLoading()
            CookieManager.getInstance().flush()
            (browser.parent as? android.view.ViewGroup)?.removeView(browser)
            browser.destroy()
        }
    }
    override fun onDestroy() {
        if (VerificationBridge.activity === this) VerificationBridge.activity = null
        shutdownBrowser()
        if (!isChangingConfigurations) VerificationBridge.didClose(verificationUrl)
        super.onDestroy()
    }
}
