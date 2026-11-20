package com.animan.app

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

/** Captures uncaught exceptions and WebView/engine failures into filesDir/last_crash.json. */
object CrashReporter {
    private val lock = Any()
    @Volatile
    private var installed = false
    private val urlPattern = Regex("https?://[^\\s<>\"']+")

    private fun utcNow(): String {
        val fmt = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US)
        fmt.timeZone = TimeZone.getTimeZone("UTC")
        return fmt.format(Date())
    }

    private fun sanitize(raw: String?, maxLen: Int = 240): String {
        val text = (raw ?: "").trim()
        val scrubbed = urlPattern.replace(text, "[url]")
        return if (scrubbed.length > maxLen) scrubbed.take(maxLen) else scrubbed
    }

    private fun writeRecord(context: Context, payload: JSONObject) {
        synchronized(lock) {
            try {
                val target = File(context.applicationContext.filesDir, "last_crash.json")
                target.writeText(payload.toString())
            } catch (_: Exception) {
            }
        }
    }

    @Synchronized
    fun install(context: Context) {
        if (installed) return
        val appContext = context.applicationContext
        val previous = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, throwable ->
            try {
                val frames = JSONArray()
                for (el in throwable.stackTrace.take(12)) {
                    frames.put(sanitize("${el.className}.${el.methodName}(${el.fileName}:${el.lineNumber})", 200))
                }
                val payload = JSONObject()
                    .put("time", utcNow())
                    .put("kind", "uncaught_exception")
                    .put("thread", sanitize(thread.name, 80))
                    .put("exception", sanitize("${throwable.javaClass.simpleName}: ${throwable.message ?: ""}", 280))
                    .put("frames", frames)
                writeRecord(appContext, payload)
            } catch (_: Exception) {
            }
            previous?.uncaughtException(thread, throwable)
        }
        installed = true
    }

    fun recordWebViewError(context: Context, kind: String, detail: String) {
        try {
            val payload = JSONObject()
                .put("time", utcNow())
                .put("kind", sanitize(kind, 60))
                .put("exception", sanitize(detail, 240))
            writeRecord(context, payload)
        } catch (_: Exception) {
        }
    }
}
