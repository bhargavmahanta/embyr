import json
from uuid import uuid4
from sqlalchemy import text
from app.learning.content import load_package
from app.learning import provision_content
from test_learning_entry_api import client_for, headers
from test_learning_content_provision import review


def test_assessment_answer_support_recovery(
    isolated_migrated_database, tmp_path, monkeypatch
):
    db = isolated_migrated_database
    attestation = tmp_path / "review.json"
    attestation.write_text(json.dumps(review()))
    monkeypatch.setenv("EMBYR_CONTENT_REVIEW_ATTESTATION", str(attestation))
    monkeypatch.setenv("EMBYR_CONTENT_ALLOW_TEST_ATTESTATION", "1")
    with db.engine.begin() as conn:
        provision_content.provision(conn, review(), allow_test=True)
    subject, other = str(uuid4()), str(uuid4())
    with client_for(db.url) as client:
        user = client.post(
            "/api/v1/session/bootstrap", headers=headers(subject)
        ).json()["id"]
        client.post("/api/v1/session/bootstrap", headers=headers(other))
        entity = load_package()["entities"][0]["id"]
        with db.engine.begin() as conn:
            exploration = str(
                conn.scalar(
                    text(
                        "insert into explorations(user_id,entity_id,entity_version,learning_intent,status,started_at) values(:u,:e,1,'DIRECT_INTEREST','ACTIVE',now()) returning id"
                    ),
                    {"u": user, "e": entity},
                )
            )
        path = "/api/v1/explorations/" + exploration
        assert (
            client.post(
                path + "/delivery", json={}, headers=headers(subject, "delivery")
            ).status_code
            == 200
        )
        started = client.post(
            path + "/assessment-sessions",
            json={"confidence_before": "FUZZY"},
            headers=headers(subject, "start"),
        )
        assert started.status_code == 200, started.text
        data = started.json()
        assert (
            client.post(
                path + "/assessment-sessions",
                json={"confidence_before": "FUZZY"},
                headers=headers(subject, "start-natural"),
            ).json()
            == data
        )
        assert (
            client.post(
                path + "/assessment-sessions",
                json={"confidence_before": "MAIN_IDEA"},
                headers=headers(subject, "start-conflict"),
            ).status_code
            == 409
        )
        assert (
            client.post(
                path + "/assessment-sessions",
                json={"confidence_before": "MAIN_IDEA"},
                headers=headers(subject, "start"),
            ).json()["code"]
            == "IDEMPOTENCY_KEY_REUSED"
        )
        assert "option_results" not in str(data) and "rubric" not in str(data)
        sid = data["id"]
        iid = data["interaction"]["id"]
        sp = "/api/v1/assessment-sessions/" + sid
        assert client.get(sp, headers=headers(other)).status_code == 404
        assert (
            client.post(
                sp + "/support-requests",
                json={"interaction_id": str(uuid4()), "level": "SMALL_NUDGE"},
                headers=headers(subject, "wrong"),
            ).status_code
            == 404
        )
        for level in ["SMALL_NUDGE", "EXPLANATION"]:
            assert (
                client.post(
                    sp + "/support-requests",
                    json={"interaction_id": iid, "level": level},
                    headers=headers(subject, level),
                ).status_code
                == 200
            )
        duplicate = client.post(
            sp + "/support-requests",
            json={"interaction_id": iid, "level": "EXPLANATION"},
            headers=headers(subject, "same-level"),
        )
        assert duplicate.status_code == 200
        with db.engine.connect() as conn:
            assert (
                conn.scalar(
                    text(
                        "select count(*) from assessment_support_requests where assessment_session_id=:id"
                    ),
                    {"id": sid},
                )
                == 2
            )
        body = {
            "interaction_id": iid,
            "response_type": "SINGLE_CHOICE",
            "content": {"option_id": "unknown"},
        }
        assert (
            client.post(
                sp + "/responses", json=body, headers=headers(subject, "unknown")
            ).status_code
            == 422
        )
        body["content"]["option_id"] = data["interaction"]["options"][0]["id"]
        answer = client.post(
            sp + "/responses", json=body, headers=headers(subject, "answer")
        )
        assert answer.status_code == 202, answer.text
        assert (
            client.post(
                path + "/completion",
                json={"base_version": 2},
                headers=headers(subject, "finish"),
            ).status_code
            == 200
        )
        assert (
            client.post(
                sp + "/responses", json=body, headers=headers(subject, "natural")
            ).json()
            == answer.json()
        )
        body["content"]["option_id"] = "not-sure"
        assert (
            client.post(
                sp + "/responses", json=body, headers=headers(subject, "conflict")
            ).status_code
            == 409
        )
        read = client.get(
            "/api/v1/assessment-responses/" + answer.json()["response_id"],
            headers=headers(subject),
        )
        assert read.json()["evaluation_status"] == "PENDING"
        with db.engine.connect() as conn:
            assert (
                conn.scalar(
                    text("select support_used from assessment_responses where id=:id"),
                    {"id": answer.json()["response_id"]},
                )
                == "EXPLANATION"
            )
            assert (
                conn.scalar(
                    text("select status from assessment_sessions where id=:id"),
                    {"id": sid},
                )
                == "WAITING_FOR_EVALUATION"
            )
        rid = answer.json()["response_id"]
        rp = "/api/v1/assessment-responses/" + rid
        assert client.get(rp, headers=headers(other)).status_code == 404
        with db.engine.begin() as conn:
            old = conn.scalar(
                text("select id from evaluation_runs where response_id=:id"),
                {"id": rid},
            )
            conn.execute(
                text("update evaluation_runs set status='FAILED' where id=:id"),
                {"id": old},
            )
            conn.execute(
                text(
                    "update jobs set status='FAILED',payload=payload || cast(:failure as jsonb) where payload->>'evaluation_run_id'=:id"
                ),
                {
                    "id": str(old),
                    "failure": json.dumps(
                        {"failure_category": "TRANSIENT_FAILURE", "retry_allowed": True}
                    ),
                },
            )
        failed = client.get(rp, headers=headers(subject)).json()
        assert (
            failed["evaluation_status"] == "FAILED" and failed["retry_allowed"] is True
        )
        retried = client.post(
            rp + "/evaluation-retries", json={}, headers=headers(subject, "retry")
        )
        assert retried.status_code == 202, retried.text
        assert retried.json()["evaluation_run_id"] != str(old)
        assert (
            client.post(
                rp + "/evaluation-retries",
                json={},
                headers=headers(subject, "retry-again"),
            ).json()
            == retried.json()
        )
        assert (
            client.post(
                rp + "/evaluation-retries", json={}, headers=headers(subject, "retry")
            ).json()
            == retried.json()
        )
        assert (
            client.get(rp, headers=headers(subject)).json()["evaluation_status"]
            == "PENDING"
        )
        assert client.get(sp, headers=headers(subject)).json()["retry_allowed"] is False
        with db.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "select id,status,supersedes_id,created_at from evaluation_runs where response_id=:id order by created_at"
                ),
                {"id": rid},
            ).all()
            assert (
                len(rows) == 2
                and rows[0].status == "FAILED"
                and rows[1].status == "PENDING"
            )
            assert (
                rows[1].supersedes_id is None
                and rows[1].created_at > rows[0].created_at
            )
        # Historical revoked feedback must not become the current evaluation.
        with db.engine.begin() as conn:
            conn.execute(
                text(
                    "update evaluation_runs set status='SUCCEEDED',result='UNCERTAIN',confidence=0,feedback='historical' where id=:id"
                ),
                {"id": retried.json()["evaluation_run_id"]},
            )
            conn.execute(
                text("update evaluation_runs set status='REVOKED' where id=:id"),
                {"id": retried.json()["evaluation_run_id"]},
            )
        current = client.get(rp, headers=headers(subject)).json()
        assert current["evaluation_run_id"] is None and current["feedback"] is None
        assert current["retry_allowed"] is False
        assert client.get(sp, headers=headers(subject)).json()["evaluation"] is None
        assert client.get(sp, headers=headers(subject)).json()["retry_allowed"] is False
        assert (
            client.post(
                rp + "/evaluation-retries",
                json={},
                headers=headers(subject, "revoked-retry"),
            ).status_code
            == 409
        )
