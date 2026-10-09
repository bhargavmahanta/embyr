# Native Memory and World (M7-05)

The Android client consumes the frozen M6 v1 contract. The backend owns every
projection status, World placement, seed, entity pin and growth category. This
client does not grade answers or derive mastery, psychological traits or growth.

## Memory writes and recovery

Memory transport uses closed decoding and semantic validation; other transport
DTOs retain their existing compatibility policy. Projection CURRENT/PENDING/FAILED
is displayed independently of saved-copy and transport freshness.

An interest PUT contains only `base_version` and `preference` and has no
idempotency header. Before sending, Room records the exact bytes and observed
version in an owner-scoped operation. These operations do not enter the keyed
POST outbox. No startup, refresh or authentication recovery automatically resends
a PUT. HTTP200 with a matching identity, preference and next version is the
acknowledgment. An uncertain result remains uncertain even when a later read
matches the requested choice.

Reconciliation reads the current summary. The learner can explicitly adopt the
current choice, or apply the saved intent using a newly observed version and a
new operation. Both preserve the historical intent. A row outside the bounded
summary is unresolved; the client never infers an absent row or version zero.
Unavailable choices retain their preference and null content title/version.

## Cache and ownership

Room version4 adds Memory cache and interest-operation tables and a World cache
generation. Migrations from all earlier versions preserve commands, journeys,
drafts, receipts, assessment state and World objects. OwnerSession issues a new
binding generation on every rebinding, including A→B→A and same-owner rebinding.
New repositories, stores and presentation use the owner plus generation.

World synchronization is serialized in the application-scoped repository. Valid
caches advance through pages requested with `limit=500`. At most20 pages commit
per synchronization; the screen exposes explicit continuation. Each page is
validated and reduced before committing its complete replacements and cursor in
one Room transaction. Growth replacements cannot alter immutable node fields.
Advancing server heads are accepted; the next request always uses the committed
`to_revision`.

Ordinary snapshot replacement is monotonic. The separate recovery replacement
compares the expected cache revision/generation and owner binding, allowing a
legitimate lower revision after resync. One automatic fresh snapshot is allowed
for a synchronization failure requiring resync; invalid recovery leaves a visible
recoverable error. A network failure can retain a valid matching-owner cache.
Rebinding removes its presentation.

## Forest

The forest is a native vector Canvas. Backend coordinates are retained in Double
precision until drawing. Seeded primitives are shared by drawing, bounding-box
culling and hit testing. Painter order is logical Y, then canonical node ID;
overlapping picks use reverse painter order. Camera fit, zoom 1–8×fit, constrained
pan, reset and zoom controls accompany a focusable tree list. Selecting a tree
highlights and recenters that same node. Names require owned public data with the
exact entity/version; a stable generic unavailable label is used otherwise.

Existing nodes animate only changes to authoritative growth categories, including
corrections, over 220ms. New nodes display their supplied growth. Android's disabled
animator duration scale disables the transition.

## Verification and benchmark boundaries

Unit tests cover closed contracts, reconstruction, paging, bounded recovery,
interest ambiguity/conflicts, missing rows, owner generations and geometry.
Instrumentation covers Room migration/rollback/reopening and Compose controls.
The physical runner must install these tests under the isolated verification UID;
legacy Keystore tests must never run against the real alpha UID.

`ForestFrameMetricsDeviceTest` requires API 31+ and
`app.embyr.verification`. It measures deterministic synthetic 100- and 500-node
Canvas scenes: 2 seconds warmup, 20 seconds repeatable pan/zoom, framework FrameMetrics
TOTAL_DURATION/DEADLINE, refresh rate, p50/p95/p99, deadline misses and dropped
samples. These are synthetic debug renderer measurements. They are not release
performance guarantees or evidence of a hosted learner journey. Release/R8
assembly and genuine physical/live-alpha evidence are separate completion gates.

No #120 acceptance item is completed merely by the existence of this source or a
successful build. Independent source and complete evidence reviews are required
before issue closure and the #121 readiness update.
