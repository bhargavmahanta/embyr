from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LearningEntity(Base):
    __tablename__ = "learning_entities"
    __table_args__ = (
        sa.CheckConstraint(
            "entity_type in ('DOMAIN', 'AREA', 'TOPIC', 'CONCEPT', 'SKILL', "
            "'TECHNIQUE', 'JOURNEY')",
            name="learning_entities_type",
        ),
        sa.CheckConstraint(
            "current_version is null or current_version > 0",
            name="learning_entities_current_version",
        ),
        sa.UniqueConstraint("canonical_key", name="uq_learning_entities_key"),
        sa.ForeignKeyConstraint(
            ["id", "current_version"],
            ["learning_entity_versions.entity_id", "learning_entity_versions.version"],
            name="fk_learning_entities_current_version",
            use_alter=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    canonical_key: Mapped[str] = mapped_column(sa.Text)
    entity_type: Mapped[str] = mapped_column(sa.Text)
    status: Mapped[str] = mapped_column(sa.Text)
    current_version: Mapped[int | None] = mapped_column(sa.Integer)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )


class LearningEntityVersion(Base):
    __tablename__ = "learning_entity_versions"
    __table_args__ = (
        sa.UniqueConstraint(
            "entity_id", "version", name="uq_learning_entity_versions_entity_version"
        ),
        sa.CheckConstraint("version > 0", name="learning_entity_versions_version"),
        sa.CheckConstraint(
            "knowledge_types <@ array['FACTUAL', 'CONCEPTUAL', 'PROCEDURAL', "
            "'REASONING', 'CREATIVE', 'PRACTICAL']::text[]",
            name="learning_entity_versions_knowledge_types",
        ),
        sa.CheckConstraint(
            "difficulty_prior is null or "
            "(difficulty_prior >= 0 and difficulty_prior <= 1)",
            name="learning_entity_versions_difficulty_prior",
        ),
        sa.CheckConstraint(
            "estimated_effort_minutes is null or estimated_effort_minutes > 0",
            name="learning_entity_versions_effort",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    entity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        sa.ForeignKey("learning_entities.id", ondelete="CASCADE"),
    )
    version: Mapped[int] = mapped_column(sa.Integer)
    title: Mapped[str] = mapped_column(sa.Text)
    summary: Mapped[str] = mapped_column(sa.Text)
    knowledge_types: Mapped[list[str]] = mapped_column(ARRAY(sa.Text))
    scope: Mapped[str] = mapped_column(sa.Text)
    difficulty_prior: Mapped[float | None] = mapped_column(sa.Double)
    estimated_effort_minutes: Mapped[int | None] = mapped_column(sa.Integer)
    freshness_requirement: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    provenance: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=sa.text("'{}'::jsonb")
    )
    source_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=sa.text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )


class EntityDomain(Base):
    __tablename__ = "entity_domains"
    __table_args__ = (
        sa.CheckConstraint(
            "membership_strength >= 0 and membership_strength <= 1",
            name="entity_domains_membership_strength",
        ),
        sa.Index("ix_entity_domains_domain_primary", "domain_id", "is_primary"),
        sa.Index(
            "uq_entity_domains_one_primary",
            "entity_id",
            unique=True,
            postgresql_where=sa.text("is_primary"),
        ),
    )

    entity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        sa.ForeignKey("learning_entities.id", ondelete="CASCADE"),
        primary_key=True,
    )
    domain_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        sa.ForeignKey("learning_entities.id", ondelete="CASCADE"),
        primary_key=True,
    )
    is_primary: Mapped[bool] = mapped_column(
        sa.Boolean, server_default=sa.text("false")
    )
    membership_strength: Mapped[float] = mapped_column(sa.Double)


class OntologyEdge(Base):
    __tablename__ = "ontology_edges"
    __table_args__ = (
        sa.CheckConstraint(
            "source_entity_id <> target_entity_id", name="ontology_edges_distinct"
        ),
        sa.CheckConstraint(
            "confidence >= 0 and confidence <= 1", name="ontology_edges_confidence"
        ),
        sa.CheckConstraint(
            "relationship_type in ('REQUIRES', 'BUILDS_ON', 'PART_OF', "
            "'RELATED_TO', 'CONTRASTS_WITH', 'APPLIES_TO', 'LEADS_TO', "
            "'EXAMPLE_OF', 'BELONGS_TO', 'CAN_BE_EXPLORED_AS')",
            name="ontology_edges_relationship_type",
        ),
        sa.Index(
            "ix_ontology_edges_source_type",
            "source_entity_id",
            "relationship_type",
        ),
        sa.Index(
            "ix_ontology_edges_target_type",
            "target_entity_id",
            "relationship_type",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    source_entity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), sa.ForeignKey("learning_entities.id")
    )
    target_entity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), sa.ForeignKey("learning_entities.id")
    )
    relationship_type: Mapped[str] = mapped_column(sa.Text)
    strength: Mapped[str | None] = mapped_column(sa.Text)
    context: Mapped[str | None] = mapped_column(sa.Text)
    confidence: Mapped[float] = mapped_column(sa.Double)
    provenance: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=sa.text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )


class LearningObjective(Base):
    __tablename__ = "learning_objectives"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["entity_id", "entity_version"],
            ["learning_entity_versions.entity_id", "learning_entity_versions.version"],
            name="fk_learning_objectives_entity_version",
        ),
        sa.UniqueConstraint(
            "entity_id", "id", name="uq_learning_objectives_entity_id_id"
        ),
        sa.CheckConstraint(
            "importance >= 0 and importance <= 1",
            name="learning_objectives_importance",
        ),
        sa.Index(
            "ix_learning_objectives_entity_version", "entity_id", "entity_version"
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    entity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    entity_version: Mapped[int] = mapped_column(sa.Integer)
    objective_type: Mapped[str] = mapped_column(sa.Text)
    description: Mapped[str] = mapped_column(sa.Text)
    importance: Mapped[float] = mapped_column(sa.Double)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )


class Misconception(Base):
    __tablename__ = "misconceptions"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    entity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), sa.ForeignKey("learning_entities.id")
    )
    objective_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), sa.ForeignKey("learning_objectives.id")
    )
    description: Mapped[str] = mapped_column(sa.Text)
    canonical_correction: Mapped[str] = mapped_column(sa.Text)
    severity: Mapped[str] = mapped_column(sa.Text)
    provenance: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=sa.text("'{}'::jsonb")
    )


class Claim(Base):
    __tablename__ = "claims"
    __table_args__ = (
        sa.CheckConstraint(
            "claim_type in ('ESTABLISHED_FACT', 'SUPPORTED_EXPLANATION', "
            "'CONTESTED_CLAIM', 'INTERPRETATION', 'NORMATIVE_POSITION')",
            name="claims_type",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    entity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), sa.ForeignKey("learning_entities.id")
    )
    claim_type: Mapped[str] = mapped_column(sa.Text)
    statement: Mapped[str] = mapped_column(sa.Text)
    provenance: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=sa.text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )


class EntityEmbedding(Base):
    __tablename__ = "entity_embeddings"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["entity_id", "entity_version"],
            ["learning_entity_versions.entity_id", "learning_entity_versions.version"],
            name="fk_entity_embeddings_entity_version",
        ),
        sa.UniqueConstraint(
            "entity_id",
            "embedding_model",
            "entity_version",
            name="uq_entity_embeddings_entity_model_version",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    entity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    entity_version: Mapped[int] = mapped_column(sa.Integer)
    embedding: Mapped[Any] = mapped_column(Vector())
    embedding_model: Mapped[str] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
