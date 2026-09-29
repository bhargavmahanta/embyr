"""M6 final vertical slice through the request and worker roles."""

import asyncio
import json
from time import perf_counter
from uuid import uuid4

import pytest
from app.learning.content import load_package
from app.learning.provision_content import provision
from app.learning.worker import run_once as evaluate_once
from sqlalchemy import text
from test_evaluation_worker import with_worker
from test_learning_content_provision import review
from test_learning_entry_api import client_for, headers
from test_learning_journey import enter
from test_projection_operator import operate
from test_projection_publisher import drain


@pytest.fixture
def pilot(isolated_migrated_database, tmp_path, monkeypatch):
    from app.integrations.voyage import VoyageQueryEmbedder

    async def no_provider(*_args, **_kwargs):
        raise AssertionError("Final M6 journey requires no provider call")

    monkeypatch.setattr(VoyageQueryEmbedder, "embed_queries", no_provider)
    approval = review()
    attestation = tmp_path / "review.json"
    attestation.write_text(json.dumps(approval))
    monkeypatch.setenv("EMBYR_CONTENT_REVIEW_ATTESTATION", str(attestation))
    monkeypatch.setenv("EMBYR_CONTENT_ALLOW_TEST_ATTESTATION", "1")
    with isolated_migrated_database.engine.begin() as connection:
        provision(connection, approval, allow_test=True)
    return isolated_migrated_database


def test_real_role_journey_reaches_memory_world_and_complete_delta(pilot):
    from app.learning.projection_operator import audit

    started = perf_counter()
    db = pilot
    subject = str(uuid4())
    with client_for(db.url) as client:
        user_id, exploration = enter(client, subject)
        path = "/api/v1/explorations/" + exploration["id"]
        lag = client.get("/api/v1/memory/summary", headers=headers(subject))
        assert lag.status_code == 200
        assert lag.json()["projection"]["status"] == "PENDING"
        assert (
            client.get("/api/v1/world", headers=headers(subject)).json()["revision"]
            == 0
        )

        delivery = client.post(
            path + "/delivery", json={}, headers=headers(subject, "delivery")
        )
        assert delivery.status_code == 200, delivery.text
        definition = next(
            item
            for item in load_package()["definitions"]
            if item["entity_id"] == exploration["entity_id"]
        )
        option = next(
            key
            for key, value in definition["assessment"]["option_results"].items()
            if value["result"] == "SUPPORTED"
        )
        check = client.post(
            path + "/assessment-sessions",
            json={"confidence_before": "FUZZY"},
            headers=headers(subject, "check"),
        )
        assert check.status_code == 200, check.text
        answer = client.post(
            "/api/v1/assessment-sessions/" + check.json()["id"] + "/responses",
            json={
                "interaction_id": check.json()["interaction"]["id"],
                "response_type": "SINGLE_CHOICE",
                "content": {"option_id": option},
            },
            headers=headers(subject, "answer"),
        )
        assert answer.status_code == 202, answer.text
        assert asyncio.run(with_worker(db, evaluate_once)) is True
        reflection = client.post(
            path + "/reflections",
            json={"text": "M6_PRIVATE_REFLECTION"},
            headers=headers(subject, "reflection"),
        )
        assert reflection.status_code == 200, reflection.text
        current = client.get(path, headers=headers(subject)).json()
        completion = client.post(
            path + "/completion",
            json={"base_version": current["version"]},
            headers=headers(subject, "completion"),
        )
        assert completion.status_code == 200, completion.text
        assert drain(db) > 0

        memory = client.get("/api/v1/memory/summary", headers=headers(subject))
        assert memory.status_code == 200, memory.text
        assert memory.json()["projection"]["status"] == "CURRENT"
        assert memory.json()["recognition_evidence"][0]["evidence_count"] == 1
        assert "M6_PRIVATE_REFLECTION" not in memory.text
        world = client.get("/api/v1/world", headers=headers(subject))
        assert world.status_code == 200, world.text
        snapshot = world.json()
        assert snapshot["nodes"][0]["growth_state"] == "YOUNG"
        delta = client.get(
            "/api/v1/world/changes?after_revision=0", headers=headers(subject)
        )
        assert delta.status_code == 200, delta.text
        changes = delta.json()["changes"]
        assert [change["revision"] for change in changes] == list(
            range(1, snapshot["revision"] + 1)
        )
        objects = {"REGION": {}, "NODE": {}}
        for change in changes:
            item = change["payload"]["object"]
            kind = "REGION" if change["type"].startswith("REGION_") else "NODE"
            objects[kind][item["id"]] = item
        assert sorted(
            objects["REGION"].values(), key=lambda item: item["id"]
        ) == sorted(snapshot["regions"], key=lambda item: item["id"])
        assert sorted(objects["NODE"].values(), key=lambda item: item["id"]) == sorted(
            snapshot["nodes"], key=lambda item: item["id"]
        )
        with db.engine.begin() as connection:
            connection.execute(text("set local role app_worker"))
            connection.execute(
                text("""update jobs set status='PENDING',completed_at=null
where user_id=:u and job_type='LEARNER_PROJECTION' and status='SUCCEEDED'"""),
                {"u": user_id},
            )
        assert drain(db) > 0
        assert (
            client.get("/api/v1/memory/summary", headers=headers(subject)).json()
            == memory.json()
        )
        assert client.get("/api/v1/world", headers=headers(subject)).json() == snapshot
        assert (
            client.get(
                "/api/v1/world/changes?after_revision=0", headers=headers(subject)
            ).json()
            == delta.json()
        )
    assert operate(db, lambda factory: audit(factory, user_id))["status"] == "PASS"
    print(
        "M6_JOURNEY_PERFORMANCE "
        + json.dumps({"elapsed_seconds": round(perf_counter() - started, 6)})
    )


@pytest.mark.parametrize(
    "variant", ["unassessed", "unanswered", "uncertain", "insufficient"]
)
def test_completion_without_eligible_recognition_stays_sprout(pilot, variant):
    db = pilot
    subject = str(uuid4())
    with client_for(db.url) as client:
        _, exploration = enter(client, subject)
        path = "/api/v1/explorations/" + exploration["id"]
        assert (
            client.post(
                path + "/delivery", json={}, headers=headers(subject, "delivery")
            ).status_code
            == 200
        )
        session_id = None
        if variant != "unassessed":
            check = client.post(
                path + "/assessment-sessions",
                json={"confidence_before": "FUZZY"},
                headers=headers(subject, "check"),
            )
            assert check.status_code == 200, check.text
            session_id = check.json()["id"]
            if variant not in ("unanswered",):
                definition = next(
                    item
                    for item in load_package()["definitions"]
                    if item["entity_id"] == exploration["entity_id"]
                )
                option = next(
                    key
                    for key, value in definition["assessment"]["option_results"].items()
                    if value["result"]
                    == (
                        "UNCERTAIN"
                        if variant == "uncertain"
                        else "INSUFFICIENT_EVIDENCE"
                    )
                )
                answer = client.post(
                    "/api/v1/assessment-sessions/" + session_id + "/responses",
                    json={
                        "interaction_id": check.json()["interaction"]["id"],
                        "response_type": "SINGLE_CHOICE",
                        "content": {"option_id": option},
                    },
                    headers=headers(subject, "answer"),
                )
                assert answer.status_code == 202, answer.text
                assert asyncio.run(with_worker(db, evaluate_once)) is True
        current = client.get(path, headers=headers(subject)).json()
        completion = client.post(
            path + "/completion",
            json={"base_version": current["version"]},
            headers=headers(subject, "completion"),
        )
        assert completion.status_code == 200, completion.text
        if variant == "unanswered":
            abandoned = client.get(
                "/api/v1/assessment-sessions/" + session_id,
                headers=headers(subject),
            )
            assert abandoned.json()["status"] == "ABANDONED"
        assert drain(db) > 0
        memory = client.get("/api/v1/memory/summary", headers=headers(subject)).json()
        world = client.get("/api/v1/world", headers=headers(subject)).json()
        assert memory["projection"]["status"] == "CURRENT"
        assert memory["recognition_evidence"] == []
        assert world["nodes"][0]["growth_state"] == "SPROUT"


def test_pause_return_resume_does_not_invent_world_growth(pilot):
    db = pilot
    subject = str(uuid4())
    with client_for(db.url) as client:
        _, exploration = enter(client, subject)
        path = "/api/v1/explorations/" + exploration["id"]
        assert drain(db) > 0
        before = client.get("/api/v1/world", headers=headers(subject)).json()
        assert before["nodes"][0]["growth_state"] == "SEED"
        for action, version in [("PAUSE", 1), ("RETURN", 2), ("RESUME", 3)]:
            result = client.post(
                path + "/actions",
                json={"action": action, "base_version": version},
                headers=headers(subject, action.lower()),
            )
            assert result.status_code == 200, result.text
        assert drain(db) > 0
        after = client.get("/api/v1/world", headers=headers(subject)).json()
        assert after["revision"] == before["revision"]
        assert after["nodes"] == before["nodes"]
        memory = client.get("/api/v1/memory/summary", headers=headers(subject)).json()
        assert memory["projection"]["status"] == "CURRENT"
        assert memory["recently_explored"][0]["entity_id"] == exploration["entity_id"]


def test_evaluation_after_completion_does_not_reopen_exploration(pilot):
    db = pilot
    subject = str(uuid4())
    with client_for(db.url) as client:
        _, exploration = enter(client, subject)
        path = "/api/v1/explorations/" + exploration["id"]
        assert (
            client.post(
                path + "/delivery", json={}, headers=headers(subject, "delivery")
            ).status_code
            == 200
        )
        definition = next(
            item
            for item in load_package()["definitions"]
            if item["entity_id"] == exploration["entity_id"]
        )
        option = next(
            key
            for key, value in definition["assessment"]["option_results"].items()
            if value["result"] == "SUPPORTED"
        )
        check = client.post(
            path + "/assessment-sessions",
            json={"confidence_before": "FUZZY"},
            headers=headers(subject, "check"),
        )
        assert check.status_code == 200, check.text
        answer = client.post(
            "/api/v1/assessment-sessions/" + check.json()["id"] + "/responses",
            json={
                "interaction_id": check.json()["interaction"]["id"],
                "response_type": "SINGLE_CHOICE",
                "content": {"option_id": option},
            },
            headers=headers(subject, "answer"),
        )
        assert answer.status_code == 202, answer.text
        current = client.get(path, headers=headers(subject)).json()
        assert (
            client.post(
                path + "/completion",
                json={"base_version": current["version"]},
                headers=headers(subject, "completion"),
            ).status_code
            == 200
        )
        assert asyncio.run(with_worker(db, evaluate_once)) is True
        assert drain(db) > 0
        assert (
            client.get(path, headers=headers(subject)).json()["status"] == "COMPLETED"
        )
        assert (
            client.get("/api/v1/world", headers=headers(subject)).json()["nodes"][0][
                "growth_state"
            ]
            == "YOUNG"
        )
