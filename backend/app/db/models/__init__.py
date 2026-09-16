"""SQLAlchemy persistence models grouped by domain."""

from app.db.models.assessment import (
    AssessmentInteraction,
    AssessmentResponse,
    AssessmentSession,
    AssessmentSupportRequest,
    EvaluationRun,
    LearningEvidence,
)
from app.db.models.artifacts import (
    Artifact,
    ArtifactAnalysis,
    MediaObject,
    PracticalChallenge,
    PracticalChallengeVersion,
    UploadSession,
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
    "Artifact",
    "ArtifactAnalysis",
    "AssessmentInteraction",
    "AssessmentResponse",
    "AssessmentSession",
    "AssessmentSupportRequest",
    "Claim",
    "EntityDomain",
    "EntityEmbedding",
    "EvaluationRun",
    "ExplicitInterestPreference",
    "Exploration",
    "IdempotencyRecord",
    "Job",
    "LearningEntity",
    "LearningEntityVersion",
    "LearningEvidence",
    "LearningObjective",
    "LearnerPreference",
    "MediaObject",
    "Misconception",
    "OntologyEdge",
    "PracticalChallenge",
    "PracticalChallengeVersion",
    "Reflection",
    "UploadSession",
    "UserDevice",
    "UserMotivation",
]
