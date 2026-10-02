# Embyr Android internal alpha

This native Kotlin and Jetpack Compose project includes the M7-02 foundation (#117) and M7-03 auth, onboarding, and recommendation flow (#118). The app signs in with a Supabase email code, bootstraps the mapped Embyr owner, lets the learner choose up to 20 starter interests, then offers explicit Explore or Surprise recommendations. ACCEPT stops at an Exploration ready handoff; Exploration delivery belongs to #119.

## Build configuration

Use JDK 21, Gradle wrapper 9.5.0, AGP 9.3.1, Kotlin/Compose compiler plugin 2.4.20, and Compose BOM 2026.09.00. The application namespace and ID are `app.embyr`. `minSdk=26`, `targetSdk=36`, and `compileSdk=37`. Install SDK Platform 37.0 and SDK Build Tools 36.0.0. External Play application-ID ownership must be checked before distribution.

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

Onboarding, recommendation generation, and recommendation decisions persist canonical request bytes and a unique idempotency key before sending. An ambiguous command replays the same bytes and key for less than 23 hours. After that cutoff, onboarding reconciles through `GET /me`, and an ambiguous ACCEPT searches at most five pages of `GET /explorations` for the exact recommendation ID. An expired SKIP or recommendation generation remains visibly unresolved. A new generation request requires an explicit learner action. Room's version 1 to 2 migration adds owner-scoped journey state without deleting the M7-02 outbox or World data.

## Commands

From `apps/android`:

```sh
./gradlew :app:lintDebug :app:testDebugUnitTest :app:assembleDebug :app:assembleRelease :app:assembleDebugAndroidTest
python -m pip install -r tools/requirements-contracts.txt
python tools/validate_m6_public_examples.py
./gradlew :app:connectedDebugAndroidTest
```

The JVM fixture tests read canonical files under the repository's `docs/api/fixtures` directory; the schema script reads the canonical M6 schema. Device tests cover Room migration and persistence, owner isolation, Keystore storage, and Compose journey screens. CI runs lint, JVM/schema tests, and debug/release builds. Run `connectedDebugAndroidTest` on API 26 and a current emulator, and record the result in the PR. A real alpha completion check also needs invited Supabase users, the email code template, a reachable backend, eligible recommendation data, and a no-result scenario.

Release assembly is unsigned and R8 enabled. Distribution signing and hosted Internal Alpha validation belong to M7-06.
