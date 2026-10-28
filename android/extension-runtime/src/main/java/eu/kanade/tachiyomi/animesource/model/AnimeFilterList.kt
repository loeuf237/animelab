// SPDX-License-Identifier: Apache-2.0
// Adapted from Aniyomi 97414446b8a95994c72dd33c41c971a89d4d25b8; see UPSTREAM.md.
package eu.kanade.tachiyomi.animesource.model


data class AnimeFilterList(val list: List<AnimeFilter<*>>) : List<AnimeFilter<*>> by list {

    constructor(vararg fs: AnimeFilter<*>) : this(if (fs.isNotEmpty()) fs.asList() else emptyList())

    override fun equals(other: Any?): Boolean {
        return false
    }

    override fun hashCode(): Int {
        return list.hashCode()
    }
}
