from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LearnerWorld(Base):
    __tablename__ = "learner_worlds"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            ondelete="CASCADE",
            name="fk_learner_worlds_user_id_app_users",
        ),
        sa.UniqueConstraint("user_id", name="uq_learner_worlds_user_id"),
        sa.UniqueConstraint(
            "user_id", "id", name="uq_learner_worlds_user_id_id"
        ),
        sa.CheckConstraint("current_revision >= 0", name="current_revision"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    generation_seed: Mapped[str] = mapped_column(sa.Text)
    layout_version: Mapped[int] = mapped_column(sa.Integer)
    current_revision: Mapped[int] = mapped_column(
        sa.Integer, server_default=sa.text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )


class WorldRegion(Base):
    __tablename__ = "world_regions"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            ondelete="CASCADE",
            name="fk_world_regions_user_id_app_users",
        ),
        sa.ForeignKeyConstraint(
            ["primary_domain_id"],
            ["learning_entities.id"],
            ondelete="SET NULL",
            name="fk_world_regions_primary_domain_id_learning_entities",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "world_id"],
            ["learner_worlds.user_id", "learner_worlds.id"],
            ondelete="CASCADE",
            name="fk_world_regions_world_owner",
        ),
        sa.UniqueConstraint(
            "user_id", "id", name="uq_world_regions_user_id_id"
        ),
        sa.CheckConstraint("logical_width > 0", name="logical_width"),
        sa.CheckConstraint("logical_height > 0", name="logical_height"),
        sa.Index("ix_world_regions_user_world", "user_id", "world_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    world_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    region_key: Mapped[str] = mapped_column(sa.Text)
    primary_domain_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    logical_x: Mapped[float] = mapped_column(sa.Double)
    logical_y: Mapped[float] = mapped_column(sa.Double)
    logical_width: Mapped[float] = mapped_column(sa.Double)
    logical_height: Mapped[float] = mapped_column(sa.Double)
    visual_archetype: Mapped[str] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )


class WorldNode(Base):
    __tablename__ = "world_nodes"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            ondelete="CASCADE",
            name="fk_world_nodes_user_id_app_users",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["learning_entities.id"],
            name="fk_world_nodes_entity_id_learning_entities",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "world_id"],
            ["learner_worlds.user_id", "learner_worlds.id"],
            ondelete="CASCADE",
            name="fk_world_nodes_world_owner",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "region_id"],
            ["world_regions.user_id", "world_regions.id"],
            ondelete="SET NULL (region_id)",
            name="fk_world_nodes_region_owner",
        ),
        sa.UniqueConstraint(
            "world_id", "entity_id", name="uq_world_nodes_world_entity"
        ),
        sa.UniqueConstraint("user_id", "id", name="uq_world_nodes_user_id_id"),
        sa.CheckConstraint("depth >= 0", name="depth"),
        sa.CheckConstraint("revision > 0", name="revision"),
        sa.Index("ix_world_nodes_user_world", "user_id", "world_id"),
        sa.Index("ix_world_nodes_user_region", "user_id", "region_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    world_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    entity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    region_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    logical_x: Mapped[float] = mapped_column(sa.Double)
    logical_y: Mapped[float] = mapped_column(sa.Double)
    depth: Mapped[int] = mapped_column(sa.Integer)
    visual_archetype: Mapped[str] = mapped_column(sa.Text)
    visual_seed: Mapped[str] = mapped_column(sa.Text)
    growth_state: Mapped[str] = mapped_column(sa.Text)
    first_placed_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    last_growth_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    revision: Mapped[int] = mapped_column(sa.Integer)


class WorldConnection(Base):
    __tablename__ = "world_connections"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            ondelete="CASCADE",
            name="fk_world_connections_user_id_app_users",
        ),
        sa.ForeignKeyConstraint(
            ["ontology_edge_id"],
            ["ontology_edges.id"],
            ondelete="SET NULL",
            name="fk_world_connections_ontology_edge_id_ontology_edges",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "world_id"],
            ["learner_worlds.user_id", "learner_worlds.id"],
            ondelete="CASCADE",
            name="fk_world_connections_world_owner",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "source_world_node_id"],
            ["world_nodes.user_id", "world_nodes.id"],
            ondelete="CASCADE",
            name="fk_world_connections_source_node_owner",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "target_world_node_id"],
            ["world_nodes.user_id", "world_nodes.id"],
            ondelete="CASCADE",
            name="fk_world_connections_target_node_owner",
        ),
        sa.CheckConstraint("importance >= 0", name="importance"),
        sa.CheckConstraint("revision > 0", name="revision"),
        sa.Index("ix_world_connections_user_world", "user_id", "world_id"),
        sa.Index(
            "ix_world_connections_source_node",
            "user_id",
            "source_world_node_id",
        ),
        sa.Index(
            "ix_world_connections_target_node",
            "user_id",
            "target_world_node_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    world_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    source_world_node_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    target_world_node_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    ontology_edge_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    connection_type: Mapped[str] = mapped_column(sa.Text)
    importance: Mapped[float] = mapped_column(sa.Double)
    is_visible: Mapped[bool] = mapped_column(sa.Boolean)
    revision: Mapped[int] = mapped_column(sa.Integer)


class WorldArtifact(Base):
    __tablename__ = "world_artifacts"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            ondelete="CASCADE",
            name="fk_world_artifacts_user_id_app_users",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "artifact_id"],
            ["artifacts.user_id", "artifacts.id"],
            ondelete="CASCADE",
            name="fk_world_artifacts_artifact_owner",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "world_id"],
            ["learner_worlds.user_id", "learner_worlds.id"],
            ondelete="CASCADE",
            name="fk_world_artifacts_world_owner",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "region_id"],
            ["world_regions.user_id", "world_regions.id"],
            ondelete="SET NULL (region_id)",
            name="fk_world_artifacts_region_owner",
        ),
        sa.UniqueConstraint(
            "world_id", "artifact_id", name="uq_world_artifacts_world_artifact"
        ),
        sa.CheckConstraint("depth >= 0", name="depth"),
        sa.CheckConstraint("revision > 0", name="revision"),
        sa.Index("ix_world_artifacts_user_world", "user_id", "world_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    world_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    artifact_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    region_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    logical_x: Mapped[float] = mapped_column(sa.Double)
    logical_y: Mapped[float] = mapped_column(sa.Double)
    depth: Mapped[int] = mapped_column(sa.Integer)
    visual_archetype: Mapped[str] = mapped_column(sa.Text)
    visual_seed: Mapped[str] = mapped_column(sa.Text)
    revision: Mapped[int] = mapped_column(sa.Integer)


class WorldChange(Base):
    __tablename__ = "world_changes"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            ondelete="CASCADE",
            name="fk_world_changes_user_id_app_users",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "world_id"],
            ["learner_worlds.user_id", "learner_worlds.id"],
            ondelete="CASCADE",
            name="fk_world_changes_world_owner",
        ),
        sa.UniqueConstraint(
            "world_id", "revision", name="uq_world_changes_world_revision"
        ),
        sa.CheckConstraint("revision > 0", name="revision"),
        sa.Index(
            "ix_world_changes_user_world_revision",
            "user_id",
            "world_id",
            "revision",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    world_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    revision: Mapped[int] = mapped_column(sa.Integer)
    change_type: Mapped[str] = mapped_column(sa.Text)
    object_type: Mapped[str] = mapped_column(sa.Text)
    object_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    payload: Mapped[Any] = mapped_column(
        JSONB, server_default=sa.text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
