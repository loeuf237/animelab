package com.animan.app

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInfo
import android.content.pm.PackageInstaller
import android.content.pm.PackageManager
import android.net.Uri
import android.provider.Settings
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest
import java.util.UUID
import kotlin.concurrent.thread

/** Android's package installer owns shared APKs; recipes never count as installation. */
internal object ExtensionPackages {
    private const val MAX_APK = 64L * 1024 * 1024
    private fun store(context: Context) = context.getSharedPreferences("extension_package_operations", Context.MODE_PRIVATE)

    private fun file(context: Context, path: String): File {
        val value = File(path).canonicalFile
        require(listOf(context.filesDir, context.cacheDir).any { value.path.startsWith(it.canonicalPath + File.separator) })
        require(value.isFile && value.length() in 1..MAX_APK) { "APK missing or too large" }
        return value
    }

    @Suppress("DEPRECATION")
    private fun archive(context: Context, value: File): PackageInfo {
        val info = requireNotNull(context.packageManager.getPackageArchiveInfo(value.path,
            PackageManager.GET_META_DATA or PackageManager.GET_CONFIGURATIONS or PackageManager.GET_SIGNING_CERTIFICATES or PackageManager.GET_SIGNATURES)) { "Invalid APK" }
        require(info.reqFeatures.orEmpty().any { it.name == "tachiyomi.animeextension" }) { "Not an anime extension" }
        requireNotNull(info.signingInfo) { "APK has no signatures" }
        return info
    }

    private fun signer(info: PackageInfo): String {
        return com.animan.extensions.APKSignatures.current(info)
    }

    fun inspect(context: Context, path: String): JSONObject {
        val value = file(context, path)
        val info = archive(context, value)
        val digest = MessageDigest.getInstance("SHA-256")
        value.inputStream().use { input -> val buffer = ByteArray(65536); while (true) { val n=input.read(buffer); if (n<0) break; digest.update(buffer,0,n) } }
        return JSONObject().put("pkg", info.packageName).put("versionCode", info.longVersionCode.toString())
            .put("version", info.versionName).put("signer", signer(info))
            .put("sha256", digest.digest().joinToString("") { "%02x".format(it) })
    }

    private fun save(context: Context, value: JSONObject) {
        val now=System.currentTimeMillis()
        if (!value.has("createdAt")) value.put("createdAt",now)
        value.put("updatedAt",now)
        val preferences=store(context)
        val editor=preferences.edit().putString(value.getString("id"),value.toString())
        val completed=preferences.all.values.filterIsInstance<String>().map(::JSONObject)
            .filter { it.optString("state") in setOf("installed","uninstalled","failed","cancelled") }
            .sortedByDescending { it.optLong("updatedAt") }
        completed.drop(99).forEach { editor.remove(it.getString("id")) }
        editor.commit()
    }

    private fun callback(context: Context, id: String, session: Int): android.content.IntentSender {
        val intent = Intent(context, ExtensionInstallReceiver::class.java).putExtra("operationId", id)
        return PendingIntent.getBroadcast(context, session, intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE).intentSender
    }

    @Synchronized fun install(context: Context, path: String, expectedPackage: String): JSONObject {
        val value = file(context, path)
        val inspected = inspect(context, path)
        require(expectedPackage.isEmpty() || inspected.getString("pkg") == expectedPackage) { "APK package differs from repository" }
        val active=store(context).all.values.filterIsInstance<String>().map(::JSONObject)
            .filter { it.optString("state") in setOf("preparing","permission_required","waiting_user","installing") }
        active.firstOrNull { it.getString("pkg")==inspected.getString("pkg") }?.let {
            require(it.optString("sha256")==inspected.getString("sha256")) { "Another installation is already pending for this package" }
            return publicOperation(it)
        }
        require(active.size<8) { "Complete or cancel pending installations first" }
        val operation = JSONObject().put("id", UUID.randomUUID().toString()).put("action", "install")
            .put("pkg", inspected.getString("pkg")).put("versionCode", inspected.getString("versionCode"))
            .put("signer", inspected.getString("signer")).put("sha256", inspected.getString("sha256"))
            .put("path", value.path).put("state", "preparing")
        if (!context.packageManager.canRequestPackageInstalls()) {
            operation.put("state", "permission_required"); save(context, operation)
            context.startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${context.packageName}")).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            return publicOperation(operation)
        }
        commit(context, operation)
        return publicOperation(operation)
    }

    @Synchronized private fun commit(context: Context, operation: JSONObject) {
        store(context).getString(operation.getString("id"),null)?.let { saved ->
            if(JSONObject(saved).optString("state") !in setOf("preparing","permission_required")) return
        }
        // Reinspect after permission/settings UI; the staged file may have changed.
        val value = file(context, operation.getString("path"))
        require(inspect(context, value.path).getString("sha256") == operation.getString("sha256")) { "Staged APK changed" }
        val installer = context.packageManager.packageInstaller
        val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL)
        params.setAppPackageName(operation.getString("pkg"))
        val sessionId = installer.createSession(params)
        operation.put("sessionId", sessionId).put("state", "installing"); save(context, operation)
        try {
            installer.openSession(sessionId).use { session ->
                session.openWrite("extension.apk",0,value.length()).use { output ->
                    value.inputStream().use { it.copyTo(output) }; session.fsync(output)
                }
                session.commit(callback(context,operation.getString("id"),sessionId))
            }
        } catch (failure: Exception) {
            installer.abandonSession(sessionId)
            operation.put("state", "failed").put("error", failure.javaClass.simpleName); save(context,operation)
            throw failure
        }
    }

    fun resume(context: Context) {
        if (!context.packageManager.canRequestPackageInstalls()) return
        thread(name="AnimeLabExtensionPermissions") {
            store(context).all.values.filterIsInstance<String>().forEach { raw ->
                val operation = JSONObject(raw)
                if (operation.optString("state") == "permission_required") {
                    try { commit(context,operation) }
                    catch (failure: Exception) { operation.put("state","failed").put("error",failure.javaClass.simpleName); save(context,operation) }
                }
            }
        }
    }

    @Suppress("DEPRECATION")
    fun uninstall(context: Context, pkg: String): JSONObject {
        val info=context.packageManager.getPackageInfo(pkg,PackageManager.GET_CONFIGURATIONS)
        require(info.reqFeatures.orEmpty().any { it.name=="tachiyomi.animeextension" })
        val operation=JSONObject().put("id",UUID.randomUUID().toString()).put("action","uninstall")
            .put("pkg",pkg).put("state","waiting_user")
        save(context,operation)
        context.packageManager.packageInstaller.uninstall(pkg,callback(context,operation.getString("id"),operation.getString("id").hashCode()))
        return publicOperation(operation)
    }

    private fun publicOperation(value: JSONObject): JSONObject = JSONObject(value.toString()).apply { remove("path") }
    fun operations(context: Context): JSONArray = JSONArray(store(context).all.values.filterIsInstance<String>().map { publicOperation(JSONObject(it)) }.sortedBy { it.optLong("createdAt") })

    fun cancel(context: Context,id: String): JSONObject {
        val operation=JSONObject(requireNotNull(store(context).getString(id,null)))
        require(operation.optString("action")=="install" && operation.optString("state") in setOf("preparing","permission_required","waiting_user","installing"))
        if (operation.has("sessionId")) {
            try { context.packageManager.packageInstaller.abandonSession(operation.getInt("sessionId")) }
            catch (_: IllegalStateException) { }
        }
        operation.put("state","cancelled"); save(context,operation)
        return publicOperation(operation)
    }

    @Suppress("DEPRECATION")
    fun received(context: Context, intent: Intent) {
        val id=intent.getStringExtra("operationId") ?: return
        val operation=store(context).getString(id,null)?.let(::JSONObject) ?: return
        val status=intent.getIntExtra(PackageInstaller.EXTRA_STATUS,PackageInstaller.STATUS_FAILURE)
        when (status) {
            PackageInstaller.STATUS_PENDING_USER_ACTION -> {
                operation.put("state","waiting_user"); save(context,operation)
                val confirmation=intent.getParcelableExtra<Intent>(Intent.EXTRA_INTENT) ?: return
                context.startActivity(confirmation.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                return
            }
            PackageInstaller.STATUS_SUCCESS -> {
                try {
                    if (operation.getString("action")=="install") {
                        val info=context.packageManager.getPackageInfo(operation.getString("pkg"),PackageManager.GET_SIGNING_CERTIFICATES)
                        check(info.longVersionCode.toString()==operation.getString("versionCode") && signer(info)==operation.getString("signer"))
                        operation.put("state","installed")
                    } else {
                        try { context.packageManager.getPackageInfo(operation.getString("pkg"),0); error("Package still installed") }
                        catch (_: PackageManager.NameNotFoundException) { operation.put("state","uninstalled") }
                    }
                } catch (failure: Exception) { operation.put("state","failed").put("error",failure.javaClass.simpleName) }
            }
            PackageInstaller.STATUS_FAILURE_ABORTED -> operation.put("state","cancelled")
            else -> operation.put("state","failed").put("error","package_installer_$status")
        }
        save(context,operation)
    }
}

class ExtensionInstallReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) { ExtensionPackages.received(context,intent) }
}
