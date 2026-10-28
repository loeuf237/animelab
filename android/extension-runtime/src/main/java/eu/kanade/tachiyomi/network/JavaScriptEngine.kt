package eu.kanade.tachiyomi.network

import android.content.Context
import app.cash.quickjs.QuickJs
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

class JavaScriptEngine(context: Context) {
    @Suppress("UNCHECKED_CAST")
    suspend fun <T> evaluate(script: String): T = withContext(Dispatchers.IO) {
        require(script.length <= 2_000_000) { "JavaScript exceeds the script budget" }
        QuickJs.create().use { it.evaluate(script) as T }
    }
}
