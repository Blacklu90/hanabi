import java.io.File

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

// Keep the app version in step with the desktop app (app/desktop.py).
val hanabiVersion: String = File(rootDir.parentFile, "app/desktop.py").readLines()
    .first { it.startsWith("VERSION = ") }.substringAfter('"').substringBefore('"')
val versionParts = hanabiVersion.split(".").map { it.toInt() }

android {
    namespace = "io.github.blacklu90.hanabi"
    compileSdk = 35

    defaultConfig {
        applicationId = "io.github.blacklu90.hanabi"
        minSdk = 24
        targetSdk = 35
        versionName = hanabiVersion
        versionCode = versionParts[0] * 10000 + versionParts[1] * 100 + versionParts[2]
        ndk { abiFilters += listOf("arm64-v8a", "x86_64") }  // phones + emulators
    }

    signingConfigs {
        create("release") {
            // A real release key can be supplied via CI secrets; otherwise the project's published debug key is used,
            // so updates install over each other (same signature) without losing your progress.
            val ks = System.getenv("HANABI_KEYSTORE")
            if (ks != null && File(ks).exists()) {
                storeFile = File(ks)
                storePassword = System.getenv("HANABI_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("HANABI_KEY_ALIAS")
                keyPassword = System.getenv("HANABI_KEY_PASSWORD")
            } else {
                storeFile = File(rootDir, "hanabi-debug.keystore")
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
}
