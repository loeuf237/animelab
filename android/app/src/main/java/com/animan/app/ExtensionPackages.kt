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
import java.util.concurrent.ConcurrentHashMap
import kotlin.concurrent.thread

/** Android's package installer owns shared APKs; recipes never count as installation. */
internal object ExtensionPackages {
    private const val MAX_APK = 64L * 1024 * 1024
    private const val LEGACY_STATUS = "android.content.pm.extra.LEGACY_STATUS"
    private const val SESSION_GONE_GRACE_MS = 15_000L
    private const val STALE_INSTALL_TIMEOUT_MS = 5L * 60_000L
    private const val STALE_PREPARING_TIMEOUT_MS = 30_000L
    private const val STALE_UNINSTALL_TIMEOUT_MS = 2L * 60_000L
    private const val STALE_PERMISSION_TIMEOUT_MS = 15L * 60_000L
    private val ACTIVE_STATES = setOf("preparing", "permission_required", "waiting_user", "installing")
    private val TERMINAL_STATES = setOf("installed", "uninstalled", "failed", "cancelled")
    private val pendingConfirmations = ConcurrentHashMap<String, Intent>()
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

    @Suppress("DEPRECATION")
    private fun installedInfo(context: Context, pkg: String): PackageInfo? {
        if (pkg.isBlank()) return null
        return try {
            context.packageManager.getPackageInfo(
                pkg,
                PackageManager.GET_SIGNING_CERTIFICATES or PackageManager.GET_SIGNATURES,
            )
        } catch (_: PackageManager.NameNotFoundException) {
            null
        }
    }

    private fun isInstalledForOperation(context: Context, op: JSONObject): Boolean {
        val info = installedInfo(context, op.optString("pkg")) ?: return false
        if (info.longVersionCode.toString() != op.optString("versionCode") ||
            signer(info) != op.optString("signer")
        ) {
            return false
        }
        return if (op.has("beforeUpdateTime")) {
            val before = op.optLong("beforeUpdateTime", -1L)
            before < 0L || info.lastUpdateTime > before
        } else {
            info.lastUpdateTime >= op.optLong("createdAt", Long.MAX_VALUE)
        }
    }

    @Synchronized
    fun reconcile(context: Context) {
        val now = System.currentTimeMillis()
        val installer = context.packageManager.packageInstaller
        val rawEntries = store(context).all.values.filterIsInstance<String>()
        for (raw in rawEntries) {
            val op = JSONObject(raw)
            val state = op.optString("state")
            if (state !in ACTIVE_STATES) continue
            val id = op.optString("id")
            val action = op.optString("action")
            val updatedAt = op.optLong("updatedAt", op.optLong("createdAt", 0L))
            val age = (now - updatedAt).coerceAtLeast(0L)
            when (action) {
                "install" -> when (state) {
                    "preparing" -> {
                        if (!op.has("sessionId") && age >= STALE_PREPARING_TIMEOUT_MS) {
                            op.put("state", "failed").put("error", "package_installer_session_expired")
                            pendingConfirmations.remove(id)
                            save(context, op)
                        }
                    }
                    "permission_required" -> {
                        if (age >= STALE_PERMISSION_TIMEOUT_MS) {
                            op.put("state", "cancelled").put("error", "package_installer_session_expired")
                            pendingConfirmations.remove(id)
                            save(context, op)
                        }
                    }
                    "installing", "waiting_user" -> {
                        val sessionId = if (op.has("sessionId")) op.getInt("sessionId") else -1
                        val sessionAlive = sessionId >= 0 && try {
                            installer.getSessionInfo(sessionId) != null
                        } catch (_: Exception) {
                            false
                        }
                        if (!sessionAlive && age >= SESSION_GONE_GRACE_MS) {
                            if (isInstalledForOperation(context, op)) {
                                op.put("state", "installed").remove("error")
                            } else {
                                op.put("state", "cancelled").put("error", "package_installer_session_expired")
                            }
                            pendingConfirmations.remove(id)
                            save(context, op)
                        } else if (sessionAlive && age >= STALE_INSTALL_TIMEOUT_MS) {
                            try {
                                installer.abandonSession(sessionId)
                            } catch (_: Exception) {
                            }
                            if (isInstalledForOperation(context, op)) {
                                op.put("state", "installed").remove("error")
                            } else {
                                op.put("state", "cancelled").put("error", "package_installer_session_expired")
                            }
                            pendingConfirmations.remove(id)
                            save(context, op)
                        }
                    }
                }
                "uninstall" -> if (state == "waiting_user") {
                    if (installedInfo(context, op.optString("pkg")) == null) {
                        op.put("state", "uninstalled").remove("error")
                        pendingConfirmations.remove(id)
                        save(context, op)
                    } else if (age >= STALE_UNINSTALL_TIMEOUT_MS) {
                        op.put("state", "cancelled").put("error", "package_installer_session_expired")
                        pendingConfirmations.remove(id)
                        save(context, op)
                    }
                }
            }
        }
    }

    private fun save(context: Context, value: JSONObject) {
        val now=System.currentTimeMillis()
        if (!value.has("createdAt")) value.put("createdAt",now)
        value.put("updatedAt",now)
        val preferences=store(context)
        val editor=preferences.edit().putString(value.getString("id"),value.toString())
        val completed=preferences.all.values.filterIsInstance<String>().map(::JSONObject)
            .filter { it.optString("state") in TERMINAL_STATES }
            .sortedByDescending { it.optLong("updatedAt") }
        completed.drop(99).forEach { editor.remove(it.getString("id")) }
        editor.commit()
    }

    private fun callback(context: Context, id: String, session: Int): android.content.IntentSender {
        val intent = Intent(context, ExtensionInstallReceiver::class.java)
            .putExtra("operationId", id).putExtra("ownerSessionId", session)
        return PendingIntent.getBroadcast(context, session, intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE).intentSender
    }

    @Synchronized fun install(context: Context, path: String, expectedPackage: String): JSONObject {
        reconcile(context)
        val value = file(context, path)
        val inspected = inspect(context, path)
        require(expectedPackage.isEmpty() || inspected.getString("pkg") == expectedPackage) { "APK package differs from repository" }
        val active=store(context).all.values.filterIsInstance<String>().map(::JSONObject)
            .filter { it.optString("state") in ACTIVE_STATES }
        active.firstOrNull { it.getString("pkg")==inspected.getString("pkg") }?.let { existing ->
            require(existing.optString("sha256")==inspected.getString("sha256")) { "Another installation is already pending for this package" }
            val id = existing.getString("id")
            when (existing.optString("state")) {
                "permission_required" -> {
                    if (context.packageManager.canRequestPackageInstalls()) {
                        commit(context, existing)
                    } else {
                        save(context, existing)
                        context.startActivity(
                            Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${context.packageName}"))
                                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                        )
                    }
                }
                "waiting_user" -> {
                    val confirmation = pendingConfirmations[id]
                    if (confirmation != null) {
                        save(context, existing)
                        try {
                            context.startActivity(Intent(confirmation).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                        } catch (_: Exception) {
                        }
                    }
                }
            }
            return publicOperation(existing)
        }
        require(active.size<8) { "Complete or cancel pending installations first" }
        val beforeUpdateTime = installedInfo(context, inspected.getString("pkg"))?.lastUpdateTime ?: -1L
        val operation = JSONObject().put("id", UUID.randomUUID().toString()).put("action", "install")
            .put("pkg", inspected.getString("pkg")).put("versionCode", inspected.getString("versionCode"))
            .put("signer", inspected.getString("signer")).put("sha256", inspected.getString("sha256"))
            .put("path", value.path).put("beforeUpdateTime", beforeUpdateTime).put("state", "preparing")
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
            pendingConfirmations.remove(operation.getString("id"))
            operation.put("state", "failed").put("error", failure.javaClass.simpleName); save(context,operation)
            throw failure
        }
    }

    fun resume(context: Context) {
        try {
            reconcile(context)
        } catch (_: Exception) {
        }
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
        reconcile(context)
        val info=context.packageManager.getPackageInfo(pkg,PackageManager.GET_CONFIGURATIONS)
        require(info.reqFeatures.orEmpty().any { it.name=="tachiyomi.animeextension" })
        val operation=JSONObject().put("id",UUID.randomUUID().toString()).put("action","uninstall")
            .put("pkg",pkg).put("state","waiting_user")
        save(context,operation)
        context.packageManager.packageInstaller.uninstall(pkg,callback(context,operation.getString("id"),operation.getString("id").hashCode()))
        return publicOperation(operation)
    }

    private fun publicOperation(value: JSONObject): JSONObject {
        val id = value.optString("id")
        val state = value.optString("state")
        val action = value.optString("action")
        val path = value.optString("path")
        val canConfirm = when (state) {
            "permission_required" -> true
            "waiting_user" -> pendingConfirmations.containsKey(id) ||
                (action == "install" && path.isNotEmpty() && File(path).isFile)
            else -> false
        }
        return JSONObject(value.toString()).apply {
            remove("path")
            remove("beforeUpdateTime")
            put("canConfirm", canConfirm)
        }
    }

    fun operations(context: Context): JSONArray {
        reconcile(context)
        return JSONArray(store(context).all.values.filterIsInstance<String>().map { publicOperation(JSONObject(it)) }.sortedBy { it.optLong("createdAt") })
    }

    @Synchronized fun cancel(context: Context,id: String): JSONObject {
        val operation=JSONObject(requireNotNull(store(context).getString(id,null)))
        require(operation.optString("action") in setOf("install","uninstall") && operation.optString("state") in ACTIVE_STATES)
        if (operation.has("sessionId")) {
            try { context.packageManager.packageInstaller.abandonSession(operation.getInt("sessionId")) }
            catch (_: Exception) { }
        }
        pendingConfirmations.remove(id)
        operation.put("state","cancelled"); save(context,operation)
        return publicOperation(operation)
    }

    @Synchronized fun openConfirmation(context: Context, id: String): JSONObject {
        reconcile(context)
        val operation = JSONObject(requireNotNull(store(context).getString(id, null)))
        val state = operation.optString("state")
        val action = operation.optString("action")
        if (state == "permission_required") {
            if (context.packageManager.canRequestPackageInstalls()) {
                commit(context, operation)
            } else {
                save(context, operation)
                context.startActivity(
                    Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${context.packageName}"))
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                )
            }
            return publicOperation(operation)
        }
        if (state == "waiting_user") {
            val confirmation = pendingConfirmations[id]
            if (confirmation != null) {
                save(context, operation)
                try {
                    context.startActivity(Intent(confirmation).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                    return publicOperation(operation)
                } catch (_: Exception) {
                    pendingConfirmations.remove(id)
                }
            }
            if (action == "install") {
                val path = operation.optString("path")
                if (path.isNotEmpty() && File(path).isFile) {
                    if (operation.has("sessionId")) {
                        try { context.packageManager.packageInstaller.abandonSession(operation.getInt("sessionId")) }
                        catch (_: Exception) { }
                        operation.remove("sessionId")
                    }
                    if (!context.packageManager.canRequestPackageInstalls()) {
                        operation.put("state", "permission_required")
                        save(context, operation)
                        context.startActivity(
                            Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${context.packageName}"))
                                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                        )
                        return publicOperation(operation)
                    }
                    operation.put("state", "preparing")
                    save(context, operation)
                    commit(context, operation)
                    return publicOperation(operation)
                }
            }
        }
        return publicOperation(operation)
    }

    @Suppress("DEPRECATION")
    @Synchronized fun received(context: Context, intent: Intent) {
        val id=intent.getStringExtra("operationId") ?: return
        val operation=store(context).getString(id,null)?.let(::JSONObject) ?: return
        // A delayed system callback must not reopen or replace a cancelled operation.
        if (operation.optString("state") in TERMINAL_STATES) return
        if (operation.has("sessionId") && intent.getIntExtra("ownerSessionId",-1)!=operation.getInt("sessionId")) return
        val status=intent.getIntExtra(PackageInstaller.EXTRA_STATUS,PackageInstaller.STATUS_FAILURE)
        operation.put("installerStatus",status)
        when (status) {
            PackageInstaller.STATUS_PENDING_USER_ACTION -> {
                operation.put("state","waiting_user")
                    .put("confirmationRequest",operation.optInt("confirmationRequest",0)+1)
                save(context,operation)
                val confirmation=intent.getParcelableExtra<Intent>(Intent.EXTRA_INTENT)
                if (confirmation==null) {
                    pendingConfirmations.remove(id)
                    operation.put("state","failed").put("error","package_installer_confirmation_missing")
                    save(context,operation)
                    return
                }
                pendingConfirmations[id] = confirmation
                try { context.startActivity(Intent(confirmation).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
                catch (_: Exception) {
                    pendingConfirmations.remove(id)
                    operation.put("state","failed").put("error","package_installer_confirmation_unavailable")
                    save(context,operation)
                }
                return
            }
            PackageInstaller.STATUS_SUCCESS -> {
                pendingConfirmations.remove(id)
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
            PackageInstaller.STATUS_FAILURE_ABORTED -> {
                pendingConfirmations.remove(id)
                operation.put("state","cancelled")
            }
            else -> {
                pendingConfirmations.remove(id)
                val code=when(status) {
                    PackageInstaller.STATUS_FAILURE_BLOCKED -> "package_installer_blocked"
                    PackageInstaller.STATUS_FAILURE_CONFLICT -> "package_installer_conflict"
                    PackageInstaller.STATUS_FAILURE_INCOMPATIBLE -> "package_installer_incompatible"
                    PackageInstaller.STATUS_FAILURE_INVALID -> "package_installer_invalid"
                    PackageInstaller.STATUS_FAILURE_STORAGE -> "package_installer_storage"
                    else -> "package_installer_failed"
                }
                // Keep numeric diagnostics; system messages may expose local paths or other apps.
                operation.put("state","failed").put("error",code)
                if(intent.hasExtra(LEGACY_STATUS)) {
                    operation.put("legacyStatus",intent.getIntExtra(LEGACY_STATUS,0))
                }
            }
        }
        save(context,operation)
    }
}

class ExtensionInstallReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) { ExtensionPackages.received(context,intent) }
}
