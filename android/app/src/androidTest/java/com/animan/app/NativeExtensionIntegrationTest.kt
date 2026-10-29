package com.animan.app

import android.content.Intent
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.net.HttpURLConnection
import java.net.Proxy
import java.net.URL
import java.net.URLEncoder
import java.security.MessageDigest
import java.util.UUID
import java.util.concurrent.TimeUnit
import java.util.regex.Pattern

/** Opt-in physical-device test of the optimized app, Python router and APK worker. */
@RunWith(AndroidJUnit4::class)
class NativeExtensionIntegrationTest {
    private class TrialFailure(val code: String) : RuntimeException(code)
    private fun request(path: String,body: JSONObject?=null,apk: java.io.File?=null): String {
        val connection=URL(EngineHost.baseUrl+path).openConnection(Proxy.NO_PROXY) as HttpURLConnection
        try {
            connection.connectTimeout=5000; connection.readTimeout=60000
            connection.setRequestProperty("X-Animan-Session",EngineHost.token)
            if(body!=null || apk!=null) {
                connection.requestMethod="POST"; connection.doOutput=true
                connection.setRequestProperty("Content-Type",if(apk==null) "application/json" else "application/octet-stream")
                if(apk!=null) {
                    connection.setFixedLengthStreamingMode(apk.length())
                    connection.outputStream.use { output -> apk.inputStream().use { it.copyTo(output) } }
                } else connection.outputStream.use { it.write(body.toString().toByteArray()) }
            }
            val code=connection.responseCode
            val text=(if(code==200) connection.inputStream else connection.errorStream)
                ?.bufferedReader()?.use { it.readText() }.orEmpty()
            // Do not print URLs, response payloads, sessions or other installed extensions.
            if(code!=200) {
                val failure=try { JSONObject(text).optString("code") } catch (_: Exception) { "" }
                throw TrialFailure(failure.takeIf { it.matches(Regex("[a-z_]{1,80}")) } ?: "http_$code")
            }
            return text
        } finally { connection.disconnect() }
    }
    private fun encoded(value: String)=URLEncoder.encode(value,"UTF-8")

    @Test(timeout=480000) fun original_apk_through_python_and_optimized_application() {
        val arguments=InstrumentationRegistry.getArguments()
        val instrumentation=InstrumentationRegistry.getInstrumentation()
        val context=instrumentation.targetContext
        assertEquals("Use only the dedicated validation installation","com.animan.app.a11test",context.packageName)
        val install=arguments.getString("install_native_fixture")=="true"
        var expected=arguments.getString("native_fixture_sha256").orEmpty()
        val staged=if(install) java.io.File(context.cacheDir,"original-api17-fixture.apk").also { file ->
            instrumentation.context.assets.open("extension-fixture-api17-debug.apk").use { input -> file.outputStream().use(input::copyTo) }
        } else null
        if(staged!=null) expected=MessageDigest.getInstance("SHA-256").digest(staged.readBytes()).joinToString("") { "%02x".format(it) }
        assumeTrue("Requires the exact controlled installed fixture or opt-in installation",expected.matches(Regex("[a-f0-9]{64}")))
        val pkg="eu.kanade.tachiyomi.animeextension.all.animelabfixture.api17"
        EngineHost.start(context,true)
        ActivityScenario.launch<MainActivity>(Intent(context,MainActivity::class.java)).use {
            it.onActivity { activity -> activity.window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) }
            val deadline=System.nanoTime()+java.util.concurrent.TimeUnit.SECONDS.toNanos(100)
            while(!EngineHost.ready && EngineHost.error==null && System.nanoTime()<deadline) Thread.sleep(250)
            assertNull("Embedded engine failed",EngineHost.error)
            assertTrue("Embedded engine did not start",EngineHost.ready)
            var inventory: String?=null
            repeat(30) {
                if(inventory==null) try { inventory=request("/api/extensions/android") }
                catch (_: java.io.IOException) { Thread.sleep(250) }
            }
            requireNotNull(inventory) { "Embedded HTTP owner did not bind" }
            if(staged!=null) {
                assertTrue("Grant install AppOp before instrumentation",context.packageManager.canRequestPackageInstalls())
                val operation=JSONObject(request("/api/extensions/android/install-apk",apk=staged)).getJSONObject("operation")
                val device=UiDevice.getInstance(instrumentation)
                val installDeadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(240)
                var current=operation
                var confirmedRequest=0
                while(System.nanoTime()<installDeadline) {
                    val ops=JSONObject(request("/api/extensions/android")).getJSONArray("operations")
                    current=(0 until ops.length()).map { ops.getJSONObject(it) }.single { it.getString("id")==operation.getString("id") }
                    if(current.getString("state") in setOf("installed","failed","cancelled")) break
                    val count=current.optInt("confirmationRequest",1)
                    if(current.getString("state")=="waiting_user" && confirmedRequest<count &&
                        device.currentPackageName.orEmpty().contains("packageinstaller")) {
                        device.wait(Until.findObject(By.text(Pattern.compile("(?i)^(install|installer|installieren|instalar)$"))),500)?.let { button ->
                            if(button.isEnabled) { button.click(); confirmedRequest=count }
                        }
                    }
                    Thread.sleep(500)
                }
                assertEquals("Original fixture installation: $current","installed",current.getString("state"))
            }
            val info=context.packageManager.getPackageInfo(pkg,0)
            val digest=MessageDigest.getInstance("SHA-256")
            java.io.File(requireNotNull(info.applicationInfo).sourceDir).inputStream().use { input ->
                val buffer=ByteArray(65536)
                while(true) { val n=input.read(buffer); if(n<0) break; digest.update(buffer,0,n) }
            }
            assertEquals(expected,digest.digest().joinToString("") { "%02x".format(it) })
            val packages=JSONObject(request("/api/extensions/android")).getJSONArray("packages")
            val fixture=(0 until packages.length()).map { packages.getJSONObject(it) }.single { it.getString("pkg")==pkg }
            request("/api/extensions/android/$pkg/trust",JSONObject().put("approved",true)
                .put("versionCode",fixture.getString("versionCode")).put("signer",fixture.getString("signer")))
            val list=JSONObject(request("/api/sources")).getJSONArray("sources")
            val sources=(0 until list.length()).map { list.getJSONObject(it) }.filter { it.getString("name").startsWith("Fixture 17 ") }
            assertEquals(2,sources.size)
            val id=sources.single { it.getString("lang")=="fr" }.getString("id")
            assertTrue(id.startsWith("aniyomi:"))
            request("/api/extensions/android/sources/${encoded(id)}/set_preferences",JSONObject().put("quality","1080"))
            val filters=JSONObject(request("/api/sources/${encoded(id)}/filters")).getJSONArray("nativeFilters")
            filters.getJSONObject(0).put("state","through-python")
            val nonce=UUID.randomUUID().toString()
            val result=JSONObject(request("/api/sources/${encoded(id)}/catalogue?mode=search&q=${encoded(nonce)}&nativeFilters=${encoded(filters.toString())}"))
            val anime=result.getJSONArray("results").getJSONObject(0)
            assertEquals(id,anime.getString("source"))
            assertTrue(anime.getString("title").endsWith("${nonce.reversed()}:42:1080:through-python"))
            val proof=JSONObject().put("androidApi",android.os.Build.VERSION.SDK_INT).put("abi",android.os.Build.SUPPORTED_ABIS[0])
                .put("optimizedApplication",true).put("artifactSha256",expected).put("realAPKClassExecution",true)
                .put("packageInstallerViaPythonAPI",staged!=null)
                .put("pythonRouter",true).put("nativeFilters",true).put("nativePreferences",true).put("quickJs",true)
                .put("operations",JSONArray(listOf("catalogue","preferences","filters")))
                .put("sourceIds",JSONArray(sources.map { it.getString("id") })).put("realHostsInteroperabilityTested",false)
            android.util.Log.i("ANIMELAB_APK_PROOF",proof.toString())
        }
    }

    /** Explicitly selected community APKs only; never install, update or mutate another host. */
    @Test(timeout=900000) fun selected_community_apks_through_embedded_python_and_network() {
        val selected=InstrumentationRegistry.getArguments().getString("community_packages").orEmpty()
            .split(',').filter { it.isNotBlank() }
        assumeTrue("Opt-in installed community APK corpus",selected.isNotEmpty())
        require(selected.size<=3 && selected.distinct().size==selected.size && selected.all {
            it.matches(Regex("eu\\.kanade\\.tachiyomi\\.animeextension\\.[a-z0-9_.]+")) && !it.contains("animelabfixture")
        })
        val context=InstrumentationRegistry.getInstrumentation().targetContext
        assertEquals("com.animan.app.a11test",context.packageName)
        EngineHost.start(context,true)
        ActivityScenario.launch<MainActivity>(Intent(context,MainActivity::class.java)).use { scenario ->
            scenario.onActivity { activity -> activity.window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) }
            val deadline=System.nanoTime()+java.util.concurrent.TimeUnit.SECONDS.toNanos(100)
            while(!EngineHost.ready && EngineHost.error==null && System.nanoTime()<deadline) Thread.sleep(250)
            assertNull("Embedded engine failed",EngineHost.error)
            assertTrue("Embedded engine did not start",EngineHost.ready)
            var inventory: String?=null
            repeat(30) {
                if(inventory==null) try { inventory=request("/api/extensions/android") }
                catch (_: java.io.IOException) { Thread.sleep(250) }
            }
            val packages=JSONObject(requireNotNull(inventory)).getJSONArray("packages")
            val cases=JSONArray()
            val runtimeFailures=mutableListOf<String>()
            for(pkg in selected) {
                val before=context.packageManager.getPackageInfo(pkg,0)
                val descriptor=(0 until packages.length()).map { packages.getJSONObject(it) }.single { it.getString("pkg")==pkg }
                val proof=JSONObject().put("pkg",pkg).put("versionCode",descriptor.getString("versionCode"))
                    .put("signer",descriptor.getString("signer")).put("operations",JSONArray())
                val steps=proof.getJSONArray("operations")
                var phase="trust"
                try {
                    request("/api/extensions/android/$pkg/trust",JSONObject().put("approved",true)
                        .put("versionCode",descriptor.getString("versionCode")).put("signer",descriptor.getString("signer")))
                    steps.put(phase)
                    val refreshed=JSONObject(request("/api/extensions/android")).getJSONArray("packages")
                    val loaded=(0 until refreshed.length()).map { refreshed.getJSONObject(it) }.single { it.getString("pkg")==pkg }
                    if(loaded.optString("state")!="loaded") throw TrialFailure("extension_load_failed")
                    val sources=loaded.getJSONArray("sources")
                    assertTrue(sources.length()>0)
                    val source=sources.getJSONObject(0)
                    val sourceId="aniyomi:"+source.getString("id")
                    fun native(operation: String,payload: JSONObject): Any {
                        val result=JSONObject(ExtensionBridge.invoke(JSONObject().put("operationId",UUID.randomUUID().toString())
                            .put("operation",operation).put("pkg",pkg).put("sourceId",source.getString("id"))
                            .put("payload",payload).toString()))
                        if(!result.optBoolean("ok")) throw TrialFailure(result.optString("code","extension_runtime_error"))
                        return result.get("result")
                    }
                    phase="filters"
                    request("/api/sources/${encoded(sourceId)}/filters"); steps.put(phase)
                    phase="preferences"
                    request("/api/extensions/android/sources/${encoded(sourceId)}/preferences",JSONObject()); steps.put(phase)
                    phase="popular"
                    val catalogue=JSONObject(request("/api/sources/${encoded(sourceId)}/catalogue?mode=popular"))
                    val results=catalogue.getJSONArray("results")
                    proof.put("catalogueResults",results.length()); steps.put(phase)
                    if(results.length()==0) throw TrialFailure("empty_catalogue")
                    phase="detail"
                    val detail=JSONObject(request("/api/anime/detail?url=${encoded(results.getJSONObject(0).getString("url"))}&source=${encoded(sourceId)}"))
                    val episodes=detail.getJSONObject("anime").getJSONArray("episodes")
                    proof.put("episodes",episodes.length()); steps.put(phase)
                    if(episodes.length()==0) throw TrialFailure("empty_episode_list")
                    phase="hosters"
                    val hosts=native("hosters",episodes.getJSONObject(0).getJSONObject("nativeMetadata")) as JSONArray
                    proof.put("hosters",hosts.length()); steps.put(phase)
                    if(hosts.length()==0) throw TrialFailure("empty_hoster_list")
                    phase="videos"
                    val videos=native("videos",hosts.getJSONObject(0)) as JSONArray
                    proof.put("videos",videos.length()); steps.put(phase)
                    if(videos.length()==0) throw TrialFailure("empty_video_list")
                    phase="resolve_video"
                    val resolved=native("resolve_video",videos.getJSONObject(0)) as JSONObject
                    if(resolved.optString("videoUrl").isBlank()) throw TrialFailure("empty_video_url")
                    steps.put(phase); proof.put("state","metadata_path_passed")
                } catch (failure: TrialFailure) {
                    proof.put("state","verification_needed").put("phase",phase).put("code",failure.code)
                    if(failure.code.startsWith("extension_") || failure.code=="source_operation_unsupported") runtimeFailures.add(pkg+":"+phase+":"+failure.code)
                } catch (_: java.io.IOException) {
                    proof.put("state","verification_needed").put("phase",phase).put("code","probe_transport_error")
                } finally {
                    val after=context.packageManager.getPackageInfo(pkg,0)
                    assertEquals(before.firstInstallTime,after.firstInstallTime)
                    assertEquals(before.lastUpdateTime,after.lastUpdateTime)
                    proof.put("notReinstalled",true); cases.put(proof)
                }
            }
            android.util.Log.i("ANIMELAB_APK_PROOF",JSONObject().put("communityAPKOperations",cases)
                .put("androidApi",android.os.Build.VERSION.SDK_INT).put("abi",android.os.Build.SUPPORTED_ABIS[0])
                .put("optimizedApplication",true).put("pythonNetworkGateway",true)
                .put("mediaPlaybackTested",false).put("mediaDownloadRequested",false).put("otherHostsModified",false).toString())
            assertTrue("Runtime incompatibilities: $runtimeFailures",runtimeFailures.isEmpty())
        }
    }
}
