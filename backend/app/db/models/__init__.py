"""SQLAlchemy persistence models grouped by domain."""

from app.db.models.identity import AppUser, IdempotencyRecord, Job, UserDevice
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
    "IdempotencyRecord",
    "Job",
    "LearningEntity",
    "LearningEntityVersion",
    "LearningObjective",
    "Misconception",
    "OntologyEdge",
    "UserDevice",
]
