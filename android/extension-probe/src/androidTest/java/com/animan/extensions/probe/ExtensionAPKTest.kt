package com.animan.extensions.probe

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.os.IBinder
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until
import com.animan.app.ExtensionPackages
import com.animan.extensions.IExtensionRuntime
import com.animan.extensions.ExtensionHostClient
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.regex.Pattern

@RunWith(AndroidJUnit4::class)
class ExtensionAPKTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context = instrumentation.targetContext
    private val device = UiDevice.getInstance(instrumentation)
    private fun decoded(raw: String): Any {
        val value=JSONObject(raw)
        assertTrue("Native error: $value",value.optBoolean("ok"))
        return value.get("result")
    }

    @Test fun original_apks_install_discover_execute_and_preserve_source_preferences() {
        device.executeShellCommand("appops set ${context.packageName} REQUEST_INSTALL_PACKAGES allow")
        ActivityScenario.launch(ProbeActivity::class.java).use {
            val latch=CountDownLatch(1)
            lateinit var runtime: IExtensionRuntime
            val connection=object : ServiceConnection {
                override fun onServiceConnected(name: ComponentName, binder: IBinder) { runtime=IExtensionRuntime.Stub.asInterface(binder); latch.countDown() }
                override fun onServiceDisconnected(name: ComponentName) { }
            }
            assertTrue(context.bindService(Intent(context,com.animan.extensions.ExtensionRuntimeService::class.java),connection,Context.BIND_AUTO_CREATE))
            try {
                assertTrue(latch.await(20,TimeUnit.SECONDS))
                val proofs=JSONArray()
                for (api in 12..17) {
                    val assets=context.assets.list("")!!.toList()
                    val asset=requireNotNull(assets.singleOrNull { it.endsWith("api$api-debug.apk") }) { "Missing fixture api$api; assets=$assets" }
                    val apk=File(context.cacheDir,asset)
                    context.assets.open(asset).use { input -> apk.outputStream().use(input::copyTo) }
                    val pkg="eu.kanade.tachiyomi.animeextension.all.animelabfixture.api$api"
                    val inspection=ExtensionPackages.inspect(context,apk.path)
                    assertEquals(pkg,inspection.getString("pkg"))
                    val installation=ExtensionPackages.install(context,apk.path,pkg)
                    val deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(60)
                    var state=""
                    while (System.nanoTime()<deadline) {
                        device.wait(Until.findObject(By.text(Pattern.compile("(?i)^(install|installer|installieren|instalar)$"))),500)?.click()
                        val ops=ExtensionPackages.operations(context)
                        state=(0 until ops.length()).map { ops.getJSONObject(it) }.single { it.getString("id")==installation.getString("id") }.getString("state")
                        if (state in listOf("installed","failed","cancelled")) break
                        Thread.sleep(150)
                    }
                    assertEquals("PackageInstaller state for $pkg", "installed",state)
                    fun discovered(): JSONObject {
                        val packages=decoded(runtime.discover()) as JSONArray
                        return requireNotNull((0 until packages.length()).map { packages.getJSONObject(it) }.singleOrNull { it.getString("pkg")==pkg }) { "Installed $pkg absent from discovery: $packages" }
                    }
                    var descriptor=discovered()
                    assertEquals("untrusted",descriptor.getString("state"))
                    fun call(operation: String, source: String="", payload: JSONObject=JSONObject(), extra: JSONObject=JSONObject()): Any {
                        val request=JSONObject().put("operationId",UUID.randomUUID().toString()).put("operation",operation)
                            .put("pkg",pkg).put("sourceId",source).put("payload",payload)
                        extra.keys().forEach { key -> request.put(key,extra.get(key)) }
                        return decoded(runtime.invoke(request.toString()))
                    }
                    call("trust",extra=JSONObject().put("versionCode",descriptor.getString("versionCode")).put("signer",descriptor.getString("signer")))
                    descriptor=discovered()
                    assertEquals("loaded",descriptor.getString("state"))
                    val sources=descriptor.getJSONArray("sources")
                    assertEquals(2,sources.length())
                    val fr=(0 until sources.length()).map { sources.getJSONObject(it) }.single { it.getString("lang")=="fr" }.getString("id")
                    val en=(0 until sources.length()).map { sources.getJSONObject(it) }.single { it.getString("lang")=="en" }.getString("id")
                    assertNotEquals(fr,en)
                    val query=UUID.randomUUID().toString()
                    val filters=call("filters",fr) as JSONArray
                    filters.getJSONObject(0).put("state","changed")
                    val initial=call("search",fr,JSONObject().put("query",query).put("filters",filters)) as JSONObject
                    assertTrue(initial.getJSONArray("results").getJSONObject(0).getString("title").endsWith("${query.reversed()}:42:720:changed"))
                    call("set_preferences",fr,JSONObject().put("quality","1080"))
                    val changed=call("search",fr,JSONObject().put("query","x")) as JSONObject
                    assertTrue(changed.getJSONArray("results").getJSONObject(0).getString("title").contains(":1080:"))
                    val other=call("search",en,JSONObject().put("query","x")) as JSONObject
                    assertTrue(other.getJSONArray("results").getJSONObject(0).getString("title").contains(":720:"))
                    val detail=call("detail",fr,JSONObject().put("url","/anime/fixture")) as JSONObject
                    assertEquals(1,detail.getJSONArray("episodes").length())
                    val hosters=call("hosters",fr,detail.getJSONArray("episodes").getJSONObject(0)) as JSONArray
                    val videos=call("videos",fr,hosters.getJSONObject(0)) as JSONArray
                    assertEquals("https://fixture.example/stream.m3u8",videos.getJSONObject(0).getString("videoUrl"))
                    assertEquals(1,videos.getJSONObject(0).getJSONArray("subtitleTracks").length())
                    proofs.put(JSONObject().put("api",api).put("pkg",pkg).put("systemInstalled",true)
                        .put("unchangedSigner",inspection.getString("signer")==descriptor.getString("signer"))
                        .put("sources",2).put("executesComputedCode",true).put("javaScript",true).put("preferencesScoped",true))
                }
                ExtensionHostClient(context,timeoutMillis=8_000).use { client ->
                    fun selected(): JSONObject {
                        val packages=decoded(client.discover()) as JSONArray
                        return (0 until packages.length()).map { packages.getJSONObject(it) }.single { it.getString("pkg").endsWith(".api17") }
                    }
                    val descriptor=selected()
                    val sources=descriptor.getJSONArray("sources")
                    val fr=(0 until sources.length()).map { sources.getJSONObject(it) }.single { it.getString("lang")=="fr" }.getString("id")
                    fun request(query: String) = JSONObject().put("operationId",UUID.randomUUID().toString())
                        .put("pkg",descriptor.getString("pkg")).put("sourceId",fr).put("operation","search")
                        .put("payload",JSONObject().put("query",query)).toString()
                    val blocked=JSONObject(client.invoke(request("__block_worker__")))
                    assertFalse(blocked.getBoolean("ok"))
                    assertEquals("extension_runtime_timeout",blocked.getString("code"))
                    // A fresh process must rebind and reload without retaining dead Binder/classes.
                    Thread.sleep(1500)
                    assertEquals("loaded",selected().getString("state"))
                    val restored=decoded(client.invoke(request("after-restart"))) as JSONObject
                    assertTrue(restored.getJSONArray("results").getJSONObject(0).getString("title").contains(":1080:"))
                }
                val proof=JSONObject().put("androidApi",android.os.Build.VERSION.SDK_INT).put("abis",JSONArray(android.os.Build.SUPPORTED_ABIS.toList()))
                    .put("blockedWorkerTerminated",true).put("workerRestarted",true).put("preferencesSurviveRestart",true)
                    .put("cases",proofs).put("realAniyomiAnikkuHostsTested",false)
                android.util.Log.i("ANIMELAB_APK_PROOF",proof.toString())
                assertEquals(6,proofs.length())
            } finally { context.unbindService(connection) }
        }
    }
}
