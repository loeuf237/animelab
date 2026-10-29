plugins {
    id("com.android.library")
}

val upstream = layout.buildDirectory.dir("upstream")
val prepareSources = tasks.register<Exec>("prepareQuickJsSources") {
    inputs.file("upstream.json")
    inputs.file(rootProject.file("../scripts/prepare_quickjs.py"))
    outputs.dir(upstream)
    commandLine(System.getenv("ANIMAN_BUILD_PYTHON") ?: "python3",
        rootProject.file("../scripts/prepare_quickjs.py"), upstream.get().asFile)
}

android {
    namespace = "app.cash.quickjs"
    compileSdk = 36
    ndkVersion = "27.2.12479018"
    defaultConfig {
        minSdk = 29
        consumerProguardFiles("consumer-rules.pro")
        ndk { abiFilters += listOf("arm64-v8a", "x86_64") }
        externalNativeBuild {
            cmake {
                arguments += listOf("-DANDROID_STL=c++_static", "-DANDROID_SUPPORT_FLEXIBLE_PAGE_SIZES=ON",
                    "-DUPSTREAM_ROOT=${upstream.get().asFile.absolutePath}")
            }
        }
    }
    sourceSets["main"].java.srcDirs(upstream.map { it.dir("quickjs/common/java") },
        upstream.map { it.dir("quickjs/android/src/main/java") })
    sourceSets["main"].assets.srcDir(upstream.map { it.dir("licenses") })
    externalNativeBuild { cmake { path = file("CMakeLists.txt"); version = "3.22.1" } }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

tasks.configureEach {
    if (name == "preBuild" || name.startsWith("configureCMake") || name.startsWith("buildCMake") ||
        name.startsWith("externalNativeBuild") || name.startsWith("generateJsonModel")) dependsOn(prepareSources)
}

dependencies { implementation("androidx.annotation:annotation:1.9.1") }
