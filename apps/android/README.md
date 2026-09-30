# Embyr Android foundation

This is the native Kotlin and Jetpack Compose Android project for M7-02 (#117). It has one `:app` module, one Activity, typed Navigation Compose placeholders, and infrastructure for auth, transport, durable commands, World storage, and local preferences. Product sign-in, onboarding, recommendations, Exploration, Memory, and forest rendering are later issues.

## Build configuration

Use JDK 21, Gradle wrapper 9.5.0, AGP 9.3.1, Kotlin/Compose compiler plugin 2.4.20, and Compose BOM 2026.09.00. The application namespace and ID are `app.embyr`. `minSdk=26`, `targetSdk=36`, and `compileSdk=37`. Install SDK Platform 37.0 and SDK Build Tools 36.0.0. External Play application-ID ownership must be checked before distribution.

Set these three **client-safe** values as environment variables or in ignored `apps/android/local.properties` before launching:

```properties
EMBYR_API_BASE_URL=https://api.example.invalid/
SUPABASE_URL=https://supabase.example.invalid/
SUPABASE_PUBLISHABLE_KEY=sb_publishable_replace_with_alpha_value
```

The values above are compilation/testing placeholders, not working alpha services. Startup rejects missing values, non-HTTPS base URLs, and keys without the `sb_publishable_` prefix. Never provide a service-role key, database credential, or backend secret to the Android build. Auth sessions are encrypted with Android Keystore and stored under `noBackupFilesDir`.

The auth callback scheme/host is not frozen yet, so the manifest has no auth deep-link filter. M7-03 owns callback verification and the sign-in flow.

## Commands

From `apps/android`:

```sh
./gradlew :app:lintDebug :app:testDebugUnitTest :app:assembleDebug :app:assembleRelease
python -m pip install -r tools/requirements-contracts.txt
python tools/validate_m6_public_examples.py
./gradlew :app:connectedDebugAndroidTest
```

The JVM fixture tests read canonical files under the repository's `docs/api/fixtures` directory; the schema script reads the canonical M6 schema. Device tests cover Room persistence, owner isolation, World rollback, Keystore storage, and placeholder navigation. CI runs lint, JVM/schema tests, and debug/release builds. Until an emulator CI gate is reliable, run `connectedDebugAndroidTest` on API 26 and a current emulator and record the result in the PR.

Release assembly is unsigned and R8 enabled. Distribution signing and hosted Internal Alpha validation belong to M7-06.
