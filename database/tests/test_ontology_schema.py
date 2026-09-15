from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


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


def test_embeddings_are_versioned_by_model(migrated_connection):
    entity_id = _insert_entity(migrated_connection)
    _insert_version(migrated_connection, entity_id, 1)
    statement = text(
        """
        insert into entity_embeddings
          (entity_id, entity_version, embedding_model, embedding)
        values (:entity_id, 1, :model, '[0.1,0.2,0.3]'::vector)
        """
    )

    migrated_connection.execute(
        statement, {"entity_id": entity_id, "model": "model-a"}
    )
    migrated_connection.execute(
        statement, {"entity_id": entity_id, "model": "model-b"}
    )
    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        migrated_connection.execute(
            statement, {"entity_id": entity_id, "model": "model-a"}
        )
