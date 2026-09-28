"""Closed public M6-v1 read contracts; persistence rows never become DTOs."""

from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    field_serializer,
    field_validator,
    model_validator,
)

BIGINT = 9223372036854775807
INTEGER = 2147483647
Sequence = Annotated[StrictInt, Field(ge=0, le=BIGINT)]
Positive = Annotated[StrictInt, Field(ge=1, le=BIGINT)]
Revision = Annotated[StrictInt, Field(ge=0, le=INTEGER)]
Seed = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Title = Annotated[str, Field(min_length=1, max_length=512)]
Code = Annotated[str, Field(min_length=1, max_length=64)]


class PublicModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    @field_validator(
        "layout_version",
        "logical_x",
        "logical_y",
        "logical_width",
        "logical_height",
        "depth",
        mode="before",
        check_fields=False,
    )
    @classmethod
    def numeric_constant(cls, value):
        # bool equals 0/1 in Python; JSON Schema numeric constants do not.
        if isinstance(value, bool):
            raise ValueError("Numeric value required")  # noqa: TRY004 - Pydantic requires ValueError
        return value

    @field_serializer("*", when_used="json", check_fields=False)
    def public_time(self, value):
        if isinstance(value, datetime):
            if value.tzinfo is None:
                raise ValueError("UTC instant required")
            return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        return value


class Projection(PublicModel):
    model_version: Literal["learner-projection/v1"]
    source_sequence: Sequence
    source_head_sequence: Sequence
    status: Literal["CURRENT", "PENDING", "FAILED"]

    @model_validator(mode="after")
    def horizon(self):
        if self.source_sequence > self.source_head_sequence:
            raise ValueError("Invalid projection horizon")
        if (self.status == "CURRENT") != (
            self.source_sequence == self.source_head_sequence
        ):
            raise ValueError("Invalid projection freshness")
        return self


class Preferences(PublicModel):
    adventure_preference: Code
    preferred_effort: Code
    support_style: Code
    practical_opt_in: StrictBool
    version: Positive


class ExplicitInterest(PublicModel):
    entity_id: UUID
    entity_version: Positive | None
    title: Title | None
    preference: Literal["NEUTRAL", "MORE", "LESS", "PAUSED", "NOT_INTERESTED"]
    version: Positive
    updated_at: AwareDatetime
    availability: Literal["AVAILABLE", "UNAVAILABLE"]

    @model_validator(mode="after")
    def display(self):
        if self.availability == "AVAILABLE":
            if self.entity_version is None or self.title is None:
                raise ValueError("Missing display version")
        elif self.entity_version is not None or self.title is not None:
            raise ValueError("Unavailable display version")
        return self


class RecentExploration(PublicModel):
    entity_id: UUID
    entity_version: Positive
    title: Title
    started_count: Positive
    returned_count: Sequence
    completed_count: Sequence
    latest_activity_at: AwareDatetime

    @model_validator(mode="after")
    def counts(self):
        if self.completed_count > self.started_count:
            raise ValueError("Invalid encounter counts")
        return self


class RecognitionEvidence(PublicModel):
    objective_id: UUID
    entity_id: UUID
    entity_version: Positive
    evidence_count: Positive
    support_required: StrictBool
    last_evidence_at: AwareDatetime
    summary: Literal["Recognition evidence recorded."]


class Truncated(PublicModel):
    explicit_interests: StrictBool
    recently_explored: StrictBool
    recognition_evidence: StrictBool


class MemorySummary(PublicModel):
    contract_version: Literal["memory-summary/v1"]
    projection: Projection
    learning_preferences: Preferences | None
    explicit_interests: Annotated[list[ExplicitInterest], Field(max_length=20)]
    recently_explored: Annotated[list[RecentExploration], Field(max_length=10)]
    recognition_evidence: Annotated[list[RecognitionEvidence], Field(max_length=10)]
    long_term_interests: Annotated[list, Field(max_length=0)]
    voluntary_revisits: Annotated[list, Field(max_length=0)]
    truncated: Truncated


class Region(PublicModel):
    id: UUID
    region_key: Literal["discovery"]
    primary_domain_id: None
    logical_x: Literal[0]
    logical_y: Literal[0]
    logical_width: Literal[1]
    logical_height: Literal[1]
    visual_archetype: Literal["grove"]


class Node(PublicModel):
    id: UUID
    entity_id: UUID
    entity_version: Positive
    region_id: UUID
    logical_x: Annotated[StrictFloat, Field(ge=0, le=1)]
    logical_y: Annotated[StrictFloat, Field(ge=0, le=1)]
    depth: Literal[0]
    visual_archetype: Literal["branching_tree"]
    visual_seed: Seed
    growth_state: Literal["SEED", "SPROUT", "YOUNG"]
    revision: Annotated[StrictInt, Field(ge=1, le=INTEGER)]


class WorldSnapshot(PublicModel):
    revision: Revision
    layout_version: Literal[1]
    generation_seed: Seed
    regions: Annotated[list[Region], Field(max_length=1)]
    nodes: list[Node]
    connections: Annotated[list, Field(max_length=0)]
    artifacts: Annotated[list, Field(max_length=0)]


class RegionPayload(PublicModel):
    schema_version: Literal["world-delta/v1"]
    object: Region


class NodePayload(PublicModel):
    schema_version: Literal["world-delta/v1"]
    object: Node


class WorldChange(PublicModel):
    revision: Annotated[StrictInt, Field(ge=1, le=INTEGER)]
    type: Literal["REGION_ADDED", "NODE_ADDED", "NODE_GROWTH_CHANGED"]
    object_id: UUID
    payload: RegionPayload | NodePayload

    @model_validator(mode="after")
    def replacement(self):
        obj = self.payload.object
        if self.object_id != obj.id or (self.type == "REGION_ADDED") != isinstance(
            obj, Region
        ):
            raise ValueError("Invalid World replacement")
        if isinstance(obj, Node) and obj.revision != self.revision:
            raise ValueError("Invalid World revision")
        return self


class WorldDeltaPage(PublicModel):
    from_revision: Revision
    to_revision: Revision
    current_revision: Revision
    has_more: StrictBool
    changes: Annotated[list[WorldChange], Field(max_length=1000)]


class WorldResyncDetails(PublicModel):
    after_revision: Sequence
    current_revision: Revision


class WorldResyncRequired(PublicModel):
    type: Literal["about:blank"]
    title: Literal["World resync required"]
    status: Literal[409]
    code: Literal["WORLD_RESYNC_REQUIRED"]
    detail: Literal["Fetch the World snapshot before requesting further changes."]
    request_id: UUID
    details: WorldResyncDetails
