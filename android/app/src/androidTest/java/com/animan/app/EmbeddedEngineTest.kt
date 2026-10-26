package com.animan.app

import android.content.Intent
import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.chaquo.python.Python
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.net.HttpURLConnection
import java.net.Proxy
import java.net.URL
import java.io.File
import android.graphics.Bitmap
import android.webkit.WebView
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import android.net.Uri
import android.provider.MediaStore
import android.os.ParcelFileDescriptor
import java.security.MessageDigest
import java.util.concurrent.atomic.AtomicBoolean

@RunWith(AndroidJUnit4::class)
class EmbeddedEngineTest {
    @org.junit.After fun removeIsolatedProbeExports() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        if (context.packageName != "com.animan.app.a11test") return
        // These preferences belong only to the disposable validation app. Delete
        // its exact exported URIs, never files selected by name in user's Downloads.
        val exports = context.getSharedPreferences("animan_exports", android.content.Context.MODE_PRIVATE)
        exports.all.values.filterIsInstance<String>().filter { it.startsWith("content://") }.distinct().forEach {
            context.contentResolver.delete(Uri.parse(it), null, null)
        }
        exports.edit().clear().commit()
    }

    private fun waitForHome(scenario: ActivityScenario<MainActivity>, message: String) {
        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(60)
        while (System.nanoTime() < deadline) {
            val checked = CountDownLatch(1)
            val rendered = AtomicBoolean(false)
            scenario.onActivity { activity ->
                // Keep only this test window awake; closing it restores normal
                // screen behavior without changing the user's timeout settings.
                activity.window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                val webView = activity.findViewById<WebView>(R.id.webView)
                if (webView.url?.startsWith(EngineHost.baseUrl + "/spa/") != true ||
                    !activity.hasWindowFocus() ||
                    activity.findViewById<android.view.View>(R.id.loadingLayout).visibility != android.view.View.GONE) checked.countDown()
                else webView.evaluateJavascript("Boolean(document.querySelector('#main-content .home-container .hero-panel'))") {
                    rendered.set(it == "true"); checked.countDown()
                }
            }
            // A renderer can start slowly after recreation. A missed callback
            // does not bypass the overall deadline or the actual DOM check.
            checked.await(5, TimeUnit.SECONDS)
            if (rendered.get()) return
            Thread.sleep(250)
        }
        fail(message)
    }
    private fun request(path: String, authenticated: Boolean = true, body: String? = null): Pair<Int, String> {
        val connection = URL(EngineHost.baseUrl + path).openConnection(Proxy.NO_PROXY) as HttpURLConnection
        try {
            connection.connectTimeout = 5000; connection.readTimeout = 20000
            if (authenticated) connection.setRequestProperty("X-Animan-Session", EngineHost.token)
            if (body != null) {
                connection.requestMethod = "POST"; connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json")
                connection.outputStream.use { it.write(body.toByteArray()) }
            }
            val code = connection.responseCode
            val stream = if (code < 400) connection.inputStream else connection.errorStream
            return Pair(code, stream?.bufferedReader()?.use { it.readText() } ?: "")
        } finally { connection.disconnect() }
    }
    @Test fun embeddedEngineAndNativeMedia() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        EngineHost.start(context, true)
        val intent = Intent(context, MainActivity::class.java).putExtra("test_mode", true)
        ActivityScenario.launch<MainActivity>(intent).use { scenario ->
            val deadline = System.currentTimeMillis() + 180000
            while (!EngineHost.ready && EngineHost.error == null && System.currentTimeMillis() < deadline) Thread.sleep(250)
            assertNull(EngineHost.error)
            assertTrue("Embedded Python did not become ready", EngineHost.ready)
            var page: Pair<Int, String>? = null
            repeat(30) {
                if (page == null) try { page = request("/spa/") } catch (_: Exception) { Thread.sleep(250) }
            }
            assertEquals(200, page?.first)
            assertTrue(page!!.second.contains("id=\"app\""))
            assertEquals(401, request("/api/download/status", false).first)
            assertEquals(200, request("/api/download/status").first)
            waitForHome(scenario, "Vue did not render in the installed System WebView")
            // Measure installed storage separately from APK size, before media
            // fixtures create downloads. Querying our own UID needs no extra grant.
            val storageManager = context.getSystemService(android.os.storage.StorageManager::class.java)
            val stats = context.getSystemService(android.app.usage.StorageStatsManager::class.java)
                .queryStatsForUid(storageManager.getUuidForPath(context.dataDir), context.applicationInfo.uid)
            val footprint = JSONObject()
                .put("phase", "after_first_render_before_media_probes")
                .put("api", android.os.Build.VERSION.SDK_INT)
                .put("apk_bytes", File(context.applicationInfo.sourceDir).length())
                .put("installed_app_bytes", stats.appBytes)
                .put("data_bytes_including_cache", stats.dataBytes)
                .put("cache_bytes", stats.cacheBytes)
                .put("installed_total_bytes", stats.appBytes + stats.dataBytes)
                .put("native_library_packaging", "direct_load_uncompressed")
            File(requireNotNull(context.getExternalFilesDir(null)), "footprint.json")
                .writeText(footprint.toString(2))
            println("ANIMAN_ANDROID_FOOTPRINT=$footprint")
            val port = EngineHost.port
            scenario.recreate()
            assertEquals("Activity recreation started another server", port, EngineHost.port)
            // Recreating the Activity creates a new WebView. Its server stays
            // alive, but its page must render again before capturing the UI.
            waitForHome(scenario, "Recreated WebView did not become visible")
            val storage = JSONObject(request("/api/system/android/storage").second)
            assertTrue(storage.getBoolean("authorized"))
            assertEquals("Downloads/AnimeLab", storage.getString("destination"))
            assertEquals(401, request("/api/system/android/storage", false, "{\"action\":\"choose_directory\"}").first)
            val selection = JSONObject(request("/api/system/android/storage", body = "{\"action\":\"choose_directory\"}").second)
            assertTrue(selection.getBoolean("selectionPending"))
            val automation = InstrumentationRegistry.getInstrumentation().uiAutomation
            val pickerDeadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(20)
            var pickerVisible = false
            while (!pickerVisible && System.nanoTime() < pickerDeadline) {
                // Android 15 may expose no accessibility root for DocumentsUI
                // while its activity is visibly resumed. Inspect the actual
                // foreground activity, then still require cancellation to
                // deliver its result and render Animan again.
                val activities = ParcelFileDescriptor.AutoCloseInputStream(
                    automation.executeShellCommand("dumpsys activity activities")).bufferedReader().use { it.readText() }
                pickerVisible = activities.lineSequence().any { it.contains("ResumedActivity") && it.contains("documentsui") }
                if (!pickerVisible) Thread.sleep(250)
            }
            assertTrue("Android folder picker did not open", pickerVisible)
            val cancelDeadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(30)
            var pending = true
            while (pending && System.nanoTime() < cancelDeadline) {
                // Back can first close a DocumentsUI drawer/search panel. Only
                // send another Back while that picker still owns the foreground;
                // never accidentally back out of Animan after its result arrives.
                val activities = ParcelFileDescriptor.AutoCloseInputStream(
                    automation.executeShellCommand("dumpsys activity activities")).bufferedReader().use { it.readText() }
                if (activities.lineSequence().any { it.contains("ResumedActivity") && it.contains("documentsui") }) {
                    ParcelFileDescriptor.AutoCloseInputStream(automation.executeShellCommand("input keyevent KEYCODE_BACK")).use { it.readBytes() }
                    Thread.sleep(1000)
                }
                pending = JSONObject(request("/api/system/android/storage").second).getBoolean("selectionPending")
                if (pending) Thread.sleep(250)
            }
            assertFalse("Folder picker cancellation did not restore permission controls", pending)
            waitForHome(scenario, "Home did not return after cancelling folder selection")
            val includeMedia = InstrumentationRegistry.getArguments().getString("skip_native_media") != "true"
            val report = JSONObject(Python.getInstance().getModule("android_runtime").callAttr("native_probe", includeMedia).toString())
            report.put("vue_rendered", true)
            report.put("webview_version", WebView.getCurrentWebViewPackage()?.versionName)
            if (!includeMedia) {
                val source = File(context.filesDir, "downloads/native-storage-probe.bin")
                val bytes = ByteArray(65537) { (it % 251).toByte() }
                source.parentFile?.mkdirs(); source.writeBytes(bytes)
                assertTrue(NativeHooks.progress(1, 99, "Storage probe", "native-storage-probe", "downloading"))
                try {
                    val uri = Uri.parse(NativeHooks.exportFile(source.path, "native-storage-probe"))
                    val exported = requireNotNull(context.contentResolver.openInputStream(uri)).use { it.readBytes() }
                    assertArrayEquals(bytes, exported)
                    context.contentResolver.query(uri, arrayOf(MediaStore.Downloads.IS_PENDING), null, null, null)?.use {
                        assertTrue(it.moveToFirst()); assertEquals(0, it.getInt(0))
                    } ?: fail("Storage export is not published")
                    report.put("storage_export", true)
                } finally { NativeHooks.progress(0, 100, "Storage probe", "native-storage-probe", "completed") }
            }
            if (includeMedia) {
            val mediaPaths = report.getJSONArray("media_paths")
            for (index in 0 until mediaPaths.length()) {
                val source = File(mediaPaths.getString(index))
                val uri = Uri.parse(NativeHooks.exportFile(source.path, "validation"))
                fun hash(input: java.io.InputStream): ByteArray = input.use {
                    val digest = MessageDigest.getInstance("SHA-256")
                    val buffer = ByteArray(65536)
                    while (true) {
                        val count = it.read(buffer)
                        if (count < 0) break
                        digest.update(buffer, 0, count)
                    }
                    digest.digest()
                }
                val shared = requireNotNull(context.contentResolver.openInputStream(uri))
                assertArrayEquals("Shared download differs from verified private media", hash(source.inputStream()), hash(shared))
                context.contentResolver.query(uri, arrayOf(MediaStore.Downloads.IS_PENDING), null, null, null)?.use {
                    assertTrue(it.moveToFirst()); assertEquals(0, it.getInt(0))
                } ?: fail("Shared download was not published")
            }
            report.put("storage_export", true)
            }
            val checkedKeys = mutableListOf("python_engine", "ffmpeg_jni", "tls", "java_aes", "atomic_media_publish")
            if (includeMedia) checkedKeys.addAll(listOf("direct_resume", "aes128_hls", "subtitle_mux", "storage_export", "decode_verification"))
            for (key in checkedKeys) assertTrue(key, report.getBoolean(key))
            assertEquals(200, request("/api/download/status").first)
            println("ANIMAN_ANDROID_PROBE=" + report.toString())
            val instrumentation = InstrumentationRegistry.getInstrumentation()
            val image = instrumentation.uiAutomation.takeScreenshot()
            assertNotNull("Screenshot could not be captured", image)
            val pictures = requireNotNull(context.getExternalFilesDir(null))
            File(pictures, "screen.png").outputStream().use {
                image.compress(Bitmap.CompressFormat.PNG, 100, it)
            }
        }
    }
}
