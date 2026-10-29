package tachiyomi.core.common.util.system

import logcat.LogPriority

inline fun Any.logcat(priority: LogPriority = LogPriority.DEBUG, throwable: Throwable? = null, message: () -> String) {
    // Never log remote bodies, source credentials or cookies.
    android.util.Log.println(android.util.Log.DEBUG, "AnimeLabExtension", message().take(512))
}
