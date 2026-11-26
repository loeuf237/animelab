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
    private fun completeFirstRun(scenario: ActivityScenario<MainActivity>) {
        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(60)
        while (System.nanoTime() < deadline) {
            val checked = CountDownLatch(1)
            val ready = AtomicBoolean(false)
            scenario.onActivity { activity ->
                activity.findViewById<WebView>(R.id.webView).evaluateJavascript("""
                    (() => {
                        const setup = document.querySelector('.startup-page');
                        if (!setup) {
                            if (!document.querySelector('#main-content')) return false;
                            if (window.location.pathname !== '/spa/') {
                                const home = document.querySelector('a[href="/spa/"]');
                                if (home) home.click();
                                return false;
                            }
                            return true;
                        }
                        const buttons = [...setup.querySelectorAll('button')];
                        const next = buttons.find(b => !b.disabled && ['Suivant','Next','Commencer','Get started','Continuer','Continue','Pas maintenant','Not now'].includes(b.textContent.trim()));
                        if (next) { next.click(); return false; }
                        const folder = buttons.find(b => !b.disabled && b.textContent.trim() === 'Utiliser Downloads/AnimeLab');
                        const englishFolder = buttons.find(b => !b.disabled && b.textContent.trim() === 'Use Downloads/AnimeLab');
                        (folder || englishFolder)?.click();
                        return false;
                    })()
                """.trimIndent()) { ready.set(it == "true"); checked.countDown() }
            }
            checked.await(5, TimeUnit.SECONDS)
            if (ready.get()) return
            Thread.sleep(250)
        }
        fail("First-run configuration did not reach the library")
    }

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
        var lastState = "init"
        while (System.nanoTime() < deadline) {
            val checked = CountDownLatch(1)
            val rendered = AtomicBoolean(false)
            scenario.onActivity { activity ->
                // Keep only this test window awake; closing it restores normal
                // screen behavior without changing the user's timeout settings.
                activity.window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                val webView = activity.findViewById<WebView>(R.id.webView)
                val url = webView.url
                val focus = activity.hasWindowFocus()
                val loadingVis = activity.findViewById<android.view.View>(R.id.loadingLayout).visibility
                if (url?.startsWith(EngineHost.baseUrl + "/spa/") != true ||
                    !focus ||
                    loadingVis != android.view.View.GONE) {
                    lastState = "url=$url focus=$focus loadingVis=$loadingVis"
                    checked.countDown()
                } else webView.evaluateJavascript(
                    "(() => (document.querySelector('#main-content .home-container .home-top-header, #main-content .home-container .hero-panel') ? 'OK' : 'WAIT') + '|' + window.location.pathname + '|main=' + Boolean(document.querySelector('#main-content')) + '|setup=' + Boolean(document.querySelector('.startup-page')))()"
                ) { result ->
                    lastState = "url=$url focus=$focus dom=$result"
                    rendered.set(result?.startsWith("\"OK|") == true)
                    checked.countDown()
                }
            }
            // A renderer can start slowly after recreation. A missed callback
            // does not bypass the overall deadline or the actual DOM check.
            checked.await(5, TimeUnit.SECONDS)
            if (rendered.get()) return
            Thread.sleep(250)
        }
        fail("$message [$lastState]")
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
            val browserUserAgent = VerificationBridge.userAgent()
            assertTrue(browserUserAgent.contains("Mozilla/"))
            val networkIdentity = JSONObject(Python.getInstance().getModule("android_runtime")
                .callAttr("extension_http", "{\"action\":\"user_agent\"}").toString())
            assertEquals(browserUserAgent, networkIdentity.getString("userAgent"))
            var page: Pair<Int, String>? = null
            repeat(30) {
                if (page == null) try { page = request("/spa/") } catch (_: Exception) { Thread.sleep(250) }
            }
            assertEquals(200, page?.first)
            assertTrue(page!!.second.contains("id=\"app\""))
            assertEquals(401, request("/api/download/status", false).first)
            assertEquals(200, request("/api/download/status").first)
            assertEquals(401, request("/api/engine/readiness", false).first)
            val readinessResp = request("/api/engine/readiness")
            assertEquals(200, readinessResp.first)
            assertTrue(JSONObject(readinessResp.second).getBoolean("ready"))
            completeFirstRun(scenario)
            waitForHome(scenario, "Vue did not render in the installed System WebView")
            assertTrue(EngineHost.httpReady)
            val startupTiming = JSONObject(EngineHost.timingJson())
            assertTrue(startupTiming.getLong("shellReadyMs") >= 0L)
            assertTrue(startupTiming.getLong("httpReadyMs") >= 0L)
            val startup = JSONObject(request("/api/app/startup").second)
            assertTrue(startup.getJSONObject("preferences").getBoolean("onboardingCompleted"))
            assertEquals(BuildConfig.RELEASE_VERSION, startup.getString("currentVersion"))
            val reportResp = request(
                "/api/diagnostics/report",
                body = "{\"kind\":\"manual\",\"code\":\"instrumentation_probe\",\"component\":\"EmbeddedEngineTest\",\"route\":\"/spa/\"}"
            )
            assertEquals(200, reportResp.first)
            val diagResp = request("/api/diagnostics/export")
            assertEquals(200, diagResp.first)
            val diagJson = JSONObject(diagResp.second)
            assertTrue(diagJson.optInt("recentErrorCount", 0) >= 1)
            assertTrue(diagJson.has("platform"))
            assertTrue(diagJson.has("lastCrash"))
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
            assertTrue(storage.getBoolean("storageChosen"))
            assertTrue(storage.has("installAppsGranted"))
            assertTrue(storage.has("batteryUnrestricted"))
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
                    val settleDeadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(3)
                    while (pending && System.nanoTime() < settleDeadline) {
                        Thread.sleep(250)
                        pending = JSONObject(request("/api/system/android/storage").second).getBoolean("selectionPending")
                    }
                    continue
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
            assertTrue("SeanimeJsBridge must be available on Android", SeanimeJsBridge.isAvailable())
            val seanimeShim = Python.getInstance()
                .getModule("animelab.services.seanime_runtime")
                .callAttr("load_shim_source")
                .toString()
            val sampleProvider = """
                class Provider {
                  getSettings() { return { episodeServers: ['default'], supportsDub: false }; }
                  async search(opts) {
                    ${'$'}store.set('lastQuery', opts.query);
                    return [{ id: 'demo-1', title: 'Probe ' + opts.query, url: 'https://seanime.invalid/1' }];
                  }
                }
            """.trimIndent()
            assertEquals("ok", SeanimeJsBridge.validateSyntax(seanimeShim, sampleProvider))
            val invokePayload = JSONObject()
                .put("extensionId", "android-probe")
                .put("shim", seanimeShim)
                .put("code", sampleProvider)
                .put("method", "search")
                .put("argsJson", "[{\"query\":\"Naruto\"}]")
                .put("userConfigJson", "{}")
                .put("defaultsJson", "{}")
                .put("storeJson", "{}")
                .put("timeoutMs", 15000)
                .toString()
            val seanimeResult = JSONObject(SeanimeJsBridge.invoke(invokePayload))
            assertTrue("SeanimeJsBridge.invoke failed: $seanimeResult", seanimeResult.getBoolean("ok"))
            assertEquals("Probe Naruto", seanimeResult.getJSONArray("result").getJSONObject(0).getString("title"))
            assertEquals("Naruto", seanimeResult.getJSONObject("store").getString("lastQuery"))
            report.put("seanime_webview", true)
            val probeApk = File(context.filesDir, "engine-state/app-updates/self-update-probe.apk")
            probeApk.parentFile?.mkdirs()
            try {
                File(context.applicationInfo.sourceDir).copyTo(probeApk, overwrite = true)
                val inspectedSelf = JSONObject(ExtensionBridge.inspectSelfUpdate(probeApk.path))
                assertEquals(context.packageName, inspectedSelf.getString("pkg"))
                assertTrue(inspectedSelf.getString("signer").isNotBlank())
                val contentUri = Uri.parse(ExtensionBridge.selfUpdateUri(probeApk.path))
                assertEquals("content", contentUri.scheme)
                assertEquals(0, JSONObject(ExtensionBridge.appUpdateStatus("nonexistent-probe")).length())
                val eventsModule = Python.getInstance().getModule("animelab.platform_events")
                assertNotNull(eventsModule["app_update_install_handler"])
                assertNotNull(eventsModule["app_update_status_handler"])
                assertNotNull(eventsModule["app_update_confirm_handler"])
                val pyStatus = eventsModule.callAttr("app_update_status", "nonexistent-probe")
                assertEquals("{}", pyStatus.toString())
                report.put("self_update_installer_ready", true)
            } finally {
                probeApk.delete()
            }
            report.put("startup_timing", JSONObject(EngineHost.timingJson()))
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
