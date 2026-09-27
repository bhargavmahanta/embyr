"""Ordered immutable projection inputs and publication metadata; no derived state."""

from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ProjectionSourceHead(Base):
    __tablename__ = "projection_source_heads"
    __table_args__ = (
        sa.CheckConstraint("source_sequence >= 0", name="sequence"),
        sa.CheckConstraint(
            "bootstrap_state in ('REQUIRED','READY')", name="bootstrap_state"
        ),
        sa.CheckConstraint(
            "baseline_through_sequence is null or baseline_through_sequence > 0",
            name="baseline",
        ),
        sa.CheckConstraint(
            "cutoff_source_sequence is null or cutoff_source_sequence >= 0",
            name="cutoff",
        ),
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID, sa.ForeignKey("app_users.id", ondelete="CASCADE"), primary_key=True
    )
    source_sequence: Mapped[int] = mapped_column(
        sa.BigInteger, server_default=sa.text("0")
    )
    bootstrap_state: Mapped[str] = mapped_column(
        sa.Text, server_default=sa.text("'REQUIRED'")
    )
    baseline_through_sequence: Mapped[int | None] = mapped_column(sa.BigInteger)
    cutoff_source_sequence: Mapped[int | None] = mapped_column(sa.BigInteger)
    cutoff_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )


class ProjectionInput(Base):
    __tablename__ = "projection_inputs"
    __table_args__ = (
        sa.UniqueConstraint(
            "user_id", "source_kind", "source_key", name="uq_projection_inputs_source"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "ledger_event_id"],
            ["learning_events.user_id", "learning_events.id"],
            name="fk_projection_inputs_event_owner",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "evidence_id"],
            ["learning_evidence.user_id", "learning_evidence.id"],
            name="fk_projection_inputs_evidence_owner",
        ),
        sa.CheckConstraint("source_sequence > 0", name="sequence"),
        sa.CheckConstraint(
            "contract_version = 'projection-input/v1' and schema_version = 1",
            name="version",
        ),
        sa.CheckConstraint("source_group ~ '^[0-9]{1,20}$'", name="group"),
        sa.CheckConstraint(
            "(source_kind = 'LEDGER' and ledger_event_id is not null and evidence_id is null and source_key = ledger_event_id::text and facts->>'event_id' = source_key) or (source_kind = 'EVIDENCE' and evidence_id is not null and ledger_event_id is null and facts->>'evidence_id' = evidence_id::text and facts->>'resulting_status' in ('ACTIVE','SUPERSEDED','REVOKED') and source_key = evidence_id::text || ':' || (facts->>'resulting_status')) or (source_kind = 'BOOTSTRAP' and ledger_event_id is null and evidence_id is null and source_key = 'learner-projection/v1:baseline')",
            name="source",
        ),
        sa.CheckConstraint("jsonb_typeof(facts) = 'object'", name="facts"),
        sa.Index(
            "ix_projection_inputs_group", "user_id", "source_group", "source_sequence"
        ),
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID, sa.ForeignKey("app_users.id", ondelete="CASCADE"), primary_key=True
    )
    source_sequence: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True)
    contract_version: Mapped[str] = mapped_column(
        sa.Text, server_default=sa.text("'projection-input/v1'")
    )
    schema_version: Mapped[int] = mapped_column(sa.Integer, server_default=sa.text("1"))
    source_kind: Mapped[str] = mapped_column(sa.Text)
    source_key: Mapped[str] = mapped_column(sa.Text)
    source_group: Mapped[str] = mapped_column(sa.Text)
    source_time: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    facts: Mapped[dict[str, Any]] = mapped_column(JSONB)
    ledger_event_id: Mapped[UUID | None] = mapped_column(PGUUID)
    evidence_id: Mapped[UUID | None] = mapped_column(PGUUID)


class LearnerProjectionCheckpoint(Base):
    __tablename__ = "learner_projection_checkpoints"
    __table_args__ = (
        sa.CheckConstraint(
            "processed_source_sequence >= 0 and generation >= 1", name="horizon"
        ),
        sa.CheckConstraint(
            "input_contract_version = 'projection-input/v1' and worker_contract_version = 'projection-worker/v1' and learner_contract_version = 'learner-projection/v1' and world_contract_version = 'world-projection/v1'",
            name="versions",
        ),
        sa.CheckConstraint(
            "blocking_group is null or blocking_group ~ '^[0-9]{1,20}$'", name="group"
        ),
        sa.CheckConstraint(
            "failure_code is null or failure_code ~ '^[A-Z][A-Z0-9_]{0,63}$'",
            name="failure",
        ),
        sa.CheckConstraint(
            "(input_fingerprint is null or input_fingerprint ~ '^[0-9a-f]{64}$') and (output_fingerprint is null or output_fingerprint ~ '^[0-9a-f]{64}$')",
            name="fingerprints",
        ),
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID, sa.ForeignKey("app_users.id", ondelete="CASCADE"), primary_key=True
    )
    processed_source_sequence: Mapped[int] = mapped_column(
        sa.BigInteger, server_default=sa.text("0")
    )
    generation: Mapped[int] = mapped_column(sa.BigInteger, server_default=sa.text("1"))
    input_contract_version: Mapped[str] = mapped_column(
        sa.Text, server_default=sa.text("'projection-input/v1'")
    )
    worker_contract_version: Mapped[str] = mapped_column(
        sa.Text, server_default=sa.text("'projection-worker/v1'")
    )
    learner_contract_version: Mapped[str] = mapped_column(
        sa.Text, server_default=sa.text("'learner-projection/v1'")
    )
    world_contract_version: Mapped[str] = mapped_column(
        sa.Text, server_default=sa.text("'world-projection/v1'")
    )
    input_fingerprint: Mapped[str | None] = mapped_column(sa.Text)
    output_fingerprint: Mapped[str | None] = mapped_column(sa.Text)
    blocking_group: Mapped[str | None] = mapped_column(sa.Text)
    failure_code: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
