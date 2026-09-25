"""Focused HTTP-to-PostgreSQL recommendation command flow under app_backend."""
from __future__ import annotations

from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.principal import ExternalIdentity
from app.config import Settings
from app.main import create_app


class _Verifier:
    def verify(self, token: str) -> ExternalIdentity:
        return ExternalIdentity("SUPABASE", token)


def _seed(engine):
    subject_a, subject_b = str(uuid4()), str(uuid4())
    with engine.begin() as connection:
        users = [connection.scalar(text("""
            insert into app_users (auth_provider, auth_subject)
            values ('SUPABASE', :subject) returning id
        """), {"subject": subject}) for subject in (subject_a, subject_b)]
        entity = connection.scalar(text("""
            insert into learning_entities (canonical_key, entity_type, status)
            values (:key, 'TOPIC', 'REVIEWED') returning id
        """), {"key": f"m4-api-{uuid4()}"})
        connection.execute(text("""
            insert into learning_entity_versions
              (entity_id, version, title, summary, knowledge_types, scope)
            values (:entity, 3, 'Recommendation target', 'A current topic',
                    array['CONCEPTUAL'], 'NORMAL')
        """), {"entity": entity})
        connection.execute(text("""
            update learning_entities set current_version = 3 where id = :entity
        """), {"entity": entity})
        connection.execute(text("""
            insert into explicit_interest_preferences (user_id, entity_id, preference)
            values (:user, :entity, 'MORE')
        """), {"user": users[0], "entity": entity})
    return (subject_a, subject_b), users, entity


def _client(database_url):
    engine = create_async_engine(database_url)

    @event.listens_for(engine.sync_engine, "connect")
    def set_backend_role(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("set role app_backend")
        cursor.close()
        dbapi_connection.commit()

    factory = async_sessionmaker(engine, expire_on_commit=False)
    app = create_app(
        settings=Settings(database_url=database_url,
                          supabase_auth_issuer="https://embyr-dev.supabase.co/auth/v1"),
        session_factory=factory, verifier=_Verifier(),
    )
    return TestClient(app), engine


def _post(client, path, subject, key, body):
    return client.post(
        f"/api/v1/recommendations{path}", json=body,
        headers={"Authorization": f"Bearer {subject}", "Idempotency-Key": key},
    )


def _count(connection, table, user_id):
    return connection.scalar(text(f"select count(*) from {table} where user_id = :user"),
                             {"user": user_id})


def test_real_route_replay_empty_decisions_and_expired_generation(
    migrated_engine, database_url,
):
    subjects, users, entity = _seed(migrated_engine)
    client, _ = _client(database_url)
    a, b = subjects
    try:
        with client:
            next_body = {"mode": "EXPLORE"}
            first = _post(client, "/next", a, "next-1", next_body)
            assert first.status_code == 200, first.text
            dto = first.json()
            assert dto["entity"] == {"id": str(entity), "title": "Recommendation target"}
            assert dto["target_type"] == "LEARNING_ENTITY"
            assert dto["distance_band"] == "COMFORT"
            with migrated_engine.connect() as connection:
                persisted = connection.execute(text("""
                    select ranking_model_version, presented_at from recommendations
                    where id = :id
                """), {"id": dto["id"]}).one()
                assert persisted.ranking_model_version == "recommendation-profile/v1"
                assert persisted.presented_at.isoformat() == dto["presented_at"]
                assert _count(connection, "recommendations", users[0]) == 1

            repeated = _post(client, "/next", a, "next-1", next_body)
            assert repeated.status_code == 200 and repeated.json() == dto
            mismatch = _post(client, "/next", a, "next-1", {"mode": "CREATE"})
            assert mismatch.status_code == 409
            assert mismatch.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
            with migrated_engine.connect() as connection:
                assert _count(connection, "recommendations", users[0]) == 1

            empty = _post(client, "/next", b, "empty-1", next_body)
            assert empty.status_code == 200 and empty.json() == {"recommendation": None}
            assert _post(client, "/next", b, "empty-1", next_body).json() == empty.json()
            create = _post(client, "/next", a, "create-1", {"mode": "CREATE"})
            assert create.status_code == 200 and create.json() == {"recommendation": None}
            with migrated_engine.connect() as connection:
                assert _count(connection, "recommendations", users[1]) == 0
                assert connection.scalar(text("""
                    select result_type from idempotency_records
                    where user_id = :user and idempotency_key = 'empty-1'
                """), {"user": users[1]}) == "EMPTY_RECOMMENDATION"

            decision_path = f"/{dto['id']}/decision"
            accepted = _post(client, decision_path, a, "accept-1", {"decision": "ACCEPT"})
            assert accepted.status_code == 200, accepted.text
            exploration = accepted.json()
            assert exploration["learning_intent"] == "DIRECT_INTEREST"
            assert exploration["status"] == "ACTIVE"
            assert _post(client, decision_path, a, "accept-1", {
                "decision": "ACCEPT"}).json() == exploration
            mismatch = _post(client, decision_path, a, "accept-1", {
                "decision": "ACCEPT", "reason": "changed"})
            assert mismatch.status_code == 409
            assert mismatch.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
            foreign = _post(client, decision_path, b, "foreign-1", {"decision": "SKIP"})
            assert foreign.status_code == 404 and foreign.json()["code"] == "RECOMMENDATION_NOT_FOUND"
            decided = _post(client, decision_path, a, "decided-1", {"decision": "SKIP"})
            assert decided.status_code == 409 and decided.json()["code"] == "RECOMMENDATION_ALREADY_DECIDED"
            with migrated_engine.connect() as connection:
                assert connection.scalar(text("""
                    select decision from recommendations where id = :id
                """), {"id": dto["id"]}) == "ACCEPT"
                assert connection.scalar(text("""
                    select recommendation_id from explorations where id = :id
                """), {"id": exploration["id"]}) == UUID(dto["id"])
                assert connection.scalar(text("""
                    select count(*) from learning_events where exploration_id = :id
                """), {"id": exploration["id"]}) == 2
                assert _count(connection, "explorations", users[0]) == 1

            second = _post(client, "/next", a, "next-2", next_body)
            assert second.status_code == 200, second.text
            skip_path = f"/{second.json()['id']}/decision"
            skipped = _post(client, skip_path, a, "reuse-key", {
                "decision": "SKIP", "reason": "arbitrary learner text"})
            assert skipped.status_code == 200, skipped.text
            assert skipped.json() == {"recommendation_id": second.json()["id"], "decision": "SKIP"}
            with migrated_engine.begin() as connection:
                old = connection.execute(text("""
                    select id, command_name, request_fingerprint, response_body
                    from idempotency_records
                    where user_id = :user and idempotency_key = 'reuse-key'
                """), {"user": users[0]}).one()
                events = connection.execute(text("""
                    select command_id, event_type, metadata from learning_events
                    where command_id = :id
                """), {"id": old.id}).all()
                assert len(events) == 1
                assert events[0].event_type == "RECOMMENDATION_SKIPPED"
                assert events[0].metadata == {"recommendation_id": second.json()["id"]}
                assert _count(connection, "explorations", users[0]) == 1
                connection.execute(text("""
                    update idempotency_records set expires_at = now() - interval '1 second'
                    where id = :id
                """), {"id": old.id})

            third = _post(client, "/next", a, "next-3", next_body)
            assert third.status_code == 200, third.text
            third_path = f"/{third.json()['id']}/decision"
            reused = _post(client, third_path, a, "reuse-key", {
                "decision": "SKIP", "reason": "different text"})
            assert reused.status_code == 200, reused.text
            with migrated_engine.connect() as connection:
                records = connection.execute(text("""
                    select id, command_name, request_fingerprint, response_body,
                           retired_at from idempotency_records
                    where user_id = :user and idempotency_key = 'reuse-key'
                    order by created_at, id
                """), {"user": users[0]}).all()
                assert len(records) == 2
                assert {row.id for row in records} - {old.id}
                historical = next(row for row in records if row.id == old.id)
                assert historical.command_name == old.command_name
                assert historical.request_fingerprint == old.request_fingerprint
                assert historical.response_body == old.response_body
                assert historical.retired_at is not None
                current = next(row for row in records if row.id != old.id)
                assert current.retired_at is None
                assert connection.scalar(text("""
                    select count(*) from learning_events
                    where command_id in (:old, :new)
                """), {"old": old.id, "new": current.id}) == 2
                assert connection.scalar(text("""
                    select count(*) from learning_events where command_id = :old
                """), {"old": old.id}) == 1
    finally:
        # Keep the migrated_engine fixture's downgrade viable after the test
        # creates two historical generations for one user/key.
        with migrated_engine.begin() as connection:
            connection.execute(text("truncate table app_users cascade"))


def test_writable_recheck_rejects_snapshot_version_race(migrated_engine, database_url, monkeypatch):
    import app.api.recommendations as api

    subjects, users, entity = _seed(migrated_engine)
    original = api.generate_recommendation

    async def advance_target(*args, **kwargs):
        result = await original(*args, **kwargs)
        with migrated_engine.begin() as connection:
            connection.execute(text("""
                insert into learning_entity_versions
                  (entity_id, version, title, summary, knowledge_types, scope)
                values (:entity, 4, 'Changed', 'New version',
                        array['CONCEPTUAL'], 'NORMAL')
            """), {"entity": entity})
            connection.execute(text("""
                update learning_entities set current_version = 4 where id = :entity
            """), {"entity": entity})
        return result

    monkeypatch.setattr(api, "generate_recommendation", advance_target)
    client, _ = _client(database_url)
    try:
        with client:
            response = _post(client, "/next", subjects[0], "race-1", {"mode": "EXPLORE"})
            assert response.status_code == 503, response.text
            assert response.json()["code"] == "RECOMMENDATION_GENERATION_UNAVAILABLE"
            with migrated_engine.connect() as connection:
                assert _count(connection, "recommendations", users[0]) == 0
                assert connection.scalar(text("""
                    select count(*) from idempotency_records
                    where user_id = :user and idempotency_key = 'race-1'
                """), {"user": users[0]}) == 0
    finally:
        with migrated_engine.begin() as connection:
            connection.execute(text("truncate table app_users cascade"))
