// SPDX-License-Identifier: Apache-2.0
// Adapted from Aniyomi 97414446b8a95994c72dd33c41c971a89d4d25b8; see UPSTREAM.md.
package mihon.core.common.extensions

import kotlinx.serialization.json.JsonObject

val JsonObjectEmpty = JsonObject(emptyMap())

val JsonObjectEmptyBytes = byteArrayOf(0x7B, 0x7D)

val JsonObject.Companion.EMPTY: JsonObject
    inline get() = JsonObjectEmpty
