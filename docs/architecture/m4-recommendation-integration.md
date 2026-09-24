# M4 Recommendation Integration

This is the implemented backend path for [`production-recommendation/v1`](../api/production-recommendation-service-contract-v0.1.md), using the frozen `m3-simulation/v5` decision mechanics and the [v0.1 API](../api/api-contracts-v0.1.md). The first release produces one learning-entity recommendation. `CREATE` returns the replayable empty result until practical targets are added.

## Request path

1. `POST /api/v1/recommendations/next` authenticates a Supabase token and resolves its internal `app_users.id`. The route checks an unexpired idempotency result before work begins.
2. `snapshot.py` opens a separate RLS-scoped PostgreSQL `REPEATABLE READ` transaction. It reads reviewed/published ontology versions, edges, matching document embeddings, explicit preferences, exploration history, and learner projections. The transaction closes before any provider call. The selected anchor set is ACTIVE exploration targets and current-version MORE targets, sorted and deduplicated.
3. For EXPLORE and SURPRISE with anchors and a document corpus, `service.py` makes one deterministic `semantic-query/v1` text per anchor from its versioned title and summary. `VoyageQueryEmbedder` sends those queries as `voyage-4`, `input_type=query`, 1024-D vectors. Provider code is outside the ranking domain.
4. `retrieval.py` nominates the five M3 source categories, applies the request-mode source filter, exact cosine threshold and cap, and bounded two-hop bidirectional RELATED_TO graph policy. It uses M3 normalization and hard eligibility. A missing categorical prerequisite state is UNKNOWN; HARD UNKNOWN is excluded.
5. `ranking.py` calls M3 feature scoring, deterministic tie handling, `DOMAIN_COVERAGE` rerank, and explanation-code builder. It selects the first result only after ranking the full eligible set. `distance-band/v1` reads the selected candidate's transient source paths and never influences M3 rank.
6. A write transaction reserves the command key, rechecks the selected ontology target's version and reviewed/published status, inserts one recommendation with compact selected provenance, stores the response for replay, and commits. No eligible candidate yields HTTP 200 `{"recommendation": null}` and no recommendation row.
7. `POST /api/v1/recommendations/{id}/decision` reserves its command key, locks a recommendation with an explicit user predicate, and writes ACCEPT or SKIP. ACCEPT creates the Exploration and two ordinal ledger events in the same transaction. SKIP creates one ledger event. Both responses are durable replay results.

The write transaction can observe a later ontology state than the input snapshot. If the selected target is no longer deliverable, it rolls back the reservation and responds `409 RECOMMENDATION_TARGET_CHANGED`; a new key requests a fresh snapshot. Concurrent same-key calls may repeat generation work, but the unique command reservation serializes the write and yields one persisted result.

## Version and data mapping

| Production source | M3 meaning | Production policy |
|---|---|---|
| `learning_entities`, versions, domains, objectives | Ontology target and scoring context | Historical versions remain readable; only REVIEWED/PUBLISHED entities can be delivered. |
| `ontology_edges` | RELATED_TO and objective-relative REQUIRES | Versioned REQUIRES endpoints and objective identity are explicit; malformed active REQUIRES fails closed. |
| `learner_objective_state.categorical_state` | Objective readiness | `UNDERSTOOD`/`RETAINED` satisfy; absent state is UNKNOWN. Numeric estimates are not used as a threshold. |
| `learner_interest_state`, `learner_challenge_state` | Inferred affinity and area ability | Recent and long-term interest stay distinct; missing ability remains missing. |
| Explicit preferences and `explorations` | Explicit nomination, continuation, revisit, anchors | PAUSED and NOT_INTERESTED hard-exclude. ACTIVE supports continuation; COMPLETED supports revisit. |
| `entity_embeddings` | Semantic document space | Only `voyage-ai`/`voyage-4`/1024/`entity-document/v1` document rows are read. Exact cosine search uses the versioned 0.55 floor and 40-target cap. |
| Checked-in JSON profiles | Ranking, retrieval, distance, presentation | `recommendation-profile/v1`, `recommendation-retrieval/v1`, `distance-band/v1`, and `recommendation-copy/v1` are immutable identities. |

Migrations `0014`–`0016` add categorical objective state, versioned REQUIRES and 1024-D embedding identity, and nullable recommendation reason. `0015` stops if old embedding rows or REQUIRES edges need explicit curation; it does not guess a re-embedding or objective mapping. Only the first canonical M3 explanation code selects reviewed hook/reason copy. All codes remain private provenance. Zero codes persist a null reason code and null copy.

The recommendation row stores the selected source categories, code list, final rank, selected score components, pre-rerank score, diversity adjustment, ordering score, copy version, and presentation time. Full paths, excluded candidates, raw feature values, weights, learner snapshots, and vectors are transient. The event metadata contains recommendation identity and optional bounded SKIP reason. No M3 simulation result, fixture ID, or evaluation report is persisted or returned.

## Security and operations

The backend uses `app_backend` and transaction-local `app.user_id` for RLS. Recommendation load and decision writes also predicate on `user_id`. The `app_worker` role and queue are not used for this synchronous path. Both endpoints require `Idempotency-Key`; same key and fingerprint replay the stored response, while changed content conflicts. ACCEPT intent maps CONTINUE to RELATED_EXPLORATION, REVISIT to RETENTION_REVISIT, EXPLORE to DIRECT_INTEREST, and SURPRISE to SERENDIPITY. Future CREATE practical acceptance maps to PRACTICAL_SUPPORT.

Set `EMBYR_VOYAGE_API_KEY` when the searchable document corpus is populated and semantic queries can run. The corpus is derived data: the ontology ingestion process must write or refresh `entity-document/v1` rows on title/summary or version changes. This milestone provides the versioned read and query adapter, not an ingestion writer or online backfill. A model transition needs an explicit re-embedding plan. Missing document rows yield no semantic paths; graph and explicit sources can still nominate.

Exact search currently loads matching document vectors in the snapshot and compares each anchor to each document in application memory. Cost is O(anchors × documents × 1024); the 0.55 threshold, 40 semantic target cap, two-hop graph bound, and 100 graph target cap are initial uncalibrated policy, not quality or latency claims. No ANN index, provider refresh job, benchmark, load test, recommendation expiry/history endpoint, worker path, Android UI, or practical-target generator is included.

## Verification gate

Focused backend tests cover the input mapper, five retrieval sources, M3 adapter, compact provenance, distance bands, API replay and ownership behavior, and an in-memory snapshot-to-ranking case. [`test_recommendation_flow.py`](../../database/tests/test_recommendation_flow.py) is the targeted disposable PostgreSQL gate for preference → recommendation → ACCEPT → Exploration/events, empty CREATE, ownership, replay, and fingerprint conflict. Run it with a running Docker daemon for Testcontainers or a dedicated disposable `EMBYR_TEST_DATABASE_URL`:

```bash
python -m pytest database/tests/test_recommendation_flow.py -q
```

After starting Docker Desktop, the disposable PostgreSQL flow passed. The adjacent recommendation schema, ontology, and RLS selection passed (68 tests), as did the backend suite (132 tests) and the frozen M3 suite (856 tests). A live Voyage request, corpus refresh operation, scale benchmark, and hosted rollout were not exercised; those remain deployment and calibration work, not evidence of recommendation quality.
