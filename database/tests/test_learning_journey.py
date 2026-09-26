"""M5 journeys require no private learner SQL setup and use the actual worker role."""

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.learning.content import load_package
from app.learning.provision_content import provision
from app.learning.worker import run_once
from test_learning_content_provision import review
from test_learning_entry_api import client_for, headers
from test_evaluation_worker import with_worker


@pytest.fixture
def pilot(isolated_migrated_database, tmp_path, monkeypatch):
    db = isolated_migrated_database

    async def no_provider(*_args, **_kwargs):
        raise AssertionError("Learning pilot requires no provider call")

    from app.integrations.voyage import VoyageQueryEmbedder

    monkeypatch.setattr(VoyageQueryEmbedder, "embed_queries", no_provider)
    approval = review()
    path = tmp_path / "review.json"
    path.write_text(json.dumps(approval))
    monkeypatch.setenv("EMBYR_CONTENT_REVIEW_ATTESTATION", str(path))
    monkeypatch.setenv("EMBYR_CONTENT_ALLOW_TEST_ATTESTATION", "1")
    with db.engine.begin() as c:
        provision(c, approval, allow_test=True)
    return db


def enter(client, subject):
    bootstrap = client.post("/api/v1/session/bootstrap", headers=headers(subject))
    assert bootstrap.status_code == 200, bootstrap.text
    user = bootstrap.json()["id"]
    catalog = client.get("/api/v1/catalog/starter-interests", headers=headers(subject))
    assert catalog.status_code == 200 and len(catalog.json()["items"]) == 2
    selected = catalog.json()["items"][0]["id"]
    onboarding = client.post(
        "/api/v1/me/onboarding/complete",
        json={
            "motivations": ["BECOME_MORE_CURIOUS"],
            "starter_interest_entity_ids": [selected],
            "adventure_preference": "BALANCED",
            "preferred_effort": "15_20_MIN",
            "support_style": "SMALL_HINT",
            "practical_opt_in": False,
        },
        headers=headers(subject, "onboard"),
    )
    assert onboarding.status_code == 200, onboarding.text
    next_ = client.post(
        "/api/v1/recommendations/next",
        json={"mode": "EXPLORE"},
        headers=headers(subject, "next"),
    )
    assert next_.status_code == 200 and next_.json().get("id"), next_.text
    accept = client.post(
        "/api/v1/recommendations/" + next_.json()["id"] + "/decision",
        json={"decision": "ACCEPT"},
        headers=headers(subject, "accept"),
    )
    assert accept.status_code == 200, accept.text
    recovered = client.get(
        "/api/v1/explorations/" + accept.json()["id"], headers=headers(subject)
    )
    assert recovered.status_code == 200, recovered.text
    return user, recovered.json()


def test_explicit_interest_addressed_update_is_owned_and_versioned(pilot):
    subject, other = str(uuid4()), str(uuid4())
    with client_for(pilot.url) as client:
        user, _ = enter(client, subject)
        other_user, _ = enter(client, other)
        starters = client.get(
            "/api/v1/catalog/starter-interests", headers=headers(subject)
        ).json()["items"]
        entity = starters[1]["id"]
        path = "/api/v1/memory/interests/" + entity
        first = client.put(
            path,
            json={"base_version": 0, "preference": "MORE"},
            headers=headers(subject),
        )
        assert first.status_code == 200 and first.json()["version"] == 1, first.text
        updated = client.put(
            path,
            json={"base_version": 1, "preference": "PAUSED"},
            headers=headers(subject),
        )
        assert updated.status_code == 200 and updated.json()["version"] == 2
        stale = client.put(
            path,
            json={"base_version": 1, "preference": "LESS"},
            headers=headers(subject),
        )
        assert stale.status_code == 409
        independent = client.put(
            path,
            json={"base_version": 0, "preference": "LESS"},
            headers=headers(other),
        )
        assert independent.status_code == 200 and independent.json()["version"] == 1
        with pilot.engine.connect() as c:
            rows = c.execute(
                text(
                    "select user_id,preference,version from explicit_interest_preferences "
                    "where entity_id=:entity"
                ),
                {"entity": entity},
            ).all()
            assert {str(r.user_id): (r.preference, r.version) for r in rows} == {
                user: ("PAUSED", 2),
                other_user: ("LESS", 1),
            }
            assert (
                c.scalar(
                    text(
                        "select count(*) from learning_events where user_id=:user "
                        "and entity_id=:entity and event_type='EXPLICIT_INTEREST_CHANGED'"
                    ),
                    {"user": user, "entity": entity},
                )
                == 2
            )


@pytest.mark.parametrize("first", ["answer", "completion"])
def test_answer_and_completion_serialize_without_losing_response(
    pilot, monkeypatch, first
):
    import app.api.learning as learning_api
    import app.api.assessments as assessment_api
    from app.db.models.exploration import Exploration

    subject = str(uuid4())
    winner_locked, loser_ready = threading.Event(), threading.Event()
    original = learning_api.owned

    def hook(command):
        async def owned_with_barrier(session, model, user, resource_id, *, lock=False):
            if model is Exploration and lock and command != first:
                loser_ready.set()
            row = await original(session, model, user, resource_id, lock=lock)
            if model is Exploration and lock and command == first:
                winner_locked.set()
                assert await asyncio.to_thread(loser_ready.wait, 5)
            return row

        return owned_with_barrier

    with client_for(pilot.url) as client, ThreadPoolExecutor(max_workers=2) as pool:
        user, exploration = enter(client, subject)
        path = "/api/v1/explorations/" + exploration["id"]
        client.post(path + "/delivery", json={}, headers=headers(subject, "work"))
        check = client.post(
            path + "/assessment-sessions",
            json={"confidence_before": "FUZZY"},
            headers=headers(subject, "check"),
        )
        assert check.status_code == 200, check.text
        sid, iid = check.json()["id"], check.json()["interaction"]["id"]
        monkeypatch.setattr(learning_api, "owned", hook("completion"))
        monkeypatch.setattr(assessment_api, "owned", hook("answer"))

        def request(command):
            if command == "completion":
                return client.post(
                    path + "/completion",
                    json={"base_version": 2},
                    headers=headers(subject, "finish-race"),
                )
            return client.post(
                "/api/v1/assessment-sessions/" + sid + "/responses",
                json={
                    "interaction_id": iid,
                    "response_type": "SINGLE_CHOICE",
                    "content": {"option_id": "not-sure"},
                },
                headers=headers(subject, "answer-race"),
            )

        winning = pool.submit(request, first)
        assert winner_locked.wait(5)
        losing = pool.submit(request, "completion" if first == "answer" else "answer")
        results = {
            first: winning.result(10),
            "completion" if first == "answer" else "answer": losing.result(10),
        }
        assert results["completion"].status_code == 200, results["completion"].text
        assert results["answer"].status_code == (202 if first == "answer" else 409)
        with pilot.engine.connect() as c:
            assert (
                c.scalar(
                    text("select status from explorations where id=:id"),
                    {"id": exploration["id"]},
                )
                == "COMPLETED"
            )
            assert c.scalar(
                text("select status from assessment_sessions where id=:id"), {"id": sid}
            ) == ("WAITING_FOR_EVALUATION" if first == "answer" else "ABANDONED")
            assert c.scalar(
                text(
                    "select count(*) from assessment_responses r "
                    "join assessment_interactions i on i.id=r.interaction_id "
                    "where i.assessment_session_id=:id"
                ),
                {"id": sid},
            ) == (1 if first == "answer" else 0)
        if first == "answer":

            async def execute(factory):
                assert await run_once(factory)

            asyncio.run(with_worker(pilot, execute))
            feedback = client.get(
                "/api/v1/assessment-responses/"
                + results["answer"].json()["response_id"],
                headers=headers(subject),
            )
            assert feedback.json()["evaluation_status"] == "SUCCEEDED"
            assert feedback.json()["result"] == "UNCERTAIN"


@pytest.mark.parametrize("result", ["SUPPORTED", "INSUFFICIENT_EVIDENCE", "UNCERTAIN"])
def test_new_learner_assessed_loop_and_frozen_revisit(pilot, result, caplog):
    db = pilot
    subject = str(uuid4())
    with client_for(db.url) as client:
        user, exploration = enter(client, subject)
        path = "/api/v1/explorations/" + exploration["id"]
        work = client.post(
            path + "/delivery", json={}, headers=headers(subject, "work")
        )
        assert work.status_code == 200, work.text
        definition = next(
            d
            for d in load_package()["definitions"]
            if d["entity_id"] == exploration["entity_id"]
        )
        option = next(
            k
            for k, v in definition["assessment"]["option_results"].items()
            if v["result"] == result
        )
        check = client.post(
            path + "/assessment-sessions",
            json={"confidence_before": "FUZZY"},
            headers=headers(subject, "check"),
        )
        assert check.status_code == 200, check.text
        sid = check.json()["id"]
        iid = check.json()["interaction"]["id"]
        sp = "/api/v1/assessment-sessions/" + sid
        for level in ("SMALL_NUDGE", "STRONG_HINT", "MISSING_CONCEPT", "EXPLANATION"):
            hint = client.post(
                sp + "/support-requests",
                json={"interaction_id": iid, "level": level},
                headers=headers(subject, level),
            )
            assert hint.status_code == 200, hint.text
            assert "option_results" not in str(hint.json())
        answer_body = {
            "interaction_id": iid,
            "response_type": "SINGLE_CHOICE",
            "content": {"option_id": option},
        }
        ack = client.post(
            sp + "/responses", json=answer_body, headers=headers(subject, "answer")
        )
        assert ack.status_code == 202, ack.text

        async def execute(factory):
            assert await run_once(factory)
            assert await run_once(factory) is False

        asyncio.run(with_worker(db, execute))
        feedback = client.get(
            "/api/v1/assessment-responses/" + ack.json()["response_id"],
            headers=headers(subject),
        )
        assert feedback.status_code == 200, feedback.text
        assert feedback.json()["evaluation_status"] == "SUCCEEDED"
        assert feedback.json()["result"] == result
        assert feedback.json()["confidence"] == (0 if result == "UNCERTAIN" else 1)
        assert feedback.json()["session_status"] == "COMPLETED"
        assert (
            client.post(
                sp + "/responses", json=answer_body, headers=headers(subject, "answer")
            ).json()
            == ack.json()
        )
        reflected = client.post(
            path + "/reflections",
            json={"text": "SECRET_REFLECTION"},
            headers=headers(subject, "reflect"),
        )
        assert reflected.status_code == 200, reflected.text
        edited = client.patch(
            "/api/v1/reflections/" + reflected.json()["id"],
            json={"base_version": 1, "text": "SECRET_EDIT"},
            headers=headers(subject),
        )
        assert edited.status_code == 200, edited.text
        current = client.get(path, headers=headers(subject)).json()
        done = client.post(
            path + "/completion",
            json={"base_version": current["version"]},
            headers=headers(subject, "done"),
        )
        assert (
            done.status_code == 200 and done.json()["status"] == "COMPLETED"
        ), done.text
        again = client.post(
            "/api/v1/recommendations/next",
            json={"mode": "REVISIT"},
            headers=headers(subject, "revisit"),
        )
        assert (
            again.status_code == 200
            and again.json()["entity"]["id"] == exploration["entity_id"]
        ), again.text
        revisit = client.post(
            "/api/v1/recommendations/" + again.json()["id"] + "/decision",
            json={"decision": "ACCEPT"},
            headers=headers(subject, "revisit-accept"),
        )
        assert revisit.status_code == 200 and revisit.json()["id"] != exploration["id"]
        assert revisit.json()["learning_intent"] == "RETENTION_REVISIT"
        with db.engine.connect() as c:
            evidence = c.execute(
                text(
                    "select evidence_type,evidence_strength,support_level from learning_evidence where user_id=:user"
                ),
                {"user": user},
            ).all()
            assert len(evidence) == (1 if result == "SUPPORTED" else 0)
            if evidence:
                assert tuple(evidence[0]) == ("RECOGNITION", "WEAK", "EXPLANATION")
            for table in (
                "learner_interest_state",
                "learner_objective_state",
                "learner_retention_state",
                "learner_confidence_state",
                "learner_challenge_state",
                "learner_worlds",
                "curiosity_stories",
            ):
                assert (
                    c.scalar(
                        text(f"select count(*) from {table} where user_id=:user"),
                        {"user": user},
                    )
                    == 0
                )
            events = (
                c.execute(
                    text("select metadata from learning_events where user_id=:user"),
                    {"user": user},
                )
                .scalars()
                .all()
            )
            jobs = (
                c.execute(
                    text("select payload from jobs where user_id=:user"), {"user": user}
                )
                .scalars()
                .all()
            )
            serialized = json.dumps(events + jobs)
            assert "SECRET_" not in serialized and option not in serialized
        assert "SECRET_" not in caplog.text


def test_started_unanswered_check_abandoned_on_learner_completion(pilot):
    subject = str(uuid4())
    with client_for(pilot.url) as client:
        _, exploration = enter(client, subject)
        path = "/api/v1/explorations/" + exploration["id"]
        assert (
            client.post(
                path + "/delivery", json={}, headers=headers(subject, "work")
            ).status_code
            == 200
        )
        check = client.post(
            path + "/assessment-sessions",
            json={"confidence_before": "MAIN_IDEA"},
            headers=headers(subject, "check"),
        )
        sid = check.json()["id"]
        done = client.post(
            path + "/completion",
            json={"base_version": 2},
            headers=headers(subject, "done"),
        )
        assert done.status_code == 200, done.text
        session = client.get(
            "/api/v1/assessment-sessions/" + sid, headers=headers(subject)
        ).json()
        assert session["status"] == "ABANDONED" and session["response_id"] is None
        answer = client.post(
            "/api/v1/assessment-sessions/" + sid + "/responses",
            json={
                "interaction_id": session["interaction"]["id"],
                "response_type": "SINGLE_CHOICE",
                "content": {"option_id": "not-sure"},
            },
            headers=headers(subject, "answer"),
        )
        assert answer.status_code == 409


def test_answer_event_failure_is_safe_and_rolls_back_command(pilot, caplog):
    subject = str(uuid4())
    with client_for(pilot.url) as client:
        user, exploration = enter(client, subject)
        path = "/api/v1/explorations/" + exploration["id"]
        client.post(path + "/delivery", json={}, headers=headers(subject, "work"))
        check = client.post(
            path + "/assessment-sessions",
            json={"confidence_before": "FUZZY"},
            headers=headers(subject, "check"),
        ).json()
        body = {
            "interaction_id": check["interaction"]["id"],
            "response_type": "SINGLE_CHOICE",
            "content": {"option_id": "not-sure"},
        }
        with pilot.engine.begin() as c:
            c.execute(
                text(
                    "create function reject_answer_event() returns trigger language plpgsql as $$ begin if new.event_type='ASSESSMENT_RESPONSE_SUBMITTED' then raise exception 'injected'; end if; return new; end $$"
                )
            )
            c.execute(
                text(
                    "create trigger reject_answer_event before insert on learning_events for each row execute function reject_answer_event()"
                )
            )
        response = client.post(
            "/api/v1/assessment-sessions/" + check["id"] + "/responses",
            json=body,
            headers=headers(subject, "answer"),
        )
        assert (
            response.status_code == 503
            and response.json()["code"] == "LEARNING_STORAGE_UNAVAILABLE"
        ), response.text
        with pilot.engine.begin() as c:
            for table in ("assessment_responses", "evaluation_runs", "jobs"):
                assert (
                    c.scalar(
                        text(f"select count(*) from {table} where user_id=:user"),
                        {"user": user},
                    )
                    == 0
                )
            assert (
                c.scalar(
                    text(
                        "select count(*) from idempotency_records where user_id=:user and idempotency_key='answer'"
                    ),
                    {"user": user},
                )
                == 0
            )
            assert (
                c.scalar(
                    text("select status from assessment_sessions where id=:id"),
                    {"id": check["id"]},
                )
                == "ACTIVE"
            )
            c.execute(text("drop trigger reject_answer_event on learning_events"))
        retry = client.post(
            "/api/v1/assessment-sessions/" + check["id"] + "/responses",
            json=body,
            headers=headers(subject, "answer"),
        )
        assert retry.status_code == 202, retry.text
        assert "option_id" not in caplog.text and "not-sure" not in caplog.text


def test_maintenance_deletes_delivered_content_and_pending_worker_job(pilot):
    subject = str(uuid4())
    with client_for(pilot.url) as client:
        user, exploration = enter(client, subject)
        path = "/api/v1/explorations/" + exploration["id"]
        client.post(path + "/delivery", json={}, headers=headers(subject, "work"))
        check = client.post(
            path + "/assessment-sessions",
            json={"confidence_before": "FUZZY"},
            headers=headers(subject, "check"),
        ).json()
        response = client.post(
            "/api/v1/assessment-sessions/" + check["id"] + "/responses",
            json={
                "interaction_id": check["interaction"]["id"],
                "response_type": "SINGLE_CHOICE",
                "content": {"option_id": "not-sure"},
            },
            headers=headers(subject, "answer"),
        )
        assert response.status_code == 202, response.text
        with pilot.engine.begin() as c:
            c.execute(text("set local role app_maintenance"))
            c.execute(
                text("select public.maintenance_delete_account(:user)"), {"user": user}
            )
        with pilot.engine.connect() as c:
            for table in (
                "explorations",
                "assessment_sessions",
                "assessment_interactions",
                "assessment_responses",
                "evaluation_runs",
                "jobs",
                "learning_events",
                "idempotency_records",
            ):
                assert (
                    c.scalar(
                        text(f"select count(*) from {table} where user_id=:user"),
                        {"user": user},
                    )
                    == 0
                )
            assert c.scalar(text("select count(*) from learning_entities")) == 3

        async def empty(factory):
            assert await run_once(factory) is False

        asyncio.run(with_worker(pilot, empty))
        assert client.get(path, headers=headers(subject)).status_code == 401


def test_lost_commit_acknowledgment_replays_durable_answer(pilot, monkeypatch, caplog):
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.exc import OperationalError

    subject = str(uuid4())
    with client_for(pilot.url) as client:
        user, exploration = enter(client, subject)
        path = "/api/v1/explorations/" + exploration["id"]
        client.post(path + "/delivery", json={}, headers=headers(subject, "work"))
        check = client.post(
            path + "/assessment-sessions",
            json={"confidence_before": "FUZZY"},
            headers=headers(subject, "check"),
        ).json()
        body = {
            "interaction_id": check["interaction"]["id"],
            "response_type": "SINGLE_CHOICE",
            "content": {"option_id": "not-sure"},
        }
        commit = AsyncSession.commit
        injected = [False]

        async def lose_ack(session):
            await commit(session)
            if not injected[0] and "learning_command_started" in session.info:
                injected[0] = True
                raise OperationalError(
                    "commit acknowledgment lost",
                    {"text": "SECRET_SQL_PARAMETER"},
                    Exception("private diagnostic"),
                )

        monkeypatch.setattr(AsyncSession, "commit", lose_ack)
        response = client.post(
            "/api/v1/assessment-sessions/" + check["id"] + "/responses",
            json=body,
            headers=headers(subject, "answer"),
        )
        assert (
            response.status_code == 503
            and response.json()["code"] == "LEARNING_STORAGE_UNAVAILABLE"
        ), response.text
        retry = client.post(
            "/api/v1/assessment-sessions/" + check["id"] + "/responses",
            json=body,
            headers=headers(subject, "answer"),
        )
        assert retry.status_code == 202, retry.text
        with pilot.engine.connect() as c:
            for table in ("assessment_responses", "evaluation_runs", "jobs"):
                assert (
                    c.scalar(
                        text(f"select count(*) from {table} where user_id=:user"),
                        {"user": user},
                    )
                    == 1
                )
            assert (
                c.scalar(
                    text(
                        "select count(*) from learning_events where user_id=:user and event_type='ASSESSMENT_RESPONSE_SUBMITTED'"
                    ),
                    {"user": user},
                )
                == 1
            )
        assert "SECRET_SQL_PARAMETER" not in caplog.text
