package com.animan.app

import android.content.Context
import android.os.ParcelFileDescriptor
import com.animan.extensions.IExtensionHttp
import com.animan.extensions.ExtensionHostClient
import com.chaquo.python.Python
import java.util.concurrent.*

/** Python talks only to this small, kept facade; extension classes live in :extensions. */
object ExtensionBridge {
    private lateinit var context: Context
    private lateinit var client: ExtensionHostClient
    private val network = ThreadPoolExecutor(2,4,30,TimeUnit.SECONDS,ArrayBlockingQueue(32))

    private val gateway = object : IExtensionHttp.Stub() {
        override fun request(payload: String): ParcelFileDescriptor {
            require(payload.length <= 3_000_000)
            val pipe = ParcelFileDescriptor.createPipe()
            network.execute {
                ParcelFileDescriptor.AutoCloseOutputStream(pipe[1]).use { output ->
                    val data = try {
                        check(Python.isStarted()) { "The HTTP owner is not ready" }
                        Python.getInstance().getModule("android_runtime").callAttr("extension_http", payload).toString()
                    } catch (_: Exception) { "{\"error\":\"source_network_unavailable\"}" }
                    output.write(data.toByteArray(Charsets.UTF_8))
                }
            }
            return pipe[0]
        }
    }

    @JvmStatic @Synchronized fun initialize(value: Context) {
        if (::context.isInitialized) return
        context = value.applicationContext
        client = ExtensionHostClient(context,gateway)
    }
    @JvmStatic fun discover(): String = client.discover()
    @JvmStatic fun invoke(payload: String): String = client.invoke(payload)
    @JvmStatic fun cancel(id: String) { client.cancel(id) }
    @JvmStatic fun inspect(path: String): String = ExtensionPackages.inspect(context, path).toString()
    @JvmStatic fun install(path: String, expectedPackage: String): String = ExtensionPackages.install(context, path, expectedPackage).toString()
    @JvmStatic fun uninstall(pkg: String): String = ExtensionPackages.uninstall(context, pkg).toString()
    @JvmStatic fun operations(): String = ExtensionPackages.operations(context).toString()
    @JvmStatic fun cancelInstallation(id: String): String = ExtensionPackages.cancel(context,id).toString()
    @JvmStatic fun resumePendingInstalls() { if (::context.isInitialized) ExtensionPackages.resume(context) }
}
