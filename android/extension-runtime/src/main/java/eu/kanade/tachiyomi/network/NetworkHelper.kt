package eu.kanade.tachiyomi.network

import android.content.Context
import android.util.Base64
import com.animan.extensions.IExtensionHttp
import okhttp3.Headers
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import okio.Buffer
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

/** Default source HTTP goes through the existing Python URL/session/proxy policy. */
class NetworkHelper(context: Context) {
    val cookieJar = AndroidCookieJar()
    val client: OkHttpClient = OkHttpClient.Builder()
        .cookieJar(cookieJar)
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .callTimeout(45, TimeUnit.SECONDS)
        .addInterceptor { chain ->
            val original = chain.request()
            val body = Buffer()
            original.body?.writeTo(body)
            if (body.size > 2_000_000) throw IOException("Request body exceeds budget")
            val payload = JSONObject().put("url", original.url.toString()).put("method", original.method)
                .put("headers", JSONArray(original.headers.map { JSONArray(listOf(it.first, it.second)) }))
                .put("body", Base64.encodeToString(body.readByteArray(), Base64.NO_WRAP))
            val bridge = gateway ?: throw IOException("The source network gateway is unavailable")
            val descriptor = bridge.request(payload.toString()) ?: throw IOException("The source request failed")
            val bytes = android.os.ParcelFileDescriptor.AutoCloseInputStream(descriptor).use { input ->
                val output = java.io.ByteArrayOutputStream()
                val buffer = ByteArray(65536)
                while (true) {
                    val n = input.read(buffer)
                    if (n < 0) break
                    if (output.size() + n > 16_000_000) throw IOException("Response exceeds budget")
                    output.write(buffer, 0, n)
                }
                output.toByteArray()
            }
            val response = JSONObject(String(bytes, Charsets.UTF_8))
            if (response.has("error")) throw IOException(response.getString("error"))
            val headers = Headers.Builder()
            val pairs = response.optJSONArray("headers") ?: JSONArray()
            for (i in 0 until pairs.length()) {
                val pair = pairs.getJSONArray(i)
                if (pair.getString(0).lowercase() !in setOf("content-encoding", "content-length"))
                    headers.add(pair.getString(0), pair.getString(1))
            }
            val content = Base64.decode(response.getString("body"), Base64.DEFAULT)
            Response.Builder().request(original.newBuilder().url(response.optString("url", original.url.toString())).build())
                .protocol(Protocol.HTTP_1_1).code(response.getInt("status")).message("Source response")
                .headers(headers.build()).body(content.toResponseBody(response.optString("contentType").toMediaTypeOrNull())).build()
        }.build()

    val cloudflareClient: OkHttpClient get() = client
    fun defaultUserAgentProvider(): String = "AnimeLab/0.1.5"

    companion object {
        @Volatile var gateway: IExtensionHttp? = null
    }
}
