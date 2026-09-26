# M6 v1 — Frozen projection, Memory and World contracts

Status: **M6-01 CONTRACTS FROZEN**. Reviewed decisions captured on 2026-09-26
against M5 merge `d5015398b494aa8df33b94392007a60ad72f026a`. This document specifies
future implementation; it does not claim that capture, migration, workers or
routes exist. M6-02 onward must implement it without changing its semantics.

The normative structural definitions are the strict [JSON Schema](schemas/m6-v1.schema.json).
The [fixtures](fixtures/m6-v1.json) illustrate public responses and internal
receipt keys. Relational, ordering and transactional requirements below are
equally normative; JSON Schema alone cannot enforce them. The
[implementation plan](../plans/m6-implementation.md) defines acceptance gates.
Public response cases and internal receipt-key examples are independent
illustrations, not a claim that four example receipts produce the populated
World. The World delta cases do share one deterministic reconstruction history.

For structural validation, use a Draft 2020-12 validator with UUID/date-time
format checks enabled and select the matching `$defs` entry for each example.
The fixture collection's wrapper is documentation metadata, not an HTTP DTO.
Validate Memory cases against `memorySummary`, snapshots against `worldSnapshot`,
pages against `worldDeltaPage`, resync responses against `worldResyncRequired`,
receipts against `projectionInput`, and the job against `projectionJob`.
Derivation, ordering, freshness and cross-field checks must additionally enforce
the semantic rules below; accepting a JSON shape alone is insufficient.

## Authority and contract identities

| Boundary | Frozen identity |
| --- | --- |
| Factual receipt | `projection-input/v1` (schema_version `1`) |
| Dedicated PostgreSQL consumer | `projection-worker/v1` |
| Current objective projection | `learner-projection/v1` |
| Memory response | `memory-summary/v1` |
| World semantics | `world-projection/v1` |
| World change payload | `world-delta/v1` |
| Eligible evaluator, unchanged from M5 | `deterministic-evaluation/v1` |

For these boundaries this document supersedes conflicting sketches in the
[historical LLD](../architecture/core-data-model-lld-v0.1.md): derived state is
one current row per logical key, with no `is_current`; explicit interests remain
in authoritative `explicit_interest_preferences`, separate from inferred state;
each material World object change has its own revision, with no `change_ordinal`.
The [v0.1 API](api-contracts-v0.1.md) World outer envelopes remain intact.
Other historical designs and the frozen M3/M4 policies retain their authority.

## Ordered factual inputs

Every receipt contains exactly `contract_version`, `schema_version`, `user_id`,
`source_sequence`, `source_kind`, `source_key`, `source_group`, `source_time` and
`facts`. UUIDs are lowercase canonical hyphenated strings. Timestamps represent
UTC instants, serialized with `Z`; comparison is by instant, never lexical
offset representation. Source sequences are positive PostgreSQL BIGINT values;
head/checkpoint zero means the empty prefix. Sequence overflow fails capture
atomically rather than wrapping. `facts` is a closed, type-specific object.

| source_kind | Exact source_key | Factual time | Closed facts definition |
| --- | --- | --- | --- |
| `LEDGER` | canonical event UUID, e.g. `55555555-5555-4555-8555-555555555555` | event `occurred_at` | `ledgerFacts` |
| `EVIDENCE` | `<canonical-evidence-uuid>:<resulting-status>`, e.g. `66666666-6666-4666-8666-666666666666:REVOKED` | evidence `created_at` | `evidenceFacts` |
| `BOOTSTRAP` | literal `learner-projection/v1:baseline` | cutoff instant | `bootstrapFacts` |

Evidence suffixes are exactly uppercase `ACTIVE`, `SUPERSEDED`, `REVOKED`.
Existing forward-only status guards prohibit reactivation, so an evidence/status
key identifies one transition. A live receipt's `transition_at` is the factual
capture instant of that status transition; it does not replace `source_time` as
the recognition evidence time. Baseline-only evidence uses `transition_at=null`
when historical transition time is unknown. Do not fabricate a transition date.
There is no separate operational snapshot source kind: validated owned resource
references/pins are captured in their ledger or evidence receipt.

Require database `UNIQUE(user_id, source_kind, source_key)` and
`PRIMARY KEY(user_id, source_sequence)`. On repeated capture, compare the existing
identity and compatible immutable facts, then reuse it without allocating a new
sequence. A contradictory duplicate is a bounded capture failure, never a
payload overwrite. The baseline overlap rule below permits reuse of a live
transition receipt rather than replacing its known transition time with null.

`source_group` is the decimal text of the full PostgreSQL transaction ID
(`pg_current_xact_id()`), scoped with `user_id`; it is at most 20 digits. It is
only a grouping identity. Ordering exclusively uses `source_sequence`. HTTP
command IDs, event ordinals, UUIDs, timestamps and transaction IDs are not
projection cursors. Receipt groups occupy contiguous ranges because the first
allocation locks the learner's source head until commit. The next group begins
at the previous group's last sequence plus one. Group contents cannot be
extended after source commit.

Capture is transaction-local to source ledger insertion and evidence
insertion/status transition. Sources, all receipts, source head and owned job
references commit together or all roll back. Sequence allocation is an update
to the head row, not a nontransactional database sequence. Evidence snapshots
must observe the final coherent run/evidence status of the complete source
transaction; a deferred capture finalization may be needed for corrections.
It must retain every actual evidence transition in the group without inventing
intermediate projected states. M4 acceptance/start events are supported even
without the M5 metadata contract marker. One accepted Exploration contributes
one encounter, regardless of the two ledger events emitted by M4.

### Receipt field allowlists

`ledgerFacts` includes only event ID/type/source schema version, entity/version,
Exploration/session/response/evaluation/reflection/recommendation references,
command ID/ordinal and preference version/value. Nullable fields explicitly
mean not applicable. Source schema version is the ledger schema version, distinct
from receipt schema version. Event types are the closed M4/M5 list in the schema.
Unknown event types or source schema versions require a reviewed parser policy;
fail capture/import with a bounded category rather than copying unknown data.

Applicable references must be coherent: Exploration events require an owned
Exploration and exact entity/version; assessment events require its owned
session; response/evaluation events require the owned response/run;
`REFLECTION_SUBMITTED`/`REFLECTION_UPDATED` require the owned reflection;
recommendation events require the owned recommendation;
`EXPLICIT_INTEREST_CHANGED` requires entity ID, preference value and version;
`ONBOARDING_COMPLETED` requires preference version. Other fields are null unless
an applicable, validated source supplies them. Command ID/ordinal are both null
or both nonnull. M4 `RECOMMENDATION_SKIPPED` can have no Exploration. No capture
depends on raw metadata being trusted: select only these known fields and
validate against owner-scoped operational records.

`evidenceFacts` includes evidence ID/resulting status, source type/ID, type,
strength, objective/entity/version, response/run references, final evaluation
status/result, evaluator/rubric version, support level, classification confidence
and nullable transition time. Only M5 `ASSESSMENT_RESPONSE` / `RECOGNITION` /
`WEAK` is supported by this v1 capture parser. Other evidence requires reviewed
parser expansion and has no v1 promotion authority. Nullable fields never make
incomplete evidence eligible. A nonnull classification confidence must be finite
and between zero and one; eligible evidence must have one. These internal
classification values are never public ability or self-confidence scores.
For assessment evidence, source_id equals response_id, and the response, run,
objective and Exploration all agree on owner and exact entity/version. The
captured classification confidence is learning_evidence.evaluation_confidence
and must agree with its successful run's confidence; captured support_level
must agree with the source response's support_used. Null or mismatched
classification confidence cannot become eligible understanding.

Receipts never contain reflection text, answers, private rubric mappings,
motivation text, embeddings, signed URLs, bearer tokens, arbitrary
`event_metadata`, computed learner state or growth. Reference a rubric version;
never copy rubric contents. Each receipt's serialized UTF-8 JSON is bounded to
8 KiB and contains one factual source, with no unbounded arrays. Load history in
pages of at most 500 receipts; a transaction group can span pages and must be
fully validated before publication. Do not split a large group into separately
visible publications. Reject oversized facts atomically.

## Learner projection and corrections

At a complete processed horizon, eligible understanding evidence is owned,
`ACTIVE`, `ASSESSMENT_RESPONSE`, `RECOGNITION`, `WEAK`, backed by a `SUCCEEDED`
evaluation run using `deterministic-evaluation/v1` with result `SUPPORTED` and
coherent user/response/objective/entity/entity-version lineage. Replay uses
receipt statuses at that horizon, not today's source statuses substituted into
old history. Validate lineage and the captured final transaction statuses;
impossible combinations fail the group. Current-source checks can detect drift
but cannot silently change an earlier prefix's reduction.

For each objective with at least one distinct eligible response source:

| Column | Exact value |
| --- | --- |
| categorical_state | `DEVELOPING` |
| understanding_estimate | `null` |
| evidence_count | number of distinct response IDs |
| evaluation_confidence | minimum included classification confidence |
| support_required | true iff any included eligible source used support |
| last_evidence_at | maximum included evidence `source_time` |
| model_version | `learner-projection/v1` |

Deduplicate by response before counting. The coherent source guards allow only
one current successful deciding evaluation per response; multiple eligible
current alternatives for that response are an integrity failure. Replace the
current `OBJECTIVE` provenance links atomically with the eligible evidence IDs;
do not populate optional link weights. With no eligible evidence, remove the
v1 objective row and its current `OBJECTIVE` links. The recommendation adapter
then receives `UNKNOWN`. No `UNDERSTOOD` or `RETAINED` is emitted by weak
recognition. There are no writes to learner interest, retention, confidence or
challenge tables. `FUZZY`, `MAIN_IDEA`, `COULD_EXPLAIN`, `CHALLENGE_ME` have no
numeric mapping.

`SUPERSEDED`/`REVOKED` deciding evidence contributes zero current understanding.
Recompute current state without mutating historical answers, evaluations,
evidence payloads, ledger events or receipts. Equivalent replacement in the
same source transaction is reduced once after all transitions: no observable
shrink/grow jitter and no delta for unchanged growth. A late successful
evaluation may update state and World after Exploration completion; it never
reopens that Exploration or changes its completion fact.

## Execution and atomic publication

Use the existing PostgreSQL jobs table with dedicated job type
`LEARNER_PROJECTION`. Its strict payload contains only `contract_version` =
`projection-worker/v1`, `user_id`, `source_group`, `first_source_sequence` and
`last_source_sequence`. Validate these against immutable owned receipts.
Baseline jobs reference their complete baseline prefix as defined below.
No job contains computed state, growth, topology or World revision numbers.

Claim with `FOR UPDATE SKIP LOCKED`, a fresh claim token, a 60-second lease,
maximum three attempts, and retry delays of 5 seconds after attempt one and
30 seconds after attempt two. A terminal failure blocks that user's earliest
unprocessed publication group; other users can progress. Jobs execute at least
once. Immutable receipts plus checkpoint define exactly-once publication.

The pure reducer consumes the complete factual prefix using bounded loading,
detached from the finalization transaction. Process one complete source group
at a time in source sequence order after the baseline. Worker scheduling and
page sizes must not coalesce away intermediate groups or affect revisions.
Store SHA-256 input/output fingerprints over canonical JSON (sorted object
keys, compact separators, UTF-8, no NaN), the ordered receipt prefix and fixed
contract identities; omit scheduling/claim timestamps from semantic output.
Use unescaped Unicode strings, no insignificant whitespace or trailing newline,
and shortest round-trippable binary64 numeric serialization. Prefix arrays are
in source_sequence order; projected objects and provenance sets use their
specified canonical key order. Reject nonfinite values before serialization.

Finalization validates owner existence (against deletion), checkpoint generation,
expected processed horizon, group completeness, active claim token and actual
lease expiry using database current wall-clock time at locked finalization.
Lock checkpoint, then World, then job in that order; hold a compatible owner
existence lock first. Revalidate expiry after acquiring locks. Never acquire
mutable Exploration/session/response locks while holding publication locks.
Preserve existing M5 source lock order, acquiring the source head at capture.
A stale/expired claim or changed generation cannot publish any state or delta.

Current objective/provenance changes, complete World objects/deltas/head,
checkpoint advancement/fingerprints and job success commit in one transaction.
Duplicate delivery of an already processed group acknowledges a no-op under a
valid claim; no re-publication. A trusted retry references the same immutable
group and cannot mutate facts. Checkpoint generation fences replay/repair;
never reset a live public revision or silently replace a corrupted stream.
Log only bounded categories, IDs, contract versions, counts, lag and timings;
never SQL parameters or learner content.

## Deterministic bootstrap

Bootstrap is an explicit reviewed per-user operation, never automatic hosted
backfill. Install live capture first. Existing users initialize source metadata
with `bootstrap_state=REQUIRED`; workers may capture/queue but cannot publish
their groups yet. Users proven newly created after capture installation start
`READY` at sequence zero and use ordinary live publication, without importing
history. Absence of metadata for an old user is never proof of a new user.

For an old user without known M6 provenance, take the owner existence lock, then
lock the same source-head row used by capture. Use READ COMMITTED and establish
the committed source snapshot **after** acquiring that head lock. Record
`C = head.source_sequence` and `cutoff_at = clock_timestamp()` after the lock.
Read currently committed owned sources while retaining the head lock until
bootstrap commit. Any source transaction changing relevant facts must acquire
that head before it can commit: a transaction already committed is visible;
one still waiting is invisible and will capture after bootstrap. Do not use a
repeatable-read snapshot established before the head lock, or lock mutable
source rows during this scan.

Refuse adoption if there are objective/provenance or World rows with unknown
projection provenance, unpinned/non-v1 nodes, foreign topology, duplicate region
keys or inconsistent ownership. Preserve all existing rows and report a bounded
import refusal pending a reviewed import policy. No guessing, wiping or
converting numeric estimates into v1 meaning.

The baseline covers every reconstructable M4/M5 ledger fact at the cutoff and
each currently stored supported evidence status, with owned resource pins.
Canonically enumerate historical ledger by `(occurred_at, received_at,
command_id-or-empty, event_ordinal-or-minus-one, event_id)`, then current evidence
by evidence ID. Insert missing source keys as bounded receipts in that order;
reuse keys already captured in sequences `1..C`, without reassigning or editing
them. A current retired evidence snapshot is allowed with unknown historical
transition time; no past ACTIVE/correction receipt is invented. Missing,
contradictory or unsupported source history fails the import atomically.

Finally append the unique `BOOTSTRAP` marker in the bootstrap transaction's
group. Its facts are exactly `cutoff_source_sequence=C` and `cutoff_at`; its own
sequence is `B`. The marker source time equals cutoff_at. Set bootstrap READY
and `baseline_through_sequence=B` in that same transaction. Thus the baseline
publication unit is the complete prefix `1..B`, comprising live groups already
captured before the cutoff plus missing historical facts and the marker. Its
job references that prefix and the marker's source_group; ordinary jobs whose
ranges are covered by it become acknowledged no-ops only after its checkpoint
commits. No worker publishes `1..C` separately before the baseline.

For baseline reduction, use reconstructable history/current evidence at the
cutoff, reconcile earlier captured transitions with the final status snapshot,
deduplicate by source identity and response, and publish the final baseline
once through the same reducer/publisher. Baseline first placement selects the
earliest accepted Exploration by `(started_at, exploration_id)` per entity,
then emits canonical additions at their highest currently justified growth.
It does not emit invented historical grow/correct revisions. Current facts
cannot reconstruct every past correction-time state; that history stays unknown.
After bootstrap releases the lock, new transactions receive sequences `B+1`
onward and publish normal complete live groups in order. Repeating bootstrap
reuses its marker/recorded cutoff and is a no-op; it never chooses a new cutoff.
A failed bootstrap rolls back receipts, head and READY together, permitting
an explicit retry. A source transaction cannot fall between baseline and live.

## Memory summary

Authenticated owner-only `GET /api/v1/memory/summary` returns the closed
`memorySummary` schema. No generated_at, arbitrary extension or extra fields.
Use a single owner-scoped REPEATABLE READ, READ ONLY transaction. Reads create
no events, jobs, checkpoints or World rows.

Top-level keys are exactly `contract_version`, `projection`,
`learning_preferences`, `explicit_interests`, `recently_explored`,
`recognition_evidence`, `long_term_interests`, `voluntary_revisits`, `truncated`.
`contract_version` is `memory-summary/v1`.

| Field | Closed shape and semantics |
| --- | --- |
| projection | model_version, source_sequence (processed), source_head_sequence (captured), status |
| learning_preferences | null before onboarding; otherwise adventure_preference, preferred_effort, support_style, practical_opt_in, version |
| explicit_interests | entity_id, entity_version, title, preference, version, updated_at, availability |
| recently_explored | entity_id, entity_version, title, started_count, returned_count, completed_count, latest_activity_at |
| recognition_evidence | objective_id, entity_id, entity_version, evidence_count, support_required, last_evidence_at, summary |
| long_term_interests | always [] |
| voluntary_revisits | always [] |
| truncated | explicit_interests, recently_explored, recognition_evidence boolean flags |

Projection model_version is `learner-projection/v1`. `CURRENT` iff processed
sequence equals captured head; `PENDING` iff behind without a terminal blocking
group; `FAILED` iff a terminal unprocessed group blocks advancement, taking
precedence over PENDING. Processed never exceeds head. An absent checkpoint
means processed zero. Freshness describes the captured horizon, not uncaptured
pre-M6 history or proof of curiosity. Behind-source safety filtering does not
upgrade PENDING to CURRENT. An empty user has the strict empty shape.

Learning preferences and explicit choices are read from current authoritative
tables immediately, even with derived lag. Preserve all five preference values
`NEUTRAL`, `MORE`, `LESS`, `PAUSED`, `NOT_INTERESTED`. Explicit interests cap at
20 and sort `(updated_at DESC, entity_id ASC)`. Required `availability` is
`AVAILABLE` or `UNAVAILABLE`, resolved in the same owner-scoped read transaction.

`AVAILABLE` requires that the LearningEntity exists, its status is REVIEWED or
PUBLISHED, current_version is non-null, and the exact matching
LearningEntityVersion row exists. Return the positive current `entity_version`
and its non-empty public `title`. Title strings are bounded to 512 Unicode
characters; slice public display titles to that bound without storing altered
ontology content.

`UNAVAILABLE` means the entity exists but has no current public display version:
current_version is null or entity status is not REVIEWED/PUBLISHED. Return
`entity_version=null` and `title=null`, preserving authoritative entity_id,
preference, preference version and updated_at. Never select a historical
version, invent a title/version or silently omit the explicit choice. If an
entity claims a public/current version but its matching LearningEntityVersion
row is missing, treat that as a data-integrity failure, not UNAVAILABLE.

Unavailable preferences remain explicit learner choices. Include them with
available choices in ordering, the max-20 cap and truncated calculation. GET
must never delete/rewrite a preference, infer a replacement or promote/demote
its value. UNAVAILABLE means only that the choice still exists while its entity
lacks a current public display version; it does not mean deletion, changed
intent or that the entity never existed. Preference codes remain bounded to
the existing 64-character contract. Do not infer promotional interest from
activity or override explicit suppression choices.

The existing PUT `/api/v1/memory/interests/{entity_id}` behavior is unchanged by
M6-01. This addition handles rows already legal under existing persistence/API
behavior. Availability is a Memory read-model concern, with no M6-02 capture or
M6-03 publication behavior depending on presentation availability. M3/M4
recommendation semantics remain unchanged; recommendation code continues its
existing deliverability/current-version rules independently of Memory display.

Recent explorations cap at 10 **distinct entity/version pairs**, ordered
`(latest_activity_at DESC, entity_id ASC, entity_version ASC)`. Title resolves
the exact historical public entity version. Count distinct Exploration starts,
distinct USER_RETURNED event IDs and distinct completed Explorations at the
processed prefix. `completed_count <= started_count`; returned_count can exceed
starts and never means voluntary-revisit attribution. `latest_activity_at` is
the max factual time of Exploration start, USER_RETURNED, first reflection
submission or Exploration completion. GET, preparation, hints, worker
evaluation, pause/resume and reflection edits alone do not advance it. With no
accepted encounter do not add a recent entry. Use “You explored …” in client
copy; never “You love …”, “You mastered …” or “deep interest”.

Recognition caps at 10 current projected objective entries, ordered
`(last_evidence_at DESC, objective_id ASC)`, with fixed neutral summary
`Recognition evidence recorded.` Entries come only from eligible evidence
included at the checkpoint. A read may inspect current owned evidence/run
statuses ahead of that checkpoint solely to remove now-invalid sources. For
each entry, derive count/support/latest time from the remaining previously
projected source subset; omit the entry if empty. Never add an unprocessed
replacement or new source, and never rewrite stored state on read. Apply safety
filtering before sorting/capping; truncated reflects the filtered eligible
entry count. A failed group remains FAILED even if this filter hides evidence.

Each truncated flag is true iff the corresponding eligible result before its
cap exceeds the cap; absence alone is false. No provenance IDs, raw evidence,
hidden scores, understanding_estimate, ability, classification confidence,
reflection/answer/rubric content, embedding or personality claim appears in the
public DTO. v1's two always-empty lists mean no supported summary, never “no
curiosity”. No prose Memory table is created.

## World identities, objects and semantics

The backend owns semantic meaning; clients own rendering. Frozen namespace:
`a6a18892-0247-5a64-adc3-1161194e67be`, obtained with UUIDv5's URL namespace over
the literal `https://embyr.app/contracts/world-projection/v1`. This identity
string requires no runtime network access.

| Value | Exact derivation |
| --- | --- |
| world_id (internal) | UUIDv5(namespace, UTF-8 `world:<canonical-user-id>`) |
| node id | UUIDv5(world_id, UTF-8 `entity:<canonical-entity-id>`) |
| region id | UUIDv5(world_id, UTF-8 `region:discovery`) |
| generation_seed | lowercase SHA-256 hex of UTF-8 `world-projection/v1:<canonical-world-id>` |
| visual_seed | lowercase SHA-256 hex of UTF-8 `world-projection/v1:<canonical-node-id>` |
| node x, y | SHA-256 of **UTF-8 canonical lowercase hyphenated node UUID text**; first bytes [0:8] and [8:16] interpreted as unsigned big-endian integers, each divided by 2^64 |

Coordinates use the exact rational above rounded once to nearest IEEE-754
binary64, ties to even, then JSON's round-trippable finite number encoding.
The extremely rare round-up to 1.0 is permitted; logical bounds are `[0,1]`.
Do not hash UUID binary bytes or the visual_seed input for coordinates. Growth
never changes placement. Logical coordinates are not pixels; overlap resolution
belongs to rendering.

Snapshot top-level keys remain exactly `revision`, `layout_version`,
`generation_seed`, `regions`, `nodes`, `connections`, `artifacts`. There is no
new outer contract_version or owner ID. Version is fixed by this contract and
layout_version `1`. A never-materialized World returns HTTP 200 with revision
0, deterministic seed, and all four arrays empty. GET writes nothing. Projector
materializes the physical root on the reviewed baseline, an onboarding group,
or the first accepted encounter; creating a root alone allocates no revision.
Profile `world_revision` remains nullable until a physical root exists.

Region public object is exactly `id`, `region_key`, `primary_domain_id`,
`logical_x`, `logical_y`, `logical_width`, `logical_height`, `visual_archetype`.
Only with the first node create `discovery`, primary_domain_id null, rectangle
(0,0,1,1), archetype `grove`. No inferred domain. Region DTO has no revision
because existing regions have no per-object revision column; its addition
revision lives in the delta stream.

Node public object is exactly `id`, `entity_id`, `entity_version`, `region_id`,
`logical_x`, `logical_y`, `depth`, `visual_archetype`, `visual_seed`,
`growth_state`, `revision`. One node per entity, existing world/entity uniqueness
preserved. Entity version pins the first accepted placement and is frozen for
`world-projection/v1`; no automatic repinning. This is not a promise of
immutability across every future World contract: reviewed evolution may define
repinning. For live groups with multiple first encounters choose minimum
`(started_at, exploration_id)`; already placed nodes keep their pins. Evidence
for another entity version can affect its own objective state/Memory but cannot
grow the old pin. Archetype is `branching_tree`, depth 0. DTOs omit source times,
owner IDs, evidence references and arbitrary metadata.

For the pinned entity version select the highest justified growth:

| Current factual basis | Growth |
| --- | --- |
| Accepted Exploration encounter | SEED |
| At least one first reflection submission OR completed Exploration | SPROUT |
| At least one currently eligible weak recognition source | YOUNG |

`ESTABLISHED` is unreachable. Work preparation, GET, repeated return alone,
hints, failed/INSUFFICIENT_EVIDENCE/UNCERTAIN evaluation, reflection edits and
elapsed time never promote. Pause, inactivity, failed attempts, leaving and
time decay never regress. Only deciding evidence SUPERSEDED/REVOKED may correct
YOUNG to the currently justified SPROUT or SEED. Encounter/placement remain.
This is a semantic correction, not punishment. Generated connections and
artifacts are always []; no recommendation adjacency topology or artifact
projection. Unknown pre-existing topology requires reviewed import.

## Revisions, deltas and reads

Under the World publication lock, compare final semantic objects ignoring their
revision fields. One changed object allocates one next contiguous revision.
Canonical order is region additions by region ID, node additions by node ID,
then growth changes by node ID, all using canonical UUID text ascending. A new
node is added directly at its final justified growth, never also emitted as a
growth change in that group. Existing unchanged objects allocate no revision.
Many revisions in one complete source group commit atomically with state,
head, checkpoint and job success. No change_ordinal. Preserve all deltas in M6;
retention/pruning is future scope.

Delta page outer shape remains exactly `from_revision`, `to_revision`,
`current_revision`, `has_more`, `changes`. Each change is exactly `revision`,
`type`, `object_id`, `payload`. Types are `REGION_ADDED`, `NODE_ADDED`,
`NODE_GROWTH_CHANGED`. Payload is exactly `schema_version` = `world-delta/v1`
and `object`, the complete replacement public region/node above. For node
changes its object revision equals change revision; object_id equals object.id.
No raw cause/evidence reference is public. Applying all changes from revision
zero by object ID replacement reconstructs the snapshot byte-equivalent after
canonical array sorting. Regions sort by `(region_key,id)`, nodes by
`(entity_id,id)`; empty connections/artifacts need no sorting.

Authenticated owner-only GET `/api/v1/world` and GET
`/api/v1/world/changes?after_revision=<cursor>&limit=<limit>` use one
owner-scoped REPEATABLE READ, READ ONLY transaction per response. Explicit
ownership predicates remain mandatory for bypass roles. No cross-user
identifiers or supplied user selector. Each read sees its head and objects or
deltas in the same snapshot. Existing authentication failure behavior applies.

`after_revision` is required, an integer >=0 within PostgreSQL BIGINT range;
negative, non-integer or overflow returns 422. `limit` defaults to 500; an
integer >=1 is required when supplied. Reject non-integer/<1 with 422; clamp
any larger positive integer to 1000 before database binding. Booleans, decimal
strings and scientific notation are not accepted as integer query values.

| Cursor/history condition | Exact behavior |
| --- | --- |
| cursor == head | 200, empty changes, from/to/current all head, has_more false |
| cursor > head | 409 WORLD_RESYNC_REQUIRED |
| any required revision cursor+1..head missing | 409 WORLD_RESYNC_REQUIRED, including missing prefix/interior/all history |
| complete requested suffix | 200, ascending contiguous changes up to clamped limit |

Check suffix continuity against the same head even beyond the current page;
history at or before an accepted cursor is not needed. For a valid page,
from_revision is the cursor, to_revision the last returned revision,
current_revision the transaction's head, has_more = to_revision < head.
Revision-zero empty virtual Worlds obey the same page rules. A 409 response
contains no partial changes; client must GET the snapshot and resume at its
revision. Subsequent requests may observe a higher head.

The strict `worldResyncRequired` schema keeps existing Problem Details keys:
type `about:blank`, title `World resync required`, status 409, code
`WORLD_RESYNC_REQUIRED`, detail `Fetch the World snapshot before requesting further changes.`,
request_id (opaque request correlation UUID), and details containing exactly
after_revision/current_revision. No source reason, SQL or private content.
Fixtures use a fixed request UUID; production correlation IDs remain operational.

## Migration specification — 0020 only, not implemented here

Future revision `0020_learner_projection_foundation` has down_revision
`0019_response_lock_security`. All migrations 0001–0019 remain byte-for-byte
unchanged. Planned metadata and invariants:

| Table/change | Required schema/invariant |
| --- | --- |
| projection_source_heads | user_id PK/FK app_users CASCADE; source_sequence BIGINT >=0 default0; bootstrap_state REQUIRED/READY; nullable baseline_through_sequence; nullable cutoff_source_sequence/cutoff_at; READY baseline metadata coherent or null for proven fresh users |
| projection_inputs | composite PK user_id/source_sequence; owned user FK; source_kind/key/group/time; contract_version + schema_version; strict bounded facts JSONB; UNIQUE(user_id,source_kind,source_key); nullable typed ledger_event_id/evidence_id owner FKs; source-kind reference consistency; immutable insert-only facts |
| learner_projection_checkpoints | user_id PK/FK CASCADE; processed source_sequence >=0 default0; generation BIGINT >=1; frozen input/worker/learner/world contract identities; input/output SHA-256 fingerprints; nullable blocking_group and bounded failure_code; initialized empty checkpoint permits nullable fingerprints; no hidden-state JSON |
| learner_objective_state | understanding_estimate nullable, preserve existing values; v1 rows write null; current-row uniqueness unchanged |
| world_nodes | nullable entity_version expansion; positive when nonnull; exact composite FK (entity_id,entity_version) -> learning_entity_versions(entity_id,version); no guessed legacy pins; v1 producer requires a pin |
| world_regions | UNIQUE(world_id,region_key) only after duplicate preflight; conflicts abort, never delete/deduplicate historical rows |

New input reference FKs are `(user_id,ledger_event_id)` to
`learning_events(user_id,id)` and `(user_id,evidence_id)` to
`learning_evidence(user_id,id)`; EVIDENCE refs and ledger refs are mutually
exclusive, BOOTSTRAP has neither. These indexed typed columns must agree with
the closed payload source ID. Other owned resource references are validated at
capture and again on loading; no raw metadata shortcut. Enforce receipt size,
schema identity and basic shape at storage boundary as well as parser validation.
Baseline metadata is immutable after READY; source_sequence advances only by
valid capture. Checkpoint processed_sequence never exceeds owned head, and
must end a normal group or the recorded baseline prefix. Validate this under
publication locks; do not treat a cross-table CHECK as sufficient.

Enable and FORCE owner-scoped RLS on all three tables. Strip default/client
grants; anon/authenticated/service_role receive no direct projection access.
app_backend may read owned metadata/receipts, allocate/update only its owned
source head's live sequence, and insert strict inputs plus existing queue
references. It cannot modify/delete receipts, set bootstrap READY, alter
checkpoint or write Learner State/World. Limit column grants accordingly.
Existing worker has trusted bypass scope, but explicitly validates every owner;
only it publishes checkpoint/state/World and invokes reviewed bootstrap. Keep
capture functions narrow and invoker-scoped unless an individually reviewed
definer is essential. Trusted functions require fixed search_path, qualified
objects, explicit execution grants and no public execution.

Immutability guards deny receipt UPDATE/DELETE except trusted physical account
deletion; privileged worker cannot rewrite receipt history. Extend the existing
trusted NOLOGIN maintenance deletion routine to remove projection jobs and
inputs before referenced ledger/evidence rows, then checkpoints/heads before
app_user, in the existing whole-transaction owner-isolated deletion order.
Serialize deletion versus capture/bootstrap/publication using owner existence
and metadata locks; late workers cannot recreate a deleted owner. Idempotent
deletion and rollback remain required. No new export/delete HTTP workflow,
Auth erasure or storage erasure is implied; eventual exports must include new
facts/current projections and provenance versions.

Preflight refuses duplicates, invalid lineage and unknown-model import without
changing existing records. Verify upgrade/downgrade on disposable databases,
single Alembic head, drift and historical checksums. No generic scores, graph
store, prose Memory table, hidden-state JSON, numeric ability/affinity model,
change_ordinal or M3/M4 ranking feature is added.

## Frozen recommendation compatibility

[M4 objective_state_entry](../../backend/app/recommendation/inputs.py) consumes
categorical_state only; understanding_estimate is deliberately unread by
readiness. Nullable estimates therefore do not change the frozen algorithm.
DEVELOPING maps to UNSATISFIED; absence maps to UNKNOWN. Existing hard
prerequisites remain ineligible in both cases with their existing distinct
reasons (PREREQUISITE_UNMET versus INSUFFICIENT_STATE). Never reinterpret weak
recognition as readiness satisfaction.

No candidate sources, M3 features, weights, diversity, ranking/reranking,
explanation order, explicit preference suppression, policy identities or
no-result semantics change. Compatibility acceptance cases are specified in
the implementation plan; no runtime compatibility code is part of M6-01.
