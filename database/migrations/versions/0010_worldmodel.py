"""Create the derived semantic WorldModel projection and delta log.

Revision ID: 0010_worldmodel
Revises: 0009_recommendations
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0010_worldmodel"
down_revision: str | None = "0009_recommendations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid() -> postgresql.UUID:
    return postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "learner_worlds",
        sa.Column(
            "id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("generation_seed", sa.Text(), nullable=False),
        sa.Column("layout_version", sa.Integer(), nullable=False),
        sa.Column(
            "current_revision",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "current_revision >= 0",
            name=op.f("ck_learner_worlds_current_revision"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            ondelete="CASCADE",
            name=op.f("fk_learner_worlds_user_id_app_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_learner_worlds")),
        sa.UniqueConstraint("user_id", name=op.f("uq_learner_worlds_user_id")),
        sa.UniqueConstraint(
            "user_id", "id", name=op.f("uq_learner_worlds_user_id_id")
        ),
    )

    op.create_table(
        "world_regions",
        sa.Column(
            "id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("world_id", _uuid(), nullable=False),
        sa.Column("region_key", sa.Text(), nullable=False),
        sa.Column("primary_domain_id", _uuid(), nullable=True),
        sa.Column("logical_x", sa.Double(), nullable=False),
        sa.Column("logical_y", sa.Double(), nullable=False),
        sa.Column("logical_width", sa.Double(), nullable=False),
        sa.Column("logical_height", sa.Double(), nullable=False),
        sa.Column("visual_archetype", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "logical_width > 0", name=op.f("ck_world_regions_logical_width")
        ),
        sa.CheckConstraint(
            "logical_height > 0", name=op.f("ck_world_regions_logical_height")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            ondelete="CASCADE",
            name=op.f("fk_world_regions_user_id_app_users"),
        ),
        sa.ForeignKeyConstraint(
            ["primary_domain_id"],
            ["learning_entities.id"],
            ondelete="SET NULL",
            name=op.f("fk_world_regions_primary_domain_id_learning_entities"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "world_id"],
            ["learner_worlds.user_id", "learner_worlds.id"],
            ondelete="CASCADE",
            name=op.f("fk_world_regions_world_owner"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_world_regions")),
        sa.UniqueConstraint(
            "user_id", "id", name=op.f("uq_world_regions_user_id_id")
        ),
    )
    op.create_index(
        "ix_world_regions_user_world",
        "world_regions",
        ["user_id", "world_id"],
    )

    op.create_table(
        "world_nodes",
        sa.Column(
            "id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("world_id", _uuid(), nullable=False),
        sa.Column("entity_id", _uuid(), nullable=False),
        sa.Column("region_id", _uuid(), nullable=True),
        sa.Column("logical_x", sa.Double(), nullable=False),
        sa.Column("logical_y", sa.Double(), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("visual_archetype", sa.Text(), nullable=False),
        sa.Column("visual_seed", sa.Text(), nullable=False),
        sa.Column("growth_state", sa.Text(), nullable=False),
        sa.Column(
            "first_placed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_growth_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.CheckConstraint("depth >= 0", name=op.f("ck_world_nodes_depth")),
        sa.CheckConstraint("revision > 0", name=op.f("ck_world_nodes_revision")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            ondelete="CASCADE",
            name=op.f("fk_world_nodes_user_id_app_users"),
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["learning_entities.id"],
            name=op.f("fk_world_nodes_entity_id_learning_entities"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "world_id"],
            ["learner_worlds.user_id", "learner_worlds.id"],
            ondelete="CASCADE",
            name=op.f("fk_world_nodes_world_owner"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_world_nodes")),
        sa.UniqueConstraint("world_id", "entity_id", name=op.f("uq_world_nodes_world_entity")),
        sa.UniqueConstraint("user_id", "id", name=op.f("uq_world_nodes_user_id_id")),
    )
    op.create_index(
        "ix_world_nodes_user_world", "world_nodes", ["user_id", "world_id"]
    )
    op.create_index(
        "ix_world_nodes_user_region", "world_nodes", ["user_id", "region_id"]
    )
    op.execute(
        "alter table world_nodes add constraint fk_world_nodes_region_owner "
        "foreign key (user_id, region_id) references world_regions (user_id, id) "
        "on delete set null (region_id)"
    )

    op.create_table(
        "world_connections",
        sa.Column(
            "id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("world_id", _uuid(), nullable=False),
        sa.Column("source_world_node_id", _uuid(), nullable=False),
        sa.Column("target_world_node_id", _uuid(), nullable=False),
        sa.Column("ontology_edge_id", _uuid(), nullable=True),
        sa.Column("connection_type", sa.Text(), nullable=False),
        sa.Column("importance", sa.Double(), nullable=False),
        sa.Column("is_visible", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "importance >= 0", name=op.f("ck_world_connections_importance")
        ),
        sa.CheckConstraint(
            "revision > 0", name=op.f("ck_world_connections_revision")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            ondelete="CASCADE",
            name=op.f("fk_world_connections_user_id_app_users"),
        ),
        sa.ForeignKeyConstraint(
            ["ontology_edge_id"],
            ["ontology_edges.id"],
            ondelete="SET NULL",
            name=op.f("fk_world_connections_ontology_edge_id_ontology_edges"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "world_id"],
            ["learner_worlds.user_id", "learner_worlds.id"],
            ondelete="CASCADE",
            name=op.f("fk_world_connections_world_owner"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "source_world_node_id"],
            ["world_nodes.user_id", "world_nodes.id"],
            ondelete="CASCADE",
            name=op.f("fk_world_connections_source_node_owner"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "target_world_node_id"],
            ["world_nodes.user_id", "world_nodes.id"],
            ondelete="CASCADE",
            name=op.f("fk_world_connections_target_node_owner"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_world_connections")),
    )
    op.create_index(
        "ix_world_connections_user_world",
        "world_connections",
        ["user_id", "world_id"],
    )
    op.create_index(
        "ix_world_connections_source_node",
        "world_connections",
        ["user_id", "source_world_node_id"],
    )
    op.create_index(
        "ix_world_connections_target_node",
        "world_connections",
        ["user_id", "target_world_node_id"],
    )

    op.create_table(
        "world_artifacts",
        sa.Column(
            "id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("world_id", _uuid(), nullable=False),
        sa.Column("artifact_id", _uuid(), nullable=False),
        sa.Column("region_id", _uuid(), nullable=True),
        sa.Column("logical_x", sa.Double(), nullable=False),
        sa.Column("logical_y", sa.Double(), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("visual_archetype", sa.Text(), nullable=False),
        sa.Column("visual_seed", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.CheckConstraint("depth >= 0", name=op.f("ck_world_artifacts_depth")),
        sa.CheckConstraint(
            "revision > 0", name=op.f("ck_world_artifacts_revision")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            ondelete="CASCADE",
            name=op.f("fk_world_artifacts_user_id_app_users"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "artifact_id"],
            ["artifacts.user_id", "artifacts.id"],
            ondelete="CASCADE",
            name=op.f("fk_world_artifacts_artifact_owner"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "world_id"],
            ["learner_worlds.user_id", "learner_worlds.id"],
            ondelete="CASCADE",
            name=op.f("fk_world_artifacts_world_owner"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_world_artifacts")),
        sa.UniqueConstraint(
            "world_id", "artifact_id", name=op.f("uq_world_artifacts_world_artifact")
        ),
    )
    op.create_index(
        "ix_world_artifacts_user_world", "world_artifacts", ["user_id", "world_id"]
    )
    op.execute(
        "alter table world_artifacts add constraint fk_world_artifacts_region_owner "
        "foreign key (user_id, region_id) references world_regions (user_id, id) "
        "on delete set null (region_id)"
    )

    op.create_table(
        "world_changes",
        sa.Column(
            "id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("world_id", _uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("change_type", sa.Text(), nullable=False),
        sa.Column("object_type", sa.Text(), nullable=False),
        sa.Column("object_id", _uuid(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "revision > 0", name=op.f("ck_world_changes_revision")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            ondelete="CASCADE",
            name=op.f("fk_world_changes_user_id_app_users"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "world_id"],
            ["learner_worlds.user_id", "learner_worlds.id"],
            ondelete="CASCADE",
            name=op.f("fk_world_changes_world_owner"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_world_changes")),
        sa.UniqueConstraint(
            "world_id", "revision", name=op.f("uq_world_changes_world_revision")
        ),
    )
    op.create_index(
        "ix_world_changes_user_world_revision",
        "world_changes",
        ["user_id", "world_id", "revision"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_world_changes_user_world_revision", table_name="world_changes"
    )
    op.drop_table("world_changes")

    op.execute(
        "alter table world_artifacts drop constraint fk_world_artifacts_region_owner"
    )
    op.drop_index(
        "ix_world_artifacts_user_world", table_name="world_artifacts"
    )
    op.drop_table("world_artifacts")

    op.drop_index(
        "ix_world_connections_target_node", table_name="world_connections"
    )
    op.drop_index(
        "ix_world_connections_source_node", table_name="world_connections"
    )
    op.drop_index(
        "ix_world_connections_user_world", table_name="world_connections"
    )
    op.drop_table("world_connections")

    op.execute("alter table world_nodes drop constraint fk_world_nodes_region_owner")
    op.drop_index("ix_world_nodes_user_region", table_name="world_nodes")
    op.drop_index("ix_world_nodes_user_world", table_name="world_nodes")
    op.drop_table("world_nodes")

    op.drop_index("ix_world_regions_user_world", table_name="world_regions")
    op.drop_table("world_regions")

    op.drop_table("learner_worlds")
