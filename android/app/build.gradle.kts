plugins { id("com.android.application"); id("org.jetbrains.kotlin.android") }
android {
    namespace = "ru.jarvis.assistant"
    compileSdk = 35
    buildToolsVersion = "36.0.0"
    defaultConfig {
        applicationId = "ru.jarvis.assistant"
        minSdk = 26
        targetSdk = 35
        versionCode = 4
        versionName = "0.1.0-alpha.7"
        resValue("string", "app_name", "Shelter")
    }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    packaging { resources.excludes += setOf("META-INF/AL2.0", "META-INF/LGPL2.1", "META-INF/INDEX.LIST") }
}
kotlin { compilerOptions { jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17) } }
dependencies {
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")
    implementation("com.alphacephei:vosk-android:0.3.75@aar")
    implementation("net.java.dev.jna:jna:5.18.1@aar")
    implementation("com.google.ai.edge.litertlm:litertlm-android:0.19.1")
    testImplementation("junit:junit:4.13.2")
}
