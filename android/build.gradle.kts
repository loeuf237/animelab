// Kotlin 2.4 extension ABI requires the corresponding metadata reader in R8.
buildscript {
    repositories {
        google(); mavenCentral()
        maven {
            url = uri("https://storage.googleapis.com/r8-releases/raw")
            content { includeModule("com.android.tools", "r8") }
        }
    }
    dependencies { classpath("com.android.tools:r8:9.1.29") }
}

// Top-level build file
plugins {
    id("com.android.application") version "8.8.0" apply false
    id("com.android.library") version "8.8.0" apply false
    id("org.jetbrains.kotlin.android") version "2.4.0" apply false
    id("org.jetbrains.kotlin.plugin.serialization") version "2.4.0" apply false
    id("com.chaquo.python") version "17.1.0" apply false
}
