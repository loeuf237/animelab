# Android extension runtime host API

The source API, HTTP request helpers, Rx/coroutine adapter and cookie jar are
adapted from Aniyomi, commit `97414446b8a95994c72dd33c41c971a89d4d25b8`:
https://github.com/aniyomiorg/aniyomi/tree/97414446b8a95994c72dd33c41c971a89d4d25b8

Copyright their respective contributors. Apache License 2.0; the full license is
included as LICENSE-APACHE-2.0.txt. The optional Compose Stable annotation is
removed; Android preference typealiases are compiled directly. Network services
and the host bridge are implemented by AnimeLab. Original APKs are not rewritten.

Dependencies are pinned in build.gradle.kts to the upstream ABI requirements.
Kotlin 2.4 and R8 9.1.29 are used for the current extension metadata format:
https://developer.android.com/build/kotlin-support

Package discovery, installation and dynamic execution must be validated by the
Android extension instrumentation workflow. A successful JVM/Python unit test is
not proof of Android APK compatibility.
