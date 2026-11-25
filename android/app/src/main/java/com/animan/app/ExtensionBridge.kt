package com.animan.app

import android.content.Context
import android.os.ParcelFileDescriptor
import androidx.core.content.FileProvider
import com.animan.extensions.IExtensionHttp
import com.animan.extensions.ExtensionHostClient
import com.chaquo.python.Python
import java.io.File
import java.util.concurrent.*

/** Python talks only to this small, kept facade; extension classes live in :extensions. */
object ExtensionBridge {
    private lateinit var context: Context
    private lateinit var client: ExtensionHostClient
    private val network = ThreadPoolExecutor(2,4,30,TimeUnit.SECONDS,ArrayBlockingQueue(32))

    private val gateway = object : IExtensionHttp.Stub() {
        override fun request(payload: String): ParcelFileDescriptor {
            require(payload.length <= 3_000_000)
            return ExtensionResponsePipe.open(network) {
                val data = try {
                    check(Python.isStarted()) { "The HTTP owner is not ready" }
                    Python.getInstance().getModule("android_runtime").callAttr("extension_http", payload).toString()
                } catch (_: Exception) { "{\"error\":\"source_network_unavailable\"}" }
                data.toByteArray(Charsets.UTF_8)
            }
        }
    }

    @JvmStatic @Synchronized fun initialize(value: Context) {
        if (::context.isInitialized) return
        context = value.applicationContext
        client = ExtensionHostClient(context,gateway)
        try { ExtensionPackages.reconcile(context) } catch (_: Exception) { }
    }
    @JvmStatic fun discover(): String = client.discover()
    @JvmStatic fun invoke(payload: String): String = client.invoke(payload)
    @JvmStatic fun cancel(id: String) { client.cancel(id) }
    @JvmStatic fun inspect(path: String): String = ExtensionPackages.inspect(context, path).toString()
    @JvmStatic fun install(path: String, expectedPackage: String): String = ExtensionPackages.install(context, path, expectedPackage).toString()
    @JvmStatic fun uninstall(pkg: String): String = ExtensionPackages.uninstall(context, pkg).toString()
    @JvmStatic fun operations(): String = ExtensionPackages.operations(context).toString()
    @JvmStatic fun cancelInstallation(id: String): String = ExtensionPackages.cancel(context,id).toString()
    @JvmStatic fun confirmOperation(id: String): String = ExtensionPackages.openConfirmation(context, id).toString()
    private fun appContext(): Context = if (::context.isInitialized) context else EngineHost.context

    @JvmStatic fun installAppUpdate(path: String): String =
        ExtensionPackages.installSelfUpdate(appContext(), path).toString()

    @JvmStatic fun appUpdateStatus(operationId: String): String =
        ExtensionPackages.operationStatus(appContext(), operationId).toString()

    @JvmStatic fun confirmAppUpdate(operationId: String, path: String): String =
        ExtensionPackages.confirmOrLaunchSelfUpdate(appContext(), operationId, path).toString()

    @JvmStatic fun inspectSelfUpdate(path: String): String =
        ExtensionPackages.inspect(appContext(), path, allowSelfUpdate = true).toString()

    @JvmStatic fun selfUpdateUri(path: String): String {
        val ctx = appContext()
        return FileProvider.getUriForFile(ctx, "${ctx.packageName}.fileprovider", File(path)).toString()
    }

    @JvmStatic fun resumePendingInstalls() {
        if (::context.isInitialized) {
            ExtensionPackages.resume(context)
        } else {
            try { ExtensionPackages.resume(EngineHost.context) } catch (_: Exception) { }
        }
    }
}
