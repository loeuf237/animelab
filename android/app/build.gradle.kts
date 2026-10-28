import java.io.File

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

// Disable only for a controlled size comparison using the same application code.
val optimizeApk = providers.gradleProperty("animelab.optimizeApk").orNull != "false"
val packagingPython = System.getenv("ANIMAN_BUILD_PYTHON") ?: "python3"
val optimizer = rootProject.file("../scripts/android_optimize.py")
val isolatedValidation = providers.gradleProperty("animelab.isolatedValidation").orNull == "true"

android {
    namespace = "com.animan.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.animan.app"
        minSdk = 29
        targetSdk = 35
        versionCode = 218
        versionName = "0.1.5"
        manifestPlaceholders["appLabel"] = "@string/app_name"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        ndk {
            abiFilters += listOf("arm64-v8a")
        }
    }

    signingConfigs {
        create("release") {
            val keyPath = System.getenv("ANIMAN_ANDROID_KEYSTORE")
            if (!keyPath.isNullOrBlank()) {
                storeFile = file(keyPath)
                storePassword = System.getenv("ANIMAN_ANDROID_STORE_PASSWORD")
                keyAlias = System.getenv("ANIMAN_ANDROID_KEY_ALIAS")
                keyPassword = System.getenv("ANIMAN_ANDROID_KEY_PASSWORD")
            }
        }
    }
    buildTypes {
        release {
            isMinifyEnabled = optimizeApk
            isShrinkResources = optimizeApk
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = signingConfigs.getByName("release")
        }
        debug {
            isMinifyEnabled = false
        }
        create("validation") {
            initWith(getByName("release"))
            // AGP's initWith does not copy every resource-shrinker property.
            isMinifyEnabled = optimizeApk
            isShrinkResources = optimizeApk
            if (isolatedValidation) {
                applicationIdSuffix = ".a11test"
                manifestPlaceholders["appLabel"] = "AnimeLab A11 test"
            }
            signingConfig = signingConfigs.getByName("debug")
            matchingFallbacks += listOf("release")
        }
    }
    // The temporary validation key is never used by the publication job.
    testBuildType = if (System.getenv("ANIMAN_ANDROID_KEYSTORE").isNullOrBlank()) "validation" else "release"

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        viewBinding = true
        buildConfig = true
    }

    lint {
        checkReleaseBuilds = false
        abortOnError = false
    }
}

dependencies {
    implementation(project(":extension-runtime"))
    implementation("androidx.core:core-ktx:1.13.0")
    implementation("androidx.appcompat:appcompat:1.6.1")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.webkit:webkit:1.10.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.7.0")
    // Keep the runtime ABI aligned with AndroidX Test (including tracing on API 30+).
    implementation("androidx.tracing:tracing:1.1.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.7.3")
    implementation("dev.ffmpegkit-maintained:ffmpeg-kit-full-gpl:6.0.4")
    // The maintained AAR still references these original exception helpers but
    // does not declare them in its published dependency metadata.
    implementation("com.arthenica:smart-exception-java:0.2.1")
    androidTestImplementation("androidx.test:runner:1.6.2")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test:rules:1.6.1")
}

chaquopy {
    defaultConfig {
        version = "3.13"
        System.getenv("ANIMAN_BUILD_PYTHON")?.let { buildPython(it) }
        extractPackages("animelab")
        pip {
            options("--timeout", "120", "--find-links", "${rootProject.projectDir}/wheels")
            install("-r", System.getenv("ANIMAN_ANDROID_REQUIREMENTS")
                ?: "${rootProject.projectDir}/requirements.txt")
        }
    }
}

val syncPythonSource by tasks.registering(Sync::class) {
    inputs.property("optimizeApk", optimizeApk)
    inputs.file(optimizer)
    from("${rootProject.projectDir}/..") {
        include("animelab/**")
        include("run.py")
        include("android_runtime.py")
        include("frontend/dist/**")
        exclude("**/__pycache__/**")
        exclude("**/.pytest_cache/**")
        exclude("**/*.pyc")
        exclude("animelab/Artefacts/**")
        exclude("animelab/ressources/**")
    }
    into("${projectDir}/src/main/python")
    if (optimizeApk) {
        doLast {
            project.exec {
                commandLine(packagingPython, optimizer, "sources", destinationDir)
            }
        }
    }
}

// Chaquopy 17.1 packages .so files inside requirements-*.imy; AGP's native
// stripping cannot see them. Modify only generated archives, before build.json
// computes their hashes. pip's unpacked inputs and downloaded wheels stay intact.
tasks.matching { it.name.matches(Regex("generate(Release|Validation)PythonRequirementsAssets")) }
    .configureEach {
        inputs.property("optimizeApk", optimizeApk)
        inputs.property("llvmStrip", System.getenv("ANIMAN_LLVM_STRIP") ?: "llvm-strip")
        inputs.file(optimizer)
        inputs.file(rootProject.file("../scripts/android_apk_size.py"))
        if (optimizeApk) {
            val variant = name.removePrefix("generate").removeSuffix("PythonRequirementsAssets")
                .replaceFirstChar { it.lowercase() }
            val audit = layout.buildDirectory.dir("reports/native-optimization/$variant")
            outputs.dir(audit)
            doLast {
                project.exec {
                    commandLine(packagingPython, optimizer, "requirements",
                        layout.buildDirectory.dir("python/assets/requirements/$variant").get().asFile,
                        "--output", audit.get().asFile)
                }
            }
        }
    }

tasks.matching { it.name.contains("Python") && it.name != "syncPythonSource" }.configureEach {
    dependsOn(syncPythonSource)
}
tasks.named("preBuild") {
    dependsOn(syncPythonSource)
}

kotlin { compilerOptions { jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17) } }
