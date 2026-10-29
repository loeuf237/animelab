# QuickJS 0.9.2 ABI with 16 KiB native alignment

The original `app.cash.quickjs:quickjs-android:0.9.2` AAR contains a native
library with 4096-byte LOAD alignment. This module builds the **same pinned
Java/JNI/C sources** with NDK 27 and 16384-byte alignment; the old AAR is not
resolved or packaged. The exported Java classes, native library name and JNI
entry points remain those of QuickJS 0.9.2.

Primary upstream reference:
[cashapp/zipline at a738129](https://github.com/cashapp/zipline/tree/a738129cc4aa99206c00ae49e9c5b15cb58ad880)
(the renamed `cashapp/quickjs-java` repository).

`upstream.json` records the exact Git blob and byte count for each of the 31
source/license files. `scripts/prepare_quickjs.py` downloads only those files,
checks their identities before use, and preserves both the Apache wrapper
license and the engine's MIT notice in the APK assets. It never downloads a
prebuilt replacement `.so`. The only compile compatibility adjustment is a
standard `<functional>` pre-include, because the historical Context.h uses
`std::function` without including that header. Upstream source bytes stay intact.

APK compilation runs in GitHub Actions. ELF alignment is checked on the final
optimized APK, and the emulator test exercises evaluation, Unicode, compiled
bytecode, Java/JavaScript proxies and the original exception type. These checks
must pass before publication; merely changing an ELF header is insufficient.
