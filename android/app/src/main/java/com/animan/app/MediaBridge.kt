package com.animan.app

import com.arthenica.ffmpegkit.FFmpegKit
import com.arthenica.ffmpegkit.FFmpegKitConfig
import com.arthenica.ffmpegkit.FFmpegSession
import com.arthenica.ffmpegkit.FFprobeSession
import com.arthenica.ffmpegkit.LogRedirectionStrategy
import com.arthenica.ffmpegkit.Session
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.ConcurrentHashMap
import java.util.UUID

object MediaBridge {
    @JvmStatic fun probeHardsub(directory: String): String = HardsubProbe.probe(directory)
    // FFmpegKit's session history retains every log before invoking callbacks.
    // Own the bounded output and serialize commands so disabling that history
    // cannot interfere with another command's diagnostics or cancellation.
    @JvmStatic fun execute(tool: String, arguments: String, timeoutMs: Int): String {
        val job = UUID.randomUUID().toString()
        return try { executeManaged(tool, arguments, timeoutMs, job) } finally { releaseManaged(job) }
    }
    private class ManagedState {
        @Volatile var sessionId: Long = -1
        @Volatile var seconds: Double = -1.0
        @Volatile var cancelled: Boolean = false
    }
    private val managed = ConcurrentHashMap<String, ManagedState>()
    @JvmStatic fun pollManaged(job: String): String {
        val state = managed[job]
        val result = JSONObject()
        if (state != null && state.seconds >= 0) result.put("seconds", state.seconds)
        return result.toString()
    }
    @JvmStatic fun cancelManaged(job: String) {
        val state = managed.computeIfAbsent(job) { ManagedState() }
        state.cancelled = true
        if (state.sessionId >= 0) FFmpegKit.cancel(state.sessionId)
    }
    @JvmStatic fun releaseManaged(job: String) { managed.remove(job) }

    @JvmStatic @Synchronized fun executeManaged(tool: String, arguments: String, timeoutMs: Int, job: String): String {
        require(tool == "ffmpeg" || tool == "ffprobe")
        require(timeoutMs > 0)
        check(!unresponsive) { "The native media worker did not stop; restart AnimeLab before retrying" }
        val state = managed.computeIfAbsent(job) { ManagedState() }
        if (state.cancelled) return result(-1, "", "Media operation cancelled", false)
        val values = JSONArray(arguments)
        val args = Array(values.length()) { values.getString(it) }
        if (args.contentEquals(arrayOf("-version"))) {
            // The native getter does not invoke the CLI's process-exit path.
            return result(0, "$tool version ${FFmpegKitConfig.getFFmpegVersion()}", "", false)
        }
        val output = StringBuilder()
        val excessiveLogs = AtomicBoolean(false)
        val completed = CountDownLatch(1)
        FFmpegKitConfig.setLogRedirectionStrategy(LogRedirectionStrategy.NEVER_PRINT_LOGS)
        val session: Session = if (tool == "ffprobe") FFprobeSession.create(args) else FFmpegSession.create(args)
        state.sessionId = session.sessionId
        FFmpegKitConfig.enableStatisticsCallback { statistics ->
            if (statistics.sessionId == session.sessionId) state.seconds = statistics.time / 1000.0
        }
        FFmpegKitConfig.clearSessions()
        FFmpegKitConfig.enableLogCallback { log ->
            if (log.sessionId == session.sessionId) {
                synchronized(output) {
                    val remaining = MAX_DIAGNOSTICS - output.length
                    if (remaining > 0) output.append(log.message.take(remaining))
                    if (log.message.length > remaining && excessiveLogs.compareAndSet(false, true)) {
                        FFmpegKit.cancel(session.sessionId)
                    }
                }
            }
        }
        Thread({
            try {
                if (!state.cancelled) {
                    if (session is FFprobeSession) FFmpegKitConfig.ffprobeExecute(session)
                    else FFmpegKitConfig.ffmpegExecute(session as FFmpegSession)
                }
            } finally { completed.countDown() }
        }, "AnimanNativeMedia").apply { isDaemon = true }.start()
        val timedOut = !completed.await(timeoutMs.toLong(), TimeUnit.MILLISECONDS)
        if (timedOut) {
            FFmpegKit.cancel(session.sessionId)
            unresponsive = !completed.await(5, TimeUnit.SECONDS)
        }
        // Drain the native callback queue without copying FFmpegKit's log list.
        val drainDeadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(1)
        while (session.thereAreAsynchronousMessagesInTransmit() && System.nanoTime() < drainDeadline) Thread.sleep(10)
        FFmpegKitConfig.enableLogCallback(null)
        FFmpegKitConfig.enableStatisticsCallback(null)
        val stdout = synchronized(output) { output.toString() }
        val code = if (excessiveLogs.get()) -1 else session.returnCode?.value ?: -1
        val stderr = when {
            excessiveLogs.get() -> "FFmpeg diagnostic limit exceeded; command cancelled. " + stdout.take(2048)
            tool == "ffprobe" && code == 0 -> ""
            else -> stdout
        }
        return result(code, stdout, stderr, timedOut)
    }
    private fun result(code: Int, stdout: String, stderr: String, timedOut: Boolean): String =
        JSONObject().put("returncode", code).put("stdout", stdout).put("stderr", stderr).put("timedOut", timedOut).toString()
    private var unresponsive = false
    private const val MAX_DIAGNOSTICS = 1024 * 1024
}
