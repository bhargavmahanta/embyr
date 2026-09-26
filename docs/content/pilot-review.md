# Pilot content review and provisioning

The repository pilot at `backend/app/learning/packages/pilot-v1.json` is an AI-assisted **draft**. Structural tests and technical inspection are factual provenance only. No human review or learning effectiveness is claimed. Human asset review is a production release acceptance gate.

A named human reviewer must inspect each work prompt, objective, recognition option, result mapping, feedback and all four support levels for accuracy, accessibility, prerequisite-free scope, coherence and safe wording. They must inspect the DOMAIN → AREA → TOPIC composition and search suggestions, including two PART_OF hierarchy edges and two RELATED_TO discovery edges between adjacent levels. Frozen M4 graph retrieval treats RELATED_TO edges bidirectionally, enabling one-hop and two-hop discovery from either end. The reviewer approves the exact package bytes, not merely its filename. Do not modify a released content/rubric identity: add a new immutable package/version and retain historical definitions when future versions are authored.

After review, the operator creates a local attestation (never prepopulate a real approval in source control):

```json
{
  "package_sha256": "<actual sha256 of packages/pilot-v1.json>",
  "reviewer": "<human reviewer name or accountable identifier>",
  "reviewed_at": "<actual ISO timestamp with timezone>",
  "decision": "APPROVED",
  "review_kind": "HUMAN"
}
```

The command `PYTHONPATH=backend python -c 'from app.learning.content import package_digest; print(package_digest())'` prints the package digest. Store approvals outside the checkout with access controlled by the operator. The attestation is an operational trust record, not a cryptographic signature. Never label an agent's validation as human review.

Provision only through the explicit operator command:

```bash
# Set EMBYR_CONTENT_OPERATOR_DATABASE_URL through your operator credential mechanism.
PYTHONPATH=backend python -m app.learning.provision_content --review-attestation /absolute/path/review.json
PYTHONPATH=backend python -m app.learning.provision_content --review-attestation /absolute/path/review.json --check-only
```

Use a synchronous SQLAlchemy PostgreSQL URL such as `postgresql+psycopg://...` and a privileged ontology provisioning identity, separately from backend runtime credentials. The command refuses TEST attestations. It provisions stable entity/version/objective/edge IDs, primary domain membership, two PART_OF hierarchy edges and two RELATED_TO discovery edges in one transaction. Rerunning the same approval is harmless; differing existing immutable fields or any global coverage gap aborts the whole transaction.

Coverage checks every current REVIEWED/PUBLISHED entity version, including entities outside this pilot. Adding reviewed catalog entities requires matching delivery packages. This release gate has no effect on recommendation candidate retrieval or ranking, and runtime content gaps retain accepted explorations for recovery.

Configure `EMBYR_CONTENT_REVIEW_ATTESTATION=/absolute/path/review.json` on backend runtime. Missing, stale-digest or invalid approvals fail closed: `get_definition` returns no content. Runtime does not provision ontology or create interests. A separate test harness may explicitly set `EMBYR_CONTENT_ALLOW_TEST_ATTESTATION=1` with a `review_kind: TEST` approval; production deployment must omit this test switch.

Delivery snapshots pin the exact entity, objective, content and rubric identities and versions. Public delivery is constructed from a positive field whitelist and omits the entire private assessment. Assessment reads must separately whitelist prompt/options and support actually requested. Option mappings, feedback before evaluation and undelivered support are private.
