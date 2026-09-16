"""Create versioned practical challenges and validated private artifacts.

Revision ID: 0006_practical_artifacts
Revises: 0005_assessment_evidence
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0006_practical_artifacts"
down_revision: str | None = "0005_assessment_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid() -> postgresql.UUID:
    return postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "practical_challenges",
        sa.Column(
            "id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("entity_id", _uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["learning_entities.id"],
            name=op.f("fk_practical_challenges_entity_id_learning_entities"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_practical_challenges")),
        sa.UniqueConstraint(
            "id",
            "entity_id",
            name=op.f("uq_practical_challenges_id_entity_id"),
        ),
    )
    op.create_index(
        "ix_practical_challenges_entity_id",
        "practical_challenges",
        ["entity_id"],
    )

    op.create_table(
        "practical_challenge_versions",
        sa.Column(
            "id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("challenge_id", _uuid(), nullable=False),
        sa.Column("entity_id", _uuid(), nullable=False),
        sa.Column("entity_version", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("target_techniques", postgresql.JSONB(), nullable=False),
        sa.Column("estimated_effort_minutes", sa.Integer(), nullable=False),
        sa.Column("materials", postgresql.JSONB(), nullable=False),
        sa.Column("environment_constraints", postgresql.JSONB(), nullable=False),
        sa.Column("physical_requirements", postgresql.JSONB(), nullable=False),
        sa.Column("evidence_requirements", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "version > 0",
            name=op.f("ck_practical_challenge_versions_version"),
        ),
        sa.CheckConstraint(
            "entity_version > 0",
            name=op.f("ck_practical_challenge_versions_entity_version"),
        ),
        sa.CheckConstraint(
            "estimated_effort_minutes > 0",
            name=op.f("ck_practical_challenge_versions_estimated_effort"),
        ),
        sa.CheckConstraint(
            "btrim(prompt) <> ''",
            name=op.f("ck_practical_challenge_versions_prompt"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(target_techniques) = 'array'",
            name=op.f("ck_practical_challenge_versions_target_techniques"),
        ),
        sa.ForeignKeyConstraint(
            ["challenge_id", "entity_id"],
            ["practical_challenges.id", "practical_challenges.entity_id"],
            name=op.f("fk_practical_challenge_versions_challenge_entity"),
        ),
        sa.ForeignKeyConstraint(
            ["entity_id", "entity_version"],
            ["learning_entity_versions.entity_id", "learning_entity_versions.version"],
            name=op.f("fk_practical_challenge_versions_entity_version"),
        ),
        sa.PrimaryKeyConstraint(
            "id", name=op.f("pk_practical_challenge_versions")
        ),
        sa.UniqueConstraint(
            "challenge_id",
            "version",
            name=op.f("uq_practical_challenge_versions_challenge_version"),
        ),
        sa.UniqueConstraint(
            "challenge_id",
            "id",
            name=op.f("uq_practical_challenge_versions_challenge_id_id"),
        ),
    )
    op.create_index(
        "ix_practical_challenge_versions_entity_version",
        "practical_challenge_versions",
        ["entity_id", "entity_version"],
    )

    op.execute(
        """
        create function prevent_practical_challenge_version_mutation()
        returns trigger
        language plpgsql
        as $$
        begin
            raise exception using
                errcode = '55000',
                constraint = 'ck_practical_challenge_versions_immutable',
                message = 'published practical challenge versions are immutable';
        end;
        $$
        """
    )
    op.execute(
        """
        create trigger trg_practical_challenge_versions_immutable
        before update or delete on practical_challenge_versions
        for each row execute function prevent_practical_challenge_version_mutation()
        """
    )

    op.add_column(
        "explorations",
        sa.Column("practical_challenge_version_id", _uuid(), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_explorations_practical_challenge_pair"),
        "explorations",
        "(practical_challenge_id is null and "
        "practical_challenge_version_id is null) or "
        "(practical_challenge_id is not null and "
        "practical_challenge_version_id is not null)",
    )
    op.create_foreign_key(
        op.f("fk_explorations_practical_challenge_version"),
        "explorations",
        "practical_challenge_versions",
        ["practical_challenge_id", "practical_challenge_version_id"],
        ["challenge_id", "id"],
    )
    op.create_unique_constraint(
        op.f("uq_explorations_owner_challenge_version"),
        "explorations",
        [
            "user_id",
            "id",
            "practical_challenge_id",
            "practical_challenge_version_id",
        ],
    )

    op.execute(
        """
        create function validate_exploration_practical_challenge_version()
        returns trigger
        language plpgsql
        as $$
        declare
            challenge_entity_id uuid;
            challenge_entity_version integer;
        begin
            if new.practical_challenge_id is null then
                return new;
            end if;

            select entity_id, entity_version
              into challenge_entity_id, challenge_entity_version
              from practical_challenge_versions
             where challenge_id = new.practical_challenge_id
               and id = new.practical_challenge_version_id
             for share;
            if not found then
                return new;
            end if;

            if challenge_entity_id <> new.entity_id
               or challenge_entity_version <> new.entity_version then
                raise exception using
                    errcode = '23514',
                    constraint = 'ck_explorations_practical_challenge_version',
                    message = 'exploration must preserve the matching challenge and canonical entity version';
            end if;
            return new;
        end;
        $$
        """
    )
    op.execute(
        """
        create trigger trg_explorations_practical_challenge_version
        before insert or update of entity_id, entity_version,
            practical_challenge_id, practical_challenge_version_id
        on explorations
        for each row execute function validate_exploration_practical_challenge_version()
        """
    )

    op.create_unique_constraint(
        op.f("uq_reflections_owner_exploration_id"),
        "reflections",
        ["user_id", "exploration_id", "id"],
    )

    op.create_table(
        "upload_sessions",
        sa.Column(
            "id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("declared_content_type", sa.Text(), nullable=False),
        sa.Column("declared_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("validated_at", sa.DateTime(timezone=True)),
        sa.Column("rejected_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "purpose = 'ARTIFACT'", name=op.f("ck_upload_sessions_purpose")
        ),
        sa.CheckConstraint(
            "declared_size_bytes > 0",
            name=op.f("ck_upload_sessions_declared_size"),
        ),
        sa.CheckConstraint(
            "btrim(declared_content_type) <> ''",
            name=op.f("ck_upload_sessions_declared_content_type"),
        ),
        sa.CheckConstraint(
            "btrim(object_key) <> '' and position('://' in object_key) = 0",
            name=op.f("ck_upload_sessions_private_object_key"),
        ),
        sa.CheckConstraint(
            "status in ('AUTHORIZED', 'UPLOADED_UNVALIDATED', 'VALIDATED', "
            "'REJECTED')",
            name=op.f("ck_upload_sessions_status"),
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
            name=op.f("ck_upload_sessions_lifecycle"),
        ),
        sa.CheckConstraint(
            "(completed_at is null or completed_at >= created_at) and "
            "(validated_at is null or validated_at >= completed_at) and "
            "(rejected_at is null or rejected_at >= completed_at)",
            name=op.f("ck_upload_sessions_timestamp_order"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            ondelete="CASCADE",
            name=op.f("fk_upload_sessions_user_id_app_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_upload_sessions")),
        sa.UniqueConstraint(
            "user_id", "id", name=op.f("uq_upload_sessions_user_id_id")
        ),
        sa.UniqueConstraint(
            "object_key", name=op.f("uq_upload_sessions_object_key")
        ),
    )
    op.create_index(
        "ix_upload_sessions_user_status_created",
        "upload_sessions",
        ["user_id", "status", sa.text("created_at DESC")],
    )

    op.execute(
        """
        create function enforce_upload_session_transition()
        returns trigger
        language plpgsql
        as $$
        begin
            if new.id is distinct from old.id
               or new.user_id is distinct from old.user_id
               or new.purpose is distinct from old.purpose
               or new.declared_content_type is distinct from old.declared_content_type
               or new.declared_size_bytes is distinct from old.declared_size_bytes
               or new.object_key is distinct from old.object_key
               or new.created_at is distinct from old.created_at then
                raise exception using
                    errcode = '55000',
                    constraint = 'ck_upload_sessions_immutable_request',
                    message = 'upload authorization details are immutable';
            end if;

            if new is not distinct from old then
                return new;
            end if;

            if not (
                (old.status = 'AUTHORIZED'
                 and new.status in ('UPLOADED_UNVALIDATED', 'VALIDATED', 'REJECTED'))
                or (old.status = 'UPLOADED_UNVALIDATED'
                    and new.status in ('VALIDATED', 'REJECTED'))
            ) then
                raise exception using
                    errcode = '55000',
                    constraint = 'ck_upload_sessions_status_transition',
                    message = 'invalid upload session status transition';
            end if;
            return new;
        end;
        $$
        """
    )
    op.execute(
        """
        create trigger trg_upload_sessions_transition
        before update on upload_sessions
        for each row execute function enforce_upload_session_transition()
        """
    )

    op.create_table(
        "media_objects",
        sa.Column(
            "id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("upload_id", _uuid(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("validated_content_type", sa.Text(), nullable=False),
        sa.Column("validated_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("metadata_stripped", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "validated_size_bytes > 0",
            name=op.f("ck_media_objects_validated_size"),
        ),
        sa.CheckConstraint(
            "btrim(validated_content_type) <> ''",
            name=op.f("ck_media_objects_validated_content_type"),
        ),
        sa.CheckConstraint(
            "btrim(object_key) <> '' and position('://' in object_key) = 0",
            name=op.f("ck_media_objects_private_object_key"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "upload_id"],
            ["upload_sessions.user_id", "upload_sessions.id"],
            name=op.f("fk_media_objects_upload_owner"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_media_objects")),
        sa.UniqueConstraint(
            "upload_id", name=op.f("uq_media_objects_upload_id")
        ),
        sa.UniqueConstraint(
            "user_id", "id", name=op.f("uq_media_objects_user_id_id")
        ),
        sa.UniqueConstraint(
            "object_key", name=op.f("uq_media_objects_object_key")
        ),
    )
    op.create_index(
        "ix_media_objects_user_created",
        "media_objects",
        ["user_id", sa.text("created_at DESC")],
    )

    op.execute(
        """
        create function validate_media_object_upload()
        returns trigger
        language plpgsql
        as $$
        declare
            upload_status text;
            upload_object_key text;
        begin
            select status, object_key
              into upload_status, upload_object_key
              from upload_sessions
             where user_id = new.user_id
               and id = new.upload_id
             for share;
            if not found then
                return new;
            end if;

            if upload_status <> 'VALIDATED' then
                raise exception using
                    errcode = '23514',
                    constraint = 'ck_media_objects_validated_upload',
                    message = 'media objects require a validated upload session';
            end if;
            if upload_object_key <> new.object_key then
                raise exception using
                    errcode = '23514',
                    constraint = 'ck_media_objects_upload_object_key',
                    message = 'media object key must match its validated upload';
            end if;
            return new;
        end;
        $$
        """
    )
    op.execute(
        """
        create trigger trg_media_objects_validated_upload
        before insert on media_objects
        for each row execute function validate_media_object_upload()
        """
    )
    op.execute(
        """
        create function prevent_media_object_mutation()
        returns trigger
        language plpgsql
        as $$
        begin
            raise exception using
                errcode = '55000',
                constraint = 'ck_media_objects_immutable',
                message = 'validated media metadata is immutable';
        end;
        $$
        """
    )
    op.execute(
        """
        create trigger trg_media_objects_immutable
        before update on media_objects
        for each row execute function prevent_media_object_mutation()
        """
    )

    op.create_table(
        "artifacts",
        sa.Column(
            "id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("practical_challenge_id", _uuid(), nullable=False),
        sa.Column("practical_challenge_version_id", _uuid(), nullable=False),
        sa.Column("exploration_id", _uuid(), nullable=False),
        sa.Column("media_object_id", _uuid(), nullable=False),
        sa.Column("reflection_id", _uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
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
            name=op.f("fk_artifacts_exploration_challenge_owner_version"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "media_object_id"],
            ["media_objects.user_id", "media_objects.id"],
            name=op.f("fk_artifacts_media_owner"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "exploration_id", "reflection_id"],
            ["reflections.user_id", "reflections.exploration_id", "reflections.id"],
            name=op.f("fk_artifacts_reflection_owner_exploration"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_artifacts")),
        sa.UniqueConstraint(
            "user_id", "id", name=op.f("uq_artifacts_user_id_id")
        ),
    )
    op.create_index(
        "ix_artifacts_user_created",
        "artifacts",
        ["user_id", sa.text("created_at DESC")],
    )

    op.execute(
        """
        create function prevent_artifact_mutation()
        returns trigger
        language plpgsql
        as $$
        begin
            if tg_op = 'DELETE' and current_user = 'app_maintenance' then
                return old;
            end if;
            raise exception using
                errcode = '55000',
                constraint = 'ck_artifacts_immutable',
                message = 'artifact provenance is immutable';
        end;
        $$
        """
    )
    op.execute(
        """
        create trigger trg_artifacts_immutable
        before update or delete on artifacts
        for each row execute function prevent_artifact_mutation()
        """
    )

    op.create_table(
        "artifact_analyses",
        sa.Column(
            "id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("artifact_id", _uuid(), nullable=False),
        sa.Column("analyzer_version", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("analysis", postgresql.JSONB()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status in ('PENDING', 'SUCCEEDED', 'FAILED')",
            name=op.f("ck_artifact_analyses_status"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "artifact_id"],
            ["artifacts.user_id", "artifacts.id"],
            ondelete="CASCADE",
            name=op.f("fk_artifact_analyses_artifact_owner"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_artifact_analyses")),
    )
    op.create_index(
        "ix_artifact_analyses_user_artifact_created",
        "artifact_analyses",
        ["user_id", "artifact_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_artifact_analyses_user_artifact_created",
        table_name="artifact_analyses",
    )
    op.drop_table("artifact_analyses")
    op.execute("drop trigger trg_artifacts_immutable on artifacts")
    op.execute("drop function prevent_artifact_mutation()")
    op.drop_index("ix_artifacts_user_created", table_name="artifacts")
    op.drop_table("artifacts")
    op.execute("drop trigger trg_media_objects_immutable on media_objects")
    op.execute("drop function prevent_media_object_mutation()")
    op.execute("drop trigger trg_media_objects_validated_upload on media_objects")
    op.execute("drop function validate_media_object_upload()")
    op.drop_index("ix_media_objects_user_created", table_name="media_objects")
    op.drop_table("media_objects")
    op.execute("drop trigger trg_upload_sessions_transition on upload_sessions")
    op.execute("drop function enforce_upload_session_transition()")
    op.drop_index(
        "ix_upload_sessions_user_status_created", table_name="upload_sessions"
    )
    op.drop_table("upload_sessions")
    op.drop_constraint(
        op.f("uq_reflections_owner_exploration_id"),
        "reflections",
        type_="unique",
    )
    op.execute(
        "drop trigger trg_explorations_practical_challenge_version on explorations"
    )
    op.execute("drop function validate_exploration_practical_challenge_version()")
    op.drop_constraint(
        op.f("uq_explorations_owner_challenge_version"),
        "explorations",
        type_="unique",
    )
    op.drop_constraint(
        op.f("fk_explorations_practical_challenge_version"),
        "explorations",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("ck_explorations_practical_challenge_pair"),
        "explorations",
        type_="check",
    )
    op.drop_column("explorations", "practical_challenge_version_id")
    op.execute(
        "drop trigger trg_practical_challenge_versions_immutable "
        "on practical_challenge_versions"
    )
    op.execute("drop function prevent_practical_challenge_version_mutation()")
    op.drop_index(
        "ix_practical_challenge_versions_entity_version",
        table_name="practical_challenge_versions",
    )
    op.drop_table("practical_challenge_versions")
    op.drop_index(
        "ix_practical_challenges_entity_id", table_name="practical_challenges"
    )
    op.drop_table("practical_challenges")
