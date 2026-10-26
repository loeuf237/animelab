package com.animan.app

import android.content.ContentValues
import android.provider.DocumentsContract
import android.os.Environment
import android.provider.MediaStore
import android.webkit.MimeTypeMap
import java.io.File
import java.util.concurrent.ConcurrentHashMap

object NativeHooks {
    private var lastNotification = 0L
    internal val exportLock = Any()
    private val taskStates = ConcurrentHashMap<String, String>()
    @JvmStatic fun ready() {
        EngineHost.ready = true
        EngineHost.main.post { DownloadService.finishIdle(EngineHost.context) }
    }

    @JvmStatic @Synchronized fun progress(count: Int, percent: Int, label: String, taskId: String, status: String): Boolean {
        taskStates[taskId] = status.uppercase()
        val changed = count != EngineHost.activeCount
        EngineHost.activeCount = count
        EngineHost.progress = percent.coerceIn(0, 100)
        EngineHost.label = label
        val now = android.os.SystemClock.elapsedRealtime()
        if (!changed && now - lastNotification < 1000) return true
        lastNotification = now
        return DownloadService.update(EngineHost.context)
    }

    @JvmStatic fun exportFile(path: String, taskId: String): String = synchronized(exportLock) {
        try {
            exportCompletedFile(path, taskId).also { StorageAccess.exportResult(it, null) }
        } catch (failure: Exception) {
            StorageAccess.exportResult(null, failure.message ?: "Storage export failed")
            throw failure
        }
    }

    private fun exportCompletedFile(path: String, taskId: String): String {
        val context = EngineHost.context
        val root = File(context.filesDir, "downloads").canonicalFile
        val source = File(path).canonicalFile
        require(source.isFile && source.path.startsWith(root.path + File.separator)) { "Invalid completed media path" }
        val tree = StorageAccess.treeUri()
        check(if (tree == null) Environment.getExternalStorageState() == Environment.MEDIA_MOUNTED else StorageAccess.authorized(tree)) {
            "Storage access unavailable; authorize a folder in Settings > Storage"
        }
        val preferences = context.getSharedPreferences("animan_exports", ContextMode)
        val sourceKey = source.path + ":" + source.length() + ":" + source.lastModified()
        // Retain the existing Downloads registry across app updates. Only a
        // user-selected directory needs a separate destination identity.
        val key = if (tree == null) sourceKey else tree.toString() + ":" + sourceKey
        val previous = preferences.getString(key, null)
        if (previous != null) {
            try { context.contentResolver.openFileDescriptor(android.net.Uri.parse(previous), "r")?.use {
                if (it.statSize == source.length()) return previous
            } }
            catch (_: Exception) { /* User removed the shared copy; export it again. */ }
        }
        val pendingKey = "pending:" + key
        preferences.getString(pendingKey, null)?.let { pending ->
            val pendingUri = android.net.Uri.parse(pending)
            var published = false
            try {
                if (tree == null) context.contentResolver.query(pendingUri, arrayOf(MediaStore.Downloads.IS_PENDING), null, null, null)?.use {
                    published = it.moveToFirst() && it.getInt(0) == 0
                }
                if (published) {
                    val complete = context.contentResolver.openFileDescriptor(pendingUri, "r")?.use {
                        it.statSize == source.length()
                    } == true
                    if (complete) {
                        check(preferences.edit().putString(key, pending).remove(pendingKey).commit())
                        return pending
                    }
                }
                val removed = if (tree == null) context.contentResolver.delete(pendingUri, null, null) > 0
                    else DocumentsContract.deleteDocument(context.contentResolver, pendingUri)
                // Never forget a pending URI when deletion failed. Otherwise a
                // retry can publish a second copy while the first is still there.
                check(removed) { "The previous incomplete export could not be removed; restore folder access and retry" }
            } catch (_: java.io.FileNotFoundException) {
                // The user/provider already removed our incomplete document.
            }
            check(preferences.edit().remove(pendingKey).commit())
        }
        val mime = MimeTypeMap.getSingleton().getMimeTypeFromExtension(source.extension.lowercase()) ?: "application/octet-stream"
        val values = ContentValues().apply {
            put(MediaStore.Downloads.DISPLAY_NAME, source.name)
            put(MediaStore.Downloads.MIME_TYPE, mime)
            put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/" + StorageAccess.MEDIA_DIRECTORY)
            put(MediaStore.Downloads.IS_PENDING, 1)
        }
        val resolver = context.contentResolver
        val uri = requireNotNull(if (tree == null) {
            try { resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values) }
            catch (failure: IllegalArgumentException) {
                if (source.extension.lowercase() !in setOf("srt", "vtt", "ass", "ssa", "ttml")) throw failure
                // Android 11's original MediaProvider forces subtitle MIME
                // types into Movies/Music, even through the Downloads table.
                // Keep their real extension and use its supported collection.
                values.put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_MOVIES + "/" + StorageAccess.MEDIA_DIRECTORY)
                resolver.insert(MediaStore.Files.getContentUri("external"), values).also {
                    if (it != null) StorageAccess.subtitleDestination(Environment.DIRECTORY_MOVIES + "/" + StorageAccess.MEDIA_DIRECTORY)
                }
            }
        } else DocumentsContract.createDocument(resolver, StorageAccess.directory(tree), mime, source.name)) { "The storage provider refused to create the file" }
        try {
            check(preferences.edit().putString(pendingKey, uri.toString()).commit())
            requireNotNull(resolver.openOutputStream(uri)).use { output -> source.inputStream().use { input ->
                val buffer = ByteArray(256 * 1024)
                while (true) {
                    check(taskStates[taskId] !in listOf("PAUSED", "CANCELLED")) { "Export was paused or cancelled" }
                    val count = input.read(buffer)
                    if (count < 0) break
                    output.write(buffer, 0, count)
                }
            } }
            check(resolver.openFileDescriptor(uri, "r")?.use { it.statSize < 0 || it.statSize == source.length() } == true) { "The exported file size does not match the download" }
            if (tree == null) check(resolver.update(uri, ContentValues().apply { put(MediaStore.Downloads.IS_PENDING, 0) }, null, null) == 1) { "The file could not be published in Downloads" }
            check(preferences.edit().putString(key, uri.toString()).remove(pendingKey).commit())
            return uri.toString()
        } catch (failure: Exception) {
            var removed = false
            try {
                removed = if (tree == null) resolver.delete(uri, null, null) > 0
                else DocumentsContract.deleteDocument(resolver, uri)
            } catch (_: Exception) { /* Preserve the original failure and pending URI for cleanup. */ }
            if (removed) preferences.edit().remove(pendingKey).commit()
            throw failure
        }
    }
    private const val ContextMode = android.content.Context.MODE_PRIVATE
}
