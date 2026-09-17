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
from app.db.models.events import LearningEvent
from app.db.models.learner_state import (
    LearnerChallengeState,
    LearnerConfidenceState,
    LearnerInterestState,
    LearnerObjectiveState,
    LearnerRetentionState,
    StateEvidenceLink,
)
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
from app.db.models.recommendations import Recommendation
from app.db.models.stories import AccountOperationRequest, CuriosityStory
from app.db.models.world import (
    LearnerWorld,
    WorldArtifact,
    WorldChange,
    WorldConnection,
    WorldNode,
    WorldRegion,
)

__all__ = [
    "AccountOperationRequest",
    "AppUser",
    "Artifact",
    "ArtifactAnalysis",
    "AssessmentInteraction",
    "AssessmentResponse",
    "AssessmentSession",
    "AssessmentSupportRequest",
    "Claim",
    "CuriosityStory",
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
    "LearningEvent",
    "LearningObjective",
    "LearnerChallengeState",
    "LearnerConfidenceState",
    "LearnerInterestState",
    "LearnerObjectiveState",
    "LearnerPreference",
    "LearnerRetentionState",
    "LearnerWorld",
    "MediaObject",
    "Misconception",
    "OntologyEdge",
    "PracticalChallenge",
    "PracticalChallengeVersion",
    "Recommendation",
    "Reflection",
    "StateEvidenceLink",
    "UploadSession",
    "UserDevice",
    "UserMotivation",
    "WorldArtifact",
    "WorldChange",
    "WorldConnection",
    "WorldNode",
    "WorldRegion",
]
