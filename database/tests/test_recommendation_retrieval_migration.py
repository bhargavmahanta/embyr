"""Focused data-preserving 0015 expansion, curation, and enforcement proof."""
from __future__ import annotations

import pytest
from alembic import command
from sqlalchemy import create_engine, text

from conftest import make_alembic_config, provision_runtime_roles

EXPAND = "0015_retrieval_expand"
ENFORCE = "0015_recommendation_retrieval"


def test_legacy_requires_survives_expand_and_curated_enforcement(database_url):
    engine = create_engine(database_url)
    config = make_alembic_config(database_url)
    provision_runtime_roles(engine)
    try:
        command.upgrade(config, "0014_objective_categorical_state")
        with engine.begin() as connection:
            entities = [connection.execute(text("""
                insert into learning_entities (canonical_key, entity_type, status)
                values (:key, 'TOPIC', 'REVIEWED') returning id
            """), {"key": f"migration-{index}"}).scalar_one() for index in range(2)]
            for entity_id in entities:
                connection.execute(text("""
                    insert into learning_entity_versions
                      (entity_id, version, title, summary, knowledge_types, scope)
                    values (:entity_id, 1, 'Title', 'Summary',
                            array['CONCEPTUAL'], 'NORMAL')
                """), {"entity_id": entity_id})
                connection.execute(text("""
                    update learning_entities set current_version = 1 where id = :id
                """), {"id": entity_id})
            objective = connection.execute(text("""
                insert into learning_objectives
                  (entity_id, entity_version, objective_type, description, importance)
                values (:entity_id, 1, 'UNDERSTANDING', 'Understand', 0.5)
                returning id
            """), {"entity_id": entities[1]}).scalar_one()
            edge = connection.execute(text("""
                insert into ontology_edges
                  (source_entity_id, target_entity_id, relationship_type,
                   confidence, status)
                values (:source, :target, 'REQUIRES', 0.8, 'ACTIVE')
                returning id
            """), {"source": entities[0], "target": entities[1]}).scalar_one()
            connection.execute(text("""
                insert into entity_embeddings
                  (entity_id, entity_version, embedding_model, embedding)
                values (:entity_id, 1, 'legacy-model', '[1,0,0,0]'::vector)
            """), {"entity_id": entities[0]})

        command.upgrade(config, EXPAND)
        with engine.connect() as connection:
            row = connection.execute(text("""
                select source_entity_version, target_entity_version,
                       objective_id, requirement from ontology_edges where id = :id
            """), {"id": edge}).one()
            assert row == (None, None, None, None)
        with pytest.raises(RuntimeError, match="clear the old derived"):
            command.upgrade(config, ENFORCE)
        with engine.begin() as connection:
            connection.execute(text("delete from entity_embeddings"))
        with pytest.raises(RuntimeError, match="REQUIRES edge"):
            command.upgrade(config, ENFORCE)

        with engine.begin() as connection:
            connection.execute(text("""
                update ontology_edges
                   set source_entity_version = 1, target_entity_version = 1,
                       objective_id = :objective, requirement = 'HARD'
                 where id = :id
            """), {"objective": objective, "id": edge})
        command.upgrade(config, ENFORCE)
        with engine.connect() as connection:
            assert connection.execute(text("""
                select version_num from alembic_version
            """)).scalar_one() == ENFORCE
            assert connection.execute(text("""
                select count(*) from ontology_edges
                 where id = :id and objective_id = :objective
                   and source_entity_version = 1 and target_entity_version = 1
                   and requirement = 'HARD'
            """), {"id": edge, "objective": objective}).scalar_one() == 1
    finally:
        command.downgrade(config, "base")
        engine.dispose()
