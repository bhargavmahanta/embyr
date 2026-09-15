"""SQLAlchemy persistence models grouped by domain."""

from app.db.models.identity import (
    AppUser,
    ExplicitInterestPreference,
    IdempotencyRecord,
    Job,
    LearnerPreference,
    UserDevice,
    UserMotivation,
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

__all__ = [
    "AppUser",
    "Claim",
    "EntityDomain",
    "EntityEmbedding",
    "ExplicitInterestPreference",
    "IdempotencyRecord",
    "Job",
    "LearningEntity",
    "LearningEntityVersion",
    "LearningObjective",
    "LearnerPreference",
    "Misconception",
    "OntologyEdge",
    "UserDevice",
    "UserMotivation",
]
