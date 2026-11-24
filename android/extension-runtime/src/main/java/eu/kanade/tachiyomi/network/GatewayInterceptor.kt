package eu.kanade.tachiyomi.network

import okhttp3.Interceptor
import okhttp3.Response
import okhttp3.internal.connection.RealCall
import okhttp3.internal.http.RealInterceptorChain

/**
 * Keep derived clients' application interceptors in front of the Python transport.
 * The adapter uses the pinned OkHttp 5.4 chain implementation; no socket is opened.
 * https://github.com/square/okhttp/blob/parent-5.4.0/okhttp/src/commonJvmAndroid/kotlin/okhttp3/internal/http/RealInterceptorChain.kt
 */
internal class GatewayInterceptor(private val transport: (Interceptor.Chain) -> Response) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val call=chain.call() as? RealCall ?: throw UnsupportedOperationException("Unsupported OkHttp call implementation")
        val client=call.client
        val index=client.interceptors.indexOfFirst { it===this }
        check(index>=0)
        // Route network interceptors through the same RealInterceptorChain before
        // delegating HTTP transport to the Python gateway so extensions remain socket-free.
        val remaining=client.interceptors.drop(index+1)+client.networkInterceptors+Interceptor { transport(it) }
        // Use OkHttp's chain rather than a partial wrapper: withReadTimeout,
        // withCookieJar and the other chain options must retain the broker.
        val rerouted=RealInterceptorChain(
            call=call, interceptors=remaining, index=0, exchange=null, request=chain.request(),
            connectTimeoutMillis=chain.connectTimeoutMillis(), readTimeoutMillis=chain.readTimeoutMillis(),
            writeTimeoutMillis=chain.writeTimeoutMillis(), authenticator=chain.authenticator,
            cache=chain.cache, certificatePinner=chain.certificatePinner, connectionPool=chain.connectionPool,
            cookieJar=chain.cookieJar, dns=chain.dns, hostnameVerifier=chain.hostnameVerifier,
            proxy=chain.proxy, proxyAuthenticator=chain.proxyAuthenticator, proxySelector=chain.proxySelector,
            retryOnConnectionFailure=chain.retryOnConnectionFailure, socketFactory=chain.socketFactory,
            sslSocketFactoryOrNull=chain.sslSocketFactoryOrNull, x509TrustManagerOrNull=chain.x509TrustManagerOrNull,
            certificateChainCleaner=(chain as? RealInterceptorChain)?.certificateChainCleaner,
        )
        return rerouted.proceed(chain.request())
    }
}
