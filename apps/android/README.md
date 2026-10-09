# Embyr Android internal alpha

This native Kotlin and Jetpack Compose project includes auth/onboarding/recommendation, reviewed Exploration and optional asynchronous assessment, factual Memory, and the native World forest. M7-06 adds signed Internal Alpha packaging and integrated hardening. Completion requires the physical and live-alpha gates in the [operator runbook](../../docs/android/m7-06-internal-alpha-runbook.md).

## Build configuration

Use JDK 21, Gradle wrapper 9.5.0, AGP 9.3.1, Kotlin/Compose compiler plugin 2.4.20, and Compose BOM 2026.09.00. The namespace and debug application ID are `app.embyr`; release uses `app.embyr.alpha` (Embyr Alpha), version code 2/name `0.1.0-alpha.1`. `minSdk=26`, `targetSdk=36`, and `compileSdk=37`. Install SDK Platform 37.0 and SDK Build Tools 36.0.0. Distribution is protected local USB installation.

Set these three **client-safe** values as environment variables or in ignored `apps/android/local.properties` before launching:

```properties
EMBYR_API_BASE_URL=https://api.example.invalid/
SUPABASE_URL=https://supabase.example.invalid/
SUPABASE_PUBLISHABLE_KEY=sb_publishable_replace_with_alpha_value
```

The values above are compilation/testing placeholders, not working alpha services. Startup rejects missing values, non-HTTPS base URLs, and keys without the `sb_publishable_` prefix. Never provide a service-role key, database credential, or backend secret to the Android build. Auth sessions are encrypted with Android Keystore and stored under `noBackupFilesDir`.

The email code request uses Supabase OTP with `createUser=false` and no redirect URL. Configure the alpha email template to display the OTP code. The manifest has no auth callback filter because this flow verifies the code in the app. The client never needs a service-role key.

## Journey and recovery

After session restore or code verification, the app calls unkeyed `POST /api/v1/session/bootstrap` before binding any private storage. It binds the local owner only to the validated Embyr profile UUID, then refreshes `GET /api/v1/me`. Bootstrap alone has a coordinator-owned, bounded retry; ordinary unkeyed POSTs are not automatically replayed.

Keyed POST commands persist canonical request bytes and a unique idempotency key before sending. An ambiguous command replays the same bytes and key for less than 23 hours. After that cutoff, supported reads reconcile results; unsupported lookup leaves visible ambiguity. A new generation request requires an explicit learner action. Room4 preserves commands, learning drafts/assessment recovery, Memory operations and owner-scoped atomic World state. Versioned interest PUT and reflection PATCH have separate recovery policies.

## Commands

From `apps/android`:

```sh
./gradlew :app:lintDebug :app:testDebugUnitTest :app:assembleDebug :app:assembleRelease :app:assembleDebugAndroidTest
python -m pip install -r tools/requirements-contracts.txt
python tools/validate_m6_public_examples.py
```

The JVM fixture tests read canonical files under the repository's `docs/api/fixtures` directory; the schema script reads the canonical M6 schema. Device tests cover Room migration/persistence, owner isolation, Keystore storage and Compose screens. Physical-device launchers must verify and explicitly target the approved serial; no emulator is authorized. Destructive storage tests use an isolated verification UID. Direct AndroidJUnitRunner results must be labeled as such, rather than as Gradle connected-task results. Real-alpha completion also requires closed enrollment, OTP delivery, reviewed content and operating workers.

`assembleRelease` remains available unsigned for CI. `signedAlphaRelease` requires all four protected signing environment variables described in the runbook, and builds the signed APK/AAB without configuration caching. Release remains non-debuggable, R8/resource-shrunk and shell-profileable for the audited local performance gate. To assemble same-signature release instrumentation, supply signing inputs and use `-PembyrTestBuildType=release :app:assembleReleaseAndroidTest`. Test-harness assembly alone does not prove it runs on the minified release.
