"""Versioned REQUIRES semantics and a single 1024-D embedding search identity.

Revision ID: 0015_recommendation_retrieval
Revises: 0015_retrieval_expand

The preceding expansion preserves legacy REQUIRES rows for explicit curation.
Clear the old derived embedding corpus before enforcement; rebuild it afterward
with Voyage document vectors and exact ontology-entity/v1 input fingerprints.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision: str = "0015_recommendation_retrieval"
down_revision: str | None = "0015_retrieval_expand"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    embeddings = bind.execute(sa.text("select count(*) from public.entity_embeddings")).scalar_one()
    if embeddings:
        raise RuntimeError(
            "clear the old derived entity_embeddings corpus before applying "
            "0015, then rebuild voyage-4/1024 ontology-entity/v1 documents"
        )
    requires = bind.execute(sa.text(
        "select count(*) from public.ontology_edges "
        "where relationship_type = 'REQUIRES' and "
        "(source_entity_version is null or target_entity_version is null "
        "or objective_id is null or requirement is null "
        "or requirement not in ('HARD', 'SOFT'))"
    )).scalar_one()
    if requires:
        raise RuntimeError(
            f"{requires} REQUIRES edge(s) still need explicit source/target "
            "versions, matching objective, and HARD/SOFT requirement; curate "
            "them after 0015_retrieval_expand"
        )

    op.alter_column(
        "entity_embeddings", "embedding", type_=Vector(1024),
        postgresql_using="embedding::vector(1024)",
    )
    op.add_column("entity_embeddings", sa.Column("embedding_provider", sa.Text(), nullable=False))
    op.add_column("entity_embeddings", sa.Column("embedding_dimension", sa.Integer(), nullable=False))
    op.add_column("entity_embeddings", sa.Column("embedding_input_version", sa.Text(), nullable=False))
    op.add_column("entity_embeddings", sa.Column("embedding_input_type", sa.Text(), nullable=False))
    op.add_column("entity_embeddings", sa.Column("embedding_input_fingerprint", sa.Text(), nullable=False))
    op.create_check_constraint(
        op.f("ck_entity_embeddings_voyage_v1_identity"), "entity_embeddings",
        "embedding_provider = 'voyage-ai' and embedding_model = 'voyage-4' "
        "and embedding_dimension = 1024 and embedding_input_type = 'document' "
        "and embedding_input_version = 'ontology-entity/v1' "
        "and embedding_input_fingerprint ~ '^sha256:[0-9a-f]{64}$'",
    )
    op.create_check_constraint(
        op.f("ck_ontology_edges_requires_identity"), "ontology_edges",
        "(relationship_type = 'REQUIRES' and source_entity_version is not null "
        "and target_entity_version is not null and objective_id is not null "
        "and requirement in ('HARD', 'SOFT')) or "
        "(relationship_type <> 'REQUIRES' and objective_id is null "
        "and requirement is null)",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_ontology_edges_requires_identity"), "ontology_edges", type_="check",
    )
    op.drop_constraint(
        op.f("ck_entity_embeddings_voyage_v1_identity"),
        "entity_embeddings", type_="check",
    )
    for column in (
        "embedding_input_fingerprint", "embedding_input_type",
        "embedding_input_version", "embedding_dimension", "embedding_provider",
    ):
        op.drop_column("entity_embeddings", column)
    op.alter_column(
        "entity_embeddings", "embedding", type_=Vector(),
        postgresql_using="embedding::vector",
    )
