"""Unit tests for server-owned Storage object keys."""
from __future__ import annotations

from uuid import uuid4

import pytest

from app.storage.keys import (
    InvalidObjectKey,
    generate_artifact_object_key,
    validate_object_key,
)


def test_generated_key_uses_canonical_owner_prefix_and_opaque_leaf():
    user_id = uuid4()
    key = generate_artifact_object_key(user_id)

    assert key.startswith(f"users/{user_id}/artifacts/")
    assert validate_object_key(key, user_id=user_id) == key
    leaf = key.rsplit("/", 1)[1]
    assert len(leaf) == 36  # opaque uuid4 leaf, never a client filename


def test_generated_keys_are_unique_per_call():
    user_id = uuid4()
    keys = {generate_artifact_object_key(user_id) for _ in range(50)}
    assert len(keys) == 50


@pytest.mark.parametrize(
    "key",
    [
        "",
        "   ",
        "users/x/artifacts/y ",
        "https://storage.test/signed?token=abc",
        "/users/x/artifacts/y",
        "users/../artifacts/y",
        "users/x/artifacts/../../etc/passwd",
        "users\\x\\artifacts\\y",
        "users//artifacts/y",
        "users/x/./artifacts/y",
    ],
)
def test_invalid_keys_are_rejected(key):
    with pytest.raises(InvalidObjectKey):
        validate_object_key(key)


def test_owner_scope_rejects_foreign_or_non_uuid_leaves():
    user_id = uuid4()
    other = uuid4()
    with pytest.raises(InvalidObjectKey):
        validate_object_key(f"users/{other}/artifacts/{uuid4()}", user_id=user_id)
    with pytest.raises(InvalidObjectKey):
        validate_object_key(
            f"users/{user_id}/artifacts/original-filename.jpg", user_id=user_id
        )


def test_owner_scope_accepts_own_key():
    user_id = uuid4()
    key = generate_artifact_object_key(user_id)
    assert validate_object_key(key, user_id=user_id) == key
