package com.animan.extensions.probe

import android.os.ParcelFileDescriptor
import android.util.Base64
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.animan.extensions.IExtensionHttp
import eu.kanade.tachiyomi.network.NetworkHelper
import okhttp3.CookieJar
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.util.concurrent.TimeUnit

@RunWith(AndroidJUnit4::class)
class NetworkGatewayTest {
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
}
