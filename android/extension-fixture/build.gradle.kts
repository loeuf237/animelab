plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "org.animelab.extensionfixture"
    compileSdk = 36
    defaultConfig {
        applicationId = "eu.kanade.tachiyomi.animeextension.all.animelabfixture"
        minSdk = 29
        targetSdk = 35
        versionCode = 1
    }
    buildFeatures { buildConfig = true }
    flavorDimensions += "extensionApi"
    productFlavors {
        (12..17).forEach { api ->
            create("api$api") {
                dimension = "extensionApi"
                applicationIdSuffix = ".api$api"
                versionName = "$api.1"
                manifestPlaceholders["fixtureApi"] = api.toString()
                buildConfigField("int", "EXTENSION_API", api.toString())
            }
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}
kotlin { compilerOptions { jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17) } }
dependencies { compileOnly(project(":extension-runtime")) }
