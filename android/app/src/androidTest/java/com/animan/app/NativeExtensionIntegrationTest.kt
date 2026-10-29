package com.animan.app

import android.content.Intent
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
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

/** Opt-in physical-device test of the optimized app, Python router and APK worker. */
@RunWith(AndroidJUnit4::class)
class NativeExtensionIntegrationTest {
    private fun request(path: String,body: JSONObject?=null): String {
        val connection=URL(EngineHost.baseUrl+path).openConnection(Proxy.NO_PROXY) as HttpURLConnection
        try {
            connection.connectTimeout=5000; connection.readTimeout=60000
            connection.setRequestProperty("X-Animan-Session",EngineHost.token)
            if(body!=null) {
                connection.requestMethod="POST"; connection.doOutput=true
                connection.setRequestProperty("Content-Type","application/json")
                connection.outputStream.use { it.write(body.toString().toByteArray()) }
            }
            val code=connection.responseCode
            // Do not print response payloads: other installed extensions remain private.
            assertEquals("Embedded API request failed: $path",200,code)
            return connection.inputStream.bufferedReader().use { it.readText() }
        } finally { connection.disconnect() }
    }
    private fun encoded(value: String)=URLEncoder.encode(value,"UTF-8")

    @Test(timeout=240000) fun original_apk_through_python_and_optimized_application() {
        val arguments=InstrumentationRegistry.getArguments()
        val expected=arguments.getString("native_fixture_sha256").orEmpty()
        assumeTrue("Requires the exact controlled installed fixture",expected.matches(Regex("[a-f0-9]{64}")))
        val context=InstrumentationRegistry.getInstrumentation().targetContext
        assertEquals("Use only the dedicated validation installation","com.animan.app.a11test",context.packageName)
        val pkg="eu.kanade.tachiyomi.animeextension.all.animelabfixture.api17"
        val info=context.packageManager.getPackageInfo(pkg,0)
        val digest=MessageDigest.getInstance("SHA-256")
        java.io.File(requireNotNull(info.applicationInfo).sourceDir).inputStream().use { input ->
            val buffer=ByteArray(65536)
            while(true) { val n=input.read(buffer); if(n<0) break; digest.update(buffer,0,n) }
        }
        assertEquals(expected,digest.digest().joinToString("") { "%02x".format(it) })
        EngineHost.start(context,true)
        ActivityScenario.launch<MainActivity>(Intent(context,MainActivity::class.java)).use {
            val deadline=System.nanoTime()+java.util.concurrent.TimeUnit.SECONDS.toNanos(100)
            while(!EngineHost.ready && EngineHost.error==null && System.nanoTime()<deadline) Thread.sleep(250)
            assertNull("Embedded engine failed",EngineHost.error)
            assertTrue("Embedded engine did not start",EngineHost.ready)
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
                .put("pythonRouter",true).put("nativeFilters",true).put("nativePreferences",true).put("quickJs",true)
                .put("operations",JSONArray(listOf("catalogue","preferences","filters")))
                .put("sourceIds",JSONArray(sources.map { it.getString("id") })).put("realHostsInteroperabilityTested",false)
            android.util.Log.i("ANIMELAB_APK_PROOF",proof.toString())
        }
    }
}
