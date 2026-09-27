"""M6-04 reads through a direct, non-bypass app_backend identity."""

from uuid import uuid4

from app.auth.principal import ExternalIdentity
from app.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


class Verifier:
    def verify(self, token):
        return ExternalIdentity("SUPABASE", token)


def client_for(db):
    engine = create_async_engine(db.url)

    @event.listens_for(engine.sync_engine, "connect")
    def role(connection, _):
        with connection.cursor() as c:
            c.execute("set session authorization app_backend")
        connection.commit()

    app = create_app(
        settings=Settings(
            database_url=db.url,
            supabase_auth_issuer="https://embyr-dev.supabase.co/auth/v1",
        ),
        session_factory=async_sessionmaker(engine, expire_on_commit=False),
        verifier=Verifier(),
    )
    return TestClient(app), engine


def headers(subject):
    return {"Authorization": f"Bearer {subject}"}


def test_required_relations_readable(isolated_migrated_database):
    db = isolated_migrated_database
    tables = [
        "projection_inputs",
        "projection_source_heads",
        "learner_projection_checkpoints",
        "learner_preferences",
        "explicit_interest_preferences",
        "learning_entities",
        "learning_entity_versions",
        "learner_objective_state",
        "state_evidence_links",
        "learning_evidence",
        "evaluation_runs",
        "assessment_responses",
        "assessment_sessions",
        "assessment_interactions",
        "learning_objectives",
        "explorations",
        "learner_worlds",
        "world_regions",
        "world_nodes",
        "world_changes",
        "jobs",
    ]
    with db.engine.connect() as c:
        c.execute(text("set session authorization app_backend"))
        c.commit()
        c.execute(text("set transaction isolation level repeatable read read only"))
        assert c.scalar(text("select current_user")) == "app_backend"
        for table in tables:
            c.execute(text(f"select 1 from public.{table} limit 0"))


def test_new_learner_memory_and_world(isolated_migrated_database):
    db = isolated_migrated_database
    subject = str(uuid4())
    client, _ = client_for(db)
    with client:
        client.post(
            "/api/v1/session/bootstrap", headers=headers(subject)
        ).raise_for_status()
        response = client.get("/api/v1/memory/summary", headers=headers(subject))
        assert response.status_code == 200, response.text
        memory = response.json()
        assert memory["projection"] == {
            "model_version": "learner-projection/v1",
            "source_sequence": 0,
            "source_head_sequence": 0,
            "status": "CURRENT",
        }
        assert memory["learning_preferences"] is None
        assert all(
            memory[k] == []
            for k in [
                "explicit_interests",
                "recently_explored",
                "recognition_evidence",
                "long_term_interests",
                "voluntary_revisits",
            ]
        )
        assert not any(memory["truncated"].values())
        world = client.get("/api/v1/world", headers=headers(subject))
        assert world.status_code == 200, world.text
        assert world.json()["revision"] == 0
        assert world.json()["nodes"] == []
        assert (
            client.get("/api/v1/me", headers=headers(subject)).json()["world_revision"]
            is None
        )


import asyncio
import json

import pytest
from sqlalchemy.exc import DBAPIError
from test_evaluation_supersession import _insert_entity_objective
from test_projection_foundation import onboard, user
from test_projection_publisher import drain, graph, sql


def subject_for(db, owner):
    with db.engine.begin() as c:
        sql(c, "update app_users set auth_provider='SUPABASE' where id=:u", u=owner)
        return c.scalar(
            text("select auth_subject from app_users where id=:u"), {"u": owner}
        )


def test_memory_freshness_preferences_and_explicit_bounds(isolated_migrated_database):
    db = isolated_migrated_database
    with db.engine.begin() as c:
        owner = user(c)
        onboard(c, owner)
        sql(
            c, "update app_users set onboarding_completed_at=now() where id=:u", u=owner
        )
        ids = []
        for i in range(21):
            entity, _ = _insert_entity_objective(c)
            ids.append(entity)
            sql(
                c,
                "update learning_entities set current_version=1 where id=:e",
                e=entity,
            )
            sql(
                c,
                "insert into explicit_interest_preferences(user_id,entity_id,preference,updated_at) values (:u,:e,:p,'2026-01-01')",
                u=owner,
                e=entity,
                p=["NEUTRAL", "MORE", "LESS", "PAUSED", "NOT_INTERESTED"][i % 5],
            )
        sql(
            c,
            "update learning_entities set current_version=null where id=:e",
            e=min(ids),
        )
    client, _ = client_for(db)
    with client:
        h = headers(subject_for(db, owner))
        r = client.get("/api/v1/memory/summary", headers=h)
        assert r.status_code == 200, r.text
        m = r.json()
        assert m["projection"]["status"] == "PENDING"
        assert m["learning_preferences"]["version"] == 1
        assert len(m["explicit_interests"]) == 20
        assert m["truncated"]["explicit_interests"] is True
        assert [x["entity_id"] for x in m["explicit_interests"]] == list(
            map(str, sorted(ids)[:20])
        )
        assert m["explicit_interests"][0]["availability"] == "UNAVAILABLE"
        assert m["explicit_interests"][0]["title"] is None
        assert {x["preference"] for x in m["explicit_interests"]} == {
            "NEUTRAL",
            "MORE",
            "LESS",
            "PAUSED",
            "NOT_INTERESTED",
        }
        with db.engine.begin() as c:
            sql(
                c,
                "update jobs set status='FAILED',attempt_count=3 where user_id=:u",
                u=owner,
            )
        assert (
            client.get("/api/v1/memory/summary", headers=h).json()["projection"][
                "status"
            ]
            == "FAILED"
        )


def test_projected_recent_recognition_and_world(isolated_migrated_database):
    db = isolated_migrated_database
    g = graph(db)
    drain(db)
    client, _ = client_for(db)
    with client:
        h = headers(subject_for(db, g["user_id"]))
        m = client.get("/api/v1/memory/summary", headers=h).json()
        assert m["projection"]["status"] == "CURRENT"
        assert m["recently_explored"][0]["started_count"] == 1
        assert m["recently_explored"][0]["entity_id"] == str(g["entity_id"])
        assert m["recognition_evidence"][0]["evidence_count"] == 1
        assert (
            m["recognition_evidence"][0]["summary"] == "Recognition evidence recorded."
        )
        w = client.get("/api/v1/world", headers=h).json()
        assert w["revision"] == 2
        assert len(w["regions"]) == 1 and len(w["nodes"]) == 1
        assert w["nodes"][0]["growth_state"] == "YOUNG"
        p = client.get("/api/v1/world/changes?after_revision=0&limit=1", headers=h)
        assert p.status_code == 200, p.text
        assert p.json()["has_more"] is True
        assert p.json()["to_revision"] == 1
        second = client.get(
            "/api/v1/world/changes?after_revision=1&limit=1", headers=h
        ).json()
        assert second["changes"][0]["payload"]["object"] == w["nodes"][0]
        assert second["has_more"] is False


def test_delta_query_matrix(isolated_migrated_database):
    db = isolated_migrated_database
    client, _ = client_for(db)
    with client:
        sub = str(uuid4())
        h = headers(sub)
        client.post("/api/v1/session/bootstrap", headers=h).raise_for_status()
        for query in [
            "",
            "?after_revision=-1",
            "?after_revision=1.0",
            "?after_revision=1e0",
            "?after_revision=true",
            "?after_revision=9223372036854775808",
            "?after_revision=0&limit=0",
            "?after_revision=0&limit=-1",
            "?after_revision=0&limit=1.0",
            "?after_revision=0&limit=1e3",
        ]:
            r = client.get("/api/v1/world/changes" + query, headers=h)
            assert r.status_code == 422, (query, r.text)
        for query in [
            "?after_revision=0",
            "?after_revision=0&limit=1",
            "?after_revision=0&limit=1000",
            "?after_revision=0&limit=1001",
            "?after_revision=0&limit=" + ("9" * 5000),
        ]:
            r = client.get("/api/v1/world/changes" + query, headers=h)
            assert r.status_code == 200, (query[:80], r.text)
            assert r.json() == {
                "from_revision": 0,
                "to_revision": 0,
                "current_revision": 0,
                "has_more": False,
                "changes": [],
            }
        r = client.get(
            "/api/v1/world/changes?after_revision=9223372036854775807", headers=h
        )
        assert r.status_code == 409, r.text
        assert r.json()["details"] == {
            "after_revision": 9223372036854775807,
            "current_revision": 0,
        }


def test_read_transaction_runtime_and_cleanup(isolated_migrated_database):
    from app.learning.read_transactions import read_transaction

    db = isolated_migrated_database
    with db.engine.begin() as c:
        owner = user(c)

    async def check():
        engine = create_async_engine(db.url, pool_size=1, max_overflow=0)

        @event.listens_for(engine.sync_engine, "connect")
        def role(connection, _):
            with connection.cursor() as c:
                c.execute("set session authorization app_backend")
            connection.commit()

        factory = async_sessionmaker(engine)
        async with read_transaction(factory, owner) as s:
            row = (
                await s.execute(
                    text(
                        "select current_user,current_setting('transaction_isolation'),current_setting('transaction_read_only'),current_setting('app.user_id')"
                    )
                )
            ).one()
            assert tuple(row) == ("app_backend", "repeatable read", "on", str(owner))
            with pytest.raises(DBAPIError):
                await s.execute(
                    text(
                        "update learner_preferences set version=version+1 where user_id=:u"
                    ),
                    {"u": owner},
                )
        async with factory() as s:
            assert not await s.scalar(
                text("select nullif(current_setting('app.user_id',true),'')")
            )
        await engine.dispose()

    asyncio.run(check())


from test_evaluation_supersession import _insert_response
from test_projection_foundation import evidence
from test_projection_publisher import add_version, start


def retire(c, g, status="REVOKED"):
    sql(
        c,
        "update learning_evidence set status=:s where user_id=:u and id=:e",
        u=g["user_id"],
        e=g["evidence_id"],
        s=status,
    )
    sql(
        c,
        "update evaluation_runs set status=:s where user_id=:u and id=:r",
        u=g["user_id"],
        r=g["run_id"],
        s=status,
    )


def test_invalidated_projected_source_does_not_admit_replacement(
    isolated_migrated_database,
):
    db = isolated_migrated_database
    g = graph(db)
    drain(db)
    sub = subject_for(db, g["user_id"])
    with db.engine.begin() as c:
        retire(c, g, "SUPERSEDED")
        run = sql(
            c,
            "insert into evaluation_runs(user_id,response_id,evaluator_type,evaluator_version,rubric_version,result,confidence,feedback,status,supersedes_id) values (:u,:r,'DETERMINISTIC','deterministic-evaluation/v1','rubric-v1','SUPPORTED',.8,'private rubric sentinel','SUCCEEDED',:prior) returning id",
            u=g["user_id"],
            r=g["response_id"],
            prior=g["run_id"],
        ).scalar_one()
        replacement = evidence(c, g, run, evaluation_confidence=0.8)
    client, _ = client_for(db)
    with client:
        h = headers(sub)
        m = client.get("/api/v1/memory/summary", headers=h).json()
        assert m["projection"]["status"] == "PENDING"
        assert m["recognition_evidence"] == []
        assert m["truncated"]["recognition_evidence"] is False
        with db.engine.begin() as c:
            sql(
                c,
                "update jobs set status='FAILED',attempt_count=3 where user_id=:u and status='PENDING'",
                u=g["user_id"],
            )
        failed = client.get("/api/v1/memory/summary", headers=h).json()
        assert (
            failed["projection"]["status"] == "FAILED"
            and failed["recognition_evidence"] == []
        )
        for secret in [
            str(g["user_id"]),
            str(g["evidence_id"]),
            str(replacement),
            "private rubric sentinel",
            "evaluation_confidence",
        ]:
            assert secret not in json.dumps(failed)


@pytest.mark.parametrize("invalid", ["run_status", "result", "version", "confidence"])
def test_current_run_may_only_remove_projected_evidence(
    isolated_migrated_database, invalid
):
    db = isolated_migrated_database
    g = graph(db)
    drain(db)
    changes = {
        "run_status": "status='REVOKED'",
        "result": "result='PARTIAL'",
        "version": "evaluator_version='other/v1'",
        "confidence": "confidence=.7",
    }
    with db.engine.begin() as c:
        # Defensive corruption probe: legal source transitions remain covered
        # by retire/replacement tests; immutable payloads cannot change normally.
        sql(c, "set local session_replication_role='replica'")
        sql(
            c,
            "update evaluation_runs set "
            + changes[invalid]
            + " where user_id=:u and id=:r",
            u=g["user_id"],
            r=g["run_id"],
        )
    client, _ = client_for(db)
    with client:
        r = client.get(
            "/api/v1/memory/summary", headers=headers(subject_for(db, g["user_id"]))
        )
        assert r.status_code == 200, r.text
        assert r.json()["recognition_evidence"] == []


def test_recognition_partial_invalidation_recomputes_subset(isolated_migrated_database):
    db = isolated_migrated_database
    g = graph(db)
    with db.engine.begin() as c:
        response = _insert_response(
            c,
            user_id=g["user_id"],
            entity_id=g["entity_id"],
            objective_id=g["objective_id"],
        )
        ex = c.scalar(
            text(
                "select s.exploration_id from assessment_sessions s join assessment_responses a on a.assessment_session_id=s.id where a.id=:r"
            ),
            {"r": response},
        )
        start(c, g["user_id"], g["entity_id"], ex)
        interaction = sql(
            c,
            "insert into assessment_interactions(user_id,assessment_session_id,objective_id,interaction_type,prompt_definition,rubric_version,sequence) select i.user_id,i.assessment_session_id,i.objective_id,i.interaction_type,i.prompt_definition,i.rubric_version,i.sequence+1 from assessment_interactions i join assessment_responses a on a.interaction_id=i.id and a.user_id=:u where i.user_id=:u and a.id=:r returning id",
            u=g["user_id"],
            r=response,
        ).scalar_one()
        response = sql(
            c,
            "insert into assessment_responses(user_id,assessment_session_id,interaction_id,response_type,response_content,support_used) select user_id,assessment_session_id,:i,response_type,response_content,'SMALL_NUDGE' from assessment_responses where user_id=:u and id=:r returning id",
            u=g["user_id"],
            r=response,
            i=interaction,
        ).scalar_one()
        run = sql(
            c,
            "insert into evaluation_runs(user_id,response_id,evaluator_type,evaluator_version,rubric_version,result,confidence,feedback,status) values (:u,:r,'DETERMINISTIC','deterministic-evaluation/v1','rubric-v1','SUPPORTED',.8,'bounded','SUCCEEDED') returning id",
            u=g["user_id"],
            r=response,
        ).scalar_one()
        g2 = dict(g, response_id=response, run_id=run)
        g2["evidence_id"] = evidence(
            c, g2, run, evaluation_confidence=0.8, support_level="SMALL_NUDGE"
        )
    drain(db)
    client, _ = client_for(db)
    with client:
        h = headers(subject_for(db, g["user_id"]))
        before = client.get("/api/v1/memory/summary", headers=h).json()[
            "recognition_evidence"
        ][0]
        assert before["evidence_count"] == 2
        assert before["support_required"] is True
        with db.engine.begin() as c:
            retire(c, g2)
        after = client.get("/api/v1/memory/summary", headers=h).json()[
            "recognition_evidence"
        ][0]
        assert after["evidence_count"] == 1
        assert after["last_evidence_at"] < before["last_evidence_at"]
        assert after["support_required"] is False


def test_recent_historical_titles_counts_and_ignored_activity(
    isolated_migrated_database,
):
    db = isolated_migrated_database
    g = graph(db, recognition=False)
    drain(db)
    with db.engine.begin() as c:
        for kind, t in [
            ("USER_RETURNED", "2026-02-01"),
            ("USER_RETURNED", "2026-03-01"),
            ("EXPLORATION_PAUSED", "2026-04-01"),
            ("EXPLORATION_RESUMED", "2026-05-01"),
        ]:
            sql(
                c,
                "insert into learning_events(user_id,event_type,entity_id,exploration_id,occurred_at,schema_version,metadata) values (:u,:k,:e,:x,cast(:t as timestamptz),1,'{}')",
                u=g["user_id"],
                e=g["entity_id"],
                x=g["exploration_id"],
                k=kind,
                t=t,
            )
    add_version(db, g, when="2026-01-01T00:00:00Z")
    drain(db)
    client, _ = client_for(db)
    with client:
        r = client.get(
            "/api/v1/memory/summary", headers=headers(subject_for(db, g["user_id"]))
        )
        assert r.status_code == 200, r.text
        recent = r.json()["recently_explored"]
        assert [(x["entity_version"], x["returned_count"]) for x in recent] == [
            (1, 2),
            (2, 0),
        ]
        assert recent[0]["latest_activity_at"] == "2026-03-01T00:00:00Z"
        assert recent[0]["title"] == "Evaluation topic"
        assert recent[0]["started_count"] == 1 and recent[0]["completed_count"] == 0


@pytest.mark.parametrize(
    "corrupt", ["missing_current", "missing_entity", "bad_horizon", "bad_preferences"]
)
def test_integrity_failures_are_sanitized(isolated_migrated_database, corrupt, caplog):
    db = isolated_migrated_database
    with db.engine.begin() as c:
        owner = user(c)
        entity, _ = _insert_entity_objective(c)
        sql(c, "update learning_entities set current_version=1 where id=:e", e=entity)
        sql(
            c,
            "insert into explicit_interest_preferences(user_id,entity_id,preference) values (:u,:e,'MORE')",
            u=owner,
            e=entity,
        )
        if corrupt == "missing_current":
            sql(c, "set local session_replication_role='replica'")
            sql(
                c,
                "update learning_entities set current_version=99 where id=:e",
                e=entity,
            )
        if corrupt == "missing_entity":
            sql(c, "set local session_replication_role='replica'")
            sql(c, "delete from learning_entities where id=:e", e=entity)
        if corrupt == "bad_horizon":
            sql(
                c,
                "update learner_projection_checkpoints set processed_source_sequence=1 where user_id=:u",
                u=owner,
            )
        if corrupt == "bad_preferences":
            sql(
                c,
                "update app_users set onboarding_completed_at=now() where id=:u",
                u=owner,
            )
    client, _ = client_for(db)
    with client:
        r = client.get(
            "/api/v1/memory/summary", headers=headers(subject_for(db, owner))
        )
        assert r.status_code == 503, r.text
        assert r.json()["code"] == "M6_READ_UNAVAILABLE"
        for secret in ["select ", str(owner), "learning_entities", "parameters"]:
            assert secret not in r.text and secret not in caplog.text


def synthetic_world(db, count=705):
    from app.learning.world_projection import (
        node_object,
        region_object,
        world_id,
        world_seed,
    )

    with db.engine.begin() as c:
        owner = user(c)
        entity, _ = _insert_entity_objective(c)
        w = world_id(owner)
        region = region_object(owner)
        sql(
            c,
            "insert into learner_worlds(id,user_id,generation_seed,layout_version,current_revision) values (:w,:u,:s,1,:n)",
            w=w,
            u=owner,
            s=world_seed(w),
            n=count,
        )
        sql(
            c,
            "insert into world_regions(id,user_id,world_id,region_key,logical_x,logical_y,logical_width,logical_height,visual_archetype) values (:id,:u,:w,'discovery',0,0,1,1,'grove')",
            id=region["id"],
            u=owner,
            w=w,
        )
        node = node_object(owner, entity, 1, "SEED", count)
        sql(
            c,
            "insert into world_nodes(id,user_id,world_id,entity_id,entity_version,region_id,logical_x,logical_y,depth,visual_archetype,visual_seed,growth_state,revision) values (:id,:u,:w,:e,1,:r,:x,:y,0,'branching_tree',:seed,'SEED',:n)",
            id=node["id"],
            u=owner,
            w=w,
            e=entity,
            r=node["region_id"],
            x=node["logical_x"],
            y=node["logical_y"],
            seed=node["visual_seed"],
            n=count,
        )
        for revision in range(1, count + 1):
            obj = region if revision == 1 else dict(node, revision=revision)
            kind = (
                "REGION_ADDED"
                if revision == 1
                else "NODE_ADDED"
                if revision == 2
                else "NODE_GROWTH_CHANGED"
            )
            sql(
                c,
                "insert into world_changes(user_id,world_id,revision,change_type,object_type,object_id,payload) values (:u,:w,:n,:k,:t,:id,cast(:p as jsonb))",
                u=owner,
                w=w,
                n=revision,
                k=kind,
                t="REGION" if revision == 1 else "NODE",
                id=obj["id"],
                p=json.dumps({"schema_version": "world-delta/v1", "object": obj}),
            )
    return owner


@pytest.mark.parametrize("hole", [1, 2, 700, 705, "all"])
def test_whole_suffix_gap_requires_resync(isolated_migrated_database, hole):
    db = isolated_migrated_database
    owner = synthetic_world(db)
    with db.engine.begin() as c:
        if hole == "all":
            sql(c, "delete from world_changes where user_id=:u", u=owner)
        else:
            sql(
                c,
                "delete from world_changes where user_id=:u and revision=:n",
                u=owner,
                n=hole,
            )
    client, _ = client_for(db)
    with client:
        r = client.get(
            "/api/v1/world/changes?after_revision=0",
            headers=headers(subject_for(db, owner)),
        )
        assert r.status_code == 409, r.text
        assert set(r.json()) == {
            "type",
            "title",
            "status",
            "code",
            "detail",
            "request_id",
            "details",
        }
        assert r.json()["details"] == {"after_revision": 0, "current_revision": 705}
        assert "changes" not in r.json()


def test_multi_page_continuation_reconstructs_snapshot(isolated_migrated_database):
    db = isolated_migrated_database
    owner = synthetic_world(db)
    client, _ = client_for(db)
    with client:
        h = headers(subject_for(db, owner))
        snapshot = client.get("/api/v1/world", headers=h).json()
        cursor = 0
        objects = {}
        seen = []
        while cursor < snapshot["revision"]:
            r = client.get(f"/api/v1/world/changes?after_revision={cursor}", headers=h)
            assert r.status_code == 200, r.text
            page = r.json()
            assert page["from_revision"] == cursor
            assert page["current_revision"] == 705
            assert page["has_more"] == (page["to_revision"] < 705)
            for change in page["changes"]:
                seen.append(change["revision"])
                objects[change["object_id"]] = change["payload"]["object"]
            cursor = page["to_revision"]
        assert seen == list(range(1, 706))
        assert sorted(objects.values(), key=lambda x: x["id"]) == sorted(
            snapshot["regions"] + snapshot["nodes"], key=lambda x: x["id"]
        )
        with db.engine.begin() as c:
            sql(
                c,
                "delete from world_changes where user_id=:u and revision<=500",
                u=owner,
            )
        assert (
            client.get(
                "/api/v1/world/changes?after_revision=500", headers=h
            ).status_code
            == 200
        )
        assert (
            client.get("/api/v1/world/changes?after_revision=705", headers=h).json()[
                "changes"
            ]
            == []
        )


def owned_state(db, owner):
    tables = [
        "learning_events",
        "projection_inputs",
        "projection_source_heads",
        "learner_projection_checkpoints",
        "jobs",
        "learner_objective_state",
        "state_evidence_links",
        "learner_worlds",
        "world_regions",
        "world_nodes",
        "world_changes",
        "learner_preferences",
        "explicit_interest_preferences",
        "explorations",
    ]
    with db.engine.connect() as c:
        return {
            table: c.scalar(
                text(
                    f"select coalesce(jsonb_agg(to_jsonb(t) order by to_jsonb(t)::text),'[]'::jsonb) from {table} t where user_id=:u"
                ),
                {"u": owner},
            )
            for table in tables
        }


def test_owned_read_privacy_and_no_side_effects(isolated_migrated_database, caplog):
    db = isolated_migrated_database
    a = graph(db)
    b = graph(db)
    drain(db)
    suba = subject_for(db, a["user_id"])
    subb = subject_for(db, b["user_id"])
    client, _ = client_for(db)
    with client:
        before = owned_state(db, a["user_id"])
        for path in [
            "/api/v1/memory/summary",
            "/api/v1/world",
            "/api/v1/world/changes?after_revision=0",
        ]:
            ra = client.get(path, headers=headers(suba))
            rb = client.get(path, headers=headers(subb))
            assert ra.status_code == rb.status_code == 200
            assert (
                str(b["entity_id"]) not in ra.text
                and str(a["entity_id"]) not in rb.text
            )
            assert str(a["user_id"]) not in ra.text
            assert client.get(path).status_code == 401
        assert owned_state(db, a["user_id"]) == before
        assert str(a["user_id"]) not in caplog.text


@pytest.mark.parametrize(
    "route", ["/api/v1/world", "/api/v1/world/changes?after_revision=0&limit=1"]
)
def test_concurrent_publisher_cannot_mix_read_snapshots(
    isolated_migrated_database, route
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    db = isolated_migrated_database
    g = graph(db)
    drain(db)
    sub = subject_for(db, g["user_id"])
    client, engine = client_for(db)
    entered = Event()
    released = Event()

    @event.listens_for(engine.sync_engine, "after_cursor_execute")
    def barrier(conn, cursor, statement, params, context, many):
        if (
            "select id,current_revision,layout_version,generation_seed from learner_worlds"
            in statement
        ):
            entered.set()
            assert released.wait(10), "publisher barrier timed out"

    with client, ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(client.get, route, headers=headers(sub))
        assert entered.wait(10)
        try:
            with db.engine.begin() as c:
                retire(c, g)
            assert drain(db) == 1
        finally:
            released.set()
        old = pending.result(timeout=10)
        assert old.status_code == 200, old.text
        if route == "/api/v1/world":
            assert (
                old.json()["revision"] == 2
                and old.json()["nodes"][0]["growth_state"] == "YOUNG"
            )
        else:
            assert (
                old.json()["current_revision"] == 2 and old.json()["to_revision"] == 1
            )
        event.remove(engine.sync_engine, "after_cursor_execute", barrier)
        new = client.get("/api/v1/world", headers=headers(sub)).json()
        assert new["revision"] == 3 and new["nodes"][0]["growth_state"] == "SEED"


def near_caps(db, count=11):
    with db.engine.begin() as c:
        owner = user(c)
        graphs = []
        for index in range(count):
            entity, objective = _insert_entity_objective(c)
            response = _insert_response(
                c, user_id=owner, entity_id=entity, objective_id=objective
            )
            ex = c.scalar(
                text(
                    "select s.exploration_id from assessment_sessions s join assessment_responses a on a.assessment_session_id=s.id where a.id=:r"
                ),
                {"r": response},
            )
            start(c, owner, entity, ex)
            run = sql(
                c,
                "insert into evaluation_runs(user_id,response_id,evaluator_type,evaluator_version,rubric_version,result,confidence,feedback,status) values (:u,:r,'DETERMINISTIC','deterministic-evaluation/v1','rubric-v1','SUPPORTED',.8,'bounded','SUCCEEDED') returning id",
                u=owner,
                r=response,
            ).scalar_one()
            g = {
                "user_id": owner,
                "entity_id": entity,
                "objective_id": objective,
                "response_id": response,
                "run_id": run,
                "exploration_id": ex,
            }
            g["evidence_id"] = evidence(c, g, run, evaluation_confidence=0.8)
            graphs.append(g)
        for _ in range(21):
            entity, _ = _insert_entity_objective(c)
            sql(
                c,
                "update learning_entities set current_version=1 where id=:e",
                e=entity,
            )
            sql(
                c,
                "insert into explicit_interest_preferences(user_id,entity_id,preference,updated_at) values (:u,:e,'MORE','2026-01-01')",
                u=owner,
                e=entity,
            )
    drain(db)
    return owner, graphs


def test_memory_filtered_boundaries_and_deterministic_ties(isolated_migrated_database):
    db = isolated_migrated_database
    owner, graphs = near_caps(db)
    client, _ = client_for(db)
    with client:
        h = headers(subject_for(db, owner))
        r = client.get("/api/v1/memory/summary", headers=h)
        assert r.status_code == 200, r.text
        m = r.json()
        assert len(m["recently_explored"]) == len(m["recognition_evidence"]) == 10
        assert m["truncated"] == {
            "explicit_interests": True,
            "recently_explored": True,
            "recognition_evidence": True,
        }
        assert [x["entity_id"] for x in m["recently_explored"]] == sorted(
            str(g["entity_id"]) for g in graphs
        )[:10]
        # All evidence rows were inserted in the same transaction, so source
        # times tie and objective UUID decides ordering.
        assert [x["objective_id"] for x in m["recognition_evidence"]] == sorted(
            str(g["objective_id"]) for g in graphs
        )[:10]
        with db.engine.begin() as c:
            retire(c, graphs[0])
            sql(
                c,
                "delete from explicit_interest_preferences where user_id=:u and entity_id=(select max(entity_id::text)::uuid from explicit_interest_preferences where user_id=:u)",
                u=owner,
            )
        m = client.get("/api/v1/memory/summary", headers=h).json()
        assert (
            len(m["recognition_evidence"]) == 10
            and m["truncated"]["recognition_evidence"] is False
        )
        assert (
            len(m["explicit_interests"]) == 20
            and m["truncated"]["explicit_interests"] is False
        )
        assert m["projection"]["status"] == "PENDING"


def test_explicit_display_title_bound_and_immediate_choice(isolated_migrated_database):
    db = isolated_migrated_database
    with db.engine.begin() as c:
        owner = user(c)
        entity, _ = _insert_entity_objective(c)
        sql(c, "update learning_entities set current_version=1 where id=:e", e=entity)
        sql(
            c,
            "update learning_entity_versions set title=:t where entity_id=:e and version=1",
            t="😀" * 600,
            e=entity,
        )
    client, _ = client_for(db)
    with client:
        h = headers(subject_for(db, owner))
        put = client.put(
            f"/api/v1/memory/interests/{entity}",
            headers=h,
            json={"preference": "PAUSED", "base_version": 0},
        )
        assert put.status_code == 200, put.text
        m = client.get("/api/v1/memory/summary", headers=h).json()
        assert m["projection"]["status"] == "PENDING"
        item = m["explicit_interests"][0]
        assert item["title"] == "😀" * 512 and item["preference"] == "PAUSED"
        with db.engine.begin() as c:
            sql(c, "update learning_entities set status='DRAFT' where id=:e", e=entity)
        m = client.get("/api/v1/memory/summary", headers=h).json()
        assert m["explicit_interests"][0]["title"] is None
        assert m["explicit_interests"][0]["preference"] == "PAUSED"
        assert m["explicit_interests"][0]["version"] == 1
        with db.engine.connect() as c:
            assert (
                len(
                    c.scalar(
                        text(
                            "select title from learning_entity_versions where entity_id=:e"
                        ),
                        {"e": entity},
                    )
                )
                == 600
            )


def test_recent_allowed_times_and_private_sentinels(isolated_migrated_database, caplog):
    db = isolated_migrated_database
    g = graph(db)
    drain(db)
    sub = subject_for(db, g["user_id"])
    with db.engine.begin() as c:
        sess = c.scalar(
            text("select assessment_session_id from assessment_responses where id=:r"),
            {"r": g["response_id"]},
        )
        reflection = sql(
            c,
            "insert into reflections(user_id,entity_id,exploration_id,text) values (:u,:e,:x,'PRIVATE_REFLECTION_SENTINEL') returning id",
            u=g["user_id"],
            e=g["entity_id"],
            x=g["exploration_id"],
        ).scalar_one()
        for kind, t, meta in [
            ("REFLECTION_SUBMITTED", "2026-02-01", {"reflection_id": str(reflection)}),
            ("REFLECTION_SUBMITTED", "2026-03-01", {"reflection_id": str(reflection)}),
            ("REFLECTION_UPDATED", "2026-04-01", {"reflection_id": str(reflection)}),
            ("HINT_REQUESTED", "2026-05-01", {}),
            (
                "ASSESSMENT_EVALUATED",
                "2026-06-01",
                {
                    "response_id": str(g["response_id"]),
                    "evaluation_run_id": str(g["run_id"]),
                    "private": "PRIVATE_METADATA_SENTINEL",
                },
            ),
            ("EXPLORATION_WORK_PREPARED", "2026-07-01", {}),
        ]:
            sql(
                c,
                "insert into learning_events(user_id,event_type,entity_id,exploration_id,assessment_session_id,occurred_at,schema_version,metadata) values (:u,:k,:e,:x,:s,cast(:t as timestamptz),1,cast(:m as jsonb))",
                u=g["user_id"],
                k=kind,
                e=g["entity_id"],
                x=g["exploration_id"],
                s=sess if kind in ("HINT_REQUESTED", "ASSESSMENT_EVALUATED") else None,
                t=t,
                m=json.dumps(meta),
            )
    drain(db)
    client, _ = client_for(db)
    with client:
        h = headers(sub)
        r = client.get("/api/v1/memory/summary", headers=h)
        assert r.status_code == 200, r.text
        assert (
            r.json()["recently_explored"][0]["latest_activity_at"]
            == "2026-02-01T00:00:00Z"
        )
        for secret in [
            "PRIVATE_REFLECTION_SENTINEL",
            "PRIVATE_METADATA_SENTINEL",
            "A historical response",
            "Explain it",
            str(g["user_id"]),
        ]:
            assert secret not in r.text and secret not in caplog.text
        with db.engine.begin() as c:
            sql(
                c,
                "insert into learning_events(user_id,event_type,entity_id,exploration_id,occurred_at,schema_version,metadata) values (:u,'EXPLORATION_COMPLETED',:e,:x,'2026-08-01',1,'{}')",
                u=g["user_id"],
                e=g["entity_id"],
                x=g["exploration_id"],
            )
        drain(db)
        item = client.get("/api/v1/memory/summary", headers=h).json()[
            "recently_explored"
        ][0]
        assert (
            item["latest_activity_at"] == "2026-08-01T00:00:00Z"
            and item["completed_count"] == 1
        )


def test_performance_characterization(isolated_migrated_database):
    from time import perf_counter

    db = isolated_migrated_database
    with db.engine.begin() as c:
        empty = user(c)
    populated, _ = near_caps(db)
    large = synthetic_world(db)
    subjects = {u: subject_for(db, u) for u in [empty, populated, large]}
    client, engine = client_for(db)
    statements = []

    @event.listens_for(engine.sync_engine, "after_cursor_execute")
    def count(conn, cursor, statement, params, context, many):
        statements.append(statement)

    results = []
    with client:
        for name, owner, path in [
            ("memory_empty", empty, "/api/v1/memory/summary"),
            ("memory_near_caps", populated, "/api/v1/memory/summary"),
            ("world_empty", empty, "/api/v1/world"),
            ("world_populated", populated, "/api/v1/world"),
            ("delta_one_page", populated, "/api/v1/world/changes?after_revision=0"),
            ("delta_large_suffix", large, "/api/v1/world/changes?after_revision=0"),
        ]:
            statements.clear()
            started = perf_counter()
            r = client.get(path, headers=headers(subjects[owner]))
            elapsed = (perf_counter() - started) * 1000
            assert r.status_code == 200, r.text
            body = r.json()
            rows = sum(
                len(body.get(k, []))
                for k in [
                    "explicit_interests",
                    "recently_explored",
                    "recognition_evidence",
                    "regions",
                    "nodes",
                    "changes",
                ]
            )
            results.append(
                {
                    "case": name,
                    "queries": len(statements),
                    "public_rows": rows,
                    "elapsed_ms": round(elapsed, 2),
                }
            )
    print("M6_PERFORMANCE " + json.dumps(results))


def test_profile_physical_revision_zero_and_three(isolated_migrated_database):
    from app.learning.world_projection import world_id, world_seed

    db = isolated_migrated_database
    with db.engine.begin() as c:
        owner = user(c)
        w = world_id(owner)
        sql(
            c,
            "insert into learner_worlds(id,user_id,generation_seed,layout_version,current_revision) values (:w,:u,:s,1,0)",
            w=w,
            u=owner,
            s=world_seed(w),
        )
    client, _ = client_for(db)
    with client:
        h = headers(subject_for(db, owner))
        assert client.get("/api/v1/me", headers=h).json()["world_revision"] == 0
        assert client.get("/api/v1/world", headers=h).json()["revision"] == 0
        assert (
            client.get("/api/v1/world/changes?after_revision=0", headers=h).json()[
                "changes"
            ]
            == []
        )
        with db.engine.begin() as c:
            sql(
                c,
                "update learner_worlds set current_revision=3 where user_id=:u",
                u=owner,
            )
        assert client.get("/api/v1/me", headers=h).json()["world_revision"] == 3


def test_storage_error_does_not_expose_sql_or_parameters(
    isolated_migrated_database, caplog
):
    from sqlalchemy.exc import OperationalError

    db = isolated_migrated_database
    with db.engine.begin() as c:
        owner = user(c)
    client, engine = client_for(db)

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def fail(conn, cursor, statement, params, context, many):
        if "from learner_preferences where user_id=" in statement:
            raise OperationalError(
                "PRIVATE_SQL_SENTINEL",
                {"token": "PRIVATE_PARAMETER_SENTINEL"},
                Exception("PRIVATE_DRIVER_SENTINEL"),
            )

    with client:
        r = client.get(
            "/api/v1/memory/summary", headers=headers(subject_for(db, owner))
        )
        assert r.status_code == 503
        for secret in [
            "PRIVATE_SQL_SENTINEL",
            "PRIVATE_PARAMETER_SENTINEL",
            "PRIVATE_DRIVER_SENTINEL",
            str(owner),
        ]:
            assert secret not in r.text and secret not in caplog.text


def test_absent_checkpoint_stays_empty_without_repair(isolated_migrated_database):
    db = isolated_migrated_database
    with db.engine.begin() as c:
        owner = user(c)
        sql(c, "delete from learner_projection_checkpoints where user_id=:u", u=owner)
    sub = subject_for(db, owner)
    client, _ = client_for(db)
    with client:
        before = owned_state(db, owner)
        h = headers(sub)
        m = client.get("/api/v1/memory/summary", headers=h).json()
        assert m["projection"] == {
            "model_version": "learner-projection/v1",
            "source_sequence": 0,
            "source_head_sequence": 0,
            "status": "CURRENT",
        }
        client.get("/api/v1/world", headers=h).raise_for_status()
        client.get(
            "/api/v1/world/changes?after_revision=0", headers=h
        ).raise_for_status()
        assert owned_state(db, owner) == before


def test_current_preferences_immediate_during_lag(isolated_migrated_database):
    db = isolated_migrated_database
    with db.engine.begin() as c:
        owner = user(c)
        onboard(c, owner)
        sql(
            c, "update app_users set onboarding_completed_at=now() where id=:u", u=owner
        )
    # The first transaction freezes onboarding's original version before the
    # current authoritative preference row advances independently.
    with db.engine.begin() as c:
        sql(
            c,
            "update learner_preferences set adventure_preference='FAMILIAR',preferred_effort='5_10_MIN',support_style='GUIDED',practical_opt_in=true,version=2 where user_id=:u",
            u=owner,
        )
    client, _ = client_for(db)
    with client:
        m = client.get(
            "/api/v1/memory/summary", headers=headers(subject_for(db, owner))
        ).json()
        assert m["projection"]["status"] == "PENDING"
        assert m["learning_preferences"] == {
            "adventure_preference": "FAMILIAR",
            "preferred_effort": "5_10_MIN",
            "support_style": "GUIDED",
            "practical_opt_in": True,
            "version": 2,
        }


def test_snapshot_and_deltas_validate_against_frozen_schema(isolated_migrated_database):
    from pathlib import Path

    from jsonschema import Draft202012Validator, FormatChecker

    db = isolated_migrated_database
    g = graph(db)
    drain(db)
    schema = json.loads(
        (Path(__file__).parents[2] / "docs/api/schemas/m6-v1.schema.json").read_text()
    )
    client, _ = client_for(db)
    with client:
        h = headers(subject_for(db, g["user_id"]))
        for path, definition in [
            ("/api/v1/memory/summary", "memorySummary"),
            ("/api/v1/world", "worldSnapshot"),
            ("/api/v1/world/changes?after_revision=0", "worldDeltaPage"),
            (
                "/api/v1/world/changes?after_revision=9223372036854775807",
                "worldResyncRequired",
            ),
        ]:
            r = client.get(path, headers=h)
            Draft202012Validator(
                {"$ref": "#/$defs/" + definition, "$defs": schema["$defs"]},
                format_checker=FormatChecker(),
            ).validate(r.json())
