package com.animan.app

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.DocumentsContract
import androidx.core.content.ContextCompat
import androidx.core.app.NotificationManagerCompat
import org.json.JSONObject

/** Storage grants belong to the document provider, not to filesystem paths. */
object StorageAccess {
    const val MEDIA_DIRECTORY = "AnimeLab"
    const val DEFAULT_DESTINATION = "Downloads/AnimeLab"
    private val preferences get() = EngineHost.context.getSharedPreferences("animan_storage", Context.MODE_PRIVATE)
    @Volatile var selectionPending = false
    @Volatile var actionHandler: ((String) -> Unit)? = null

    fun treeUri(): Uri? = preferences.getString("tree_uri", null)?.let(Uri::parse)
    fun directory(uri: Uri): Uri = DocumentsContract.buildDocumentUriUsingTree(uri, DocumentsContract.getTreeDocumentId(uri))

    fun authorized(uri: Uri): Boolean = try {
        val resolver = EngineHost.context.contentResolver
        val grant = resolver.persistedUriPermissions.any { it.uri == uri && it.isWritePermission && it.isReadPermission }
        grant && resolver.query(directory(uri), arrayOf(DocumentsContract.Document.COLUMN_FLAGS), null, null, null)?.use {
            it.moveToFirst() && it.getInt(0) and DocumentsContract.Document.FLAG_DIR_SUPPORTS_CREATE != 0
        } == true
    } catch (_: Exception) { false }

    fun select(uri: Uri, flags: Int) = synchronized(NativeHooks.exportLock) {
        val resolver = EngineHost.context.contentResolver
        val access = flags and (Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
        require(access and Intent.FLAG_GRANT_WRITE_URI_PERMISSION != 0 && access and Intent.FLAG_GRANT_READ_URI_PERMISSION != 0) {
            "The selected folder did not grant read and write access"
        }
        val previous = treeUri()
        resolver.takePersistableUriPermission(uri, access)
        require(authorized(uri)) { "The selected folder is not writable; select another folder" }
        val name = resolver.query(directory(uri), arrayOf(DocumentsContract.Document.COLUMN_DISPLAY_NAME), null, null, null)?.use {
            if (it.moveToFirst()) it.getString(0) else null
        } ?: uri.lastPathSegment.orEmpty()
        check(preferences.edit().putString("tree_uri", uri.toString()).putString("tree_name", name).remove("permission_error").commit())
        if (previous != null && previous != uri) try { resolver.releasePersistableUriPermission(previous, access) } catch (_: Exception) { }
    }

    fun useDownloads() = synchronized(NativeHooks.exportLock) {
        val previous = treeUri()
        check(preferences.edit().remove("tree_uri").remove("tree_name").remove("permission_error").commit())
        if (previous != null) try { EngineHost.context.contentResolver.releasePersistableUriPermission(previous,
            Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION) } catch (_: Exception) { }
    }

    fun error(message: String?) { preferences.edit().putString("permission_error", message).apply() }
    fun subtitleDestination(path: String) { preferences.edit().putString("subtitle_destination", path).apply() }
    fun exportResult(uri: String?, error: String?) {
        preferences.edit().putString("export_error", error).putString("last_export_uri", uri).apply()
    }

    @JvmStatic fun status(): String {
        val uri = treeUri()
        val allowed = if (uri == null) Environment.getExternalStorageState() == Environment.MEDIA_MOUNTED else authorized(uri)
        val context = EngineHost.context
        return JSONObject().put("android", true).put("apiLevel", Build.VERSION.SDK_INT)
            .put("mode", if (uri == null) "downloads" else "directory")
            .put("destination", if (uri == null) DEFAULT_DESTINATION else preferences.getString("tree_name", ""))
            .put("subtitleDestination", if (uri == null) preferences.getString("subtitle_destination", null) ?: JSONObject.NULL else JSONObject.NULL)
            .put("authorized", allowed).put("selectionPending", selectionPending)
            .put("notificationsGranted", NotificationManagerCompat.from(context).areNotificationsEnabled() &&
                (Build.VERSION.SDK_INT < 33 || ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED))
            .put("error", preferences.getString("permission_error", null) ?: JSONObject.NULL)
            .put("exportError", preferences.getString("export_error", null) ?: JSONObject.NULL).toString()
    }

    @JvmStatic @Synchronized fun request(action: String): String {
        require(action in listOf("choose_directory", "use_downloads", "notifications", "app_settings", "open_downloads")) { "Unknown permission action" }
        if (action == "use_downloads") useDownloads()
        else {
            val handler = actionHandler ?: throw IllegalStateException("Open AnimeLab before changing permissions")
            if (action == "choose_directory") {
                check(!selectionPending) { "A folder selection is already open" }
                selectionPending = true
            }
            EngineHost.main.post { handler(action) }
        }
        return status()
    }
}
