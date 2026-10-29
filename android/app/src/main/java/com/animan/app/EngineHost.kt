package com.animan.app

import android.content.Context
import android.os.Handler
import android.os.Looper
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.net.InetAddress
import java.net.ServerSocket
import java.security.SecureRandom
import kotlin.concurrent.thread

/** One engine per process; Activity recreation only reconnects to it. */
object EngineHost {
    lateinit var context: Context
        private set
    val token = ByteArray(32).also { SecureRandom().nextBytes(it) }.joinToString("") { "%02x".format(it) }
    @Volatile var port = 0
        private set
    val baseUrl: String get() = "http://127.0.0.1:$port"
    @Volatile var ready = false
    @Volatile var error: String? = null
    @Volatile var activeCount = 0
    @Volatile var progress = 0
    @Volatile var label = ""
    private var started = false
    val main = Handler(Looper.getMainLooper())

    @Synchronized fun start(applicationContext: Context, testMode: Boolean = false) {
        if (started) return
        started = true
        context = applicationContext.applicationContext
        if (BuildConfig.EXTENSION_RUNTIME_ENABLED) ExtensionBridge.initialize(context)
        port = ServerSocket(0, 1, InetAddress.getByName("127.0.0.1")).use { it.localPort }
        thread(name = "AnimanPythonEngine", isDaemon = true) {
            try {
                if (!Python.isStarted()) Python.start(AndroidPlatform(context))
                Python.getInstance().getModule("android_runtime").callAttr("start",
                    context.filesDir.absolutePath, context.cacheDir.absolutePath, port, token, testMode)
            } catch (failure: Exception) {
                error = failure.message ?: failure.javaClass.simpleName
                android.util.Log.e("AnimanEngine", "Embedded engine failed", failure)
                main.post { DownloadService.finishIdle(context) }
            }
        }
    }

    fun command(action: String) {
        thread(name = "AnimanNotificationAction") {
            if (Python.isStarted()) Python.getInstance().getModule("android_runtime").callAttr("command", action)
        }
    }
}
