plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}
android {
    namespace = "com.animan.nativeprobe"
    compileSdk = 35
    defaultConfig {
        applicationId = "com.animan.nativeprobe"
        minSdk = 29; targetSdk = 35
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        ndk { abiFilters += listOf(providers.gradleProperty("mediaProbeAbi").orElse("x86_64").get()) }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    sourceSets["main"].java.srcDir(layout.buildDirectory.dir("generated/bridges"))
}
val copyBridges by tasks.registering(Sync::class) {
    from("../app/src/main/java/com/animan/app") { include("MediaBridge.kt", "HardsubProbe.kt", "CryptoBridge.kt", "NativeHooks.kt", "StorageAccess.kt") }
    into(layout.buildDirectory.dir("generated/bridges/com/animan/app"))
}
tasks.named("preBuild") { dependsOn(copyBridges) }
dependencies {
    implementation("androidx.core:core-ktx:1.13.0")
    implementation("dev.ffmpegkit-maintained:ffmpeg-kit-full-gpl:6.0.4")
    implementation("com.arthenica:smart-exception-java:0.2.1")
    androidTestImplementation("androidx.test:runner:1.6.2")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
}

kotlin { compilerOptions { jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17) } }
