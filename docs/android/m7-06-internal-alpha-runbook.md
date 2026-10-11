# Internal Alpha operator runbook

Status: implementation candidate. Physical release, performance, deletion and independent acceptance gates remain pending. This document is not an acceptance certificate.

## Responsibility and boundaries

Bhargav owns the signing identity, environment, tester enrollment and supervised worker session. Use the established non-production `embyr-dev` and existing Render Free API, with automatic deployment disabled. The backend remains pinned to `e3bfed74840978526c71c92cd7a5f7476a8acf25`. Android and backend revisions are separate evidence fields.

Keep operator inputs, endpoints, tester aliases, credentials and raw evidence in the protected local setup directory. Only redactable conclusions and artifact hashes belong in GitHub. Never load operator database credentials or privileged Auth keys into Gradle or the Android runtime. Distribution is local USB only; no public upload or Play publication is authorized.

## Build and signing

The namespace remains `app.embyr`. Debug retains application ID `app.embyr`; Internal Alpha release uses `app.embyr.alpha`, label **Embyr Alpha**, version code **2**, version name **0.1.0-alpha.1**. Preserve the existing development installation and its accounts.

Use the frozen JDK 21/Gradle 9.5.0/AGP 9.3.1/Kotlin 2.4.20/Compose 2026.09.00 toolchain. Supply only the three client-safe API/Supabase values described in the Android README. Release is non-debuggable, minified and resource-shrunk. Its shell-profileable manifest capability permits local performance tracing; it does not authorize `run-as` or enable debugging. Audit that capability in the merged manifest for each distributed candidate.

The persistent key is PKCS12, RSA4096/SHA256withRSA, alias `embyr-internal-alpha`, with 10,000-day validity. Keep the keystore and password configuration outside Git with directory mode 0700 and file mode 0600. Export these variables only into the local signing process:

```text
EMBYR_ALPHA_KEYSTORE_PATH
EMBYR_ALPHA_KEYSTORE_PASSWORD
EMBYR_ALPHA_KEY_ALIAS
EMBYR_ALPHA_KEY_PASSWORD
```

From `apps/android`, run `./gradlew --no-daemon --no-configuration-cache :app:signedAlphaRelease`. Missing or partial signing inputs fail; CI may run `assembleRelease` without those inputs to build an unsigned artifact. Do not publish an unsigned CI artifact as an Alpha release. Do not use a build scan or verbose environment logging for a signing process.

Before distributing, create an encrypted backup of the keystore and its recovery configuration. Store the encrypted backup off this workstation, and keep the decryption secret separately in the owner's password manager. Verify decryption into a protected temporary directory and compare the certificate and key identity; remove the temporary copy. Record the backup checkpoint without recording passwords. If the key is lost, stop: replacing it silently breaks compatible upgrades. A local encrypted copy alone does not establish disaster recovery.

For each candidate, record reviewed source/tree, public configuration hash, tool versions, signing certificate SHA-256, APK/AAB SHA-256, version and merged-main relationship. Verify the APK using `apksigner verify --verbose --print-certs`; inspect its manifest/package/version with SDK tooling. Validate the AAB with the digest-verified bundletool 1.18.3 and verify its JAR signature and certificate. AAB validation is not an installation test. Audit packaged assets/DEX/resources for secrets, learner content and test-only code; inspect exported components, backup exclusions and HTTPS policy.

## Signing recovery checkpoints

Record these separately: primary key identity, authenticated local backup round trip, off-device encrypted-backup custody, separate recovery-secret custody, and retrieval/recovery verification. A passing local round trip does not prove the external copy is retrievable. Keep unfinished checkpoints pending in the acceptance matrix.

The protected setup uses the `embyr-signing-recovery-v1` envelope: AES-256-GCM with a 32-byte recovery key, a fresh 12-byte nonce, and authenticated context `embyr-internal-alpha-signing-recovery-v1`. The encrypted payload contains only the PKCS12 bytes and the four Alpha signing settings. Its recovery secret is stored separately. Neither operator database credentials nor tester data belong in this backup.

To recover, retrieve the encrypted file and compare its SHA-256 with the retained trusted receipt. Use the reviewed local procedure and separate recovery secret to authenticate/decrypt the envelope before consuming the payload. Verify the PKCS12 alias, RSA4096 key, certificate SHA-256, SHA256withRSA certificate signature and matching key/certificate public numbers against the retained release identity. Never take the expected certificate identity from the supplied backup alone.

Any restored plaintext keystore/configuration must use a new protected directory outside Git, with directory mode 0700 and file mode 0600. Update only the local keystore path for its new location. Keep passwords out of command arguments, shell history and logs. A failed authentication, identity mismatch, partial write or inaccessible external copy stops recovery; retain the failure evidence and inspect actual state. Do not replace the persistent signing key to work around recovery failure.

After verification, supply the restored four values only to the designated local signing process with configuration caching disabled. Validate the resulting APK certificate before attempting a compatible upgrade. Delete only the temporary recovery copies created for the drill after evidence capture; preserve the primary key, external encrypted backup and separate recovery secret.

## Installation and rollback

Every launcher must verify the independently approved physical-device profile, serial and model/API, then pass that serial explicitly. Keep each device's records separate and ADB bound to loopback. Never select an emulator. Before installing, inspect both packages' current UID, version and certificates and save their identities locally. On Android16, use exact package UID enumeration with explicit Android user0 and verify the current user; do not assume the older dumpsys `userId` field is present or confuse an app ID with another user's UID.

Fresh installation requires `app.embyr.alpha` to be absent. Use the verified signed APK. Record installation, startup and real journey separately. A compatible upgrade uses `adb -s <approved-serial> install -r <verified-apk>` only after package, signing certificate and non-decreasing version checks. Capture active flow, owner, outbox, draft and World stamps before/after. Never uninstall or clear `app.embyr` to manufacture fresh-install evidence.

Stop on signature mismatch; do not replace another signing identity. A rollback must preserve version/signature compatibility and validated Room schema. Prefer stopping distribution and retaining the installed candidate over an unreviewed downgrade. Any permitted reset is limited to the new disposable Alpha installation after evidence capture. Backend and retained account data are never reset for an Android rollback.

## Enrollment, content and runtime

Reuse the installed reviewed pilot corpus and its existing HUMAN attestation. Verify the pinned provenance/hash and public review state before a journey; do not install fabricated content to force a result. Closed enrollment is configured: pre-provision designated disposable plus aliases derived locally from controlled inboxes, and prove email delivery before relying on an alias. A separate alias is designated for deletion. OTP is a code entered on the phone; codes and inbox identities stay out of chat and public evidence.

The API uses only `app_backend` TLS Session-pooler configuration. Each separately supervised local evaluation/projection worker uses only `app_worker`; neither receives `app_owner`, the operator PAT or another runtime's credentials. Use the reviewed precision launchers with unchanged backend source. Verify role and TLS, and preserve transaction-local `extra_float_digits=3`: the API read-only repeatable-read boundary must still be the first SQL statement of its transaction. Do not alter stored float8 bits or round client coordinates to compensate for transport precision.

Namespace supervision records for M7-06. Record each PID, start ticks, process-group ownership, command/source hash, role/TLS verification, precision configuration, supervision expiry and progress. Confirm both workers actually running and healthy at acceptance. Delayed/failed recovery needs observed job transitions, not merely process existence. Stop only the owned process groups after recording acceptance; record shutdown separately. Free API cold starts and bounded local worker availability are operating limitations, not a continuous-service guarantee.

## Learner recovery

Restore the encrypted Keystore session, bootstrap the mapped Embyr owner and rebind private stores before presenting private data. Account rebinding clears presentation immediately. Never bind by email or Supabase Auth UUID. Validate A→B→A and generation rejection of stale responses on the actual release.

Keyed POST recovery preserves canonical bytes and the original key. Automatic replay is permitted only for age less than 23 hours, within the server's 24-hour guarantee. Clock rollback and age at the cutoff fail closed. After expiry, use supported read reconciliation; otherwise retain visible ambiguity. Do not silently create a new logical command. Record controlled-clock boundary tests as synthetic.

Interest PUT is versioned and unkeyed: preserve exact intent, reconcile by summary reads, and require explicit adoption/reapply against an observed version. Missing bounded-summary rows remain unresolved. Reflection PATCH retains the draft and observed version; refetch on conflict and require the learner's explicit action. Do not treat these as keyed POST replay.

Assessment answers are immutable and return HTTP202; support returns HTTP200. Poll boundedly, expose FAILED, and create a new eligible evaluation run without resubmitting the answer. Completion is independent of assessment/mastery. World cache commits objects/cursor together; use guarded snapshot recovery for gaps, incompatible data or resync requirements. Keep only valid matching-owner cached presentation on network failure.

## Operator-mediated disposable deletion

This is a trusted maintenance operation, not an Android endpoint or user-facing deletion feature. Before any mutation, independently review the exact bounded procedure and allowlist the designated disposable probe UUID. Recheck the hosted function definition, revision, ownership/grants and all currently owned tables against frozen migrations. The existing `public.maintenance_delete_account(uuid)` is SECURITY DEFINER, owned by `app_maintenance`, and executable by `app_worker`; it does not remove Auth users or external Storage objects.

1. Record target ownership, dependent rows/jobs/storage keys and a second owner's preservation checkpoint. Reject retained evidence accounts and all non-allowlisted UUIDs.
2. Disable new sign-in for the probe using existing supported Auth administration and revoke its refresh sessions. The pinned backend validates JWT signatures/expiry locally; refresh revocation or Auth deletion alone does **not** invalidate an already issued access token. Inventory the probe's sessions and wait until the latest possible issued-token expiry (including configured clock tolerance), then verify a retained probe token is rejected before deleting the application mapping. If issuance/expiry cannot be bounded, stop the deletion operation. Coordinate and quiesce target jobs so workers cannot recreate state during cleanup.
3. Enumerate durable owned Storage keys before deleting their database references. Delete only those objects through trusted capabilities; verify deletion and handle partial failures before proceeding. Do not assume an empty object list without checking.
4. In a trusted role-specific transaction, execute the verified maintenance function for the bound probe UUID. Verify owned application rows and jobs are gone and the second owner remains intact. Do not recreate roles or broaden grants.
5. Remove the probe's Supabase Auth identity using scoped administration and verify removal. Check subsequent authentication/bootstrap denial and all cleanup results. Record each stage; a failure requires inspection of actual state before retrying.

Provider backup retention is a separate operator responsibility; record its policy rather than claiming immediate erasure of provider backups. Retain redacted audit evidence without credentials or private learner payloads.

## Evidence and closure

Maintain a protected seven-item #121 matrix and separate ten-item #115 exit matrix with PASS/FAIL/NOT RUN, exact source/build/backend/runtime/environment/device and limitations. Historical M7-05 results retain their identities. Freeze and review fault/measurement harnesses before execution; synthetic data never enters Room or the backend. Capture actual phone settings before testing and restore them afterward.

The fixed physical release performance protocol is documented in [the profiling gate](m7-06-performance-protocol.md). Retain every attempt and every valid measurement. Unavailable metrics or failed thresholds keep the gate open. Obtain exact-head source review, required CI/security checks, verified merge/main CI and independent seven-item acceptance before closing #121. Then conduct a separate independent umbrella exit review before closing #115/milestone 7. Stop after the M7 verdict.

## Profiling preconditions and cleanup

Check both the host launcher and installed test harness's actual preconditions before collection. The retained harness requires all accessibility services disabled, including non-TalkBack services. The operator selected temporary suspension of the new phone's Phone Link/Wispr Flow accessibility services for profiling. Review the exact suspension/restoration procedure, capture their original service list and enabled state, and restore both afterward. Keep that profiling environment consistent across qualification, baseline and optimized cases; do not silently disable additional services.

Capture font, animation, motion smoothness, brightness policy/value and accessibility settings before any changes. Restore the requested brightness while manual policy is active and verify its readback before restoring the original automatic policy. Verify static settings separately: an adaptive brightness value can change after automatic policy is restored. Record the requested, verified manual and subsequent adaptive values without claiming that the adaptive numeric readout is fixed. Restore the operator's original refresh setting when the bounded profiling session ends.

Retained APK/AAB static auditing supports signature, manifest, backup exclusions and configuration checks; runtime log/private-content checks and final source/merge correspondence still need evidence. The current bundle's embedded version-control metadata lacks a commit SHA, so retain external frozen build-input/source/artifact receipts. A local encrypted signing backup still requires verified off-device custody by the responsible operator. None of these supporting checkpoints closes an acceptance item.
