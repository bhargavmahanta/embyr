"""The production snapshot keeps owner-scoped domains and unknown state distinct."""
from __future__ import annotations

from uuid import UUID

from app.recommendation.snapshot import QUERIES, INPUT_VERSION, build_production_snapshot

USER = UUID("11111111-1111-1111-1111-111111111111")
ENTITY = UUID("22222222-2222-2222-2222-222222222222")
OBJECTIVE = UUID("33333333-3333-3333-3333-333333333333")


def test_snapshot_is_versioned_and_keeps_unknown_objective_out_of_m3_state():
    rows = {name: [] for name in QUERIES}
    rows["entities"] = [{
        "entity_id": ENTITY, "entity_version": 2, "current_version": 2,
        "status": "REVIEWED", "title": "A title", "summary": "A summary",
    }]
    rows["preferences"] = [{
        "entity_id": ENTITY, "entity_version": 2,
        "preference": "MORE", "version": 1,
    }]
    rows["objective_states"] = [{
        "objective_id": OBJECTIVE, "entity_id": ENTITY, "entity_version": 2,
        "categorical_state": None, "understanding_estimate": 1.0,
    }]
    rows["interest_states"] = [{
        "entity_id": ENTITY, "entity_version": 2, "recent_affinity": 0.5,
        "long_term_affinity": 0.2,
    }]
    snapshot = build_production_snapshot(USER, rows)
    assert snapshot.user_id == str(USER)
    assert snapshot.input_version == INPUT_VERSION
    assert snapshot.fingerprint.startswith("sha256:")
    assert snapshot.objective_states == ()
    assert snapshot.interest_states[0]["recent_affinity"] == 0.5
    assert snapshot.explicit_preferences[0]["preference"] == "MORE"
    assert snapshot.anchor_entities == ({
        "entity_id": str(ENTITY), "entity_version": 2,
    },)
    assert snapshot == build_production_snapshot(USER, rows)

async def _collect_snapshot_queries():
    from app.recommendation.snapshot import assemble_production_snapshot

    calls = []

    class Result:
        def mappings(self):
            return self

        def all(self):
            return []

    class Context:
        async def __aenter__(self):
            return self.session

        async def __aexit__(self, *_args):
            return None

    class Session:
        def begin(self):
            context = Context()
            context.session = self
            return context

        async def execute(self, statement, params=None):
            calls.append((str(statement).strip(), params))
            return Result()

    class Factory:
        def __call__(self):
            context = Context()
            context.session = Session()
            return context

    snapshot = await assemble_production_snapshot(Factory(), USER)
    return calls, snapshot


def test_snapshot_reads_set_isolation_and_rls_identity_before_data():
    import asyncio

    calls, snapshot = asyncio.run(_collect_snapshot_queries())
    assert calls[0][0].lower().split() == [
        "set", "transaction", "isolation", "level", "repeatable", "read"
    ]
    assert calls[1][0].lower().split() == ["set", "transaction", "read", "only"]
    assert "set_config('app.user_id'" in calls[2][0]
    assert calls[2][1] == {"user_id": str(USER)}
    assert len(calls) == len(QUERIES) + 3
    for statement, params in calls[3:]:
        if " :user_id" in statement:
            assert params == {"user_id": USER}
    assert snapshot.anchor_entities == ()
