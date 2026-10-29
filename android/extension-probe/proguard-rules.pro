# Instrumentation runs in a separate APK, outside the target shrinker's call graph.
# Keep shared AndroidX ABI (Trace, ActivityScenario and lifecycle facades included).
-keep class androidx.** { *; }
# The driver invokes the copied real installer from its separate test APK.
-keep class com.animan.app.ExtensionPackages { *; }
-keep class com.animan.app.ExtensionInstallReceiver { *; }
