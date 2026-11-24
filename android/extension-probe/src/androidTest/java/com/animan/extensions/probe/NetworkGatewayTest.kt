package com.animan.extensions.probe

import android.os.ParcelFileDescriptor
import android.util.Base64
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.animan.extensions.IExtensionHttp
import eu.kanade.tachiyomi.network.NetworkHelper
import eu.kanade.tachiyomi.animesource.online.AnimeHttpSource
import okhttp3.CookieJar
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.util.concurrent.TimeUnit
import uy.kohesive.injekt.Injekt
import uy.kohesive.injekt.api.*

@RunWith(AndroidJUnit4::class)
class NetworkGatewayTest {
    @Test fun aggregate_deadline_is_a_timeout_and_explicit_cancel_remains_cancelled() = kotlinx.coroutines.runBlocking {
        val failure = runCatching {
            kotlinx.coroutines.withTimeout(10) { kotlinx.coroutines.delay(1_000) }
        }.exceptionOrNull()!!
        assertEquals("extension_runtime_timeout", com.animan.extensions.ExtensionOperationPolicy.failureCode(failure))
        assertEquals("cancelled", com.animan.extensions.ExtensionOperationPolicy.failureCode(kotlinx.coroutines.CancellationException("user")))
        for (operation in listOf("search", "detail", "hosters", "videos", "resolve_video", "preferences")) {
            val worker = com.animan.extensions.ExtensionOperationPolicy.workerTimeoutMillis(operation)
            val parent = com.animan.extensions.ExtensionOperationPolicy.parentTimeoutMillis(operation)
            assertTrue(worker < parent && parent <= 180_000)
        }
        assertTrue(com.animan.extensions.ExtensionOperationPolicy.workerTimeoutMillis("hosters") >
            com.animan.extensions.ExtensionOperationPolicy.workerTimeoutMillis("preferences"))
    }
    @Test fun source_scripts_keep_their_origin_without_overriding_extension_headers_or_other_hosts() {
        val requests=mutableListOf<JSONObject>()
        val before=NetworkHelper.gateway
        NetworkHelper.gateway=object : IExtensionHttp.Stub() {
            override fun request(payload: String): ParcelFileDescriptor {
                val input=JSONObject(payload); requests.add(input)
                val result=JSONObject().put("url",input.getString("url")).put("status",200)
                    .put("headers",JSONArray()).put("contentType","application/javascript")
                    .put("body",Base64.encodeToString("var eps1=[];".toByteArray(),Base64.NO_WRAP))
                val pipe=ParcelFileDescriptor.createPipe()
                ParcelFileDescriptor.AutoCloseOutputStream(pipe[1]).use { it.write(result.toString().toByteArray()) }
                return pipe[0]
            }
        }
        try {
            val helper=NetworkHelper(InstrumentationRegistry.getInstrumentation().targetContext)
            Injekt.importModule(object : InjektModule {
                override fun InjektRegistrar.registerInjectables() { addSingleton<NetworkHelper>(helper) }
            })
            val source=object : AnimeHttpSource() {
                override val name="Script origin fixture"
                override val lang="fr"
                override val supportsLatest=false
                override var baseUrl="https://private:credential@source.fixture.invalid/path?secret=value#private"
            }
            val client=source.client.newBuilder().cookieJar(CookieJar.NO_COOKIES)
                .addInterceptor { chain -> chain.proceed(chain.request().newBuilder().header("X-Source","derived").build()) }
                .build()
            fun fetch(url: String, expected: String?, referer: String?=null, method: String="GET") {
                val request=Request.Builder().url(url).apply {
                    if(referer!=null) header("Referer",referer)
                    if(method=="HEAD") head()
                    if(method=="POST") post("payload".toRequestBody())
                }.build()
                client.newCall(request).execute().use { assertEquals(200,it.code) }
                val headers=requests.last().getJSONArray("headers")
                val values=(0 until headers.length()).associate { i -> headers.getJSONArray(i).let {
                    it.getString(0).lowercase() to it.getString(1)
                } }
                assertEquals(expected,values["referer"])
                assertEquals("derived",values["x-source"])
            }
            val script="https://source.fixture.invalid/catalogue/season/episodes.js"
            fetch(script,"https://source.fixture.invalid/")
            fetch(script,"https://source.fixture.invalid/",method="HEAD")
            fetch(script,"https://explicit.fixture.invalid/",referer="https://explicit.fixture.invalid/")
            fetch(script,"",referer="")
            fetch("https://source.fixture.invalid/video.mp4",null)
            fetch("https://cdn.fixture.invalid/episodes.js",null)
            fetch("https://source.fixture.invalid:444/episodes.js",null)
            fetch("http://source.fixture.invalid/episodes.js",null)
            fetch(script,null,method="POST")
            source.baseUrl="https://mirror.fixture.invalid/new-path"
            fetch("https://mirror.fixture.invalid/episodes.js","https://mirror.fixture.invalid/")
            fetch(script,null)
        } finally { NetworkHelper.gateway=before }
    }

    @Test fun derived_client_interceptors_can_follow_redirects_and_change_chain_options_without_sockets() {
        val requests=mutableListOf<JSONObject>()
        val before=NetworkHelper.gateway
        NetworkHelper.gateway=object : IExtensionHttp.Stub() {
            override fun request(payload: String): ParcelFileDescriptor {
                val input=JSONObject(payload)
                requests.add(input)
                val first=input.getString("url").endsWith("/start")
                val result=JSONObject().put("url",input.getString("url")).put("status",if(first) 302 else 200)
                    .put("headers",if(first) JSONArray().put(JSONArray(listOf("Location","https://second.fixture.invalid/end"))) else JSONArray())
                    .put("contentType","text/plain").put("body",Base64.encodeToString("computed".toByteArray(),Base64.NO_WRAP))
                val pipe=ParcelFileDescriptor.createPipe()
                ParcelFileDescriptor.AutoCloseOutputStream(pipe[1]).use { it.write(result.toString().toByteArray()) }
                return pipe[0]
            }
        }
        try {
            val helper=NetworkHelper(InstrumentationRegistry.getInstrumentation().targetContext)
            var callbacks=0
            val client=helper.client.newBuilder().cookieJar(CookieJar.NO_COOKIES).followRedirects(false)
                .addInterceptor { original ->
                    callbacks++
                    val chain=original.withReadTimeout(4,TimeUnit.SECONDS)
                    val request=chain.request().newBuilder().header("X-Source-Callback","ran").build()
                    val response=chain.proceed(request)
                    assertEquals(302,response.code)
                    val target=requireNotNull(response.header("Location")); response.close()
                    chain.proceed(request.newBuilder().url(target).build()).newBuilder().header("X-Source-Response","ran").build()
                }.build()
            client.newCall(Request.Builder().url("https://first.fixture.invalid/start").build()).execute().use { response ->
                assertEquals("computed",response.body.string())
                assertEquals("ran",response.header("X-Source-Response"))
            }
            assertEquals(1,callbacks)
            assertEquals(2,requests.size)
            for(request in requests) {
                assertFalse(request.getBoolean("followRedirects"))
                assertEquals(4000,request.getInt("readTimeoutMillis"))
                val headers=request.getJSONArray("headers")
                assertTrue((0 until headers.length()).any { headers.getJSONArray(it).let { pair -> pair.getString(0)=="X-Source-Callback" && pair.getString(1)=="ran" } })
            }
            assertTrue(requests.last().getString("url").startsWith("https://second.fixture.invalid/"))
        } finally { NetworkHelper.gateway=before }
    }

    @Test fun network_interceptors_execute_without_sockets() {
        val requests = mutableListOf<JSONObject>()
        val before = NetworkHelper.gateway
        NetworkHelper.gateway = object : IExtensionHttp.Stub() {
            override fun request(payload: String): ParcelFileDescriptor {
                val input = JSONObject(payload)
                requests.add(input)
                val result = JSONObject().put("url", input.getString("url")).put("status", 200)
                    .put("headers", JSONArray())
                    .put("contentType", "application/json")
                    .put("body", Base64.encodeToString("{\"ok\":true}".toByteArray(), Base64.NO_WRAP))
                val pipe = ParcelFileDescriptor.createPipe()
                ParcelFileDescriptor.AutoCloseOutputStream(pipe[1]).use { it.write(result.toString().toByteArray()) }
                return pipe[0]
            }
        }
        try {
            val helper = NetworkHelper(InstrumentationRegistry.getInstrumentation().targetContext)
            val client = helper.client.newBuilder().cookieJar(CookieJar.NO_COOKIES)
                .addNetworkInterceptor { chain ->
                    val req = chain.request().newBuilder().header("X-Net-Interceptor", "active").build()
                    chain.proceed(req).newBuilder().header("X-Net-Handled", "yes").build()
                }.build()
            client.newCall(Request.Builder().url("https://api.fixture.invalid/graphql").build()).execute().use { response ->
                assertEquals(200, response.code)
                assertEquals("yes", response.header("X-Net-Handled"))
                assertEquals("{\"ok\":true}", response.body.string())
            }
            val headers = requests.single().getJSONArray("headers")
            assertTrue((0 until headers.length()).any {
                headers.getJSONArray(it).let { p -> p.getString(0) == "X-Net-Interceptor" && p.getString(1) == "active" }
            })
        } finally { NetworkHelper.gateway = before }
    }
}
