package com.animan.extensions

import eu.kanade.tachiyomi.animesource.model.*
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import okhttp3.Headers
import org.json.JSONArray
import org.json.JSONObject

internal object ExtensionCodec {
    private fun JSONObject.optionalString(key: String): String? = if (isNull(key)) null else getString(key)
    private fun initialized(read: () -> String, fallback: (() -> String)?): String = try { read() }
        catch (error: UninitializedPropertyAccessException) { fallback?.invoke() ?: throw error }

    fun anime(value: SAnime): JSONObject = anime(value, null)
    // Legacy detail parsers commonly return metadata without initializing url/title.
    // Only unset lateinit fields inherit the requested identity; explicit values survive.
    fun anime(value: SAnime, fallback: SAnime?): JSONObject = JSONObject()
        .put("url", initialized({ value.url }, fallback?.let { { it.url } }))
        .put("title", initialized({ value.title }, fallback?.let { { it.title } }))
        .put("thumbnail_url", value.thumbnail_url).put("background_url", value.background_url)
        .put("artist", value.artist).put("author", value.author).put("description", value.description)
        .put("genre", value.genre).put("status", value.status).put("initialized", value.initialized)
        .put("season_number", value.season_number).put("fetch_type", value.fetch_type.name)
        .put("update_strategy", value.update_strategy.name)
        .put("memo", JSONObject(value.memo.toString()))

    fun anime(value: JSONObject): SAnime = SAnime.create().apply {
        url = value.getString("url"); title = value.optString("title", url)
        thumbnail_url = value.optionalString("thumbnail_url"); description = value.optionalString("description")
        genre = value.optionalString("genre"); status = value.optInt("status")
        background_url = value.optionalString("background_url"); artist = value.optionalString("artist"); author = value.optionalString("author")
        initialized = value.optBoolean("initialized"); season_number = value.optDouble("season_number", -1.0)
        value.optString("fetch_type").takeIf { it.isNotEmpty() }?.let { fetch_type = FetchType.valueOf(it) }
        value.optString("update_strategy").takeIf { it.isNotEmpty() }?.let { update_strategy = AnimeUpdateStrategy.valueOf(it) }
        value.optJSONObject("memo")?.let { memo = Json.parseToJsonElement(it.toString()) as JsonObject }
    }

    fun episode(value: SEpisode): JSONObject = JSONObject().put("url", value.url).put("name", value.name)
        .put("episode_number", value.episode_number).put("date_upload", value.date_upload)
        .put("scanlator", value.scanlator).put("memo", JSONObject(value.memo.toString()))
        .put("fillermark", value.fillermark).put("summary", value.summary).put("preview_url", value.preview_url)

    fun episode(value: JSONObject): SEpisode = SEpisode.create().apply {
        url = value.getString("url"); name = value.optString("name", url)
        episode_number = value.optDouble("episode_number", -1.0).toFloat()
        date_upload = value.optLong("date_upload"); scanlator = value.optionalString("scanlator")
        fillermark = value.optBoolean("fillermark"); summary = value.optionalString("summary"); preview_url = value.optionalString("preview_url")
        value.optJSONObject("memo")?.let { memo = Json.parseToJsonElement(it.toString()) as JsonObject }
    }

    fun video(value: Video): JSONObject = JSONObject().put("videoUrl", value.videoUrl)
        .put("videoTitle", value.videoTitle).put("resolution", value.resolution).put("bitrate", value.bitrate)
        .put("headers", value.headers?.let { JSONArray(it.map { header -> JSONArray(listOf(header.first, header.second)) }) })
        .put("subtitleTracks", JSONArray(value.subtitleTracks.map { JSONObject().put("url", it.url).put("lang", it.lang) }))
        .put("audioTracks", JSONArray(value.audioTracks.map { JSONObject().put("url", it.url).put("lang", it.lang) }))
        .put("timestamps", JSONArray(value.timestamps.map { JSONObject().put("start", it.start).put("end", it.end).put("name", it.name).put("type", it.type.name) }))
        .put("preferred", value.preferred).put("internalData", value.internalData)
        .put("initialized", value.initialized).put("memo", JSONObject(value.memo.toString()))
        // Player command-line arguments remain data and are not forwarded to FFmpeg/mpv.
        .put("mpvArgs", JSONArray(value.mpvArgs.map { JSONArray(listOf(it.first, it.second)) }))
        .put("ffmpegStreamArgs", JSONArray(value.ffmpegStreamArgs.map { JSONArray(listOf(it.first, it.second)) }))
        .put("ffmpegVideoArgs", JSONArray(value.ffmpegVideoArgs.map { JSONArray(listOf(it.first, it.second)) }))

    fun video(value: JSONObject): Video {
        val headers = Headers.Builder()
        val pairs = value.optJSONArray("headers")
        for (i in 0 until (pairs?.length() ?: 0)) {
            requireNotNull(pairs)
            val pair = pairs.getJSONArray(i); headers.add(pair.getString(0), pair.getString(1))
        }
        fun tracks(key: String): List<Track> {
            val array = value.optJSONArray(key) ?: JSONArray()
            return (0 until array.length()).map { array.getJSONObject(it).let { Track(it.getString("url"), it.optString("lang")) } }
        }
        fun args(key: String): List<Pair<String,String>> {
            val array = value.optJSONArray(key) ?: JSONArray()
            return (0 until array.length()).map { array.getJSONArray(it).let { it.getString(0) to it.getString(1) } }
        }
        val chapters = value.optJSONArray("timestamps") ?: JSONArray()
        return Video(videoUrl=value.optString("videoUrl"), videoTitle=value.optString("videoTitle"),
            resolution=if(value.isNull("resolution")) null else value.getInt("resolution"),
            bitrate=if(value.isNull("bitrate")) null else value.getInt("bitrate"),
            headers=if(pairs==null) null else headers.build(), preferred=value.optBoolean("preferred"), subtitleTracks=tracks("subtitleTracks"),
            timestamps=(0 until chapters.length()).map { chapters.getJSONObject(it).let { row ->
                TimeStamp(row.getDouble("start"),row.getDouble("end"),row.optString("name"),ChapterType.valueOf(row.optString("type","Other"))) } },
            mpvArgs=args("mpvArgs"), ffmpegStreamArgs=args("ffmpegStreamArgs"), ffmpegVideoArgs=args("ffmpegVideoArgs"),
            audioTracks=tracks("audioTracks"), internalData=value.optString("internalData"),
            initialized=value.optBoolean("initialized"),
            memo=value.optJSONObject("memo")?.let { Json.parseToJsonElement(it.toString()) as JsonObject } ?: JsonObject(emptyMap()))
    }

    fun hoster(value: Hoster): JSONObject = JSONObject().put("hosterUrl", value.hosterUrl)
        .put("hosterName", value.hosterName).put("lazy", value.lazy).put("internalData", value.internalData)
        .put("memo", JSONObject(value.memo.toString()))
        .put("videoList", value.videoList?.let { JSONArray(it.map(::video)) })

    fun hoster(value: JSONObject): Hoster {
        val videos = value.optJSONArray("videoList")
        return Hoster(hosterUrl=value.optString("hosterUrl"), hosterName=value.optString("hosterName"),
            videoList=videos?.let { array -> (0 until array.length()).map { video(array.getJSONObject(it)) } },
            internalData=value.optString("internalData"), lazy=value.optBoolean("lazy"),
            memo=value.optJSONObject("memo")?.let { Json.parseToJsonElement(it.toString()) as JsonObject } ?: JsonObject(emptyMap()))
    }

    fun filters(list: List<AnimeFilter<*>>): JSONArray = JSONArray(list.map { filter ->
        val value = JSONObject().put("name", filter.name)
        when (filter) {
            is AnimeFilter.Header -> value.put("type", "header")
            is AnimeFilter.Separator -> value.put("type", "separator")
            is AnimeFilter.Select<*> -> value.put("type", "select").put("options", JSONArray(filter.values.toList())).put("state", filter.state)
            is AnimeFilter.Text -> value.put("type", "text").put("state", filter.state)
            is AnimeFilter.CheckBox -> value.put("type", "checkbox").put("state", filter.state)
            is AnimeFilter.TriState -> value.put("type", "triState").put("state", filter.state)
            is AnimeFilter.Group<*> -> value.put("type", "group").put("children", filters(filter.state.filterIsInstance<AnimeFilter<*>>()))
            is AnimeFilter.Sort -> value.put("type", "sort").put("options", JSONArray(filter.values.toList()))
                .put("state", filter.state?.let { JSONObject().put("index", it.index).put("ascending", it.ascending) })
        }
        value
    })

    fun applyFilters(list: List<AnimeFilter<*>>, states: JSONArray) {
        require(states.length() == list.size) { "The filter schema changed; reload it" }
        list.forEachIndexed { i, filter ->
            val input = states.getJSONObject(i)
            require(input.getString("name") == filter.name) { "Invalid filter identity" }
            when (filter) {
                is AnimeFilter.Select<*> -> input.getInt("state").also { require(it in filter.values.indices); filter.state = it }
                is AnimeFilter.Text -> input.getString("state").also { require(it.length <= 4096); filter.state = it }
                is AnimeFilter.CheckBox -> filter.state = input.getBoolean("state")
                is AnimeFilter.TriState -> input.getInt("state").also { require(it in 0..2); filter.state = it }
                is AnimeFilter.Group<*> -> applyFilters(filter.state.filterIsInstance<AnimeFilter<*>>(), input.getJSONArray("children"))
                is AnimeFilter.Sort -> filter.state = input.optJSONObject("state")?.let {
                    val index = it.getInt("index"); require(index in filter.values.indices)
                    AnimeFilter.Sort.Selection(index, it.getBoolean("ascending"))
                }
                else -> Unit
            }
        }
    }
}
