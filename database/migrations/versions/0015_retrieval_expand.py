"""Expand ontology edges for explicit, data-preserving REQUIRES curation.

Revision ID: 0015_retrieval_expand
Revises: 0014_objective_categorical_state

After this revision, curate each existing REQUIRES row's exact source version,
target version, prerequisite objective, and HARD/SOFT requirement. No value is
inferred from legacy entity-only edges. Then apply 0015_recommendation_retrieval.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0015_retrieval_expand"
down_revision: str | None = "0014_objective_categorical_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for column in (
        sa.Column("source_entity_version", sa.Integer()),
        sa.Column("target_entity_version", sa.Integer()),
        sa.Column("objective_id", sa.UUID()),
        sa.Column("requirement", sa.Text()),
    ):
        op.add_column("ontology_edges", column)
    op.create_unique_constraint(
        op.f("uq_learning_objectives_id_entity_version"),
        "learning_objectives", ["id", "entity_id", "entity_version"],
    )
    op.create_foreign_key(
        op.f("fk_ontology_edges_source_version"), "ontology_edges",
        "learning_entity_versions", ["source_entity_id", "source_entity_version"],
        ["entity_id", "version"],
    )
    op.create_foreign_key(
        op.f("fk_ontology_edges_target_version"), "ontology_edges",
        "learning_entity_versions", ["target_entity_id", "target_entity_version"],
        ["entity_id", "version"],
    )
    op.create_foreign_key(
        op.f("fk_ontology_edges_objective_target_version"), "ontology_edges",
        "learning_objectives",
        ["objective_id", "target_entity_id", "target_entity_version"],
        ["id", "entity_id", "entity_version"],
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_ontology_edges_objective_target_version"),
        "ontology_edges", type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_ontology_edges_target_version"),
        "ontology_edges", type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_ontology_edges_source_version"),
        "ontology_edges", type_="foreignkey",
    )
    op.drop_constraint(
        op.f("uq_learning_objectives_id_entity_version"),
        "learning_objectives", type_="unique",
    )
    for column in (
        "requirement", "objective_id", "target_entity_version",
        "source_entity_version",
    ):
        op.drop_column("ontology_edges", column)
