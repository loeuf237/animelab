# Python resolves these names and methods with java.jclass, outside R8's call graph.
-keep class com.animan.app.BuildConfig { public static boolean EXTENSION_RUNTIME_ENABLED; }
-keep class com.animan.app.MediaBridge { *; }
-keep class com.animan.app.CryptoBridge { *; }
-keep class com.animan.app.NativeHooks { *; }
-keep class com.animan.app.VerificationBridge { *; }
-keep class com.animan.app.StorageAccess { *; }
-keep class com.animan.app.ExtensionBridge { *; }
-keep class com.animan.app.ExtensionInstallReceiver { *; }

# FFmpeg calls these classes from JNI. Retain callbacks as well as native methods.
# Chaquopy adds its own consumer rules for com.chaquo.python and Kotlin functions.
-keep class com.arthenica.ffmpegkit.** { *; }
-keep class com.arthenica.smartexception.** { *; }

# Keep the same entry points for release instrumentation and lifecycle callbacks.
-keep class com.animan.app.EngineHost { *; }
-keep class com.animan.app.MainActivity { *; }

# AndroidX instrumentation shares this class with the optimized application.
# Its null-check entry points may be called only by the external test APK.
-keep class kotlin.jvm.internal.Intrinsics { *; }

# Kotlin/AndroidX APIs invoked by the separately compiled instrumentation APK.
# R8 may otherwise rewrite signatures or inline the only application call sites.
# Keep the small shared boundary, while shrinking the remaining libraries.
-keep class kotlin.Pair { *; }
-keep class kotlin.Result { *; }
-keep class kotlin.jvm.internal.Ref$ObjectRef { *; }
-keep class kotlin.coroutines.jvm.internal.SuspendLambda { *; }
-keep class kotlinx.coroutines.CancellableContinuationImpl { *; }
-keep class kotlinx.coroutines.CancellableContinuation { *; }
-keep class kotlin.coroutines.Continuation { *; }
-keep class kotlinx.coroutines.Dispatchers { *; }
-keep class androidx.concurrent.futures.** { *; }
-keep class androidx.tracing.** { *; }
-keep class com.animan.app.R$id {
    public static int webView;
    public static int loadingLayout;
}

# The runner and the Kotlin test source also use these shared facades. Retain
# their ABI even where the application optimizer would inline every own caller.
-keep class kotlin.Lazy** { *; }
-keep class kotlin.ResultKt { *; }
-keep class kotlin.Unit { *; }
-keep class kotlin.coroutines.ContinuationKt { *; }
-keep class kotlin.coroutines.intrinsics.IntrinsicsKt** { *; }
-keep class kotlin.coroutines.jvm.internal.DebugProbesKt { *; }
-keep class kotlin.io.ByteStreamsKt { *; }
-keep class kotlin.io.CloseableKt { *; }
-keep class kotlin.io.FilesKt** { *; }
-keep class kotlin.io.TextStreamsKt { *; }
-keep class kotlin.jvm.internal.FunctionReferenceImpl { *; }
-keep class kotlin.jvm.internal.StringCompanionObject { *; }
-keep class kotlin.text.Charsets { *; }
-keep class kotlin.time.Duration** { *; }
-keep class kotlinx.coroutines.BuildersKt** { *; }
-keep class kotlinx.coroutines.CancellableContinuation$DefaultImpls { *; }
-keep class kotlinx.coroutines.CoroutineStart { *; }
-keep class kotlinx.coroutines.Deferred { *; }
-keep class kotlinx.coroutines.ExecutorsKt { *; }
-keep class kotlinx.coroutines.Job { *; }
-keep class kotlinx.coroutines.Job$DefaultImpls { *; }
-keep class kotlinx.coroutines.TimeoutKt { *; }
-keep class kotlin.collections.CollectionsKt** {
    public static java.util.List distinct(java.lang.Iterable);
    public static java.util.List mutableListOf(java.lang.Object[]);
    public static java.util.List listOf(...);
}
-keep class kotlin.text.StringsKt** {
    public static *** contains*(...);
    public static *** startsWith*(...);
    public static *** endsWith*(...);
    public static *** lineSequence(...);
}
