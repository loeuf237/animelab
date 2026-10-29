package com.animan.nativeprobe

import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.animan.app.MediaBridge
import com.animan.app.NativeHooks
import com.animan.app.EngineHost
import com.animan.app.StorageAccess
import android.provider.MediaStore
import android.net.Uri
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

@RunWith(AndroidJUnit4::class)
class NativeMediaTest {
    private fun run(tool: String, vararg args: String): String {
        val result = JSONObject(MediaBridge.execute(tool, JSONArray(args.toList()).toString(), 120000))
        assertFalse(result.toString(), result.getBoolean("timedOut"))
        assertEquals(result.getString("stderr"), 0, result.getInt("returncode"))
        return result.getString("stdout")
    }
    @Test fun realNativeMediaCommands() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        EngineHost.context = context
        StorageAccess.useDownloads()
        assertTrue(JSONObject(StorageAccess.status()).getBoolean("authorized"))
        val root = context.cacheDir
        val probeDir = File(root, "hardsub test").apply { mkdirs() }
        val startedAt = android.os.SystemClock.elapsedRealtime()
        val nativeHeapBefore = android.os.Debug.getNativeHeapAllocatedSize()
        val power = context.getSystemService(android.content.Context.POWER_SERVICE) as android.os.PowerManager
        val thermalBefore = power.currentThermalStatus
        val hardsub = JSONObject(MediaBridge.probeHardsub(probeDir.path))
        assertTrue(hardsub.toString(), hardsub.getBoolean("available"))
        assertTrue(hardsub.toString(), hardsub.getBoolean("renderVerified"))
        hardsub.put("elapsedMs", android.os.SystemClock.elapsedRealtime() - startedAt)
            .put("nativeHeapBefore", nativeHeapBefore).put("nativeHeapAfter", android.os.Debug.getNativeHeapAllocatedSize())
            .put("thermalBefore", thermalBefore).put("thermalAfter", power.currentThermalStatus)
            .put("pageSize", android.system.Os.sysconf(android.system.OsConstants._SC_PAGESIZE))
            .put("api", android.os.Build.VERSION.SDK_INT)
        val source = File(root, "native fixture.mp4")
        run("ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=160x90:r=10",
            "-f", "lavfi", "-i", "sine=frequency=440", "-t", "40", "-c:v", "mpeg4", "-c:a", "aac", source.path)
        assertTrue(source.length() > 1000)
        val subtitle = File(root, "English.srt").apply { writeText("1\n00:00:00,000 --> 00:00:01,000\nNative subtitle probe\n") }
        val burned = File(root, "native hardsub.mp4")
        run("ffmpeg", "-v", "error", "-y", "-i", source.path, "-t", "2", "-vf",
            "subtitles=filename=${subtitle.path}:fontsdir=/system/fonts", "-c:v", "libx264", "-threads", "1",
            "-filter_threads", "1", "-preset", "ultrafast", "-c:a", "aac", "-sn", burned.path)
        val muxed = File(root, "native subtitle.mkv")
        run("ffmpeg", "-v", "error", "-y", "-i", source.path, "-i", subtitle.path, "-map", "0", "-map", "1", "-c", "copy", "-metadata:s:s:0", "language=eng", muxed.path)
        val streams = JSONObject(run("ffprobe", "-v", "error", "-show_streams", "-of", "json", muxed.path)).getJSONArray("streams")
        assertTrue((0 until streams.length()).any { streams.getJSONObject(it).optString("codec_type") == "subtitle" && streams.getJSONObject(it).getJSONObject("tags").optString("language") == "eng" })
        val segment = File(root, "segment.ts")
        run("ffmpeg", "-v", "error", "-y", "-i", source.path, "-t", "2", "-c:v", "mpeg2video", "-c:a", "aac", "-f", "mpegts", segment.path)
        val hls = File(root, "hls remux.mp4")
        run("ffmpeg", "-v", "error", "-y", "-i", segment.path, "-c", "copy", "-f", "mp4", hls.path)
        for (point in listOf("1", "20", "34")) run("ffmpeg", "-v", "error", "-ss", point, "-i", muxed.path, "-t", "1", "-f", "null", "-")
        val bad = JSONObject(MediaBridge.execute("ffprobe", JSONArray(listOf("-v", "error", File(root, "missing.mp4").path)).toString(), 30000))
        assertNotEquals(0, bad.getInt("returncode"))
        assertTrue(bad.getString("stderr").isNotBlank())
        val privateRoot = File(context.filesDir, "downloads").apply { mkdirs() }
        val published = mutableListOf<Uri>()
        try {
            for (file in listOf(muxed, subtitle, burned)) {
                val privateFile = File(privateRoot, file.name)
                file.copyTo(privateFile, overwrite = true)
                val uri = Uri.parse(NativeHooks.exportFile(privateFile.path, "storage-probe"))
                published.add(uri)
                assertArrayEquals(privateFile.readBytes(), context.contentResolver.openInputStream(uri)!!.use { it.readBytes() })
                context.contentResolver.query(uri, arrayOf(MediaStore.Downloads.IS_PENDING, MediaStore.Downloads.RELATIVE_PATH), null, null, null)!!.use {
                    assertTrue(it.moveToFirst()); assertEquals(0, it.getInt(0))
                    val directory = it.getString(1)
                    if (file == subtitle) assertTrue(directory == "Download/AnimeLab/" || directory == "Movies/AnimeLab/")
                    else assertEquals("Download/AnimeLab/", directory)
                }
                // Reconstruct the registry format used by installed APKs;
                // upgrading must reuse this shared copy, not create another.
                val legacyKey = privateFile.canonicalPath + ":" + privateFile.length() + ":" + privateFile.lastModified()
                context.getSharedPreferences("animan_exports", android.content.Context.MODE_PRIVATE).edit()
                    .clear().putString(legacyKey, uri.toString()).commit()
                assertEquals(uri.toString(), NativeHooks.exportFile(privateFile.path, "storage-probe"))
                // A readable URI can still contain an incomplete copy. It must
                // not be accepted merely because the registry entry exists.
                context.contentResolver.openOutputStream(uri, "wt")!!.use { it.write(byteArrayOf(0)) }
                val repaired = Uri.parse(NativeHooks.exportFile(privateFile.path, "storage-probe"))
                published.add(repaired)
                assertNotEquals(uri, repaired)
                assertArrayEquals(privateFile.readBytes(), context.contentResolver.openInputStream(repaired)!!.use { it.readBytes() })
            }
            val blocked = File(privateRoot, "paused.mp4").apply { writeBytes(ByteArray(300000)) }
            for (state in listOf("paused", "PAUSED", "CANCELLED")) {
                NativeHooks.progress(0, 0, "Paused", "paused-storage-probe", state)
                try {
                    NativeHooks.exportFile(blocked.path, "paused-storage-probe")
                    fail("An interrupted export must not become a shared file")
                } catch (_: IllegalStateException) { assertTrue(blocked.exists()) }
            }
            try {
                NativeHooks.exportFile(source.path, "outside-private-root")
                fail("Export must reject media outside the private downloads directory")
            } catch (_: IllegalArgumentException) { assertTrue(source.exists()) }
        } finally { for (uri in published) context.contentResolver.delete(uri, null, null) }
        val job = "p14-cancel"
        var cancelResult = ""
        val worker = Thread {
            cancelResult = MediaBridge.executeManaged("ffmpeg", JSONArray(listOf("-v", "error", "-y", "-re", "-f", "lavfi",
                "-i", "color=s=320x180:r=10", "-t", "60", "-c:v", "libx264", "-threads", "1", File(root, "cancel.mp4").path)).toString(), 90000, job)
        }
        worker.start()
        val deadline = android.os.SystemClock.elapsedRealtime() + 10000
        while (worker.isAlive && JSONObject(MediaBridge.pollManaged(job)).optDouble("seconds", -1.0) < 0 &&
            android.os.SystemClock.elapsedRealtime() < deadline) Thread.sleep(50)
        val progressObserved = JSONObject(MediaBridge.pollManaged(job)).optDouble("seconds", -1.0) >= 0
        MediaBridge.cancelManaged(job)
        worker.join(10000)
        assertFalse("JNI encode must terminate after cancellation", worker.isAlive)
        assertNotEquals(0, JSONObject(cancelResult).getInt("returncode"))
        assertTrue("JNI encoding statistics must reach the managed job", progressObserved)
        MediaBridge.releaseManaged(job)
        File(root, "cancel.mp4").delete()
        val receipt = "ANIMAN_NATIVE_MEDIA_PROBE=" + JSONObject().put("abi", android.os.Build.SUPPORTED_ABIS[0])
            .put("probeRunId", InstrumentationRegistry.getArguments().getString("probe_run_id"))
            .put("hardsub", hardsub).put("managed_cancellation", true).put("managed_progress", true)
            .put("encode", true).put("subtitle_mux", true).put("hls_remux", true).put("decode", true).put("errors_reported", true)
            .put("storage_export", true).put("storage_permission_required", false).put("paused_export_rejected", true)
        // Instrumentation may terminate its process before the host asks pidof.
        // A dedicated tag plus a run nonce preserves only this test's receipt.
        android.util.Log.i("ANIMAN_MEDIA_PROOF", receipt)
        println(receipt)
    }
}
