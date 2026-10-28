@file:Suppress("DEPRECATION")

package com.animan.extensions

import android.app.Application
import android.app.Service
import android.content.Intent
import android.content.pm.PackageInfo
import android.content.pm.PackageManager
import android.os.Binder
import android.os.IBinder
import dalvik.system.PathClassLoader
import eu.kanade.tachiyomi.animesource.*
import eu.kanade.tachiyomi.animesource.model.*
import eu.kanade.tachiyomi.animesource.online.AnimeHttpSource
import eu.kanade.tachiyomi.network.JavaScriptEngine
import eu.kanade.tachiyomi.network.NetworkHelper
import kotlinx.coroutines.*
import kotlinx.serialization.json.Json
import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest
import java.util.concurrent.ConcurrentHashMap
import uy.kohesive.injekt.Injekt
import uy.kohesive.injekt.api.*

/** Separate crash/lifecycle process. Same UID: this is NOT a security sandbox. */
class ExtensionRuntimeService : Service() {
    private data class Loaded(val identity: String, val pkg: String, val sources: List<AnimeSource>)
    private val loaded = ConcurrentHashMap<String, Loaded>()
    private val jobs = ConcurrentHashMap<String, Job>()
    private val errors = ConcurrentHashMap<String, String>()
    private val trust by lazy { getSharedPreferences("extension_trust", MODE_PRIVATE) }
    private val codec = ExtensionCodec

    override fun onCreate() {
        super.onCreate()
        val app = application
        Injekt.importModule(object : InjektModule {
            override fun InjektRegistrar.registerInjectables() {
                addSingleton<Application>(app)
                addSingleton<android.content.Context>(app)
                addSingleton(NetworkHelper(app))
                addSingleton(JavaScriptEngine(app))
                addSingleton(Json { ignoreUnknownKeys = true; isLenient = true })
            }
        })
    }

    private fun ownCaller() { require(Binder.getCallingUid() == applicationInfo.uid) { "Unauthorized caller" } }
    private val binder = object : IExtensionRuntime.Stub() {
        override fun attachGateway(gateway: IExtensionHttp) { ownCaller(); NetworkHelper.gateway = gateway }
        override fun discover(): String { ownCaller(); return guarded { discoverPackages() } }
        override fun invoke(payload: String): String {
            ownCaller()
            require(payload.length <= 256_000)
            return guarded {
                val request = JSONObject(payload)
                val id = request.getString("operationId")
                require(id.length in 1..128)
                runBlocking {
                    withTimeout(45_000) {
                        jobs[id] = currentCoroutineContext().job
                        try { withContext(Dispatchers.IO) { execute(request) } }
                        finally { jobs.remove(id) }
                    }
                }
            }
        }
        override fun cancel(operation: String) { ownCaller(); jobs[operation]?.cancel() }
        override fun terminate() {
            ownCaller()
            // Only this explicitly bound worker process. Never the Python/UI owner.
            android.os.Process.killProcess(android.os.Process.myPid())
        }
    }
    override fun onBind(intent: Intent): IBinder = binder

    private fun guarded(work: () -> Any): String = try {
        val result = JSONObject().put("ok", true).put("result", work()).toString()
        require(result.toByteArray().size <= 700_000) { "Result exceeds IPC budget; request a smaller page" }
        result
    } catch (error: Throwable) {
        val code = when (error) {
            is CancellationException -> "cancelled"
            is LinkageError -> "extension_abi_incompatible"
            is SecurityException -> "extension_untrusted"
            is UnsupportedOperationException, is NotImplementedError -> "source_operation_unsupported"
            else -> "extension_runtime_error"
        }
        // Remote exceptions can contain URLs/credentials; export only a stable code/type.
        JSONObject().put("ok", false).put("code", code).put("type", error.javaClass.simpleName).toString()
    }

    private fun packageInfo(pkg: String): PackageInfo = packageManager.getPackageInfo(pkg,
        PackageManager.GET_META_DATA or PackageManager.GET_CONFIGURATIONS or PackageManager.GET_SIGNING_CERTIFICATES)

    private fun fingerprints(info: PackageInfo): List<String> {
        val signing = requireNotNull(info.signingInfo) { "Unsigned package" }
        val signatures = if (signing.hasMultipleSigners()) signing.apkContentsSigners else signing.signingCertificateHistory
        return signatures.map { signature -> MessageDigest.getInstance("SHA-256").digest(signature.toByteArray()).joinToString("") { "%02x".format(it) } }
    }

    private fun api(info: PackageInfo): Int {
        val metadata = info.applicationInfo!!.metaData
        val declared = metadata?.getInt("aniyomix.extensionLib", 0) ?: 0
        if (declared != 0) return declared
        val prefix = info.versionName.orEmpty().substringBeforeLast('.', "")
        val value = prefix.toDoubleOrNull() ?: return -1
        return if (value in 1.2..1.7) (value*10 + .01).toInt() else value.toInt()
    }

    private fun identity(info: PackageInfo): String = "${info.packageName}:${info.longVersionCode}:${fingerprints(info).last()}"
    private fun isExtension(info: PackageInfo): Boolean = info.reqFeatures.orEmpty().any { it.name == "tachiyomi.animeextension" }

    private fun discoverPackages(): JSONArray {
        val installed = packageManager.getInstalledPackages(PackageManager.GET_CONFIGURATIONS)
            .filter(::isExtension).map { packageInfo(it.packageName) }
        val present = installed.map { it.packageName }.toSet()
        loaded.keys.filterNot { it in present }.forEach { loaded.remove(it) }
        return JSONArray(installed.map { info ->
            val metadata = info.applicationInfo!!.metaData
            val key = identity(info)
            val trusted = trust.getBoolean(key, false)
            val compatible = api(info) in 12..17
            val result = JSONObject().put("pkg", info.packageName)
                .put("name", metadata?.getString("aniyomix.name") ?: packageManager.getApplicationLabel(info.applicationInfo!!).toString())
                .put("version", info.versionName).put("versionCode", info.longVersionCode.toString())
                .put("api", api(info)).put("signatures", JSONArray(fingerprints(info)))
                .put("signer", fingerprints(info).last()).put("trusted", trusted).put("is_installed", true)
                .put("location", "shared").put("runtime", "android-apk").put("compatible", compatible)
            if (trusted && compatible) {
                try {
                    result.put("sources", JSONArray(load(info).sources.map { source -> describe(source) }))
                    result.put("state", "loaded")
                    errors.remove(info.packageName)
                } catch (error: Throwable) {
                    loaded.remove(info.packageName)
                    errors[info.packageName] = error.javaClass.simpleName
                    result.put("state", "load_failed").put("error", error.javaClass.simpleName)
                }
            } else {
                loaded.remove(info.packageName)
                result.put("sources", JSONArray()).put("state", if (compatible) "untrusted" else "incompatible")
            }
            result
        })
    }

    private fun describe(source: AnimeSource): JSONObject = JSONObject().put("id", source.id.toString())
        .put("name", source.name).put("lang", source.lang)
        .put("baseUrl", (source as? AnimeHttpSource)?.baseUrl ?: "")
        .put("supportsLatest", (source as? AnimeCatalogueSource)?.supportsLatest ?: false)
        .put("configurable", source is ConfigurableAnimeSource)
        .put("supportsRelatedAnime", source.supportsRelatedAnime)

    private fun load(info: PackageInfo): Loaded {
        val key = identity(info)
        if (!trust.getBoolean(key, false)) throw SecurityException("Approve this package/version/signer first")
        require(api(info) in 12..17) { "Unsupported extension API" }
        loaded[info.packageName]?.takeIf { it.identity == key }?.let { return it }
        val application = requireNotNull(info.applicationInfo)
        val names = requireNotNull(application.metaData?.getString("tachiyomi.animeextension.class"))
        val loader = object : PathClassLoader(application.sourceDir, application.nativeLibraryDir, javaClass.classLoader) {
            override fun loadClass(name: String, resolve: Boolean): Class<*> {
                val shared = listOf("java.", "android.", "androidx.", "kotlin.", "kotlinx.", "rx.", "okhttp3.", "okio.",
                    "uy.kohesive.injekt.", "eu.kanade.tachiyomi.animesource.", "eu.kanade.tachiyomi.network.")
                if (shared.any(name::startsWith)) return super.loadClass(name, resolve)
                return synchronized(getClassLoadingLock(name)) {
                    findLoadedClass(name) ?: try { findClass(name) } catch (_: ClassNotFoundException) { super.loadClass(name, resolve) }
                }
            }
        }
        val sources = names.split(';').filter { it.isNotBlank() }.flatMap { entry ->
            val name = entry.trim().let { if (it.startsWith('.')) info.packageName + it else it }
            when (val instance = Class.forName(name, true, loader).getDeclaredConstructor().newInstance()) {
                is AnimeSource -> listOf(instance)
                is AnimeSourceFactory -> instance.createSources()
                else -> throw IllegalArgumentException("Invalid source entry class")
            }
        }
        require(sources.isNotEmpty() && sources.size <= 1000)
        require(sources.map { it.id }.distinct().size == sources.size) { "Duplicate source identifiers" }
        return Loaded(key, info.packageName, sources).also { loaded[info.packageName] = it }
    }

    private suspend fun execute(request: JSONObject): Any {
        val operation = request.getString("operation")
        val info = packageInfo(request.getString("pkg"))
        require(isExtension(info)) { "This is not an anime extension" }
        if (operation == "trust") {
            require(request.getString("signer") == fingerprints(info).last()) { "Signer changed" }
            require(request.getString("versionCode") == info.longVersionCode.toString()) { "Version changed" }
            trust.edit().putBoolean(identity(info), true).commit()
            loaded.remove(info.packageName)
            return JSONObject().put("trusted", true)
        }
        if (operation == "revoke") {
            trust.edit().remove(identity(info)).commit(); loaded.remove(info.packageName)
            return JSONObject().put("trusted", false)
        }
        val entry = load(info)
        val source = entry.sources.single { it.id.toString() == request.getString("sourceId") }
        val payload = request.optJSONObject("payload") ?: JSONObject()

        fun animeInput(): SAnime = codec.anime(payload.optJSONObject("anime") ?: payload)
        return when (operation) {
            "filters" -> codec.filters(source.getFilterList())
            "preferences" -> ExtensionPreferences.describe(this, source)
            "set_preferences" -> ExtensionPreferences.update(this, source, payload)
            "popular", "latest", "search" -> {
                val selected = source
                val page = payload.optInt("page", 1); require(page in 1..100_000)
                val result = when (operation) {
                    "popular" -> selected.getPopularAnime(page)
                    "latest" -> { require(selected.supportsLatest); selected.getLatestUpdates(page) }
                    else -> {
                        val filters = selected.getFilterList()
                        payload.optJSONArray("filters")?.let { codec.applyFilters(filters, it) }
                        selected.getSearchAnime(page, payload.optString("query"), filters)
                    }
                }
                JSONObject().put("results", JSONArray(result.animes.map(codec::anime))).put("hasNextPage", result.hasNextPage)
            }
            "detail" -> {
                val result = source.getAnimeEpisodeUpdate(animeInput(), emptyList(), true, true)
                JSONObject().put("anime", codec.anime(result.anime)).put("episodes", JSONArray(result.episodes.map(codec::episode)))
            }
            "seasons" -> {
                val result = source.getAnimeSeasonUpdate(animeInput(), emptyList(), true, true)
                JSONObject().put("anime", codec.anime(result.anime)).put("seasons", JSONArray(result.seasons.map(codec::anime)))
            }
            "related" -> {
                require(source.supportsRelatedAnime)
                JSONArray(source.getRelatedAnimeList(animeInput()).map { JSONObject().put("name", it.name).put("animes", JSONArray(it.animes.map(codec::anime))) })
            }
            "hosters" -> {
                val episode = codec.episode(payload)
                val hosts = if (api(info) < 16) listOf(Hoster(videoList=source.getVideoList(episode)))
                    else source.getHosterList(episode)
                JSONArray(hosts.map(codec::hoster))
            }
            "videos" -> {
                val host = codec.hoster(payload)
                JSONArray((host.videoList ?: source.getVideoList(host)).map(codec::video))
            }
            "resolve_video" -> codec.video((source as? AnimeHttpSource)?.resolveVideo(codec.video(payload)) ?: codec.video(payload))
            else -> throw UnsupportedOperationException("Unknown source operation")
        }
    }
}
