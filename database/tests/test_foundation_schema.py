from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


def _insert_user(connection, provider: str = "SUPABASE", subject: str | None = None):
    return connection.execute(
        text(
            """
            insert into app_users (auth_provider, auth_subject)
            values (:provider, :subject)
            returning id
            """
        ),
        {"provider": provider, "subject": subject or str(uuid4())},
    ).scalar_one()


def test_provider_identity_is_unique(migrated_connection):
    subject = str(uuid4())
    _insert_user(migrated_connection, subject=subject)

    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        _insert_user(migrated_connection, subject=subject)


def test_idempotency_key_is_unique_per_user(migrated_connection):
    user_id = _insert_user(migrated_connection)
    params = {
        "user_id": user_id,
        "key": "offline-command-1",
        "command": "create_exploration",
        "fingerprint": "sha256:one",
    }
    statement = text(
        """
        insert into idempotency_records
          (user_id, idempotency_key, command_name, request_fingerprint, expires_at)
        values
          (:user_id, :key, :command, :fingerprint, now() + interval '1 day')
        """
    )
    migrated_connection.execute(statement, params)

    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        migrated_connection.execute(statement, params)


def test_same_idempotency_key_is_allowed_for_different_users(migrated_connection):
    statement = text(
        """
        insert into idempotency_records
          (user_id, idempotency_key, command_name, request_fingerprint, expires_at)
        values
          (:user_id, 'shared-device-key', 'bootstrap', 'sha256:same',
           now() + interval '1 day')
        """
    )

    migrated_connection.execute(statement, {"user_id": _insert_user(migrated_connection)})
    migrated_connection.execute(statement, {"user_id": _insert_user(migrated_connection)})


def test_reused_key_with_different_fingerprint_is_detectable(migrated_connection):
    user_id = _insert_user(migrated_connection)
    migrated_connection.execute(
        text(
            """
            insert into idempotency_records
              (user_id, idempotency_key, command_name, request_fingerprint, expires_at)
            values
              (:user_id, 'command-key', 'create_exploration', 'sha256:original',
               now() + interval '1 day')
            """
        ),
        {"user_id": user_id},
    )

    stored = migrated_connection.execute(
        text(
            """
            select command_name, request_fingerprint
            from idempotency_records
            where user_id = :user_id and idempotency_key = 'command-key'
            """
        ),
        {"user_id": user_id},
    ).one()

    assert stored.command_name == "create_exploration"
    assert stored.request_fingerprint != "sha256:different"
