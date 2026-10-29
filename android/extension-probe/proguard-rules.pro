# Instrumentation runs in a separate APK, outside the target shrinker's call graph.
# Keep shared AndroidX ABI (Trace, ActivityScenario and lifecycle facades included).
-keep class androidx.** { *; }
