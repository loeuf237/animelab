package com.animan.app

import android.app.Activity
import android.content.Context
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import androidx.core.content.FileProvider
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.withTimeoutOrNull
import org.json.JSONObject
import java.lang.ref.WeakReference
import java.net.HttpURLConnection
import java.net.InetAddress
import java.net.Proxy
import java.net.ServerSocket
import java.net.URL
import java.security.SecureRandom
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference
import kotlin.concurrent.thread

/** One engine per process; Activity recreation only reconnects to it. */
object EngineHost {
    lateinit var context: Context
        private set
    val token = ByteArray(32).also { SecureRandom().nextBytes(it) }.joinToString("") { "%02x".format(it) }
    @Volatile var port = 0
        private set
    val baseUrl: String get() = "http://127.0.0.1:$port"
    private val readyDeferred = CompletableDeferred<Boolean>()
    private val httpReadyDeferred = CompletableDeferred<Boolean>()
    private val httpReadyLatch = CountDownLatch(1)
    private val loopbackProbeStarted = AtomicBoolean(false)
    @Volatile var startElapsedMs = 0L
        private set
    @Volatile var pythonStartedMs = 0L
        private set
    @Volatile var stage0ReadyMs = 0L
        private set
    @Volatile var httpReadyMs = 0L
        private set
    @Volatile var shellReadyMs = 0L
        private set
    @Volatile var fullReadyMs = 0L
        private set
    @Volatile var httpReady = false
        private set
    @Volatile var fullyReady = false
        private set
    @Volatile var ready = false
        set(value) {
            field = value
            if (value) {
                if (stage0ReadyMs == 0L) stage0ReadyMs = SystemClock.elapsedRealtime()
                readyDeferred.complete(true)
                startLoopbackProbe()
            }
        }
    @Volatile var error: String? = null
    @Volatile var activeCount = 0
    @Volatile var progress = 0
    @Volatile var label = ""
    private var started = false
    private val foregroundActivityRef = AtomicReference<WeakReference<Activity>?>(null)
    val main = Handler(Looper.getMainLooper())

    fun attachActivity(activity: Activity) {
        foregroundActivityRef.set(WeakReference(activity))
    }

    fun detachActivity(activity: Activity) {
        val current = foregroundActivityRef.get()?.get()
        if (current === activity) foregroundActivityRef.set(null)
    }

    fun foregroundActivity(): Activity? =
        foregroundActivityRef.get()?.get()?.takeIf { !it.isFinishing && !it.isDestroyed }

    @JvmStatic fun markFullReady() {
        if (fullReadyMs == 0L) fullReadyMs = SystemClock.elapsedRealtime()
        fullyReady = true
        android.util.Log.i("AnimanEngine", "ANIMAN_STARTUP_TIMING=${timingJson()}")
    }

    @JvmStatic fun markShellReady() {
        if (shellReadyMs == 0L) shellReadyMs = SystemClock.elapsedRealtime()
    }

    @JvmStatic fun engineStateJson(): String =
        JSONObject()
            .put("ready", httpReady)
            .put("fullyReady", fullyReady)
            .put("error", error ?: JSONObject.NULL)
            .toString()

    @JvmStatic fun timingJson(): String {
        val origin = startElapsedMs
        fun delta(stamp: Long): Long = if (origin > 0L && stamp >= origin) stamp - origin else -1L
        return JSONObject()
            .put("ready", ready)
            .put("httpReady", httpReady)
            .put("fullyReady", fullyReady)
            .put("pythonStartMs", delta(pythonStartedMs))
            .put("stage0ReadyMs", delta(stage0ReadyMs))
            .put("httpReadyMs", delta(httpReadyMs))
            .put("shellReadyMs", delta(shellReadyMs))
            .put("fullReadyMs", delta(fullReadyMs))
            .toString()
    }

    suspend fun awaitReady(timeoutMs: Long): Boolean {
        if (ready) return true
        if (error != null) return false
        return withTimeoutOrNull(timeoutMs.coerceAtLeast(1L)) { readyDeferred.await() } == true
    }

    suspend fun awaitHttpReady(timeoutMs: Long): Boolean {
        if (httpReady) return true
        if (error != null) return false
        return withTimeoutOrNull(timeoutMs.coerceAtLeast(1L)) { httpReadyDeferred.await() } == true
    }

    fun awaitHttpReadyBlocking(timeoutMs: Long): Boolean {
        if (httpReady) return true
        if (error != null) return false
        return try {
            httpReadyLatch.await(timeoutMs.coerceAtLeast(1L), TimeUnit.MILLISECONDS) && httpReady
        } catch (_: InterruptedException) {
            false
        }
    }

    private fun startLoopbackProbe() {
        if (!loopbackProbeStarted.compareAndSet(false, true)) return
        thread(name = "AnimanLoopbackProbe", isDaemon = true) {
            val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(60)
            var delayMs = 15L
            while (System.nanoTime() < deadline && error == null) {
                val reachable = try {
                    val conn = URL("$baseUrl/api/engine/readiness").openConnection(Proxy.NO_PROXY) as HttpURLConnection
                    try {
                        conn.connectTimeout = 1500
                        conn.readTimeout = 2000
                        conn.setRequestProperty("X-Animan-Session", token)
                        conn.responseCode == 200
                    } finally {
                        conn.disconnect()
                    }
                } catch (_: Exception) {
                    false
                }
                if (reachable) {
                    if (httpReadyMs == 0L) httpReadyMs = SystemClock.elapsedRealtime()
                    httpReady = true
                    httpReadyDeferred.complete(true)
                    httpReadyLatch.countDown()
                    return@thread
                }
                try {
                    Thread.sleep(delayMs)
                } catch (_: InterruptedException) {
                    break
                }
                delayMs = (delayMs * 2).coerceAtMost(200L)
            }
            httpReadyDeferred.complete(false)
            httpReadyLatch.countDown()
        }
    }

    @Synchronized fun start(applicationContext: Context, testMode: Boolean = false) {
        if (started) return
        started = true
        startElapsedMs = SystemClock.elapsedRealtime()
        context = applicationContext.applicationContext
        ExtensionPackages.activityProvider = { foregroundActivity() }
        ExtensionPackages.apkUriProvider = { ctx, file ->
            FileProvider.getUriForFile(ctx, "${ctx.packageName}.fileprovider", file)
        }
        CrashReporter.install(context)
        if (BuildConfig.EXTENSION_RUNTIME_ENABLED) {
            thread(name = "AnimanExtensionInit", isDaemon = true) {
                try {
                    ExtensionBridge.initialize(context)
                } catch (failure: Exception) {
                    android.util.Log.w("AnimanEngine", "Background extension init skipped", failure)
                }
            }
        }
        port = ServerSocket(0, 1, InetAddress.getByName("127.0.0.1")).use { it.localPort }
        thread(name = "AnimanPythonEngine", isDaemon = true) {
            try {
                if (!Python.isStarted()) Python.start(AndroidPlatform(context))
                pythonStartedMs = SystemClock.elapsedRealtime()
                Python.getInstance().getModule("android_runtime").callAttr("start",
                    context.filesDir.absolutePath, context.cacheDir.absolutePath, port, token, testMode)
            } catch (failure: Exception) {
                error = failure.message ?: failure.javaClass.simpleName
                readyDeferred.complete(false)
                httpReadyDeferred.complete(false)
                httpReadyLatch.countDown()
                CrashReporter.recordWebViewError(context, "engine_start_failed", error ?: "unknown")
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
