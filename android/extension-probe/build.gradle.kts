plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}
val fixtures = tasks.register<Copy>("stageExtensionFixtures") {
    dependsOn((12..17).map { ":extension-fixture:assembleApi${it}Debug" })
    from(rootProject.file("extension-fixture/build/outputs/apk")) {
        include("**/*.apk")
        eachFile { path = name }
        includeEmptyDirs = false
    }
    into(layout.buildDirectory.dir("generated/fixture-assets"))
}
val installerSource = tasks.register<Copy>("stagePackageInstaller") {
    from(rootProject.file("app/src/main/java/com/animan/app")) { include("ExtensionPackages.kt") }
    into(layout.buildDirectory.dir("generated/package-installer/com/animan/app"))
}
android {
    namespace = "com.animan.extensions.probe"
    compileSdk = 36
    defaultConfig {
        applicationId = "com.animan.extensions.probe"
        minSdk = 29
        targetSdk = 35
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }
    buildTypes {
        create("validation") {
            initWith(getByName("release"))
            isMinifyEnabled = true
            signingConfig = signingConfigs.getByName("debug")
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"))
            matchingFallbacks += listOf("release")
        }
    }
    testBuildType = "validation"
    sourceSets["main"].assets.srcDir(layout.buildDirectory.dir("generated/fixture-assets"))
    sourceSets["main"].java.srcDir(layout.buildDirectory.dir("generated/package-installer"))
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}
tasks.named("preBuild").configure { dependsOn(installerSource, fixtures) }
kotlin { compilerOptions { jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17) } }
dependencies {
    implementation(project(":extension-runtime"))
    androidTestImplementation("androidx.test:runner:1.6.2")
    androidTestImplementation("com.google.errorprone:error_prone_annotations:2.36.0")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test.uiautomator:uiautomator:2.3.0")
}
