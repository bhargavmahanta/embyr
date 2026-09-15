"""Create the versioned relational ontology and vector storage.

Revision ID: 0002_ontology
Revises: 0001_foundation
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0002_ontology"
down_revision: str | None = "0001_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid() -> postgresql.UUID:
    return postgresql.UUID(as_uuid=True)


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "learning_entities",
        sa.Column(
            "id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("canonical_key", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("current_version", sa.Integer()),
        _created_at(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "entity_type in ('DOMAIN', 'AREA', 'TOPIC', 'CONCEPT', 'SKILL', "
            "'TECHNIQUE', 'JOURNEY')",
            name="ck_learning_entities_type",
        ),
        sa.CheckConstraint(
            "current_version is null or current_version > 0",
            name="ck_learning_entities_current_version",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_learning_entities"),
        sa.UniqueConstraint("canonical_key", name="uq_learning_entities_key"),
    )

    op.create_table(
        "learning_entity_versions",
        sa.Column(
            "id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("entity_id", _uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("knowledge_types", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("difficulty_prior", sa.Double()),
        sa.Column("estimated_effort_minutes", sa.Integer()),
        sa.Column("freshness_requirement", postgresql.JSONB()),
        sa.Column(
            "provenance",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "source_metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        _created_at(),
        sa.CheckConstraint("version > 0", name="ck_learning_entity_versions_version"),
        sa.CheckConstraint(
            "knowledge_types <@ array['FACTUAL', 'CONCEPTUAL', 'PROCEDURAL', "
            "'REASONING', 'CREATIVE', 'PRACTICAL']::text[]",
            name="ck_learning_entity_versions_knowledge_types",
        ),
        sa.CheckConstraint(
            "difficulty_prior is null or "
            "(difficulty_prior >= 0 and difficulty_prior <= 1)",
            name="ck_learning_entity_versions_difficulty_prior",
        ),
        sa.CheckConstraint(
            "estimated_effort_minutes is null or estimated_effort_minutes > 0",
            name="ck_learning_entity_versions_effort",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["learning_entities.id"],
            ondelete="CASCADE",
            name="fk_learning_entity_versions_entity_id_learning_entities",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_learning_entity_versions"),
        sa.UniqueConstraint(
            "entity_id", "version", name="uq_learning_entity_versions_entity_version"
        ),
    )
    op.create_foreign_key(
        "fk_learning_entities_current_version",
        "learning_entities",
        "learning_entity_versions",
        ["id", "current_version"],
        ["entity_id", "version"],
    )

    op.create_table(
        "entity_domains",
        sa.Column("entity_id", _uuid(), nullable=False),
        sa.Column("domain_id", _uuid(), nullable=False),
        sa.Column(
            "is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("membership_strength", sa.Double(), nullable=False),
        sa.CheckConstraint(
            "membership_strength >= 0 and membership_strength <= 1",
            name="ck_entity_domains_membership_strength",
        ),
        sa.ForeignKeyConstraint(
            ["domain_id"],
            ["learning_entities.id"],
            ondelete="CASCADE",
            name="fk_entity_domains_domain_id_learning_entities",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["learning_entities.id"],
            ondelete="CASCADE",
            name="fk_entity_domains_entity_id_learning_entities",
        ),
        sa.PrimaryKeyConstraint("entity_id", "domain_id", name="pk_entity_domains"),
    )
    op.create_index(
        "ix_entity_domains_domain_primary",
        "entity_domains",
        ["domain_id", "is_primary"],
    )
    op.create_index(
        "uq_entity_domains_one_primary",
        "entity_domains",
        ["entity_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
    )

    op.create_table(
        "ontology_edges",
        sa.Column(
            "id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("source_entity_id", _uuid(), nullable=False),
        sa.Column("target_entity_id", _uuid(), nullable=False),
        sa.Column("relationship_type", sa.Text(), nullable=False),
        sa.Column("strength", sa.Text()),
        sa.Column("context", sa.Text()),
        sa.Column("confidence", sa.Double(), nullable=False),
        sa.Column(
            "provenance",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), nullable=False),
        _created_at(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source_entity_id <> target_entity_id", name="ck_ontology_edges_distinct"
        ),
        sa.CheckConstraint(
            "confidence >= 0 and confidence <= 1",
            name="ck_ontology_edges_confidence",
        ),
        sa.CheckConstraint(
            "relationship_type in ('REQUIRES', 'BUILDS_ON', 'PART_OF', "
            "'RELATED_TO', 'CONTRASTS_WITH', 'APPLIES_TO', 'LEADS_TO', "
            "'EXAMPLE_OF', 'BELONGS_TO', 'CAN_BE_EXPLORED_AS')",
            name="ck_ontology_edges_relationship_type",
        ),
        sa.ForeignKeyConstraint(
            ["source_entity_id"],
            ["learning_entities.id"],
            name="fk_ontology_edges_source_entity_id_learning_entities",
        ),
        sa.ForeignKeyConstraint(
            ["target_entity_id"],
            ["learning_entities.id"],
            name="fk_ontology_edges_target_entity_id_learning_entities",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ontology_edges"),
    )
    op.create_index(
        "ix_ontology_edges_source_type",
        "ontology_edges",
        ["source_entity_id", "relationship_type"],
    )
    op.create_index(
        "ix_ontology_edges_target_type",
        "ontology_edges",
        ["target_entity_id", "relationship_type"],
    )

    op.create_table(
        "learning_objectives",
        sa.Column(
            "id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("entity_id", _uuid(), nullable=False),
        sa.Column("entity_version", sa.Integer(), nullable=False),
        sa.Column("objective_type", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("importance", sa.Double(), nullable=False),
        _created_at(),
        sa.CheckConstraint(
            "importance >= 0 and importance <= 1",
            name="ck_learning_objectives_importance",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id", "entity_version"],
            ["learning_entity_versions.entity_id", "learning_entity_versions.version"],
            name="fk_learning_objectives_entity_version",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_learning_objectives"),
    )
    op.create_index(
        "ix_learning_objectives_entity_version",
        "learning_objectives",
        ["entity_id", "entity_version"],
    )

    op.create_table(
        "misconceptions",
        sa.Column(
            "id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("entity_id", _uuid(), nullable=False),
        sa.Column("objective_id", _uuid()),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("canonical_correction", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column(
            "provenance",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["learning_entities.id"],
            name="fk_misconceptions_entity_id_learning_entities",
        ),
        sa.ForeignKeyConstraint(
            ["objective_id"],
            ["learning_objectives.id"],
            name="fk_misconceptions_objective_id_learning_objectives",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_misconceptions"),
    )

    op.create_table(
        "claims",
        sa.Column(
            "id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("entity_id", _uuid(), nullable=False),
        sa.Column("claim_type", sa.Text(), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column(
            "provenance",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        _created_at(),
        sa.CheckConstraint(
            "claim_type in ('ESTABLISHED_FACT', 'SUPPORTED_EXPLANATION', "
            "'CONTESTED_CLAIM', 'INTERPRETATION', 'NORMATIVE_POSITION')",
            name="ck_claims_type",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["learning_entities.id"],
            name="fk_claims_entity_id_learning_entities",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_claims"),
    )

    op.create_table(
        "entity_embeddings",
        sa.Column(
            "id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("entity_id", _uuid(), nullable=False),
        sa.Column("entity_version", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(), nullable=False),
        sa.Column("embedding_model", sa.Text(), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["entity_id", "entity_version"],
            ["learning_entity_versions.entity_id", "learning_entity_versions.version"],
            name="fk_entity_embeddings_entity_version",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_entity_embeddings"),
        sa.UniqueConstraint(
            "entity_id",
            "embedding_model",
            "entity_version",
            name="uq_entity_embeddings_entity_model_version",
        ),
    )


def downgrade() -> None:
    op.drop_table("entity_embeddings")
    op.drop_table("claims")
    op.drop_table("misconceptions")
    op.drop_index(
        "ix_learning_objectives_entity_version", table_name="learning_objectives"
    )
    op.drop_table("learning_objectives")
    op.drop_index("ix_ontology_edges_target_type", table_name="ontology_edges")
    op.drop_index("ix_ontology_edges_source_type", table_name="ontology_edges")
    op.drop_table("ontology_edges")
    op.drop_index("uq_entity_domains_one_primary", table_name="entity_domains")
    op.drop_index("ix_entity_domains_domain_primary", table_name="entity_domains")
    op.drop_table("entity_domains")
    op.drop_constraint(
        "fk_learning_entities_current_version",
        "learning_entities",
        type_="foreignkey",
    )
    op.drop_table("learning_entity_versions")
    op.drop_table("learning_entities")
