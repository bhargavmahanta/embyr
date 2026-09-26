"""Public learner entry and lifecycle commands under the real backend role."""

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.principal import ExternalIdentity
from app.config import Settings
from app.main import create_app


class Verifier:
    def verify(self, token):
        return ExternalIdentity("SUPABASE", token)


def client_for(url):
    engine = create_async_engine(url)

    @event.listens_for(engine.sync_engine, "connect")
    def role(connection, _):
        with connection.cursor() as cursor:
            cursor.execute("set role app_backend")
        connection.commit()

    app = create_app(
        settings=Settings(
            database_url=url,
            supabase_auth_issuer="https://embyr-dev.supabase.co/auth/v1",
        ),
        session_factory=async_sessionmaker(engine, expire_on_commit=False),
        verifier=Verifier(),
    )
    return TestClient(app)


def headers(subject, key=None):
    result = {"Authorization": f"Bearer {subject}"}
    if key:
        result["Idempotency-Key"] = key
    return result


def test_empty_onboarding_owned_lifecycle_reflection_and_reference_replay(
    isolated_migrated_database,
):
    db = isolated_migrated_database
    subject = str(uuid4())
    other = str(uuid4())
    with client_for(db.url) as client:
        a = client.post("/api/v1/session/bootstrap", headers=headers(subject)).json()[
            "id"
        ]
        client.post("/api/v1/session/bootstrap", headers=headers(other))
        body = {
            "motivations": ["LEARN_DAILY"],
            "starter_interest_entity_ids": [],
            "adventure_preference": "BALANCED",
            "preferred_effort": "15_20_MIN",
            "support_style": "SMALL_HINT",
            "practical_opt_in": False,
        }
        first = client.post(
            "/api/v1/me/onboarding/complete",
            json=body,
            headers=headers(subject, "onboard"),
        )
        assert first.status_code == 200, first.text
        assert (
            client.post(
                "/api/v1/me/onboarding/complete",
                json=body,
                headers=headers(subject, "onboard"),
            ).json()
            == first.json()
        )
        assert (
            client.post(
                "/api/v1/me/onboarding/complete",
                json=body,
                headers=headers(subject, "different"),
            ).status_code
            == 409
        )
        empty = client.post(
            "/api/v1/recommendations/next",
            json={"mode": "SURPRISE"},
            headers=headers(subject, "surprise"),
        )
        assert empty.json() == {"recommendation": None}
        with db.engine.begin() as connection:
            entity = connection.scalar(
                text(
                    "insert into learning_entities(canonical_key,entity_type,status) values (:key,'TOPIC','REVIEWED') returning id"
                ),
                {"key": str(uuid4())},
            )
            connection.execute(
                text(
                    "insert into learning_entity_versions(entity_id,version,title,summary,knowledge_types,scope) values (:id,1,'test','summary',array['CONCEPTUAL'],'NORMAL')"
                ),
                {"id": entity},
            )
            connection.execute(
                text("update learning_entities set current_version=1 where id=:id"),
                {"id": entity},
            )
            exploration = str(
                connection.scalar(
                    text(
                        "insert into explorations(user_id,entity_id,entity_version,learning_intent,status,started_at) values (:user,:entity,1,'DIRECT_INTEREST','ACTIVE',now()) returning id"
                    ),
                    {"user": a, "entity": entity},
                )
            )
        path = f"/api/v1/explorations/{exploration}"
        assert client.get(path, headers=headers(other)).status_code == 404
        paused = client.post(
            path + "/actions",
            json={"action": "PAUSE", "base_version": 1},
            headers=headers(subject, "pause"),
        )
        assert paused.status_code == 200, paused.text
        returned = client.post(
            path + "/actions",
            json={"action": "RETURN", "base_version": 2},
            headers=headers(subject, "return"),
        )
        assert returned.json()["status"] == "PAUSED"
        completed = client.post(
            path + "/completion",
            json={"base_version": 3},
            headers=headers(subject, "complete"),
        )
        assert completed.status_code == 200, completed.text
        assert completed.json()["status"] == "COMPLETED"
        assert (
            client.post(
                path + "/completion",
                json={"base_version": 1},
                headers=headers(subject, "complete-again"),
            ).json()
            == completed.json()
        )
        reflection = client.post(
            path + "/reflections",
            json={"text": "private draft"},
            headers=headers(subject, "reflect"),
        )
        assert reflection.status_code == 200, reflection.text
        edited = client.patch(
            "/api/v1/reflections/" + reflection.json()["id"],
            json={"base_version": 1, "text": "private edit"},
            headers=headers(subject),
        )
        assert edited.status_code == 200, edited.text
        replay = client.post(
            path + "/reflections",
            json={"text": "private draft"},
            headers=headers(subject, "reflect"),
        )
        assert replay.json() == edited.json()
        assert (
            client.patch(
                "/api/v1/reflections/" + reflection.json()["id"],
                json={"base_version": 1, "text": "stale"},
                headers=headers(subject),
            ).status_code
            == 409
        )
        read = client.get(path, headers=headers(subject))
        assert read.json()["reflection"] == edited.json()
        assert read.json()["delivery"] is None
        assert (
            client.get(
                "/api/v1/explorations?status=COMPLETED", headers=headers(subject)
            ).json()["items"][0]["id"]
            == exploration
        )
        missing = client.post(
            path + "/delivery", json={}, headers=headers(subject, "delivery")
        )
        assert missing.status_code == 409
        with db.engine.connect() as connection:
            records = (
                connection.execute(
                    text(
                        "select response_body from idempotency_records where user_id=:id"
                    ),
                    {"id": a},
                )
                .scalars()
                .all()
            )
            events = (
                connection.execute(
                    text("select metadata from learning_events where user_id=:id"),
                    {"id": a},
                )
                .scalars()
                .all()
            )
            assert "private" not in str(records) + str(events)
            assert (
                connection.scalar(
                    text(
                        "select count(*) from learning_events where user_id=:id and event_type='EXPLORATION_COMPLETED'"
                    ),
                    {"id": a},
                )
                == 1
            )
