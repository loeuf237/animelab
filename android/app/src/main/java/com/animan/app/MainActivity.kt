package com.animan.app

import android.Manifest
import android.annotation.SuppressLint
import android.content.Intent
import android.content.pm.ActivityInfo
import android.graphics.Bitmap
import android.net.Uri
import android.app.DownloadManager
import android.provider.Settings
import android.widget.Toast
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.FrameLayout
import android.os.Build
import android.os.Bundle
import android.view.View
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.core.view.WindowCompat
import android.webkit.*
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.animan.app.databinding.ActivityMainBinding
import kotlinx.coroutines.*
import java.net.HttpURLConnection
import java.net.Proxy
import java.net.URL

class MainActivity : AppCompatActivity() {
    override fun onResume() {
        super.onResume()
        EngineHost.attachActivity(this)
        ExtensionBridge.resumePendingInstalls()
    }

    override fun onPause() {
        EngineHost.detachActivity(this)
        super.onPause()
    }
    private lateinit var binding: ActivityMainBinding
    private var customView: View? = null
    private var customCallback: WebChromeClient.CustomViewCallback? = null
    private var savedCutoutMode: Int? = null
    private var fileCallback: ValueCallback<Array<Uri>>? = null
    private var connectJob: Job? = null
    private lateinit var nativeUiBridge: NativeUiBridge

    internal fun isInFullscreenVideo(): Boolean = customView != null

    private fun isKeepScreenOnRequested(): Boolean =
        ::nativeUiBridge.isInitialized && nativeUiBridge.keepScreenOnRequested
    private val backCallback = object : OnBackPressedCallback(true) {
        override fun handleOnBackPressed() {
            if (customView != null) {
                binding.webView.webChromeClient?.onHideCustomView()
                return
            }
            binding.webView.evaluateJavascript(
                "(function(){return window.__animelabHandleBack ? Boolean(window.__animelabHandleBack()) : false;})()"
            ) { result ->
                if (result == "true") return@evaluateJavascript
                if (binding.webView.canGoBack()) {
                    binding.webView.goBack()
                } else {
                    isEnabled = false
                    onBackPressedDispatcher.onBackPressed()
                    isEnabled = true
                }
            }
        }
    }
    private val filePicker = registerForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        fileCallback?.onReceiveValue(uris.toTypedArray()); fileCallback = null
    }
    private val notificationPermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { }
    private val directoryPicker = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        lifecycleScope.launch {
            try {
                if (result.resultCode == RESULT_OK) {
                    val data = requireNotNull(result.data)
                    withContext(Dispatchers.IO) { StorageAccess.select(requireNotNull(data.data), data.flags) }
                }
            } catch (cancelled: CancellationException) { throw cancelled }
            catch (failure: Exception) {
                StorageAccess.error(failure.message ?: getString(R.string.storage_permission_error))
                Toast.makeText(this@MainActivity, R.string.storage_permission_error, Toast.LENGTH_LONG).show()
            } finally { StorageAccess.selectionPending = false }
        }
    }
    private val permissionAction: (String) -> Unit = { action ->
        try {
            when (action) {
                "choose_directory" -> directoryPicker.launch(Intent(Intent.ACTION_OPEN_DOCUMENT_TREE).apply {
                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION or Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION)
                })
                "notifications" -> if (Build.VERSION.SDK_INT >= 33) notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
                    else startActivity(Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, packageName))
                "app_settings" -> startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName")))
                "install_apps" -> startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:$packageName")))
                "battery" -> startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
                "open_downloads" -> {
                    val uri = StorageAccess.treeUri()
                    if (uri == null) startActivity(Intent(DownloadManager.ACTION_VIEW_DOWNLOADS))
                    else startActivity(Intent(Intent.ACTION_VIEW).setDataAndType(StorageAccess.directory(uri), "vnd.android.document/directory").addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION))
                }
            }
        } catch (failure: Exception) {
            StorageAccess.selectionPending = false
            StorageAccess.error(failure.message ?: getString(R.string.storage_permission_error))
            Toast.makeText(this, R.string.storage_permission_error, Toast.LENGTH_LONG).show()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        NativeUiBridge.applySavedChrome(
            this,
            binding.root,
            binding.webView,
            binding.loadingLayout,
            binding.loadingTitle,
            binding.loadingStatus,
        )
        ViewCompat.setOnApplyWindowInsetsListener(binding.root) { view, insets ->
            if (customView != null) {
                view.setPadding(0, 0, 0, 0)
            } else {
                val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout())
                view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            }
            insets
        }
        onBackPressedDispatcher.addCallback(this, backCallback)
        setupWebView()
        EngineHost.attachActivity(this)
        EngineHost.start(applicationContext, BuildConfig.DEBUG && intent.getBooleanExtra("test_mode", false))
        StorageAccess.actionHandler = permissionAction
        DownloadService.update(applicationContext)
        binding.retryButton.setOnClickListener { connect() }
        connect()
    }

    private fun connect() {
        connectJob?.cancel()
        binding.loadingLayout.visibility = View.VISIBLE
        binding.loadingStatus.text = getString(R.string.starting_engine)
        binding.retryButton.visibility = View.GONE
        connectJob = lifecycleScope.launch {
            val deadline = System.nanoTime() + java.util.concurrent.TimeUnit.MINUTES.toNanos(3)
            while (System.nanoTime() < deadline && EngineHost.error == null) {
                if (!EngineHost.ready) { delay(500); continue }
                val reachable = withContext(Dispatchers.IO) {
                    try {
                        val conn = URL(EngineHost.baseUrl + "/manifest.json").openConnection(Proxy.NO_PROXY) as HttpURLConnection
                        try {
                            conn.connectTimeout = 500; conn.readTimeout = 500
                            conn.setRequestProperty("X-Animan-Session", EngineHost.token)
                            conn.responseCode == 200
                        } finally { conn.disconnect() }
                    } catch (_: Exception) { false }
                }
                if (reachable) {
                    val cookies = CookieManager.getInstance()
                    cookies.setAcceptCookie(true)
                    cookies.setCookie(EngineHost.baseUrl, "animan_android_session=${EngineHost.token}; Path=/; HttpOnly; SameSite=Strict") {
                        if (!isDestroyed && !isFinishing) binding.webView.loadUrl(EngineHost.baseUrl + "/spa/")
                    }
                    return@launch
                }
                delay(500)
            }
            binding.loadingStatus.text = getString(R.string.engine_error, EngineHost.error ?: getString(R.string.engine_timeout))
            binding.retryButton.visibility = View.VISIBLE
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun setupWebView() {
        binding.webView.apply {
            overScrollMode = View.OVER_SCROLL_NEVER
            isVerticalScrollBarEnabled = false
            isHorizontalScrollBarEnabled = false
        }
        nativeUiBridge = NativeUiBridge(this, binding.webView, binding.root)
        binding.webView.addJavascriptInterface(nativeUiBridge, "AnimeLabAndroid")
        binding.webView.settings.apply {
            javaScriptEnabled = true; domStorageEnabled = true
            allowFileAccess = false; allowContentAccess = true
            mediaPlaybackRequiresUserGesture = false
            mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
            setSupportMultipleWindows(true)
        }
        binding.webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                if (!request.isForMainFrame) return false
                val uri = request.url
                if (uri.scheme == "http" && uri.host == "127.0.0.1" && uri.port == EngineHost.port) return false
                if (uri.scheme in listOf("http", "https")) {
                    try { startActivity(Intent(Intent.ACTION_VIEW, uri)) } catch (_: Exception) { }
                }
                return true
            }
            override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) { binding.progressBar.visibility = View.VISIBLE }
            override fun onPageFinished(view: WebView?, url: String?) {
                binding.progressBar.visibility = View.GONE; binding.loadingLayout.visibility = View.GONE
            }
            override fun onReceivedError(view: WebView?, request: WebResourceRequest?, error: WebResourceError?) {
                if (request?.isForMainFrame == true) {
                    val detail = error?.description?.toString() ?: "webview_error"
                    CrashReporter.recordWebViewError(applicationContext, "webview_error", detail)
                    binding.loadingLayout.visibility = View.VISIBLE
                    binding.loadingStatus.text = getString(R.string.engine_error, error?.description ?: "")
                    binding.retryButton.visibility = View.VISIBLE
                }
            }
            override fun onRenderProcessGone(view: WebView?, detail: RenderProcessGoneDetail?): Boolean {
                val reason = if (detail?.didCrash() == true) "crashed" else "killed"
                CrashReporter.recordWebViewError(applicationContext, "webview_render_gone", reason)
                binding.loadingLayout.visibility = View.VISIBLE
                binding.loadingStatus.text = getString(R.string.engine_error, reason)
                binding.retryButton.visibility = View.VISIBLE
                return true
            }
        }
        binding.webView.webChromeClient = object : WebChromeClient() {
            override fun onProgressChanged(view: WebView?, progress: Int) { binding.progressBar.progress = progress }
            override fun onShowFileChooser(webView: WebView?, callback: ValueCallback<Array<Uri>>?, params: FileChooserParams?): Boolean {
                fileCallback?.onReceiveValue(null); fileCallback = callback
                val accepted = params?.acceptTypes?.filter { it.isNotBlank() }?.map {
                    if (it.startsWith(".")) MimeTypeMap.getSingleton().getMimeTypeFromExtension(it.drop(1)) ?: "*/*" else it
                }?.toTypedArray()
                filePicker.launch(if (accepted.isNullOrEmpty()) arrayOf("*/*") else accepted)
                return true
            }
            override fun onCreateWindow(view: WebView?, dialog: Boolean, gesture: Boolean, result: android.os.Message?): Boolean {
                val hit = view?.hitTestResult?.extra
                if (hit != null) {
                    val uri = Uri.parse(hit)
                    if (uri.scheme !in listOf("http", "https")) return false
                    try { startActivity(Intent(Intent.ACTION_VIEW, uri)) } catch (_: Exception) { }
                    return false
                }
                val transport = result?.obj as? WebView.WebViewTransport ?: return false
                val context = view?.context ?: return false
                val tempWebView = WebView(context)
                tempWebView.webViewClient = object : WebViewClient() {
                    override fun shouldOverrideUrlLoading(w: WebView?, request: WebResourceRequest?): Boolean {
                        val uri = request?.url
                        if (uri != null && uri.scheme in listOf("http", "https")) {
                            try { startActivity(Intent(Intent.ACTION_VIEW, uri)) } catch (_: Exception) { }
                        }
                        w?.destroy()
                        return true
                    }
                    override fun onPageStarted(w: WebView?, url: String?, favicon: Bitmap?) {
                        w?.stopLoading()
                        w?.destroy()
                    }
                }
                transport.webView = tempWebView
                result.sendToTarget()
                return true
            }
            override fun onShowCustomView(view: View?, callback: CustomViewCallback?) {
                if (customView != null || view == null) { callback?.onCustomViewHidden(); return }
                customView = view; customCallback = callback
                binding.webView.visibility = View.GONE
                binding.customViewContainer.visibility = View.VISIBLE
                binding.customViewContainer.addView(
                    view,
                    FrameLayout.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT,
                        ViewGroup.LayoutParams.MATCH_PARENT,
                    ),
                )
                requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE
                window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                    savedCutoutMode = window.attributes.layoutInDisplayCutoutMode
                    window.attributes = window.attributes.apply {
                        layoutInDisplayCutoutMode =
                            WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
                    }
                }
                WindowInsetsControllerCompat(window, window.decorView).apply {
                    systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
                    hide(WindowInsetsCompat.Type.systemBars())
                }
                ViewCompat.requestApplyInsets(binding.root)
            }
            override fun onHideCustomView() {
                if (customView == null) return
                customView?.let { binding.customViewContainer.removeView(it) }
                customView = null; customCallback?.onCustomViewHidden(); customCallback = null
                binding.customViewContainer.visibility = View.GONE; binding.webView.visibility = View.VISIBLE
                requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED
                if (!isKeepScreenOnRequested()) {
                    window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                }
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P && savedCutoutMode != null) {
                    val mode = savedCutoutMode!!
                    savedCutoutMode = null
                    window.attributes = window.attributes.apply { layoutInDisplayCutoutMode = mode }
                }
                WindowInsetsControllerCompat(window, window.decorView).show(WindowInsetsCompat.Type.systemBars())
                ViewCompat.requestApplyInsets(binding.root)
            }
        }
    }
    override fun onDestroy() {
        EngineHost.detachActivity(this)
        customView?.let { binding.customViewContainer.removeView(it) }
        customCallback?.onCustomViewHidden()
        customView = null; customCallback = null
        window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        if (StorageAccess.actionHandler === permissionAction) StorageAccess.actionHandler = null
        fileCallback?.onReceiveValue(null); fileCallback = null
        (binding.webView.parent as? ViewGroup)?.removeView(binding.webView)
        binding.webView.stopLoading(); binding.webView.destroy()
        super.onDestroy()
    }
}
