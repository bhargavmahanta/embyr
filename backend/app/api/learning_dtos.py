"""Public v1 client contracts. Private content is never part of these schemas."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PublicDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")


ExplorationStatus = Literal["ACTIVE", "PAUSED", "COMPLETED"]
SessionStatus = Literal["ACTIVE", "WAITING_FOR_EVALUATION", "COMPLETED", "ABANDONED"]
EvaluationStatus = Literal["PENDING", "SUCCEEDED", "FAILED"]
Result = Literal[
    "SUPPORTED", "PARTIAL", "MISCONCEPTION", "INSUFFICIENT_EVIDENCE", "UNCERTAIN"
]
SupportLevel = Literal["SMALL_NUDGE", "STRONG_HINT", "MISSING_CONCEPT", "EXPLANATION"]


class PreferencesDTO(PublicDTO):
    adventure_preference: str
    preferred_effort: str
    support_style: str
    practical_opt_in: bool
    version: int = Field(ge=1)


class OnboardingDTO(PublicDTO):
    preferences: PreferencesDTO
    onboarding_completed_at: datetime


class InterestDTO(PublicDTO):
    entity_id: UUID
    preference: Literal["NEUTRAL", "MORE", "LESS", "PAUSED", "NOT_INTERESTED"]
    version: int = Field(ge=1)


class StarterDTO(PublicDTO):
    id: UUID
    entity_type: Literal["DOMAIN", "AREA"]
    entity_version: int = Field(ge=1)
    title: str
    summary: str


class StarterPageDTO(PublicDTO):
    items: list[StarterDTO]


class ExplorationDTO(PublicDTO):
    id: UUID
    entity_id: UUID
    entity_version: int = Field(ge=1)
    recommendation_id: UUID | None
    practical_challenge_id: UUID | None
    practical_challenge_version_id: UUID | None
    learning_intent: Literal[
        "DIRECT_INTEREST",
        "PREREQUISITE_SUPPORT",
        "RELATED_EXPLORATION",
        "RETENTION_REVISIT",
        "PRACTICAL_SUPPORT",
        "SERENDIPITY",
    ]
    status: ExplorationStatus
    started_at: datetime
    returned_at: datetime | None
    paused_at: datetime | None
    completed_at: datetime | None
    version: int = Field(ge=1)


class ExplorationPageDTO(PublicDTO):
    items: list[ExplorationDTO]
    next_cursor: str | None


class EntitySummaryDTO(PublicDTO):
    id: UUID
    entity_version: int = Field(ge=1)
    title: str
    summary: str


class DeliveryDTO(PublicDTO):
    content_id: UUID
    content_version: int = Field(ge=1)
    entity_id: UUID
    entity_version: int = Field(ge=1)
    objective_id: UUID
    delivery_contract_version: Literal["exploration-delivery/v1"]
    work_prompt: str
    effort_guidance: str
    search_nudges: list[str]
    reflection_prompt: str


class ReflectionDTO(PublicDTO):
    id: UUID
    exploration_id: UUID
    entity_id: UUID
    text: str = Field(max_length=10000)
    version: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime


class AssessmentReferenceDTO(PublicDTO):
    id: UUID
    status: SessionStatus


class ExplorationDetailDTO(ExplorationDTO):
    lifecycle_contract_version: Literal["exploration-lifecycle/v1"]
    entity: EntitySummaryDTO | None
    delivery: DeliveryDTO | None
    reflection: ReflectionDTO | None
    assessment_session: AssessmentReferenceDTO | None


class OptionDTO(PublicDTO):
    id: str
    label: str


class InteractionDTO(PublicDTO):
    id: UUID
    interaction_type: Literal["RECOGNITION"]
    prompt: str
    strategy_version: Literal["assessment-strategy/v1"]
    interaction_contract_version: Literal["assessment-interaction/v1"]
    evaluator_version: Literal["deterministic-evaluation/v1"]
    evidence_contract_version: Literal["assessment-evidence/v1"]
    options: list[OptionDTO]


class SupportTextDTO(PublicDTO):
    text: str


class SupportDTO(PublicDTO):
    id: UUID
    level: SupportLevel
    content: SupportTextDTO


class EvaluationDTO(PublicDTO):
    id: UUID
    status: EvaluationStatus
    result: Result | None
    confidence: float | None = Field(ge=0, le=1)
    feedback: str | None
    failure_category: str | None
    retry_allowed: bool


class AssessmentSessionDTO(PublicDTO):
    id: UUID
    exploration_id: UUID
    status: SessionStatus
    confidence_before: Literal["FUZZY", "MAIN_IDEA", "COULD_EXPLAIN", "CHALLENGE_ME"]
    strategy_version: Literal["assessment-strategy/v1"]
    interaction: InteractionDTO
    delivered_support: list[SupportDTO]
    response_id: UUID | None
    evaluation: EvaluationDTO | None
    evaluation_status: EvaluationStatus | None
    feedback: str | None
    retry_allowed: bool


class AnswerAcknowledgmentDTO(PublicDTO):
    response_id: UUID
    evaluation_status: Literal["PENDING"]
    session_status: Literal["WAITING_FOR_EVALUATION"]
    next_interaction: None


class EvaluationRetryDTO(AnswerAcknowledgmentDTO):
    evaluation_run_id: UUID


class AssessmentResponseDTO(PublicDTO):
    response_id: UUID
    assessment_session_id: UUID
    session_status: SessionStatus
    support_used: SupportLevel | None
    evaluation_run_id: UUID | None
    evaluation_status: EvaluationStatus | None
    result: Result | None
    confidence: float | None = Field(ge=0, le=1)
    feedback: str | None
    failure_category: str | None
    retry_allowed: bool
