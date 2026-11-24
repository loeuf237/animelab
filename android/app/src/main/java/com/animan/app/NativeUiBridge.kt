package com.animan.app

import android.app.Activity
import android.content.ContentValues
import android.content.Context
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.os.Looper
import android.provider.MediaStore
import android.view.HapticFeedbackConstants
import android.view.View
import android.view.WindowManager
import android.webkit.JavascriptInterface
import android.webkit.WebView
import android.widget.Toast
import androidx.core.view.WindowInsetsControllerCompat
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

class NativeUiBridge(
    private val activity: Activity,
    private val webView: WebView,
    private val rootView: View,
) {
    @Volatile
    var keepScreenOnRequested: Boolean = false
        private set

    companion object {
        const val PREFS_NAME = "animelab_ui"
        const val KEY_STATUS_COLOR = "status_color"
        const val KEY_NAV_COLOR = "nav_color"
        const val KEY_LIGHT_ICONS = "light_icons"

        private val HEX_COLOR = Regex("^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")

        fun isLocalOrigin(url: String?): Boolean {
            if (url.isNullOrBlank()) return false
            val uri = Uri.parse(url)
            return uri.scheme == "http" && uri.host == "127.0.0.1" && uri.port == EngineHost.port
        }

        fun applySavedChrome(
            activity: Activity,
            rootView: View,
            webView: WebView? = null,
            loadingLayout: View? = null,
            loadingTitle: android.widget.TextView? = null,
            loadingStatus: android.widget.TextView? = null,
        ) {
            val prefs = activity.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            val statusHex = prefs.getString(KEY_STATUS_COLOR, "#0b1517") ?: "#0b1517"
            val navHex = prefs.getString(KEY_NAV_COLOR, "#0f1b1e") ?: "#0f1b1e"
            val lightIcons = prefs.getBoolean(KEY_LIGHT_ICONS, false)
            applyColors(
                activity,
                rootView,
                statusHex,
                navHex,
                lightIcons,
                webView,
                loadingLayout,
                loadingTitle,
                loadingStatus,
            )
        }

        private fun applyColors(
            activity: Activity,
            rootView: View,
            statusHex: String,
            navHex: String,
            lightIcons: Boolean,
            webView: WebView? = null,
            loadingLayout: View? = null,
            loadingTitle: android.widget.TextView? = null,
            loadingStatus: android.widget.TextView? = null,
        ) {
            val statusColor = Color.parseColor(statusHex)
            val navColor = Color.parseColor(navHex)
            val window = activity.window
            @Suppress("DEPRECATION")
            run {
                window.statusBarColor = statusColor
                window.navigationBarColor = navColor
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                window.isNavigationBarContrastEnforced = false
                window.isStatusBarContrastEnforced = false
            }
            window.decorView.setBackgroundColor(statusColor)
            rootView.setBackgroundColor(statusColor)
            webView?.setBackgroundColor(statusColor)
            WindowInsetsControllerCompat(window, window.decorView).apply {
                isAppearanceLightStatusBars = lightIcons
                isAppearanceLightNavigationBars = lightIcons
            }
            loadingLayout?.setBackgroundColor(statusColor)
            when {
                lightIcons -> {
                    loadingTitle?.setTextColor(Color.parseColor("#15282b"))
                    loadingStatus?.setTextColor(Color.parseColor("#465f64"))
                }
                statusHex.equals("#000000", ignoreCase = true) -> {
                    loadingTitle?.setTextColor(Color.parseColor("#ffffff"))
                    loadingStatus?.setTextColor(Color.parseColor("#b0b0b0"))
                }
                statusHex.equals("#1b1b1f", ignoreCase = true) -> {
                    loadingTitle?.setTextColor(Color.parseColor("#e3e2e6"))
                    loadingStatus?.setTextColor(Color.parseColor("#c5c6d0"))
                }
                else -> {
                    loadingTitle?.setTextColor(Color.parseColor("#dce7e9"))
                    loadingStatus?.setTextColor(Color.parseColor("#afbec1"))
                }
            }
        }
    }

    @JavascriptInterface
    fun syncSystemBars(statusHex: String?, navHex: String?, lightIcons: Boolean) {
        if (statusHex == null || navHex == null) return
        if (!HEX_COLOR.matches(statusHex) || !HEX_COLOR.matches(navHex)) return
        activity.runOnUiThread {
            if (activity.isDestroyed || activity.isFinishing) return@runOnUiThread
            if (!isLocalOrigin(webView.url)) return@runOnUiThread
            try {
                applyColors(activity, rootView, statusHex, navHex, lightIcons, webView)
                activity.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit()
                    .putString(KEY_STATUS_COLOR, statusHex)
                    .putString(KEY_NAV_COLOR, navHex)
                    .putBoolean(KEY_LIGHT_ICONS, lightIcons)
                    .apply()
            } catch (_: Exception) {
            }
        }
    }

    @JavascriptInterface
    fun haptic(kind: String?) {
        activity.runOnUiThread {
            if (activity.isDestroyed || activity.isFinishing) return@runOnUiThread
            if (!isLocalOrigin(webView.url)) return@runOnUiThread
            val code = when (kind) {
                "confirm" -> if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) HapticFeedbackConstants.CONFIRM else HapticFeedbackConstants.CONTEXT_CLICK
                "impact" -> HapticFeedbackConstants.CONTEXT_CLICK
                else -> HapticFeedbackConstants.CLOCK_TICK
            }
            webView.performHapticFeedback(code)
        }
    }

    @JavascriptInterface
    fun setKeepScreenOn(enabled: Boolean) {
        activity.runOnUiThread {
            if (activity.isDestroyed || activity.isFinishing) return@runOnUiThread
            if (!isLocalOrigin(webView.url)) return@runOnUiThread
            keepScreenOnRequested = enabled
            if (enabled) {
                activity.window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            } else if (activity !is MainActivity || !activity.isInFullscreenVideo()) {
                activity.window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            }
        }
    }

    @JavascriptInterface
    fun getPlatformInfo(): String {
        return JSONObject()
            .put("os", "android")
            .put("runtime", "android")
            .put("sdk", Build.VERSION.SDK_INT)
            .put("edgeToEdge", true)
            .toString()
    }

    private fun checkLocalOriginSync(): Boolean {
        if (activity.isDestroyed || activity.isFinishing) return false
        if (Looper.myLooper() == Looper.getMainLooper()) {
            return isLocalOrigin(webView.url)
        }
        var allowed = false
        val latch = CountDownLatch(1)
        activity.runOnUiThread {
            try {
                if (!activity.isDestroyed && !activity.isFinishing) {
                    allowed = isLocalOrigin(webView.url)
                }
            } finally {
                latch.countDown()
            }
        }
        return try {
            latch.await(2, TimeUnit.SECONDS) && allowed
        } catch (_: InterruptedException) {
            false
        }
    }

    @JavascriptInterface
    fun exportDiagnostics(jsonPayload: String?): String {
        if (jsonPayload.isNullOrBlank() || jsonPayload.length > 2 * 1024 * 1024) return ""
        if (!checkLocalOriginSync()) return ""
        return try {
            val stamp = SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).apply {
                timeZone = TimeZone.getTimeZone("UTC")
            }.format(Date())
            val fileName = "animelab-diagnostics-$stamp.json"
            val values = ContentValues().apply {
                put(MediaStore.Downloads.DISPLAY_NAME, fileName)
                put(MediaStore.Downloads.MIME_TYPE, "application/json")
                put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/" + StorageAccess.MEDIA_DIRECTORY)
                put(MediaStore.Downloads.IS_PENDING, 1)
            }
            val resolver = activity.contentResolver
            val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values) ?: return ""
            try {
                resolver.openOutputStream(uri)?.use { stream ->
                    stream.write(jsonPayload.toByteArray(Charsets.UTF_8))
                } ?: run {
                    resolver.delete(uri, null, null)
                    return ""
                }
                val done = ContentValues().apply { put(MediaStore.Downloads.IS_PENDING, 0) }
                resolver.update(uri, done, null, null)
                val dest = "${StorageAccess.DEFAULT_DESTINATION}/$fileName"
                activity.runOnUiThread {
                    if (!activity.isDestroyed && !activity.isFinishing) {
                        Toast.makeText(activity, dest, Toast.LENGTH_LONG).show()
                    }
                }
                dest
            } catch (_: Exception) {
                try { resolver.delete(uri, null, null) } catch (_: Exception) { }
                ""
            }
        } catch (_: Exception) {
            ""
        }
    }
}
