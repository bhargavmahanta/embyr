from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError


def _assert_constraint(connection, expected: str, statement, parameters) -> None:
    with pytest.raises(IntegrityError) as error, connection.begin_nested():
        connection.execute(statement, parameters)

    assert error.value.orig.diag.constraint_name == expected


def _insert_user(connection):
    return connection.execute(
        text(
            """
            insert into app_users (auth_provider, auth_subject)
            values ('test', :subject)
            returning id
            """
        ),
        {"subject": str(uuid4())},
    ).scalar_one()


def _insert_practical_graph(connection, *, user_id=None):
    user_id = user_id or _insert_user(connection)
    entity_id = connection.execute(
        text(
            """
            insert into learning_entities (canonical_key, entity_type, status)
            values (:key, 'TECHNIQUE', 'REVIEWED') returning id
            """
        ),
        {"key": f"artifact-{uuid4()}"},
    ).scalar_one()
    connection.execute(
        text(
            """
            insert into learning_entity_versions
              (entity_id, version, title, summary, knowledge_types, scope)
            values
              (:entity_id, 1, 'Artifact topic', 'Summary',
               array['PROCEDURAL'], 'NORMAL')
            """
        ),
        {"entity_id": entity_id},
    )
    challenge_id = connection.execute(
        text(
            """
            insert into practical_challenges (entity_id)
            values (:entity_id) returning id
            """
        ),
        {"entity_id": entity_id},
    ).scalar_one()
    challenge_version_id = connection.execute(
        text(
            """
            insert into practical_challenge_versions
              (challenge_id, entity_id, entity_version, version, prompt,
               target_techniques, estimated_effort_minutes, materials,
               environment_constraints, physical_requirements,
               evidence_requirements, status)
            values
              (:challenge_id, :entity_id, 1, 1, 'Make an artifact',
               '["composition"]'::jsonb, 30, '["paper"]'::jsonb,
               '[]'::jsonb, '[]'::jsonb, '{"media":["image"]}'::jsonb,
               'REVIEWED')
            returning id
            """
        ),
        {"challenge_id": challenge_id, "entity_id": entity_id},
    ).scalar_one()
    exploration_id = connection.execute(
        text(
            """
            insert into explorations
              (user_id, entity_id, entity_version, practical_challenge_id,
               practical_challenge_version_id, learning_intent, status,
               started_at)
            values
              (:user_id, :entity_id, 1, :challenge_id,
               :challenge_version_id, 'PRACTICAL_SUPPORT', 'ACTIVE', now())
            returning id
            """
        ),
        {
            "user_id": user_id,
            "entity_id": entity_id,
            "challenge_id": challenge_id,
            "challenge_version_id": challenge_version_id,
        },
    ).scalar_one()
    reflection_id = connection.execute(
        text(
            """
            insert into reflections (user_id, exploration_id, entity_id, text)
            values (:user_id, :exploration_id, :entity_id, 'Reflection')
            returning id
            """
        ),
        {
            "user_id": user_id,
            "exploration_id": exploration_id,
            "entity_id": entity_id,
        },
    ).scalar_one()
    return {
        "user_id": user_id,
        "entity_id": entity_id,
        "challenge_id": challenge_id,
        "challenge_version_id": challenge_version_id,
        "exploration_id": exploration_id,
        "reflection_id": reflection_id,
    }


def _insert_upload(
    connection,
    *,
    user_id,
    status="AUTHORIZED",
    object_key=None,
):
    object_key = object_key or f"users/{user_id}/artifacts/{uuid4()}"
    completed_at = "now()" if status != "AUTHORIZED" else "null"
    validated_at = "now()" if status == "VALIDATED" else "null"
    rejected_at = "now()" if status == "REJECTED" else "null"
    upload_id = connection.execute(
        text(
            f"""
            insert into upload_sessions
              (user_id, purpose, declared_content_type, declared_size_bytes,
               object_key, status, completed_at, validated_at, rejected_at)
            values
              (:user_id, 'ARTIFACT', 'image/jpeg', 1024, :object_key, :status,
               {completed_at}, {validated_at}, {rejected_at})
            returning id
            """
        ),
        {"user_id": user_id, "object_key": object_key, "status": status},
    ).scalar_one()
    return upload_id, object_key


def _insert_media(connection, *, user_id, upload_id, object_key):
    return connection.execute(
        text(
            """
            insert into media_objects
              (user_id, upload_id, object_key, validated_content_type,
               validated_size_bytes, sha256, metadata_stripped)
            values
              (:user_id, :upload_id, :object_key, 'image/jpeg', 1000,
               :sha256, true)
            returning id
            """
        ),
        {
            "user_id": user_id,
            "upload_id": upload_id,
            "object_key": object_key,
            "sha256": uuid4().hex,
        },
    ).scalar_one()


def _insert_artifact(connection, graph, *, media_object_id):
    return connection.execute(
        text(
            """
            insert into artifacts
              (user_id, practical_challenge_id,
               practical_challenge_version_id, exploration_id,
               media_object_id, reflection_id)
            values
              (:user_id, :challenge_id, :challenge_version_id,
               :exploration_id, :media_object_id, :reflection_id)
            returning id
            """
        ),
        {**graph, "media_object_id": media_object_id},
    ).scalar_one()


def test_upload_status_and_timestamps_are_coherent(migrated_connection):
    user_id = _insert_user(migrated_connection)
    statement = text(
        """
        insert into upload_sessions
          (user_id, purpose, declared_content_type, declared_size_bytes,
           object_key, status)
        values
          (:user_id, 'ARTIFACT', 'image/jpeg', 10, :object_key, :status)
        """
    )
    _assert_constraint(
        migrated_connection,
        "ck_upload_sessions_status",
        statement,
        {
            "user_id": user_id,
            "object_key": f"users/{user_id}/{uuid4()}",
            "status": "UPLOADED",
        },
    )
    _assert_constraint(
        migrated_connection,
        "ck_upload_sessions_lifecycle",
        statement,
        {
            "user_id": user_id,
            "object_key": f"users/{user_id}/{uuid4()}",
            "status": "VALIDATED",
        },
    )


def test_upload_rejects_public_or_signed_url_as_object_key(migrated_connection):
    user_id = _insert_user(migrated_connection)
    statement = text(
        """
        insert into upload_sessions
          (user_id, purpose, declared_content_type, declared_size_bytes,
           object_key, status)
        values (:user_id, 'ARTIFACT', 'image/jpeg', 10, :object_key, 'AUTHORIZED')
        """
    )
    _assert_constraint(
        migrated_connection,
        "ck_upload_sessions_private_object_key",
        statement,
        {"user_id": user_id, "object_key": "https://storage.test/signed?token=x"},
    )


@pytest.mark.parametrize(
    ("purpose", "content_type", "size_bytes", "expected"),
    [
        ("PROFILE", "image/jpeg", 10, "ck_upload_sessions_purpose"),
        ("ARTIFACT", "", 10, "ck_upload_sessions_declared_content_type"),
        ("ARTIFACT", "image/jpeg", 0, "ck_upload_sessions_declared_size"),
    ],
)
def test_upload_rejects_invalid_authorization_metadata(
    migrated_connection, purpose, content_type, size_bytes, expected
):
    user_id = _insert_user(migrated_connection)
    statement = text(
        """
        insert into upload_sessions
          (user_id, purpose, declared_content_type, declared_size_bytes,
           object_key, status)
        values
          (:user_id, :purpose, :content_type, :size_bytes,
           :object_key, 'AUTHORIZED')
        """
    )
    _assert_constraint(
        migrated_connection,
        expected,
        statement,
        {
            "user_id": user_id,
            "purpose": purpose,
            "content_type": content_type,
            "size_bytes": size_bytes,
            "object_key": f"users/{user_id}/{uuid4()}",
        },
    )


def test_upload_lifecycle_is_forward_only_and_terminal(migrated_connection):
    user_id = _insert_user(migrated_connection)
    upload_id, _ = _insert_upload(migrated_connection, user_id=user_id)
    migrated_connection.execute(
        text(
            """
            update upload_sessions
               set status = 'UPLOADED_UNVALIDATED', completed_at = now()
             where id = :id
            """
        ),
        {"id": upload_id},
    )
    migrated_connection.execute(
        text(
            """
            update upload_sessions
               set status = 'VALIDATED', validated_at = now()
             where id = :id
            """
        ),
        {"id": upload_id},
    )

    with pytest.raises(DBAPIError) as error, migrated_connection.begin_nested():
        migrated_connection.execute(
            text(
                """
                update upload_sessions
                   set status = 'REJECTED', validated_at = null,
                       rejected_at = now()
                 where id = :id
                """
            ),
            {"id": upload_id},
        )
    assert error.value.orig.diag.constraint_name == (
        "ck_upload_sessions_status_transition"
    )


def test_media_requires_matching_validated_owned_upload(migrated_connection):
    user_id = _insert_user(migrated_connection)
    upload_id, object_key = _insert_upload(
        migrated_connection, user_id=user_id, status="UPLOADED_UNVALIDATED"
    )
    statement = text(
        """
        insert into media_objects
          (user_id, upload_id, object_key, validated_content_type,
           validated_size_bytes, sha256, metadata_stripped)
        values
          (:user_id, :upload_id, :object_key, 'image/jpeg', 1000, 'abc', true)
        """
    )
    with pytest.raises(DBAPIError) as error, migrated_connection.begin_nested():
        migrated_connection.execute(
            statement,
            {"user_id": user_id, "upload_id": upload_id, "object_key": object_key},
        )
    assert error.value.orig.diag.constraint_name == (
        "ck_media_objects_validated_upload"
    )

    other_user_id = _insert_user(migrated_connection)
    validated_id, validated_key = _insert_upload(
        migrated_connection, user_id=user_id, status="VALIDATED"
    )
    _assert_constraint(
        migrated_connection,
        "fk_media_objects_upload_owner",
        statement,
        {
            "user_id": other_user_id,
            "upload_id": validated_id,
            "object_key": validated_key,
        },
    )


def test_media_upload_is_one_to_one_and_object_key_must_match(migrated_connection):
    user_id = _insert_user(migrated_connection)
    upload_id, object_key = _insert_upload(
        migrated_connection, user_id=user_id, status="VALIDATED"
    )
    _insert_media(
        migrated_connection,
        user_id=user_id,
        upload_id=upload_id,
        object_key=object_key,
    )
    statement = text(
        """
        insert into media_objects
          (user_id, upload_id, object_key, validated_content_type,
           validated_size_bytes, sha256, metadata_stripped)
        values
          (:user_id, :upload_id, :object_key, 'image/jpeg', 1000, :sha256, true)
        """
    )
    _assert_constraint(
        migrated_connection,
        "uq_media_objects_upload_id",
        statement,
        {
            "user_id": user_id,
            "upload_id": upload_id,
            "object_key": object_key,
            "sha256": uuid4().hex,
        },
    )

    other_upload_id, other_key = _insert_upload(
        migrated_connection, user_id=user_id, status="VALIDATED"
    )
    with pytest.raises(DBAPIError) as error, migrated_connection.begin_nested():
        migrated_connection.execute(
            statement,
            {
                "user_id": user_id,
                "upload_id": other_upload_id,
                "object_key": f"{other_key}-different",
                "sha256": uuid4().hex,
            },
        )
    assert error.value.orig.diag.constraint_name == (
        "ck_media_objects_upload_object_key"
    )


def test_validated_media_freezes_upload_and_storage_metadata(migrated_connection):
    user_id = _insert_user(migrated_connection)
    upload_id, object_key = _insert_upload(
        migrated_connection, user_id=user_id, status="VALIDATED"
    )
    media_id = _insert_media(
        migrated_connection,
        user_id=user_id,
        upload_id=upload_id,
        object_key=object_key,
    )

    with pytest.raises(DBAPIError) as error, migrated_connection.begin_nested():
        migrated_connection.execute(
            text(
                """
                update upload_sessions
                   set object_key = :object_key
                 where id = :id
                """
            ),
            {"id": upload_id, "object_key": f"users/{user_id}/{uuid4()}"},
        )
    assert error.value.orig.diag.constraint_name == (
        "ck_upload_sessions_immutable_request"
    )

    with pytest.raises(DBAPIError) as error, migrated_connection.begin_nested():
        migrated_connection.execute(
            text("update media_objects set sha256 = 'changed' where id = :id"),
            {"id": media_id},
        )
    assert error.value.orig.diag.constraint_name == "ck_media_objects_immutable"

    _assert_constraint(
        migrated_connection,
        "fk_media_objects_upload_owner",
        text("delete from upload_sessions where id = :id"),
        {"id": upload_id},
    )


def test_artifact_requires_coherent_owner_exploration_and_challenge_version(
    migrated_connection,
):
    graph = _insert_practical_graph(migrated_connection)
    upload_id, object_key = _insert_upload(
        migrated_connection, user_id=graph["user_id"], status="VALIDATED"
    )
    media_id = _insert_media(
        migrated_connection,
        user_id=graph["user_id"],
        upload_id=upload_id,
        object_key=object_key,
    )
    statement = text(
        """
        insert into artifacts
          (user_id, practical_challenge_id, practical_challenge_version_id,
           exploration_id, media_object_id, reflection_id)
        values
          (:user_id, :challenge_id, :challenge_version_id, :exploration_id,
           :media_object_id, :reflection_id)
        """
    )
    other_user = _insert_user(migrated_connection)
    _assert_constraint(
        migrated_connection,
        "fk_artifacts_exploration_challenge_owner_version",
        statement,
        {**graph, "user_id": other_user, "media_object_id": media_id},
    )

    other_graph = _insert_practical_graph(
        migrated_connection, user_id=graph["user_id"]
    )
    _assert_constraint(
        migrated_connection,
        "fk_artifacts_exploration_challenge_owner_version",
        statement,
        {
            **graph,
            "challenge_id": other_graph["challenge_id"],
            "challenge_version_id": other_graph["challenge_version_id"],
            "media_object_id": media_id,
        },
    )


def test_artifact_rejects_cross_exploration_reflection_and_cross_user_media(
    migrated_connection,
):
    graph = _insert_practical_graph(migrated_connection)
    same_user_other_graph = _insert_practical_graph(
        migrated_connection, user_id=graph["user_id"]
    )
    upload_id, object_key = _insert_upload(
        migrated_connection, user_id=graph["user_id"], status="VALIDATED"
    )
    media_id = _insert_media(
        migrated_connection,
        user_id=graph["user_id"],
        upload_id=upload_id,
        object_key=object_key,
    )
    statement = text(
        """
        insert into artifacts
          (user_id, practical_challenge_id, practical_challenge_version_id,
           exploration_id, media_object_id, reflection_id)
        values
          (:user_id, :challenge_id, :challenge_version_id, :exploration_id,
           :media_object_id, :reflection_id)
        """
    )
    _assert_constraint(
        migrated_connection,
        "fk_artifacts_reflection_owner_exploration",
        statement,
        {
            **graph,
            "reflection_id": same_user_other_graph["reflection_id"],
            "media_object_id": media_id,
        },
    )

    other_user = _insert_user(migrated_connection)
    other_upload, other_key = _insert_upload(
        migrated_connection, user_id=other_user, status="VALIDATED"
    )
    other_media = _insert_media(
        migrated_connection,
        user_id=other_user,
        upload_id=other_upload,
        object_key=other_key,
    )
    _assert_constraint(
        migrated_connection,
        "fk_artifacts_media_owner",
        statement,
        {**graph, "media_object_id": other_media},
    )


def test_artifacts_may_share_validated_media_and_reflection(migrated_connection):
    graph = _insert_practical_graph(migrated_connection)
    upload_id, object_key = _insert_upload(
        migrated_connection, user_id=graph["user_id"], status="VALIDATED"
    )
    media_id = _insert_media(
        migrated_connection,
        user_id=graph["user_id"],
        upload_id=upload_id,
        object_key=object_key,
    )

    first = _insert_artifact(migrated_connection, graph, media_object_id=media_id)
    second = _insert_artifact(migrated_connection, graph, media_object_id=media_id)

    assert first != second
    assert migrated_connection.execute(
        text(
            """
            select count(*) from artifacts
             where media_object_id = :media_id and reflection_id = :reflection_id
            """
        ),
        {"media_id": media_id, "reflection_id": graph["reflection_id"]},
    ).scalar_one() == 2


def test_artifact_history_is_immutable_and_protects_referenced_media(
    migrated_connection,
):
    graph = _insert_practical_graph(migrated_connection)
    upload_id, object_key = _insert_upload(
        migrated_connection, user_id=graph["user_id"], status="VALIDATED"
    )
    media_id = _insert_media(
        migrated_connection,
        user_id=graph["user_id"],
        upload_id=upload_id,
        object_key=object_key,
    )
    artifact_id = _insert_artifact(
        migrated_connection, graph, media_object_id=media_id
    )

    with pytest.raises(DBAPIError) as error, migrated_connection.begin_nested():
        migrated_connection.execute(
            text("update artifacts set reflection_id = null where id = :id"),
            {"id": artifact_id},
        )
    assert error.value.orig.diag.constraint_name == "ck_artifacts_immutable"

    statement = text("delete from media_objects where id = :id")
    _assert_constraint(
        migrated_connection,
        "fk_artifacts_media_owner",
        statement,
        {"id": media_id},
    )


def test_artifact_analysis_is_owned_and_uses_frozen_status(migrated_connection):
    graph = _insert_practical_graph(migrated_connection)
    upload_id, object_key = _insert_upload(
        migrated_connection, user_id=graph["user_id"], status="VALIDATED"
    )
    media_id = _insert_media(
        migrated_connection,
        user_id=graph["user_id"],
        upload_id=upload_id,
        object_key=object_key,
    )
    artifact_id = _insert_artifact(
        migrated_connection, graph, media_object_id=media_id
    )
    statement = text(
        """
        insert into artifact_analyses
          (user_id, artifact_id, analyzer_version, status, analysis)
        values (:user_id, :artifact_id, 'artifact-v1', :status, null)
        """
    )
    _assert_constraint(
        migrated_connection,
        "ck_artifact_analyses_status",
        statement,
        {
            "user_id": graph["user_id"],
            "artifact_id": artifact_id,
            "status": "RUNNING",
        },
    )
    other_user = _insert_user(migrated_connection)
    _assert_constraint(
        migrated_connection,
        "fk_artifact_analyses_artifact_owner",
        statement,
        {"user_id": other_user, "artifact_id": artifact_id, "status": "PENDING"},
    )

    migrated_connection.execute(
        statement,
        {
            "user_id": graph["user_id"],
            "artifact_id": artifact_id,
            "status": "PENDING",
        },
    )
    migrated_connection.execute(
        text(
            """
            insert into artifact_analyses
              (user_id, artifact_id, analyzer_version, status, analysis)
            values
              (:user_id, :artifact_id, 'artifact-v2', 'SUCCEEDED',
               '{"summary":"Visible shapes detected"}'::jsonb)
            """
        ),
        {"user_id": graph["user_id"], "artifact_id": artifact_id},
    )
