plugins {
    id("com.android.library")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.serialization")
}

android {
    namespace = "com.animan.extensions"
    compileSdk = 36
    buildFeatures { aidl = true }
    defaultConfig {
        minSdk = 29
        consumerProguardFiles("consumer-rules.pro")
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
        freeCompilerArgs.add("-Xjvm-default=all-compatibility")
        freeCompilerArgs.add("-Xcontext-parameters")
    }
}

dependencies {
    implementation("org.jspecify:jspecify:1.0.0")
    api("com.squareup.okhttp3:okhttp:5.4.0")
    api("org.jsoup:jsoup:1.22.2")
    api("io.reactivex:rxjava:1.3.8")
    api("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")
    api("org.jetbrains.kotlinx:kotlinx-serialization-json:1.9.0")
    api("org.jetbrains.kotlinx:kotlinx-serialization-json-okio:1.9.0")
    api("com.github.mihonapp:injekt:91edab2317")
    api("androidx.preference:preference-ktx:1.2.1")
    api("app.cash.quickjs:quickjs-android:0.9.2")
    api("org.nanohttpd:nanohttpd:2.3.1")
    implementation("com.squareup.logcat:logcat:0.1")
}
