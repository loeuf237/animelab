package com.animan.app

import android.content.Context
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import java.io.ByteArrayInputStream
import java.io.IOException
import java.util.Locale

object SpaAssetInterceptor {
    @Volatile
    private var packagedShellCached: Boolean? = null

    fun hasPackagedShell(context: Context): Boolean {
        packagedShellCached?.let { return it }
        val available = try {
            context.assets.open("spa/index.html").use { true }
        } catch (_: IOException) {
            false
        }
        packagedShellCached = available
        return available
    }

    fun shouldIntercept(context: Context, request: WebResourceRequest): WebResourceResponse? {
        val uri = request.url ?: return null
        if (uri.scheme != "http" || uri.host != "127.0.0.1" || uri.port != EngineHost.port) {
            return null
        }

        val path = uri.path ?: return null
        val method = request.method ?: "GET"

        if (path.startsWith("/api/")) {
            if (EngineHost.httpReady) return null
            if (EngineHost.ready && method.equals("GET", ignoreCase = true)) {
                if (EngineHost.awaitHttpReadyBlocking(2000L)) return null
            }
            return jsonError(503, "Service Unavailable", "{\"error\":\"Engine starting\"}")
        }

        if (path == "/sw.js" && !EngineHost.httpReady) {
            return textError(404, "Not Found", "")
        }

        val isGet = method.equals("GET", ignoreCase = true)
        val isHead = method.equals("HEAD", ignoreCase = true)
        if (!isGet && !isHead) return null

        if (isSpaDocumentPath(path)) {
            return openAssetResponse(
                context = context,
                assetPath = "spa/index.html",
                headOnly = isHead,
                cacheControl = "no-cache, no-store, must-revalidate",
            )
        }

        val encodedPath = uri.encodedPath ?: path
        if (!isSafeAssetUriPath(path, encodedPath)) return null

        return when {
            path.startsWith("/assets/") -> openAssetResponse(
                context = context,
                assetPath = "spa$path",
                headOnly = isHead,
                cacheControl = "public, max-age=31536000, immutable",
            )
            path == "/manifest.json" -> openAssetResponse(
                context = context,
                assetPath = "spa/manifest.json",
                headOnly = isHead,
                cacheControl = "no-cache",
            )
            path == "/icons.svg" || path == "/favicon.svg" || path.startsWith("/img/") -> openAssetResponse(
                context = context,
                assetPath = "spa$path",
                headOnly = isHead,
                cacheControl = "public, max-age=3600",
            )
            else -> null
        }
    }

    private fun isSpaDocumentPath(path: String): Boolean =
        path == "/spa" || path.startsWith("/spa/") || path == "/app" || path.startsWith("/app/")

    private fun isSafeAssetUriPath(path: String, encodedPath: String): Boolean {
        if (!path.startsWith("/") || path.contains('\u0000') || path.contains('\\')) return false
        val lowerEncoded = encodedPath.lowercase(Locale.US)
        if (lowerEncoded.contains("%2e") || lowerEncoded.contains("%2f") || lowerEncoded.contains("%5c")) {
            return false
        }
        val trimmed = path.removePrefix("/")
        if (trimmed.isEmpty()) return false
        val segments = trimmed.split('/')
        return segments.none { it.isEmpty() || it == "." || it == ".." }
    }

    private fun openAssetResponse(
        context: Context,
        assetPath: String,
        headOnly: Boolean,
        cacheControl: String,
    ): WebResourceResponse? {
        val stream = try {
            val opened = context.assets.open(assetPath)
            if (headOnly) {
                opened.close()
                ByteArrayInputStream(ByteArray(0))
            } else {
                opened
            }
        } catch (_: IOException) {
            return null
        }

        val (mime, encoding) = mimeTypeFor(assetPath)
        val headers = linkedMapOf(
            "Cache-Control" to cacheControl,
            "X-Content-Type-Options" to "nosniff",
            "Access-Control-Allow-Origin" to EngineHost.baseUrl,
            "Vary" to "Origin",
        )
        return WebResourceResponse(mime, encoding, 200, "OK", headers, stream)
    }

    private fun mimeTypeFor(assetPath: String): Pair<String, String?> {
        val ext = assetPath.substringAfterLast('.', "").lowercase(Locale.US)
        return when (ext) {
            "html" -> "text/html" to "UTF-8"
            "js", "mjs" -> "application/javascript" to "UTF-8"
            "css" -> "text/css" to "UTF-8"
            "json" -> "application/json" to "UTF-8"
            "svg" -> "image/svg+xml" to "UTF-8"
            "png" -> "image/png" to null
            "jpg", "jpeg" -> "image/jpeg" to null
            "webp" -> "image/webp" to null
            "ico" -> "image/x-icon" to null
            "woff" -> "font/woff" to null
            "woff2" -> "font/woff2" to null
            else -> "application/octet-stream" to null
        }
    }

    private fun jsonError(status: Int, reason: String, body: String): WebResourceResponse =
        WebResourceResponse(
            "application/json",
            "UTF-8",
            status,
            reason,
            mapOf("Cache-Control" to "no-store", "X-Content-Type-Options" to "nosniff"),
            ByteArrayInputStream(body.toByteArray(Charsets.UTF_8)),
        )

    private fun textError(status: Int, reason: String, body: String): WebResourceResponse =
        WebResourceResponse(
            "text/plain",
            "UTF-8",
            status,
            reason,
            mapOf("Cache-Control" to "no-store", "X-Content-Type-Options" to "nosniff"),
            ByteArrayInputStream(body.toByteArray(Charsets.UTF_8)),
        )
}
