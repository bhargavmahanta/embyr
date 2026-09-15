# LLD v0.1 — Core Data Model

## 1. Design Goal

The backend must keep four fundamentally different kinds of information separate:

```text
WHAT HAPPENED
Experience Ledger

WHAT KNOWLEDGE EXISTS
Ontology Graph

WHAT WE CURRENTLY BELIEVE
Learner State

WHAT THE LEARNER'S WORLD LOOKS LIKE
WorldModel
```

These should never collapse into one giant user/profile document.

The central flow is:

```text
User action
    ↓
Operational data
    ↓
Experience Ledger
    ↓
Evidence
    ↓
Learner State projector
    ↓
Recommendation / Retention
    ↓
WorldModel projector
    ↓
Native clients
```

---

## 2. Important Architectural Decision

We are **not building a pure event-sourced system**.

The Experience Ledger records factual learning events, but normal operational tables still exist.

Example:

```text
reflection_submitted event
            │
            └── references reflection_id

reflections table
            │
            └── contains actual reflection text
```

This is preferable to storing every piece of private user-generated content directly inside event payloads.

The ledger answers:

> What happened?

Operational tables answer:

> What currently exists?

---

# Part A — Experience Ledger

## 3. Experience Ledger Purpose

The Experience Ledger is the factual history used to derive Curiosity Memory.

Examples:

```text
TOPIC_PRESENTED
TOPIC_ACCEPTED
TOPIC_SKIPPED
EXPLORATION_STARTED
USER_RETURNED

REFLECTION_SUBMITTED

ASSESSMENT_STARTED
ASSESSMENT_RESPONSE_SUBMITTED
HINT_REQUESTED
ASSESSMENT_COMPLETED

ARTIFACT_CREATED

TOPIC_PAUSED
TOPIC_REVISITED

RETENTION_CHECK_STARTED
RETENTION_CHECK_COMPLETED

RECOMMENDATION_ACCEPTED
RECOMMENDATION_REJECTED
```

Events must never contain conclusions such as:

```text
USER_LOVES_ASTRONOMY
USER_IS_BAD_AT_MATH
```

Those are inferences.

---

## 4. `learning_events`

Conceptual schema:

```text
learning_events
────────────────────────────────
id                  UUID
user_id             UUID
device_id           UUID nullable

event_type          ENUM/string

entity_id           UUID nullable
exploration_id      UUID nullable
assessment_id       UUID nullable
artifact_id         UUID nullable

learning_intent     ENUM nullable

occurred_at         timestamptz
received_at         timestamptz

command_id          UUID nullable
event_ordinal       integer nullable
schema_version      integer

metadata            JSONB

created_at          timestamptz
```

Idempotency belongs to the command record, not directly to individual events. A single idempotent command may legitimately emit several ordered Experience Ledger events.

Where `command_id` is present:

```text
UNIQUE(command_id, event_ordinal)
```

---

## 5. Why `occurred_at` and `received_at` Both Exist

Offline use makes these different.

Example:

```text
User answers:
14:32

Internet reconnects:
16:10
```

Therefore:

```text
occurred_at = 14:32
received_at = 16:10
```

This lets us reconstruct actual learner behavior without pretending the interaction happened when synchronization occurred.

---

## 6. Command Idempotency

Offline synchronization can accidentally submit the same operation twice.

Every client-generated mutating command receives an idempotency key stored in an idempotency record.

Conceptually:

```text
idempotency_records
────────────────────────────
id
user_id
idempotency_key
request_fingerprint
response_status
response_body
created_at
```

Backend rule:

```text
same user
+
same idempotency_key
+
same request fingerprint
=
same command result
```

Reusing the same idempotency key with a different request fingerprint is rejected.

Repeated submission returns the existing durable result rather than re-running the command.

---

## 7. `learning_intent`

Frozen values:

```text
DIRECT_INTEREST
PREREQUISITE_SUPPORT
RELATED_EXPLORATION
RETENTION_REVISIT
PRACTICAL_SUPPORT
SERENDIPITY
```

This solves an important recommendation problem.

If the application recommended calculus because the user needed it for another topic, completing calculus does not automatically imply:

> this person loves calculus.

---

## 8. Sensitive Event Payloads

The event ledger should contain references wherever possible.

Bad:

```json
{
  "reflection": "I've been struggling with..."
}
```

Better:

```json
{
  "reflection_id": "..."
}
```

Actual content remains in:

```text
reflections
```

with independent privacy/deletion controls.

---

## 9. Reflections

```text
reflections
─────────────────────────────
id
user_id
exploration_id
entity_id

text

created_at
updated_at
version
```

A reflection can be edited.

Its corresponding original event is not edited.

---

## 10. Assessment Responses

```text
assessment_responses
─────────────────────────────
id
user_id

assessment_session_id
objective_id
interaction_id

response_type
response_content

confidence_before
support_used

submitted_at
```

`response_content` may support:

```text
text
selected options
ordering
matching
media reference
structured response
```

---

## 11. Evaluation Runs

AI or deterministic evaluation must be versioned rather than overwritten.

```text
evaluation_runs
─────────────────────────────────
id
response_id

evaluator_type
evaluator_version
rubric_version

result
confidence

status
supersedes_evaluation_id nullable

created_at
```

Possible result classes include:

```text
SUPPORTED
PARTIAL
MISCONCEPTION
INSUFFICIENT_EVIDENCE
UNCERTAIN
```

Possible statuses include:

```text
ACTIVE
SUPERSEDED
REVOKED
```

If an AI evaluation is corrected later, the old evaluation remains historical but stops affecting current Learner State.

---

## 12. Evidence

Assessment responses themselves are not equivalent to learning evidence.

Evaluation produces:

```text
learning_evidence
─────────────────────────────────
id
user_id

entity_id
objective_id

source_type
source_id
evaluation_run_id nullable

evidence_type
evidence_strength

support_level
evaluation_confidence

status
created_at
```

Evidence types are the frozen ontology values:

```text
RECOGNITION
RECALL
EXPLANATION
APPLICATION
ARGUMENT
PREDICTION
CREATION
DEMONSTRATION
REFLECTION
RETENTION
```

Strength:

```text
WEAK
MODERATE
STRONG
```

Evidence status may be:

```text
ACTIVE
SUPERSEDED
REVOKED
```

---

## 13. Why Evidence Is Separate

Consider:

```text
Question:
Explain TCP reliability.
```

Learner answers correctly after a strong hint.

That is still positive evidence.

But it differs from:

```text
Correct explanation
without support
in an unfamiliar application scenario.
```

Both should exist in history.

The learner does not see:

```text
Evidence strength = 0.73
```

The model does.

---

# Part B — Ontology Graph

## 14. Stable Entity Identity

Every learning entity receives a stable ID.

Examples:

```text
TCP three-way handshake
Opportunity cost
Rule of thirds
Ship of Theseus
```

The identity remains stable even if we improve its description later.

---

## 15. `learning_entities`

```text
learning_entities
────────────────────────────
id
canonical_key

entity_type

status
current_version

created_at
updated_at
```

Possible types:

```text
DOMAIN
AREA
TOPIC
CONCEPT
SKILL
TECHNIQUE
JOURNEY
```

---

## 16. Entity Versions

Canonical definitions change.

Therefore:

```text
learning_entity_versions
────────────────────────────────
id
entity_id
version

title
summary

knowledge_types[]
scope

difficulty_prior
estimated_effort

freshness_requirement

provenance
source_metadata

created_at
```

An old learning event still points to:

```text
entity_id
```

while assessment sessions additionally record the historical canonical version being used at the time.

---

## 17. Knowledge Types

Stored as an array because topics can contain several:

```text
FACTUAL
CONCEPTUAL
PROCEDURAL
REASONING
CREATIVE
PRACTICAL
```

Example:

```text
Rule of Thirds

[
  PRACTICAL,
  CREATIVE,
  CONCEPTUAL
]
```

---

## 18. Domain Membership

Because topics may belong to multiple domains:

```text
entity_domains
──────────────────────────
entity_id
domain_id

is_primary
membership_strength
```

Example:

```text
Game Theory
├── Economics       primary
├── Mathematics
├── Computer Science
└── Political Science
```

No artificial single-parent restriction.

The database must enforce at most one primary domain per entity.

---

## 19. Ontology Edges

```text
ontology_edges
────────────────────────────────
id

source_entity_id
target_entity_id

relationship_type

strength nullable
context nullable
confidence

provenance

status
created_at
updated_at
```

Relationship types:

```text
REQUIRES
BUILDS_ON
PART_OF
RELATED_TO
CONTRASTS_WITH
APPLIES_TO
LEADS_TO
EXAMPLE_OF
BELONGS_TO
CAN_BE_EXPLORED_AS
```

---

## 20. Contextual Prerequisites

Important example:

```text
Derivatives
    REQUIRES
Backpropagation
```

may be:

```text
strength = HARD
context = mathematical_derivation
```

but for:

> What is a neural network?

derivatives may be:

```text
NOT_REQUIRED
```

Therefore prerequisite relationships are evaluated against the **target learning objective**, not treated as universal laws.

---

## 21. Objectives Are First-Class

```text
learning_objectives
────────────────────────────────
id
entity_id
entity_version_id

objective_type
description

importance
created_at
```

Example:

```text
CAP theorem
│
├── Explain partition tolerance
├── Explain consistency during partition
└── Apply CAP reasoning to a scenario
```

Learner understanding eventually attaches to objectives rather than only to topics.

---

## 22. Misconceptions

```text
misconceptions
───────────────────────────
id
entity_id
objective_id nullable

description
canonical_correction

severity
provenance
```

Example:

```text
CAP consistency
=
ACID consistency
```

can be explicitly represented as a misconception.

---

## 23. Claim Representation

For topics where truth status matters:

```text
claims
────────────────────────────
id
entity_id

claim_type
statement

source/provenance
```

Types:

```text
ESTABLISHED_FACT
SUPPORTED_EXPLANATION
CONTESTED_CLAIM
INTERPRETATION
NORMATIVE_POSITION
```

This protects philosophical and controversial topics from being evaluated as though every question has one factual answer.

---

## 24. Embeddings

Embeddings belong to canonical entities:

```text
entity_embeddings
────────────────────────────
entity_id
entity_version_id

embedding
embedding_model

created_at
```

Use pgvector.

Changing the embedding model does not change the entity.

It creates another embedding record/version.

Initial semantic retrieval should use exact search. Approximate indexes such as HNSW or IVFFlat are added only if measured scale requires them.

---

# Part C — Learner State

## 25. Learner State Is Derived

Nothing in Learner State should be treated as unquestionable truth.

Every state contains:

```text
computed_at
model_version
evidence/provenance
```

And it must remain recomputable.

---

## 26. Keep Interest Separate From Knowledge

Do **not** create:

```text
learner_topic_score
```

representing everything.

We explicitly separate:

```text
Interest
Understanding
Retention
Confidence
Challenge
Preferences
```

---

## 27. `learner_interest_state`

```text
learner_interest_state
────────────────────────────────
id
user_id
entity_id

explicit_preference nullable

recent_affinity
long_term_affinity

user_initiated_strength
algorithm_exposure_strength

voluntary_revisit_count

last_interaction_at
computed_at

model_version
is_current
```

Only one current row may exist for a logical learner/entity interest state.

Historical derived-state versions may remain for audit/research.

This distinction protects against the algorithm manufacturing its own interests.

---

## 28. Example

Suppose the recommender shows astronomy five times.

User completes every recommendation.

Possible state:

```text
algorithm_exposure_strength = HIGH

user_initiated_strength = LOW/MEDIUM
```

Then the learner voluntarily searches:

> black holes

and later revisits time dilation.

Now:

```text
user_initiated_strength ↑
```

That is substantially stronger curiosity evidence.

---

## 29. `learner_objective_state`

```text
learner_objective_state
────────────────────────────────
id
user_id
objective_id

understanding_estimate
evaluation_confidence

support_required
last_evidence_at

evidence_count

computed_at
model_version
is_current
```

This becomes the core knowledge model.

Only one current row may exist per learner/objective.

---

## 30. No Universal Mastery

We may aggregate topic-level state for convenience:

```text
learner_entity_state
```

but it should be derived from objectives.

Possible internal state:

```text
ENCOUNTERED
EXPLORING
DEVELOPING
UNDERSTOOD
REVISITING
RETAINED
PAUSED
```

No requirement that everything reaches:

```text
MASTERED
```

Philosophical/reasoning topics may remain deeply explored without a mastery endpoint.

---

## 31. Retention State

```text
learner_retention_state
────────────────────────────────
id
user_id
entity_id

retention_estimate

last_successful_recall
last_revisit

next_revisit_window

model_version
computed_at
is_current
```

Later this can contain an estimated half-life if Half-Life Regression or a related method proves useful.

For v0.1, keep it model-agnostic.

---

## 32. Confidence State

```text
learner_confidence_state
──────────────────────────────
id
user_id
entity_id

self_reported_confidence

observed_understanding

calibration_state

computed_at
model_version
is_current
```

Internal calibration might indicate:

```text
UNDERCONFIDENT
CALIBRATED
OVERCONFIDENT
UNKNOWN
```

But user-facing language stays gentle.

---

## 33. Challenge State

Difficulty should be domain/concept-specific.

```text
learner_challenge_state
──────────────────────────────
id
user_id
area_id

ability_estimate
estimate_confidence

recent_support_rate
recent_success_rate

model_version
computed_at
is_current
```

Initially this can use an Elo-like model.

Later the same interface can be backed by IRT.

---

## 34. Learner Preferences

Explicit user preferences belong separately from inferred state:

```text
learner_preferences
────────────────────────────
user_id

adventure_preference
preferred_effort
difficulty_support_style

practical_opt_in

notification_preferences

version
updated_at
```

Explicit preference beats inference.

Always.

---

## 35. State Provenance

For high-value inferred state we must know:

> Why do we think this?

Do not copy hundreds of event IDs into one JSON field forever.

Use:

```text
state_evidence_links
────────────────────────────
state_type
state_id

evidence_id
weight
```

or maintain an aggregate plus trace to recent/high-value evidence.

This lets us explain:

> Astronomy appeared because you searched for black holes and revisited time dilation.

---

## 36. State Recomputation

Every derived-state table stores:

```text
model_version
computed_at
is_current
```

A recomputation job can target:

```text
user
entity
state type
```

rather than rebuilding the person's entire history every time.

Example:

```text
delete photography interaction
        ↓
identify affected entities
        ↓
recompute photography state
        ↓
update recommendations
        ↓
update WorldModel
```

---

# Part D — WorldModel

## 37. WorldModel Principle

The WorldModel represents the **semantic visual world**.

It does not contain screen coordinates.

It does not contain SpriteKit nodes.

It does not contain Android Canvas objects.

It tells native renderers:

> What exists, where it logically lives, and what state it represents.

---

## 38. `learner_worlds`

```text
learner_worlds
──────────────────────────
user_id

generation_seed
layout_version

current_revision

created_at
updated_at
```

`generation_seed` ensures deterministic visual generation where required.

`current_revision` must increase monotonically.

---

## 39. World Regions

```text
world_regions
────────────────────────────
id
user_id

region_key
primary_domain_id

logical_x
logical_y

logical_width
logical_height

visual_archetype

created_at
```

Example:

```text
region_key:
technology

logical position:
(0.25, 0.60)
```

---

## 40. World Knowledge Nodes

```text
world_nodes
────────────────────────────────
id
user_id

entity_id
region_id

logical_x
logical_y
depth

visual_archetype
visual_seed

growth_state

first_placed_at
last_growth_at

revision
```

Example:

```text
entity:
TCP Handshake

visual_archetype:
branching_tree

growth_state:
YOUNG

logical position:
0.42, 0.71
```

---

## 41. Growth States

The visual system should use a small number of semantic states.

Possible:

```text
SEED
SPROUT
YOUNG
ESTABLISHED
```

Do not create:

```text
Level 1
Level 2
Level 3
```

And importantly:

> growth state is a visual interpretation of learning evidence, not a numerical mastery score.

---

## 42. World Connections

```text
world_connections
────────────────────────────────
id
user_id

source_world_node_id
target_world_node_id

ontology_edge_id nullable

connection_type

importance

is_visible

revision
```

The ontology might contain thousands of relationships.

The forest renders only selected meaningful ones.

---

## 43. Artifacts

Artifact data itself:

```text
artifacts
────────────────────────────
id
user_id

skill_entity_id
challenge_id

media_object_id

reflection_id

created_at
```

World placement:

```text
world_artifacts
────────────────────────────
artifact_id
user_id

region_id

logical_x
logical_y
depth

visual_archetype
visual_seed

revision
```

The photograph/crochet object/program therefore exists independently of its visual representation.

---

## 44. World Revision

Every committed change to the logical world increments:

```text
current_revision
```

Example:

```text
Phone last knows:
revision 215

Server now:
revision 219
```

Client asks:

> Give me changes after 215.

Backend returns a paginated delta stream rather than the whole forest.

The API distinguishes:

```text
returned_through_revision
current_server_revision
has_more
next_cursor
```

so a large delta set can be synchronized safely across multiple pages.

---

## 45. World Deltas

```text
world_changes
────────────────────────────
id
user_id
revision
change_ordinal

change_type
object_type
object_id

payload

created_at
```

Examples:

```text
NODE_ADDED
NODE_GROWTH_CHANGED
NODE_MOVED
CONNECTION_ADDED
ARTIFACT_ADDED
REGION_ADDED
```

Ordering is stable within a revision.

This makes world synchronization efficient.

---

## 46. Full Snapshots

Clients occasionally need a complete snapshot.

Useful when:

- first login,
- new device,
- local state corrupted,
- delta history expired.

Normal synchronization uses deltas.

---

## 47. Stable Placement

Existing trees should not move every time our recommendation or layout algorithms improve.

Rule:

> Once an object has a meaningful position, preserve it unless moving it is necessary.

New growth expands around the existing world.

This is important emotionally.

The forest is a place the user remembers.

---

# Part E — Supporting Models

## 48. Users and Authentication Identities

Embyr must use an internal provider-independent user identifier.

```text
users
────────────────────────────
id
created_at
updated_at
```

External authentication identities are mapped separately:

```text
auth_identities
────────────────────────────
id
user_id

provider
provider_subject

created_at
```

This prevents the rest of the schema from becoming coupled to one authentication provider such as Supabase.

---

## 49. Explorations

A Topic and a learner interaction with that topic are different things.

```text
explorations
────────────────────────────
id
user_id
entity_id
entity_version_id

recommendation_id nullable

learning_intent

status
version

started_at
returned_at
completed_at
paused_at
```

This is the lifecycle object for one exploration.

Practical recommendations also use this same lifecycle rather than introducing a separate progression resource.

---

## 50. Assessment Sessions

```text
assessment_sessions
────────────────────────────────
id
user_id
exploration_id

status

started_at
completed_at

assessment_strategy_version
entity_version_id
```

Its interactions:

```text
assessment_interactions
────────────────────────────────
id
assessment_session_id

objective_id
interaction_type

prompt_definition
rubric_version

sequence
```

Generated prompts should be stored so we know exactly what the learner was asked.

---

## 51. Assessment Support Requests

Hints and other support requests are operationally significant and must be persisted.

```text
assessment_support_requests
────────────────────────────────
id
user_id
assessment_session_id
interaction_id

support_type
support_level

request_context
response_content nullable

created_at
resolved_at nullable
```

This supports the frozen hint ladder and allows support usage to influence evidence without losing provenance.

---

## 52. Practical Challenges

```text
practical_challenges
────────────────────────────
id
entity_id

target_techniques[]

estimated_effort

materials
environment_constraints
physical_requirements

evidence_requirements

version
```

Practical challenges are content definitions. A learner accepting one creates or uses a normal `Exploration`.

---

## 53. Media Uploads

Media upload lifecycle must be explicit.

```text
media_uploads
────────────────────────────
id
user_id

purpose

object_key
expected_content_type
expected_size_bytes

status

created_at
uploaded_at nullable
validated_at nullable
failed_at nullable
```

Possible statuses:

```text
CREATED
UPLOADED
VALIDATING
VALIDATED
FAILED
```

Only validated uploads can become durable artifact media.

Signed upload/download URLs are short-lived capabilities and must not be treated as durable stored API responses.

---

## 54. Recommendations

Recommendation provenance must be persisted.

```text
recommendations
────────────────────────────────
id
user_id

entity_id
entity_version_id

intent_mode
distance_band

ranking_model_version

score_components
candidate_source
presentation_context

presented_at
```

Possible `distance_band`:

```text
COMFORT
ADJACENT
FRONTIER
WILD
```

Detailed score components can remain JSONB initially:

```json
{
  "interest_fit": 0.0,
  "difficulty_fit": 0.0,
  "novelty": 0.0,
  "connection_value": 0.0,
  "diversity_penalty": 0.0,
  "retention_value": 0.0
}
```

This gives us the ability to debug recommendation behavior later.

The exact presentation provenance is retained so later analysis can distinguish what was ranked from what the user actually saw.

---

## 55. Recommendation Outcomes

The Experience Ledger tells us what subsequently happened:

```text
RECOMMENDATION_ACCEPTED
RECOMMENDATION_SKIPPED
EXPLORATION_STARTED
VOLUNTARY_REVISIT
```

Therefore we can later evaluate recommendation quality scientifically.

---

# Part F — Write Flow

## 56. Example: Learner Finishes an Assessment

```text
Assessment answer
      ↓
assessment_responses
      ↓
AI/deterministic evaluator
      ↓
evaluation_run
      ↓
learning_evidence
      ↓
ASSESSMENT_RESPONSE event(s)
      ↓
Learner State Projector
      ↓
learner_objective_state
learner_retention_state
confidence state
      ↓
World Projector
      ↓
world node growth changes
      ↓
world revision increments
      ↓
mobile receives delta
      ↓
plant grows
```

This creates a direct trace from:

> learner action

to:

> visual meaning.

---

## 57. Example: New Curiosity Interest

```text
User voluntarily searches:
"black holes"
       ↓
SEARCH / DISCOVERY event
       ↓
astronomy recent interest ↑
       ↓
recommendation engine
       ↓
more astronomy candidates become plausible
       ↓
forest may gradually form astronomy region
```

But only after enough meaningful evidence.

One search does not define identity.

---

## 58. Example: Forgotten Concept

```text
Retention check
       ↓
weak recall evidence
       ↓
retention estimate decreases
       ↓
topic becomes revisit candidate
```

World node does **not** die.

Its growth state does not necessarily reverse.

Knowledge history remains represented.

---

# Part G — Transaction Rules

## 59. Operational Write + Event Must Stay Together

Suppose reflection text is stored but corresponding event insertion fails.

Bad.

Use one database transaction:

```text
BEGIN

INSERT reflection
INSERT command/idempotency state as required
INSERT learning_event(s)

COMMIT
```

Either the command's durable operational state and its corresponding event history commit together, or neither does.

---

## 60. Heavy Processing Does Not Belong Inside That Transaction

Example:

```text
INSERT artifact
INSERT event
INSERT AI analysis job
COMMIT
```

Then worker processes AI later.

Do not leave DB transactions open while waiting for an LLM.

---

## 61. Job Table

Initial worker queue:

```text
jobs
───────────────────────────
id
job_type

payload

status

attempt_count
available_at

locked_at
locked_by

created_at
completed_at
```

States:

```text
PENDING
RUNNING
SUCCEEDED
RETRYABLE_FAILURE
FAILED
```

---

# Part H — Privacy Rules in the Schema

## 62. User Ownership

Every user-owned table contains:

```text
user_id
```

directly where reasonable.

This makes:

- authorization,
- RLS,
- deletion,
- export

much easier.

---

## 63. Private Media

Database contains:

```text
media_object_id
```

or object-storage keys, not permanent public URLs.

Actual objects remain private.

Signed URLs are created only when required and expire.

---

## 64. User Deletion

Deleting an account should conceptually remove or irreversibly anonymize, according to the final deletion policy:

```text
Experience Ledger
Reflections
Assessments
Evaluation Runs
Evidence
Learner State
Recommendations
WorldModel
Artifacts
Media
Preferences
Devices
Auth identities
```

Canonical ontology data remains because it is not owned by that user.

Account deletion itself is represented as an asynchronous operation so progress and failures can be inspected.

---

## 65. Derived State Rule

No irreplaceable information may live only in:

```text
learner_*_state
```

Everything important there must be derivable from:

```text
explicit preferences
+
events
+
evidence
+
canonical ontology
```

This is one of the most important invariants in the system.

---

# Part I — Module Ownership

## 66. Backend Ownership

```text
identity/
    internal users
    auth identities
    devices

ontology/
    learning entities
    objectives
    misconceptions
    edges
    claims
    embeddings

exploration/
    explorations
    reflections

assessment/
    sessions
    interactions
    responses
    support requests
    evaluation runs
    evidence

memory/
    learner state
    projection logic

recommendation/
    recommendations
    candidate generation
    ranking

world/
    regions
    nodes
    connections
    world deltas

artifacts/
    challenges
    uploads
    artifacts
    media metadata

events/
    Experience Ledger

jobs/
    asynchronous execution

account/
    exports
    deletion operations
```

Modules may reference each other's public interfaces.

They should not casually manipulate one another's tables.

---

# Part J — Core Invariants

These become architectural rules.

## Invariant 1

**Events record facts, never psychological conclusions.**

## Invariant 2

**Learner State is derived and replaceable.**

## Invariant 3

**Curiosity and knowledge remain separate.**

## Invariant 4

**Explicit user preference overrides inference.**

## Invariant 5

**The ontology describes knowledge; it does not describe a learner.**

## Invariant 6

**The WorldModel visualizes learning history; it does not become the source of truth.**

## Invariant 7

**A forest object cannot disappear merely because retention declines.**

## Invariant 8

**Algorithm-suggested exposure and user-initiated curiosity remain distinguishable.**

## Invariant 9

**Every assessment result must ultimately trace to an objective and versioned evidence.**

## Invariant 10

**Every recommendation must be explainable after the fact.**

## Invariant 11

**Offline operations must be idempotent at the command boundary.**

## Invariant 12

**Sensitive content should not be duplicated into the Experience Ledger unnecessarily.**

## Invariant 13

**AI evaluation is versioned and correctable; it never overwrites historical evidence silently.**

## Invariant 14

**The server is authoritative for synchronized user state; conflicting edits use explicit version semantics.**

## Invariant 15

**Canonical ontology versions used by historical assessments remain identifiable even after newer versions are published.**

---

# 67. Simplified Relationship Map

```text
                     ONTOLOGY
                         │
                  learning_entity
                         │
               ┌─────────┼─────────┐
               │         │         │
           objective    edge   misconception
               │
               │
               ▼
USER ──► exploration
           │
           ├── reflection
           │
           └── assessment_session
                    │
                    ▼
             assessment_response
                    │
                    ▼
              evaluation_run
                    │
                    ▼
             learning_evidence
                    │
                    ▼
              LEARNER STATE
                    │
          ┌─────────┼─────────┐
          │         │         │
       interest  knowledge  retention
          │         │         │
          └─────────┼─────────┘
                    │
             recommendation
                    │
                    ▼
                exploration

Every meaningful action
        │
        └────────────► EXPERIENCE LEDGER

Learner State
        │
        ▼
    WORLDMODEL
        │
        ├── region
        ├── node
        ├── connection
        └── artifact
```

---

# 68. What We Have Deliberately Not Frozen Yet

We should not prematurely freeze:

- exact numeric learner-state formulas;
- Elo constants;
- IRT model parameters;
- recommendation weights;
- retention algorithm;
- exact WorldModel layout algorithm;
- exact embedding model;
- individual LLM provider;
- exact JSON schemas for every assessment interaction;
- approximate vector-index strategy before measured need.

Those belong to experimentation.

The **data boundaries and invariants** are what matter now.

---

# 69. LLD v0.1 Verdict

This schema supports the frozen Embyr product without requiring:

- pure event sourcing,
- microservices,
- graph database,
- separate vector database,
- massive ML infrastructure.

At the same time, it gives us clean migration paths toward:

- IRT;
- knowledge tracing;
- contextual bandits;
- advanced retention models;
- much larger ontology graphs;
- dedicated recommendation services;
- alternative world renderers.

The underlying product semantics do not need to change when those systems become more sophisticated.

> **Facts are recorded. Evidence is interpreted. State is inferred. The world is rendered.**
