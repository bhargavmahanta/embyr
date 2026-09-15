"""SQLAlchemy persistence models grouped by domain."""

from app.db.models.assessment import (
    AssessmentInteraction,
    AssessmentResponse,
    AssessmentSession,
    AssessmentSupportRequest,
)
from app.db.models.identity import (
    AppUser,
    ExplicitInterestPreference,
    IdempotencyRecord,
    Job,
    LearnerPreference,
    UserDevice,
    UserMotivation,
)
from app.db.models.exploration import Exploration, Reflection
from app.db.models.ontology import (
    Claim,
    EntityDomain,
    EntityEmbedding,
    LearningEntity,
    LearningEntityVersion,
    LearningObjective,
    Misconception,
    OntologyEdge,
)

__all__ = [
    "AppUser",
    "AssessmentInteraction",
    "AssessmentResponse",
    "AssessmentSession",
    "AssessmentSupportRequest",
    "Claim",
    "EntityDomain",
    "EntityEmbedding",
    "ExplicitInterestPreference",
    "Exploration",
    "IdempotencyRecord",
    "Job",
    "LearningEntity",
    "LearningEntityVersion",
    "LearningObjective",
    "LearnerPreference",
    "Misconception",
    "OntologyEdge",
    "Reflection",
    "UserDevice",
    "UserMotivation",
]
