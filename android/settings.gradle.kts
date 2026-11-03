pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
    resolutionStrategy {
        eachPlugin {
            // Chaquopy (Python for Android, MIT licence) is published as com.chaquo.python:gradle
            if (requested.id.id == "com.chaquo.python") useModule("com.chaquo.python:gradle:${requested.version}")
        }
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}
rootProject.name = "Shuinkan"
include(":app")
