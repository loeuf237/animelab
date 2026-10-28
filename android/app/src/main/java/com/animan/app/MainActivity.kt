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
import android.os.Build
import android.os.Bundle
import android.view.View
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowCompat
import android.webkit.*
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
        ExtensionBridge.resumePendingInstalls()
    }
    private lateinit var binding: ActivityMainBinding
    private var customView: View? = null
    private var customCallback: WebChromeClient.CustomViewCallback? = null
    private var fileCallback: ValueCallback<Array<Uri>>? = null
    private var connectJob: Job? = null
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
        ViewCompat.setOnApplyWindowInsetsListener(binding.root) { view, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout())
            view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            insets
        }
        setupWebView()
        EngineHost.start(applicationContext, BuildConfig.DEBUG && intent.getBooleanExtra("test_mode", false))
        StorageAccess.actionHandler = permissionAction
        DownloadService.update(applicationContext)
        if (Build.VERSION.SDK_INT >= 33) notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
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
                    binding.loadingLayout.visibility = View.VISIBLE
                    binding.loadingStatus.text = getString(R.string.engine_error, error?.description ?: "")
                    binding.retryButton.visibility = View.VISIBLE
                }
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
                val hit = view?.hitTestResult?.extra ?: return false
                val uri = Uri.parse(hit)
                if (uri.scheme !in listOf("http", "https")) return false
                try { startActivity(Intent(Intent.ACTION_VIEW, uri)) } catch (_: Exception) { return false }
                return false
            }
            override fun onShowCustomView(view: View?, callback: CustomViewCallback?) {
                if (customView != null || view == null) { callback?.onCustomViewHidden(); return }
                customView = view; customCallback = callback
                binding.webView.visibility = View.GONE
                binding.customViewContainer.visibility = View.VISIBLE
                binding.customViewContainer.addView(view)
                requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE
                window.decorView.systemUiVisibility = View.SYSTEM_UI_FLAG_FULLSCREEN or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
            }
            override fun onHideCustomView() {
                customView?.let { binding.customViewContainer.removeView(it) }
                customView = null; customCallback?.onCustomViewHidden(); customCallback = null
                binding.customViewContainer.visibility = View.GONE; binding.webView.visibility = View.VISIBLE
                requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED
                window.decorView.systemUiVisibility = View.SYSTEM_UI_FLAG_VISIBLE
            }
        }
    }
    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (customView != null) binding.webView.webChromeClient?.onHideCustomView()
        else if (binding.webView.canGoBack()) binding.webView.goBack()
        else super.onBackPressed()
    }
    override fun onDestroy() {
        if (StorageAccess.actionHandler === permissionAction) StorageAccess.actionHandler = null
        fileCallback?.onReceiveValue(null); fileCallback = null
        (binding.webView.parent as? ViewGroup)?.removeView(binding.webView)
        binding.webView.stopLoading(); binding.webView.destroy()
        super.onDestroy()
    }
}
