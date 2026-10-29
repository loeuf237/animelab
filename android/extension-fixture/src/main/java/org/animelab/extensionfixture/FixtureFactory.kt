@file:Suppress("DEPRECATION")
package org.animelab.extensionfixture

import android.app.Application
import androidx.preference.ListPreference
import eu.kanade.tachiyomi.animesource.*
import eu.kanade.tachiyomi.animesource.model.*
import eu.kanade.tachiyomi.animesource.online.AnimeHttpSource
import eu.kanade.tachiyomi.network.JavaScriptEngine
import kotlinx.coroutines.runBlocking
import okhttp3.Headers
import rx.Observable
import uy.kohesive.injekt.Injekt
import uy.kohesive.injekt.api.get

class FixtureFactory : AnimeSourceFactory {
    override fun createSources() = listOf(Fixture("fr"), Fixture("en"))
}

class Fixture(override val lang: String) : AnimeHttpSource(), ConfigurableAnimeSource {
    override val name = "Fixture ${BuildConfig.EXTENSION_API} $lang"
    override val baseUrl = "https://fixture.example"
    override val supportsLatest = true
    override fun getFilterList() = AnimeFilterList(object : AnimeFilter.Text("Suffix", "default") {})
    private fun resultPage(value: String) = AnimesPage(listOf(SAnime.create().apply {
        url = "/anime/fixture"; title = "$name:$value"; initialized = true
    }), false)
    override fun fetchPopularAnime(page: Int): Observable<AnimesPage> = Observable.just(resultPage((page*7).toString()))
    override fun fetchLatestUpdates(page: Int): Observable<AnimesPage> = fetchPopularAnime(page)
    override fun fetchSearchAnime(page: Int, query: String, filters: AnimeFilterList): Observable<AnimesPage> {
        if (query == "__block_worker__") Thread.sleep(120_000)
        // In the full app this crosses Binder back into the real Python broker,
        // proving a nested callback can complete while the source call waits.
        if(BuildConfig.EXTENSION_API>=14) network.defaultUserAgentProvider()
        val computed = runBlocking { JavaScriptEngine(Injekt.get<Application>()).evaluate<Int>("6 * 7") }
        val suffix = (filters[0] as AnimeFilter.Text).state
        val quality = getSourcePreferences().getString("quality", "720")
        return Observable.just(resultPage("${query.reversed()}:$computed:$quality:$suffix"))
    }
    override fun fetchAnimeDetails(anime: SAnime): Observable<SAnime> = Observable.just(SAnime.create().apply {
        url = anime.url; title = "$name details"; description = "APK code executed"; initialized = true
    })
    override fun fetchEpisodeList(anime: SAnime): Observable<List<SEpisode>> = Observable.just(listOf(SEpisode.create().apply {
        url = "/episode/1"; name = "Computed episode"; episode_number = 1f
    }))
    private fun video() = Video(url="https://fixture.example/episode/1", quality="720p", videoUrl="https://fixture.example/stream.m3u8",
        headers=Headers.headersOf("Referer", "https://fixture.example/", "X-Fixture", lang),
        subtitleTracks=listOf(Track("https://fixture.example/sub.vtt",lang)))
    override fun fetchVideoList(episode: SEpisode): Observable<List<Video>> = Observable.just(listOf(video()))
    override suspend fun getHosterList(episode: SEpisode): List<Hoster> = listOf(Hoster(hosterName="Computed host",videoList=listOf(video())))
    override suspend fun getVideoList(hoster: Hoster): List<Video> = listOf(video())
    override fun setupPreferenceScreen(screen: PreferenceScreen) {
        screen.addPreference(ListPreference(screen.context).apply {
            key="quality"; title="Quality"; entries=arrayOf("720p","1080p"); entryValues=arrayOf("720","1080")
            setDefaultValue("720")
        })
    }
}
