package com.animan.extensions

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import java.util.concurrent.*

/** Parent-side deadlines remain effective even if extension code blocks a Binder thread. */
class ExtensionHostClient(value: Context, private val gateway: IExtensionHttp?=null,
                          private val timeoutMillis: Long=55_000) : AutoCloseable {
    private val context=value.applicationContext
    private val main=Handler(Looper.getMainLooper())
    @Volatile private var worker: IExtensionRuntime?=null
    @Volatile private var ready=CountDownLatch(1)
    @Volatile private var closed=false
    private val calls=ThreadPoolExecutor(2,4,30,TimeUnit.SECONDS,ArrayBlockingQueue(16))
    private val connection=object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName,binder: IBinder) {
            val service=IExtensionRuntime.Stub.asInterface(binder)
            gateway?.let(service::attachGateway)
            worker=service; ready.countDown()
        }
        override fun onServiceDisconnected(name: ComponentName) { worker=null; ready=CountDownLatch(1) }
        override fun onBindingDied(name: ComponentName) {
            worker=null; ready=CountDownLatch(1)
            try { context.unbindService(this) } catch (_: IllegalArgumentException) { }
            bind()
        }
    }
    init { bind() }
    private fun bind() { main.post { if(!closed) context.bindService(Intent(context,ExtensionRuntimeService::class.java),connection,Context.BIND_AUTO_CREATE) } }
    private fun runtime(): IExtensionRuntime {
        check(ready.await(15,TimeUnit.SECONDS))
        return requireNotNull(worker)
    }
    private fun call(action: (IExtensionRuntime)->String): String {
        if(closed) return "{\"ok\":false,\"code\":\"extension_runtime_unavailable\"}"
        val future=try { calls.submit<String> { action(runtime()) } }
            catch (_: RejectedExecutionException) { return "{\"ok\":false,\"code\":\"extension_runtime_busy\"}" }
        return try { future.get(timeoutMillis,TimeUnit.MILLISECONDS) }
        catch (_: TimeoutException) {
            future.cancel(true)
            try { worker?.terminate() } catch (_: Exception) { }
            "{\"ok\":false,\"code\":\"extension_runtime_timeout\"}"
        } catch (_: Exception) { "{\"ok\":false,\"code\":\"extension_runtime_unavailable\"}" }
    }
    fun discover(): String=call { it.discover() }
    fun invoke(payload: String): String=call { it.invoke(payload) }
    fun cancel(id: String) { try { worker?.cancel(id) } catch (_: Exception) { } }
    override fun close() {
        closed=true; calls.shutdownNow()
        main.post { try { context.unbindService(connection) } catch (_: IllegalArgumentException) { } }
    }
}
