package com.animan.app

import android.annotation.SuppressLint
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Bundle
import android.os.Message
import android.text.TextUtils
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.webkit.CookieManager
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import java.net.URI
import kotlin.math.roundToInt

/** Source pages never receive a JavaScript bridge or the engine's session token. */
class VerificationActivity : AppCompatActivity() {
    var verificationUrl = ""
        private set
    private lateinit var browser: WebView
    private lateinit var backBtn: TextView
    private lateinit var forwardBtn: TextView
    private lateinit var titleView: TextView
    private lateinit var urlView: TextView
    private lateinit var progressBar: ProgressBar
    private var browserStopped = false
    private var autoCloseEnabled = true
    private var targetHost = ""
    private var initialCookies: Map<String, String> = emptyMap()
    private var pendingAutoClose: Runnable? = null

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).roundToInt()

    private fun isAllowedUri(uri: Uri?): Boolean {
        if (uri == null || uri.scheme != "https") return false
        val host = uri.host?.lowercase() ?: return false
        return host != "127.0.0.1" && host != "localhost" && host != "::1" && uri.userInfo == null
    }

    private fun sameOrSubdomain(candidateUrl: String?): Boolean {
        val candidateHost = try {
            Uri.parse(candidateUrl ?: "").host?.lowercase() ?: ""
        } catch (_: Exception) {
            ""
        }
        if (candidateHost.isEmpty() || targetHost.isEmpty()) return false
        val baseApex = targetHost.split(".").takeLast(2).joinToString(".")
        return candidateHost == targetHost || candidateHost.endsWith(".$baseApex") || candidateHost == baseApex
    }

    private fun parseCookies(raw: String): Map<String, String> {
        if (raw.isBlank()) return emptyMap()
        val out = LinkedHashMap<String, String>()
        for (part in raw.split(";")) {
            val trimmed = part.trim()
            val eq = trimmed.indexOf('=')
            if (eq > 0) {
                out[trimmed.substring(0, eq).trim()] = trimmed.substring(eq + 1).trim()
            }
        }
        return out
    }

    private fun isChallengeTitle(title: String): Boolean {
        val low = title.trim().lowercase()
        if (low.isEmpty()) return true
        return listOf(
            "just a moment",
            "attention required",
            "checking your browser",
            "ddos-guard",
            "un instant",
            "vérification",
            "cloudflare",
            "please wait",
            "access denied",
            "one more step",
        ).any { it in low }
    }

    private fun toolbarIcon(label: String, desc: String, onClick: () -> Unit): TextView =
        TextView(this).apply {
            text = label
            contentDescription = desc
            setTextColor(Color.parseColor("#E2E8F0"))
            textSize = 18f
            gravity = Gravity.CENTER
            minWidth = dp(38)
            minHeight = dp(38)
            setPadding(dp(8), dp(6), dp(8), dp(6))
            setOnClickListener { onClick() }
        }

    private fun updateNavButtons() {
        val canBack = ::browser.isInitialized && !browserStopped && browser.canGoBack()
        val canForward = ::browser.isInitialized && !browserStopped && browser.canGoForward()
        backBtn.alpha = if (canBack) 1.0f else 0.35f
        backBtn.isEnabled = canBack
        forwardBtn.alpha = if (canForward) 1.0f else 0.35f
        forwardBtn.isEnabled = canForward
    }

    private fun scheduleAutoCloseCheck(url: String?, title: String?) {
        pendingAutoClose?.let {
            if (::browser.isInitialized) browser.removeCallbacks(it)
        }
        pendingAutoClose = null
        if (!autoCloseEnabled || browserStopped || !sameOrSubdomain(url)) return
        val cleanTitle = (title ?: "").trim()
        if (isChallengeTitle(cleanTitle)) return

        val current = parseCookies(VerificationBridge.cookies(verificationUrl))
        val clearanceNames = setOf("cf_clearance", "ddg_clearance", "__ddg2_", "sucuri_cloudproxy")
        val hasClearance = current.keys.any { it in clearanceNames }
        val changed = current != initialCookies && current.isNotEmpty()
        if (!hasClearance && !changed) return

        val task = Runnable {
            if (!browserStopped && !isFinishing && !isDestroyed) {
                val stillTitle = (browser.title ?: "").trim()
                if (!isChallengeTitle(stillTitle)) {
                    CookieManager.getInstance().flush()
                    shutdownBrowser()
                    finish()
                }
            }
        }
        pendingAutoClose = task
        browser.postDelayed(task, 1500L)
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        verificationUrl = intent.getStringExtra("url") ?: ""
        if (!VerificationBridge.isOpen(verificationUrl)) { finish(); return }
        val parsed = try { URI(verificationUrl) } catch (_: Exception) { finish(); return }
        if (parsed.scheme != "https" || parsed.host == null || parsed.userInfo != null) { finish(); return }

        targetHost = parsed.host.lowercase()
        autoCloseEnabled = intent.getBooleanExtra(VerificationBridge.EXTRA_AUTO_CLOSE, true)
        initialCookies = parseCookies(VerificationBridge.cookies(verificationUrl))
        VerificationBridge.activity = this

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.parseColor("#0F172A"))
        }

        val toolbar = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setBackgroundColor(Color.parseColor("#1E293B"))
            setPadding(dp(8), dp(8), dp(10), dp(8))
        }

        val closeBtn = toolbarIcon("✕", "Fermer") {
            shutdownBrowser()
            finish()
        }
        backBtn = toolbarIcon("←", "Précédent") {
            if (::browser.isInitialized && browser.canGoBack()) browser.goBack()
        }
        forwardBtn = toolbarIcon("→", "Suivant") {
            if (::browser.isInitialized && browser.canGoForward()) browser.goForward()
        }
        val reloadBtn = toolbarIcon("↻", "Actualiser") {
            if (::browser.isInitialized) browser.reload()
        }

        val infoColumn = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(8), 0, dp(8), 0)
        }
        titleView = TextView(this).apply {
            text = parsed.host
            setTextColor(Color.parseColor("#F8FAFC"))
            textSize = 14f
            setTypeface(null, Typeface.BOLD)
            isSingleLine = true
            ellipsize = TextUtils.TruncateAt.END
        }
        urlView = TextView(this).apply {
            text = verificationUrl
            setTextColor(Color.parseColor("#94A3B8"))
            textSize = 11f
            isSingleLine = true
            ellipsize = TextUtils.TruncateAt.MIDDLE
        }
        infoColumn.addView(titleView)
        infoColumn.addView(urlView)

        val doneBtn = Button(this).apply {
            text = getString(R.string.return_to_animan)
            isAllCaps = false
            setTextColor(Color.WHITE)
            textSize = 13f
            setTypeface(null, Typeface.BOLD)
            background = GradientDrawable().apply {
                setColor(Color.parseColor("#6366F1"))
                cornerRadius = dp(8).toFloat()
            }
            setPadding(dp(12), dp(6), dp(12), dp(6))
            minHeight = dp(36)
            setOnClickListener {
                CookieManager.getInstance().flush()
                shutdownBrowser()
                finish()
            }
        }

        toolbar.addView(closeBtn)
        toolbar.addView(backBtn)
        toolbar.addView(forwardBtn)
        toolbar.addView(reloadBtn)
        toolbar.addView(infoColumn, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        toolbar.addView(doneBtn)

        progressBar = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply {
            max = 100
            progressTintList = ColorStateList.valueOf(Color.parseColor("#6366F1"))
            progressBackgroundTintList = ColorStateList.valueOf(Color.parseColor("#1E293B"))
            visibility = View.GONE
        }

        browser = WebView(this).apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.databaseEnabled = true
            settings.allowFileAccess = false
            settings.allowContentAccess = false
            settings.setSupportMultipleWindows(true)
            settings.javaScriptCanOpenWindowsAutomatically = true
            settings.userAgentString = intent.getStringExtra("user_agent") ?: VerificationBridge.userAgent()
            webChromeClient = object : WebChromeClient() {
                override fun onProgressChanged(view: WebView?, newProgress: Int) {
                    progressBar.progress = newProgress
                    progressBar.visibility = if (newProgress in 1..99) View.VISIBLE else View.GONE
                }

                override fun onReceivedTitle(view: WebView?, title: String?) {
                    if (!title.isNullOrBlank()) titleView.text = title
                }

                override fun onCreateWindow(
                    view: WebView?,
                    isDialog: Boolean,
                    isUserGesture: Boolean,
                    resultMsg: Message?,
                ): Boolean {
                    val ctx = view?.context ?: return false
                    val temp = WebView(ctx)
                    temp.webViewClient = object : WebViewClient() {
                        override fun shouldOverrideUrlLoading(v: WebView, request: WebResourceRequest): Boolean {
                            val popupUri = request.url
                            if (isAllowedUri(popupUri) && ::browser.isInitialized && !browserStopped) {
                                browser.loadUrl(popupUri.toString())
                            }
                            temp.stopLoading()
                            temp.post { temp.destroy() }
                            return true
                        }
                    }
                    val transport = resultMsg?.obj as? WebView.WebViewTransport ?: run {
                        temp.destroy()
                        return false
                    }
                    transport.webView = temp
                    resultMsg.sendToTarget()
                    return true
                }
            }
            webViewClient = object : WebViewClient() {
                override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                    return !isAllowedUri(request.url)
                }

                override fun onPageFinished(view: WebView?, url: String?) {
                    if (browserStopped) return
                    val current = url ?: ""
                    if (current.startsWith("https://")) {
                        VerificationBridge.updateCurrentUrl(current)
                        urlView.text = current
                    }
                    if (!view?.title.isNullOrBlank()) {
                        titleView.text = view?.title
                    }
                    CookieManager.getInstance().flush()
                    updateNavButtons()
                    scheduleAutoCloseCheck(current, view?.title)
                }
            }
        }

        CookieManager.getInstance().setAcceptCookie(true)
        CookieManager.getInstance().setAcceptThirdPartyCookies(browser, true)

        root.addView(toolbar, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT))
        root.addView(progressBar, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(3)))
        root.addView(browser, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))

        setContentView(root)
        updateNavButtons()
        browser.loadUrl(verificationUrl)
    }

    fun shutdownBrowser() {
        if (::browser.isInitialized && !browserStopped) {
            browserStopped = true
            pendingAutoClose?.let { browser.removeCallbacks(it) }
            pendingAutoClose = null
            browser.stopLoading()
            CookieManager.getInstance().flush()
            (browser.parent as? ViewGroup)?.removeView(browser)
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
