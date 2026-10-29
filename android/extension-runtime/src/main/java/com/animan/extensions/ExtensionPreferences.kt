package com.animan.extensions

import android.content.Context
import android.view.ContextThemeWrapper
import androidx.preference.*
import eu.kanade.tachiyomi.animesource.AnimeSource
import eu.kanade.tachiyomi.animesource.ConfigurableAnimeSource
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

/** Build actual source preference callbacks, then expose supported widgets as data. */
internal object ExtensionPreferences {
    private fun screen(context: Context, source: AnimeSource): PreferenceScreen {
        if(source !is ConfigurableAnimeSource) throw UnsupportedOperationException("This source has no preferences")
        val manager = PreferenceManager(ContextThemeWrapper(context, androidx.appcompat.R.style.Theme_AppCompat))
        manager.sharedPreferencesName = "source_${source.id}"
        return manager.createPreferenceScreen(manager.context).also(source::setupPreferenceScreen)
    }

    private fun collect(group: PreferenceGroup): List<Preference> = (0 until group.preferenceCount).flatMap {
        val preference = group.getPreference(it)
        listOf(preference) + if (preference is PreferenceGroup) collect(preference) else emptyList()
    }

    suspend fun describe(context: Context, source: AnimeSource): JSONArray = withContext(Dispatchers.Main) {
        val root = screen(context, source)
        JSONArray(collect(root).map { preference ->
            val secret = preference is EditTextPreference && Regex("(?i)password|passwd|token|secret|api.?key|credential|cookie|authorization").containsMatchIn("${preference.key} ${preference.title}")
            val type = when (preference) {
                is PreferenceGroup -> "group"
                is TwoStatePreference -> "boolean"
                is MultiSelectListPreference -> "multiSelect"
                is ListPreference -> "select"
                is EditTextPreference -> "text"
                else -> "unsupported"
            }
            val value = when (preference) {
                is TwoStatePreference -> preference.isChecked
                is MultiSelectListPreference -> JSONArray(preference.values.toList())
                is ListPreference -> preference.value
                is EditTextPreference -> preference.text
                else -> null
            }
            JSONObject().put("key", preference.key).put("title", preference.title?.toString())
                .put("type", type).put("enabled", preference.isEnabled).put("value", if(secret) "" else value)
                .put("secret",secret).put("hasValue", secret && !preference.sharedPreferences?.getString(preference.key,"").isNullOrEmpty())
                .put("entries", when (preference) {
                    is ListPreference -> JSONArray(preference.entries?.map { it.toString() } ?: emptyList<String>())
                    is MultiSelectListPreference -> JSONArray(preference.entries?.map { it.toString() } ?: emptyList<String>())
                    else -> JSONArray()
                }).put("entryValues", when (preference) {
                    is ListPreference -> JSONArray(preference.entryValues?.map { it.toString() } ?: emptyList<String>())
                    is MultiSelectListPreference -> JSONArray(preference.entryValues?.map { it.toString() } ?: emptyList<String>())
                    else -> JSONArray()
                })
        })
    }

    suspend fun update(context: Context, source: AnimeSource, values: JSONObject): JSONObject = withContext(Dispatchers.Main) {
        val root = screen(context, source)
        val allowed = collect(root).filter { !it.key.isNullOrEmpty() }.associateBy { it.key }
        // Validate the whole update before invoking callbacks or persisting any value.
        val changes = values.keys().asSequence().map { key ->
            val preference = requireNotNull(allowed[key]) { "Unknown preference" }
            require(preference.isEnabled) { "Disabled preference" }
            val value: Any = when (preference) {
                is TwoStatePreference -> values.getBoolean(key)
                is MultiSelectListPreference -> values.getJSONArray(key).let { array ->
                    (0 until array.length()).map { array.getString(it) }.toSet().also {
                        require(it.all { value -> preference.entryValues.any { entry -> entry.toString() == value } })
                    }
                }
                is ListPreference -> values.getString(key).also { value -> require(preference.entryValues.any { it.toString() == value }) }
                is EditTextPreference -> values.getString(key).also { require(it.length <= 8192) }
                else -> throw IllegalArgumentException("Unsupported preference widget")
            }
            preference to value
        }.toList()
        changes.forEach { (preference, value) -> require(preference.callChangeListener(value)) { "Source rejected a preference" } }
        changes.forEach { (preference, value) ->
            when (preference) {
                is TwoStatePreference -> preference.isChecked = value as Boolean
                is MultiSelectListPreference -> { @Suppress("UNCHECKED_CAST") preference.values = value as Set<String> }
                is ListPreference -> preference.value = value as String
                is EditTextPreference -> preference.text = value as String
            }
        }
        JSONObject().put("saved", true)
    }
}
