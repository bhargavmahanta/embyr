"""Versioned REQUIRES semantics and a single 1024-D embedding search identity.

Revision ID: 0015_recommendation_retrieval
Revises: 0014_objective_categorical_state

Existing derived embeddings must be explicitly re-embedded into the selected
Voyage identity. Existing REQUIRES edges must be curated with objective and
version identity before this migration, since silent backfill is unsafe.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision: str = "0015_recommendation_retrieval"
down_revision: str | None = "0014_objective_categorical_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    embeddings = bind.execute(sa.text("select count(*) from public.entity_embeddings")).scalar_one()
    if embeddings:
        raise RuntimeError(
            "entity_embeddings must be explicitly re-embedded for voyage-4/1024 "
            "before applying 0015; existing vectors are never silently migrated"
        )
    requires = bind.execute(sa.text(
        "select count(*) from public.ontology_edges "
        "where relationship_type = 'REQUIRES'"
    )).scalar_one()
    if requires:
        raise RuntimeError(
            "existing REQUIRES edges need explicit objective/version curation "
            "before applying 0015"
        )

    op.alter_column(
        "entity_embeddings", "embedding", type_=Vector(1024),
        postgresql_using="embedding::vector(1024)",
    )
    op.add_column("entity_embeddings", sa.Column("embedding_provider", sa.Text(), nullable=False))
    op.add_column("entity_embeddings", sa.Column("embedding_dimension", sa.Integer(), nullable=False))
    op.add_column("entity_embeddings", sa.Column("embedding_input_version", sa.Text(), nullable=False))
    op.add_column("entity_embeddings", sa.Column("embedding_input_type", sa.Text(), nullable=False))
    op.create_check_constraint(
        "ck_entity_embeddings_voyage_v1_identity", "entity_embeddings",
        "embedding_provider = 'voyage-ai' and embedding_model = 'voyage-4' "
        "and embedding_dimension = 1024 and embedding_input_type = 'document' "
        "and embedding_input_version = 'entity-document/v1'",
    )

    op.add_column("ontology_edges", sa.Column("source_entity_version", sa.Integer()))
    op.add_column("ontology_edges", sa.Column("target_entity_version", sa.Integer()))
    op.add_column("ontology_edges", sa.Column("objective_id", sa.UUID()))
    op.add_column("ontology_edges", sa.Column("requirement", sa.Text()))
    op.create_foreign_key(
        "fk_ontology_edges_source_version", "ontology_edges",
        "learning_entity_versions", ["source_entity_id", "source_entity_version"],
        ["entity_id", "version"],
    )
    op.create_foreign_key(
        "fk_ontology_edges_target_version", "ontology_edges",
        "learning_entity_versions", ["target_entity_id", "target_entity_version"],
        ["entity_id", "version"],
    )
    op.create_foreign_key(
        "fk_ontology_edges_objective", "ontology_edges",
        "learning_objectives", ["objective_id"], ["id"],
    )
    op.create_check_constraint(
        "ck_ontology_edges_requires_identity", "ontology_edges",
        "(relationship_type = 'REQUIRES' and source_entity_version is not null "
        "and target_entity_version is not null and objective_id is not null "
        "and requirement in ('HARD', 'SOFT')) or "
        "(relationship_type <> 'REQUIRES' and objective_id is null "
        "and requirement is null)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_ontology_edges_requires_identity", "ontology_edges", type_="check")
    op.drop_constraint("fk_ontology_edges_objective", "ontology_edges", type_="foreignkey")
    op.drop_constraint("fk_ontology_edges_target_version", "ontology_edges", type_="foreignkey")
    op.drop_constraint("fk_ontology_edges_source_version", "ontology_edges", type_="foreignkey")
    for column in ("requirement", "objective_id", "target_entity_version", "source_entity_version"):
        op.drop_column("ontology_edges", column)
    op.drop_constraint("ck_entity_embeddings_voyage_v1_identity", "entity_embeddings", type_="check")
    for column in ("embedding_input_type", "embedding_input_version", "embedding_dimension", "embedding_provider"):
        op.drop_column("entity_embeddings", column)
    op.alter_column(
        "entity_embeddings", "embedding", type_=Vector(),
        postgresql_using="embedding::vector",
    )
