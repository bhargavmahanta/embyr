import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
    alias(libs.plugins.ksp)
    alias(libs.plugins.room)
}

val localProperties = Properties().apply {
    val file = rootProject.file("local.properties")
    if (file.isFile) file.inputStream().use(::load)
}

fun clientConfig(name: String): String =
    providers.environmentVariable(name).orNull ?: localProperties.getProperty(name, "")

fun quoted(value: String): String = "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"") + "\""

// Signing inputs are intentionally environment-only and never read from client configuration.
val alphaSigningNames = listOf(
    "EMBYR_ALPHA_KEYSTORE_PATH", "EMBYR_ALPHA_KEYSTORE_PASSWORD",
    "EMBYR_ALPHA_KEY_ALIAS", "EMBYR_ALPHA_KEY_PASSWORD",
)
val alphaSigningInputs = alphaSigningNames.associateWith { providers.environmentVariable(it).orNull }
val hasAlphaSigning = alphaSigningInputs.values.all { !it.isNullOrBlank() }
val requestsSignedAlpha = gradle.startParameter.taskNames.any { it.substringAfterLast(':') == "signedAlphaRelease" }
check(!alphaSigningInputs.values.any { !it.isNullOrBlank() } || hasAlphaSigning) {
    "Incomplete Alpha signing configuration: supply all four EMBYR_ALPHA signing inputs."
}
check(!requestsSignedAlpha || hasAlphaSigning) {
    "signedAlphaRelease requires the protected EMBYR_ALPHA signing inputs."
}
if (hasAlphaSigning) {
    check(file(alphaSigningInputs.getValue("EMBYR_ALPHA_KEYSTORE_PATH")!!).isFile) {
        "Alpha keystore is unavailable."
    }
    check(!gradle.startParameter.isConfigurationCacheRequested) {
        "Disable configuration caching for local signed builds."
    }
}

android {
    namespace = "app.embyr"
    compileSdk = 37

    defaultConfig {
        applicationId = "app.embyr"
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
        manifestPlaceholders["appLabel"] = "Embyr"
        manifestPlaceholders["shellProfileable"] = "false"
        testInstrumentationRunner = if (providers.gradleProperty("embyrTestBuildType").orNull == "release")
            "app.embyr.AlphaPlatformRunner" else "androidx.test.runner.AndroidJUnitRunner"
        buildConfigField("String", "EMBYR_API_BASE_URL", quoted(clientConfig("EMBYR_API_BASE_URL")))
        buildConfigField("String", "SUPABASE_URL", quoted(clientConfig("SUPABASE_URL")))
        buildConfigField("String", "SUPABASE_PUBLISHABLE_KEY", quoted(clientConfig("SUPABASE_PUBLISHABLE_KEY")))
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    signingConfigs {
        getByName("debug") {
            clientConfig("EMBYR_DEBUG_KEYSTORE").takeIf { it.isNotBlank() }?.let { storeFile = file(it) }
        }
        if (hasAlphaSigning) {
            create("alpha") {
                storeFile = file(alphaSigningInputs.getValue("EMBYR_ALPHA_KEYSTORE_PATH")!!)
                storePassword = alphaSigningInputs.getValue("EMBYR_ALPHA_KEYSTORE_PASSWORD")
                keyAlias = alphaSigningInputs.getValue("EMBYR_ALPHA_KEY_ALIAS")
                keyPassword = alphaSigningInputs.getValue("EMBYR_ALPHA_KEY_PASSWORD")
                storeType = "PKCS12"
            }
        }
    }

    buildTypes {
        release {
            applicationIdSuffix = ".alpha"
            versionNameSuffix = "-alpha.1"
            // Release version differs from the retained development installation.
            manifestPlaceholders["appLabel"] = "Embyr Alpha"
            manifestPlaceholders["shellProfileable"] = "true"
            isDebuggable = false
            if (hasAlphaSigning) signingConfig = signingConfigs.getByName("alpha")
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            testProguardFiles("proguard-android-test.pro")
        }
    }

    // Local same-signature instrumentation may target the actual minified release.
    testBuildType = providers.gradleProperty("embyrTestBuildType").orElse("debug").get().also {
        check(it == "debug" || it == "release") { "Unsupported instrumentation target build type." }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

androidComponents {
    onVariants(selector().withBuildType("release")) { variant ->
        variant.outputs.forEach { it.versionCode.set(2) }
    }
}

tasks.register("signedAlphaRelease") {
    group = "build"
    description = "Build protected signed Internal Alpha APK and AAB (requires local signing inputs)."
    dependsOn("assembleRelease", "bundleRelease")
    doFirst { check(hasAlphaSigning) { "Alpha signing inputs are required." } }
}

room {
    schemaDirectory("$projectDir/schemas")
}

dependencies {
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.material3)
    implementation(libs.activity.compose)
    implementation(libs.navigation.compose)
    implementation(libs.lifecycle.viewmodel.compose)
    implementation(libs.lifecycle.runtime.compose)
    implementation(libs.coroutines.android)
    implementation(libs.serialization.json)
    implementation(libs.retrofit)
    implementation(libs.retrofit.serialization)
    implementation(libs.okhttp)
    implementation(libs.room.runtime)
    ksp(libs.room.compiler)
    implementation(libs.datastore.preferences)
    implementation(libs.supabase.auth)
    implementation(libs.ktor.cio)

    testImplementation(libs.coroutines.test)
    testImplementation(libs.junit)
    testImplementation(libs.mockwebserver)
    testImplementation(libs.room.testing)
    androidTestImplementation(platform(libs.compose.bom))
    debugImplementation(libs.compose.ui.test.manifest)
    androidTestImplementation(libs.compose.ui.test.junit4)
    androidTestImplementation(libs.androidx.test.core)
    androidTestImplementation(libs.androidx.test.runner)
    androidTestImplementation(libs.androidx.test.junit)
    androidTestImplementation(libs.room.testing)
}
