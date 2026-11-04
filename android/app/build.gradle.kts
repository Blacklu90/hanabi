import java.io.File

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

// Keep the app version in step with the desktop app (app/desktop.py).
val shuinkanVersion: String = File(rootDir.parentFile, "app/desktop.py").readLines()
    .first { it.startsWith("VERSION = ") }.substringAfter('"').substringBefore('"')
val versionParts = shuinkanVersion.split(".").map { it.toInt() }

android {
    namespace = "io.github.blacklu90.shuinkan"
    compileSdk = 35

    defaultConfig {
        applicationId = "io.github.blacklu90.shuinkan"
        minSdk = 24
        targetSdk = 35
        versionName = shuinkanVersion
        versionCode = versionParts[0] * 10000 + versionParts[1] * 100 + versionParts[2]
        ndk { abiFilters += listOf("arm64-v8a", "x86_64") }  // phones + emulators
    }

    signingConfigs {
        create("release") {
            // A real release key can be supplied via CI secrets; otherwise the project's published debug key is used,
            // so updates install over each other (same signature) without losing your progress.
            val ks = System.getenv("SHUINKAN_KEYSTORE")
            if (ks != null && File(ks).exists()) {
                storeFile = File(ks)
                storePassword = System.getenv("SHUINKAN_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("SHUINKAN_KEY_ALIAS")
                keyPassword = System.getenv("SHUINKAN_KEY_PASSWORD")
            } else {
                storeFile = File(rootDir, "shuinkan-debug.keystore")
                storePassword = "android"
                keyAlias = "androiddebugkey"
                keyPassword = "android"
            }
        }
    }

    buildTypes {
        getByName("release") {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("release")
        }
    }
    buildFeatures { buildConfig = true }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    androidResources { noCompress += listOf("db") }  // content.db: copy straight out of the APK
}

chaquopy {
    defaultConfig {
        version = "3.12"
        System.getenv("CHAQUOPY_BUILD_PYTHON")?.let { buildPython(it) }
        pip {
            install("-r", "../../requirements-android.txt")
        }
    }
}

dependencies {
    implementation("androidx.activity:activity-ktx:1.9.3")
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.webkit:webkit:1.12.1")
    implementation("com.google.android.gms:play-services-code-scanner:16.1.0")  // QR codes for Wi-Fi sync
    implementation("androidx.fragment:fragment-ktx:1.8.5")  // the scanner brings an old Fragment; ActivityResult needs 1.3+
}
