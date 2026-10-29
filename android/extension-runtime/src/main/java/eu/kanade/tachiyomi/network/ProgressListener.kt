// SPDX-License-Identifier: Apache-2.0
// Adapted from Aniyomi 97414446b8a95994c72dd33c41c971a89d4d25b8; see UPSTREAM.md.
package eu.kanade.tachiyomi.network

interface ProgressListener {
    fun update(bytesRead: Long, contentLength: Long, done: Boolean)
}
