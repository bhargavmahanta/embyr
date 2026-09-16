from __future__ import annotations

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PracticalChallenge(Base):
    __tablename__ = "practical_challenges"
    __table_args__ = (
        sa.UniqueConstraint(
            "id", "entity_id", name="uq_practical_challenges_id_entity_id"
        ),
        sa.Index("ix_practical_challenges_entity_id", "entity_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    entity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), sa.ForeignKey("learning_entities.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )


class PracticalChallengeVersion(Base):
    __tablename__ = "practical_challenge_versions"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["challenge_id", "entity_id"],
            ["practical_challenges.id", "practical_challenges.entity_id"],
            name="fk_practical_challenge_versions_challenge_entity",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id", "entity_version"],
            ["learning_entity_versions.entity_id", "learning_entity_versions.version"],
            name="fk_practical_challenge_versions_entity_version",
        ),
        sa.UniqueConstraint(
            "challenge_id",
            "version",
            name="uq_practical_challenge_versions_challenge_version",
        ),
        sa.UniqueConstraint(
            "challenge_id",
            "id",
            name="uq_practical_challenge_versions_challenge_id_id",
        ),
        sa.CheckConstraint(
            "version > 0", name="practical_challenge_versions_version"
        ),
        sa.CheckConstraint(
            "entity_version > 0",
            name="practical_challenge_versions_entity_version",
        ),
        sa.CheckConstraint(
            "estimated_effort_minutes > 0",
            name="practical_challenge_versions_estimated_effort",
        ),
        sa.CheckConstraint(
            "btrim(prompt) <> ''", name="practical_challenge_versions_prompt"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(target_techniques) = 'array'",
            name="practical_challenge_versions_target_techniques",
        ),
        sa.Index(
            "ix_practical_challenge_versions_entity_version",
            "entity_id",
            "entity_version",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    challenge_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    entity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    entity_version: Mapped[int] = mapped_column(sa.Integer)
    version: Mapped[int] = mapped_column(sa.Integer)
    prompt: Mapped[str] = mapped_column(sa.Text)
    target_techniques: Mapped[dict | list] = mapped_column(JSONB)
    estimated_effort_minutes: Mapped[int] = mapped_column(sa.Integer)
    materials: Mapped[dict | list] = mapped_column(JSONB)
    environment_constraints: Mapped[dict | list] = mapped_column(JSONB)
    physical_requirements: Mapped[dict | list] = mapped_column(JSONB)
    evidence_requirements: Mapped[dict | list] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )


class UploadSession(Base):
    __tablename__ = "upload_sessions"
    __table_args__ = (
        sa.UniqueConstraint(
            "user_id", "id", name="uq_upload_sessions_user_id_id"
        ),
        sa.UniqueConstraint("object_key", name="uq_upload_sessions_object_key"),
        sa.CheckConstraint("purpose = 'ARTIFACT'", name="upload_sessions_purpose"),
        sa.CheckConstraint(
            "declared_size_bytes > 0", name="upload_sessions_declared_size"
        ),
        sa.CheckConstraint(
            "btrim(declared_content_type) <> ''",
            name="upload_sessions_declared_content_type",
        ),
        sa.CheckConstraint(
            "btrim(object_key) <> '' and position('://' in object_key) = 0",
            name="upload_sessions_private_object_key",
        ),
        sa.CheckConstraint(
            "status in ('AUTHORIZED', 'UPLOADED_UNVALIDATED', 'VALIDATED', "
            "'REJECTED')",
            name="upload_sessions_status",
        ),
        sa.CheckConstraint(
            "status not in ('AUTHORIZED', 'UPLOADED_UNVALIDATED', "
            "'VALIDATED', 'REJECTED') or "
            "(status = 'AUTHORIZED' and completed_at is null and "
            "validated_at is null and rejected_at is null) or "
            "(status = 'UPLOADED_UNVALIDATED' and completed_at is not null and "
            "validated_at is null and rejected_at is null) or "
            "(status = 'VALIDATED' and completed_at is not null and "
            "validated_at is not null and rejected_at is null) or "
            "(status = 'REJECTED' and completed_at is not null and "
            "validated_at is null and rejected_at is not null)",
            name="upload_sessions_lifecycle",
        ),
        sa.CheckConstraint(
            "(completed_at is null or completed_at >= created_at) and "
            "(validated_at is null or validated_at >= completed_at) and "
            "(rejected_at is null or rejected_at >= completed_at)",
            name="upload_sessions_timestamp_order",
        ),
        sa.Index(
            "ix_upload_sessions_user_status_created",
            "user_id",
            "status",
            sa.desc("created_at"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="CASCADE")
    )
    purpose: Mapped[str] = mapped_column(sa.Text)
    declared_content_type: Mapped[str] = mapped_column(sa.Text)
    declared_size_bytes: Mapped[int] = mapped_column(sa.BigInteger)
    object_key: Mapped[str] = mapped_column(sa.Text)
    status: Mapped[str] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    validated_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    rejected_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class MediaObject(Base):
    __tablename__ = "media_objects"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["user_id", "upload_id"],
            ["upload_sessions.user_id", "upload_sessions.id"],
            name="fk_media_objects_upload_owner",
        ),
        sa.UniqueConstraint("upload_id", name="uq_media_objects_upload_id"),
        sa.UniqueConstraint("user_id", "id", name="uq_media_objects_user_id_id"),
        sa.UniqueConstraint("object_key", name="uq_media_objects_object_key"),
        sa.CheckConstraint(
            "validated_size_bytes > 0", name="media_objects_validated_size"
        ),
        sa.CheckConstraint(
            "btrim(validated_content_type) <> ''",
            name="media_objects_validated_content_type",
        ),
        sa.CheckConstraint(
            "btrim(object_key) <> '' and position('://' in object_key) = 0",
            name="media_objects_private_object_key",
        ),
        sa.Index(
            "ix_media_objects_user_created", "user_id", sa.desc("created_at")
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    upload_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    object_key: Mapped[str] = mapped_column(sa.Text)
    validated_content_type: Mapped[str] = mapped_column(sa.Text)
    validated_size_bytes: Mapped[int] = mapped_column(sa.BigInteger)
    sha256: Mapped[str] = mapped_column(sa.Text)
    metadata_stripped: Mapped[bool] = mapped_column(sa.Boolean)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )


class Artifact(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            [
                "user_id",
                "exploration_id",
                "practical_challenge_id",
                "practical_challenge_version_id",
            ],
            [
                "explorations.user_id",
                "explorations.id",
                "explorations.practical_challenge_id",
                "explorations.practical_challenge_version_id",
            ],
            name="fk_artifacts_exploration_challenge_owner_version",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "media_object_id"],
            ["media_objects.user_id", "media_objects.id"],
            name="fk_artifacts_media_owner",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "exploration_id", "reflection_id"],
            ["reflections.user_id", "reflections.exploration_id", "reflections.id"],
            name="fk_artifacts_reflection_owner_exploration",
        ),
        sa.UniqueConstraint("user_id", "id", name="uq_artifacts_user_id_id"),
        sa.Index("ix_artifacts_user_created", "user_id", sa.desc("created_at")),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    practical_challenge_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    practical_challenge_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    exploration_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    media_object_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    reflection_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )


class ArtifactAnalysis(Base):
    __tablename__ = "artifact_analyses"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["user_id", "artifact_id"],
            ["artifacts.user_id", "artifacts.id"],
            ondelete="CASCADE",
            name="fk_artifact_analyses_artifact_owner",
        ),
        sa.CheckConstraint(
            "status in ('PENDING', 'SUCCEEDED', 'FAILED')",
            name="artifact_analyses_status",
        ),
        sa.Index(
            "ix_artifact_analyses_user_artifact_created",
            "user_id",
            "artifact_id",
            sa.desc("created_at"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    artifact_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    analyzer_version: Mapped[str] = mapped_column(sa.Text)
    status: Mapped[str] = mapped_column(sa.Text)
    analysis: Mapped[dict | list | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
