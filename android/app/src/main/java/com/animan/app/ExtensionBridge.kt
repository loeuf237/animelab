package com.animan.app

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.os.IBinder
import android.os.ParcelFileDescriptor
import com.animan.extensions.IExtensionHttp
import com.animan.extensions.IExtensionRuntime
import com.chaquo.python.Python
import org.json.JSONObject
import java.util.concurrent.*

/** Python talks only to this small, kept facade; extension classes live in :extensions. */
object ExtensionBridge {
    private lateinit var context: Context
    @Volatile private var worker: IExtensionRuntime? = null
    @Volatile private var connectionReady = CountDownLatch(1)
    private val calls = ThreadPoolExecutor(2, 4, 30, TimeUnit.SECONDS, ArrayBlockingQueue(16))
    private val network = Executors.newFixedThreadPool(4)

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

    private val connection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName, binder: IBinder) {
            val service = IExtensionRuntime.Stub.asInterface(binder)
            service.attachGateway(gateway)
            worker = service
            connectionReady.countDown()
        }
        override fun onServiceDisconnected(name: ComponentName) {
            worker = null; connectionReady = CountDownLatch(1)
        }
        override fun onBindingDied(name: ComponentName) {
            worker = null; connectionReady = CountDownLatch(1)
            context.unbindService(this)
            bind()
        }
    }

    @JvmStatic @Synchronized fun initialize(value: Context) {
        if (::context.isInitialized) return
        context = value.applicationContext
        bind()
    }

    private fun bind() {
        EngineHost.main.post {
            context.bindService(Intent(context, com.animan.extensions.ExtensionRuntimeService::class.java), connection, Context.BIND_AUTO_CREATE)
        }
    }

    private fun runtime(): IExtensionRuntime {
        check(connectionReady.await(15, TimeUnit.SECONDS)) { "Extension runtime did not bind" }
        return requireNotNull(worker) { "Extension runtime unavailable" }
    }

    private fun call(action: (IExtensionRuntime) -> String): String {
        val future = calls.submit<String> { action(runtime()) }
        return try { future.get(55, TimeUnit.SECONDS) }
        catch (_: TimeoutException) {
            future.cancel(true)
            try { worker?.terminate() } catch (_: Exception) { }
            "{\"ok\":false,\"code\":\"extension_runtime_timeout\"}"
        } catch (_: Exception) {
            "{\"ok\":false,\"code\":\"extension_runtime_unavailable\"}"
        }
    }

    @JvmStatic fun discover(): String = call { it.discover() }
    @JvmStatic fun invoke(payload: String): String = call { it.invoke(payload) }
    @JvmStatic fun cancel(id: String) { try { worker?.cancel(id) } catch (_: Exception) { } }
    @JvmStatic fun inspect(path: String): String = ExtensionPackages.inspect(context, path).toString()
    @JvmStatic fun install(path: String, expectedPackage: String): String = ExtensionPackages.install(context, path, expectedPackage).toString()
    @JvmStatic fun uninstall(pkg: String): String = ExtensionPackages.uninstall(context, pkg).toString()
    @JvmStatic fun operations(): String = ExtensionPackages.operations(context).toString()
    @JvmStatic fun cancelInstallation(id: String): String = ExtensionPackages.cancel(context,id).toString()
    @JvmStatic fun resumePendingInstalls() { if (::context.isInitialized) ExtensionPackages.resume(context) }
}
