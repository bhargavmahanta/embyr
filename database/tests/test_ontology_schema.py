from __future__ import annotations

from uuid import uuid4
import hashlib

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DataError, IntegrityError


def _insert_entity(connection, entity_type: str = "TOPIC"):
    return connection.execute(
        text(
            """
            insert into learning_entities
              (canonical_key, entity_type, status)
            values
              (:canonical_key, :entity_type, 'REVIEWED')
            returning id
            """
        ),
        {"canonical_key": f"entity-{uuid4()}", "entity_type": entity_type},
    ).scalar_one()


def _insert_version(connection, entity_id, version: int = 1):
    return connection.execute(
        text(
            """
            insert into learning_entity_versions
              (entity_id, version, title, summary, knowledge_types, scope,
               difficulty_prior, estimated_effort_minutes, provenance,
               source_metadata)
            values
              (:entity_id, :version, :title, 'Summary', array['CONCEPTUAL'],
               'NORMAL', 0.5, 15, '{}'::jsonb, '{}'::jsonb)
            returning id
            """
        ),
        {"entity_id": entity_id, "version": version, "title": f"Version {version}"},
    ).scalar_one()


def test_entity_versions_are_unique_and_current_version_must_exist(
    migrated_connection,
):
    entity_id = _insert_entity(migrated_connection)
    _insert_version(migrated_connection, entity_id, 1)
    migrated_connection.execute(
        text("update learning_entities set current_version = 1 where id = :id"),
        {"id": entity_id},
    )

    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        _insert_version(migrated_connection, entity_id, 1)

    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        migrated_connection.execute(
            text("update learning_entities set current_version = 2 where id = :id"),
            {"id": entity_id},
        )


def test_entity_has_at_most_one_primary_domain(migrated_connection):
    entity_id = _insert_entity(migrated_connection)
    first_domain = _insert_entity(migrated_connection, "DOMAIN")
    second_domain = _insert_entity(migrated_connection, "DOMAIN")
    statement = text(
        """
        insert into entity_domains
          (entity_id, domain_id, is_primary, membership_strength)
        values (:entity_id, :domain_id, true, 1.0)
        """
    )
    migrated_connection.execute(
        statement, {"entity_id": entity_id, "domain_id": first_domain}
    )

    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        migrated_connection.execute(
            statement, {"entity_id": entity_id, "domain_id": second_domain}
        )


def test_ontology_edges_reject_self_edges_and_invalid_confidence(
    migrated_connection,
):
    source = _insert_entity(migrated_connection)
    target = _insert_entity(migrated_connection)
    statement = text(
        """
        insert into ontology_edges
          (source_entity_id, target_entity_id, relationship_type, confidence,
           provenance, status)
        values
          (:source, :target, 'RELATED_TO', :confidence, '{}'::jsonb, 'ACTIVE')
        """
    )

    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        migrated_connection.execute(
            statement,
            {"source": source, "target": source, "confidence": 0.8},
        )

    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        migrated_connection.execute(
            statement,
            {"source": source, "target": target, "confidence": 1.1},
        )


def test_objective_requires_an_existing_entity_version(migrated_connection):
    entity_id = _insert_entity(migrated_connection)
    _insert_version(migrated_connection, entity_id, 1)
    statement = text(
        """
        insert into learning_objectives
          (entity_id, entity_version, objective_type, description, importance)
        values (:entity_id, :version, 'EXPLANATION', 'Explain it', 0.8)
        """
    )

    migrated_connection.execute(statement, {"entity_id": entity_id, "version": 1})
    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        migrated_connection.execute(
            statement, {"entity_id": entity_id, "version": 2}
        )


def test_embeddings_use_one_versioned_voyage_identity(migrated_connection):
    entity_id = _insert_entity(migrated_connection)
    _insert_version(migrated_connection, entity_id, 1)
    vector = "[" + ",".join(["0.1"] + ["0"] * 1023) + "]"
    statement = text(
        """
        insert into entity_embeddings
          (entity_id, entity_version, embedding_model, embedding,
           embedding_provider, embedding_dimension, embedding_input_version,
           embedding_input_type, embedding_input_fingerprint)
        values (:entity_id, 1, :model, cast(:vector as vector(1024)),
                'voyage-ai', 1024, 'ontology-entity/v1', 'document', :fingerprint)
        """
    )
    params = {
        "entity_id": entity_id, "model": "voyage-4", "vector": vector,
        "fingerprint": "sha256:" + hashlib.sha256(
            b"TITLE: Version 1\nSUMMARY: Summary"
        ).hexdigest(),
    }
    migrated_connection.execute(statement, params)
    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        migrated_connection.execute(statement, params)
    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        migrated_connection.execute(statement, {**params, "model": "other-model"})
    for column, value in (
        ("embedding_input_version", "other-recipe/v1"),
        ("embedding_input_type", "query"),
        ("embedding_input_fingerprint", "not-a-sha256-digest"),
    ):
        with pytest.raises(IntegrityError), migrated_connection.begin_nested():
            migrated_connection.execute(
                text(f"update entity_embeddings set {column} = :value where entity_id = :id"),
                {"value": value, "id": entity_id},
            )
    with pytest.raises(DataError), migrated_connection.begin_nested():
        migrated_connection.execute(
            text("update entity_embeddings set embedding = '[1,0,0,0]'::vector "
                 "where entity_id = :id"),
            {"id": entity_id},
        )


def test_requires_exact_versioned_objective_and_named_constraints(migrated_connection):
    connection = migrated_connection
    source, target, unrelated = (_insert_entity(connection) for _ in range(3))
    for entity in (source, target, unrelated):
        _insert_version(connection, entity, 1)
    _insert_version(connection, target, 2)
    objective = connection.execute(text("""
        insert into learning_objectives
          (entity_id, entity_version, objective_type, description, importance)
        values (:entity_id, 1, 'UNDERSTANDING', 'Understand', 0.5)
        returning id
    """), {"entity_id": target}).scalar_one()
    other_objective = connection.execute(text("""
        insert into learning_objectives
          (entity_id, entity_version, objective_type, description, importance)
        values (:entity_id, 1, 'UNDERSTANDING', 'Understand', 0.5)
        returning id
    """), {"entity_id": unrelated}).scalar_one()
    statement = text("""
        insert into ontology_edges
          (source_entity_id, source_entity_version, target_entity_id,
           target_entity_version, objective_id, requirement,
           relationship_type, confidence, status)
        values (:source, :source_version, :target, :target_version, :objective,
                :requirement, 'REQUIRES', 0.8, 'ACTIVE')
    """)
    valid = {
        "source": source, "source_version": 1,
        "target": target, "target_version": 1,
        "objective": objective, "requirement": "HARD",
    }
    connection.execute(statement, valid)
    connection.execute(statement, {**valid, "requirement": "SOFT"})
    for invalid in (
        {**valid, "source_version": 2},
        {**valid, "target_version": 2},
        {**valid, "objective": other_objective},
        {**valid, "requirement": "OPTIONAL"},
    ):
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(statement, invalid)

    names = set(connection.execute(text("""
        select conname from pg_constraint
         where conrelid in ('public.ontology_edges'::regclass,
                            'public.entity_embeddings'::regclass,
                            'public.learning_objectives'::regclass)
    """)).scalars())
    assert "ck_ontology_edges_requires_identity" in names
    assert "ck_entity_embeddings_voyage_v1_identity" in names
    assert "fk_ontology_edges_objective_target_version" in names
    assert "fk_ontology_edges_source_version" in names
    assert "fk_ontology_edges_target_version" in names
    assert "uq_learning_objectives_id_entity_version" in names
