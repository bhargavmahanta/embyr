# Exploration and assessment recovery

M7-04 extends the existing Android foundation. ACCEPT supplies an ID; detail and
reviewed delivery come from the existing owned M5 endpoints. RETURN preserves
ACTIVE/PAUSED, RESUME requires PAUSED, and completion is learner intent independent
of assessment. No client grading or mastery claim is made.

## Persistence and replay

Room version 3 adds owner-scoped Exploration drafts/detail, assessment references,
selected navigation and command receipts. Migrations 1→2→3 and 2→3 preserve the
existing command, journey and World tables. No destructive fallback is used.

A keyed POST commits its canonical bytes/path/key before send. Its typed public
presentation and receipt commit before local acknowledgment. A retained receipt
resolves a crash before ACK. An ambiguous request uses the same bytes/key within
the existing strictly less than 23-hour client safe window. Owner binding uses the
bootstrap Profile ID, and owner scopes cancel work on sign-out/account change.

| Operation | After safe replay expires |
| --- | --- |
| Delivery | Fetch the accepted parent; a pinned delivery can reconcile it. Otherwise keep the outcome unconfirmed. |
| RETURN/PAUSE/RESUME | Fetch current lifecycle; timestamps/status alone do not prove that exact command. Keep it unconfirmed. |
| Completion | The owned parent being COMPLETED reconciles learner completion intent. |
| Reflection creation | Require a known result ID matching the owned reflection; matching text alone is insufficient. |
| Assessment start | Require the owned parent's session and compatible original self-report. |
| Support | Match the owned session, original interaction and unique delivered support level. |
| Answer | Require a known response ID and owned session relationship. A response with unknown submission provenance does not authorize another answer. |
| Evaluation retry | Require a known new run ID. An unrelated latest run cannot prove that exact retry. |

Reflection PATCH is separate from the POST dispatcher and has no invented
idempotency key. Persist the submitted base version/text and keep the working draft
separate. Recheck the same reflection through detail. Matching newer server text
can confirm the desired state; differing newer text is a conflict. Applying again
requires explicit review of the current version; a further version change requires
another review. Neither GET nor recomposition silently overwrites a draft.

## Optional assessment

Collect one explicit confidence-before self-report from the four server values.
Support succeeds with HTTP 200. An immutable SINGLE_CHOICE answer and eligible
retry require HTTP 202. Preserve the response and run references before ACK, then
read current response progress: an original answer replay may still say PENDING
when current GET says SUCCEEDED.

Foreground polling has at most eight reads, delays of 1, 2, 4, then 8 seconds,
and a 60-second overall budget including request time. Backgrounding/owner changes
cancel polling; offline or exhausted budget leaves visible pending state and an
explicit recheck. FAILED overrides a WAITING_FOR_EVALUATION session label. Retry
requires current retry_allowed and creates a new run for the existing response,
without another answer submission. Run changes fence stale reads.

## Verification boundaries

JVM/network-fake tests and compilation are separate from physical and hosted gates.
Build the instrumentation APK, then verify migration/storage/Compose behavior on
the explicitly targeted physical Samsung. Real-alpha acceptance additionally needs
both supervised local app_worker evaluation and projection workers, actual
asynchronous success and reviewed failure injection/retry, lifecycle/reflection
conflicts, process/lost-response/auth/account recovery, accessibility and redacted
logs. Historical M7-03 evidence does not prove these new paths. Issue #119 remains
open until all six acceptance items receive independent evidence approval.

## Navigation and upgrade identity

Changing checks supersedes the old UI action and clears its presentation. Old
commands remain in the owner outbox for exact recovery. Current route/session IDs
fence display and callbacks. Leaving a detail fences a delayed start callback;
its public session result persists independently of selected navigation. Assessment
snapshot merges share the Room store lock, so a stale poll cannot replace a newly
acknowledged run between the read and write.

For a local alpha upgrade, optional EMBYR_DEBUG_KEYSTORE selects the existing
debug signing identity through ignored local configuration. Verify the resulting
APK/test-APK certificates against retained evidence before installing with data
preserved. A different builder's default debug key must not lead to uninstalling
or clearing the alpha app. CI continues to use its default disposable signing key.
