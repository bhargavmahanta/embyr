"""RLS-scoped, repeatable-read production recommendation input snapshot.

The snapshot contains production data only. Retrieval and the adapter to M3's
simulation-shaped pure functions belong to later M4 stages.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.session import set_current_user
from app.recommendation.inputs import objective_state_entry, select_anchors

INPUT_VERSION = "recommendation-input/v1"

# Global ontology reads happen in the same database snapshot as user-scoped
# reads. Historical versions remain available for active/revisit references.
QUERIES = {
    "entities": """
        select e.id as entity_id, e.canonical_key, e.entity_type, e.status,
               e.current_version, v.version as entity_version, v.title,
               v.summary, v.difficulty_prior, v.estimated_effort_minutes
          from public.learning_entities e
          join public.learning_entity_versions v on v.entity_id = e.id
         where e.current_version is not null
           and e.status in ('REVIEWED', 'PUBLISHED')
         order by e.id, v.version
    """,
    "domains": """
        select entity_id, domain_id, is_primary, membership_strength
          from public.entity_domains order by entity_id, domain_id
    """,
    "objectives": """
        select id as objective_id, entity_id, entity_version,
               objective_type, importance
          from public.learning_objectives
         order by entity_id, entity_version, id
    """,
    "edges": """
        select id as edge_id, source_entity_id, source_entity_version,
               target_entity_id, target_entity_version, objective_id,
               requirement, relationship_type, strength, context,
               confidence, status
          from public.ontology_edges order by source_entity_id, target_entity_id, id
    """,
    "embeddings": """
        select entity_id, entity_version, embedding::text as vector,
               embedding_provider, embedding_model, embedding_dimension,
               embedding_input_version, embedding_input_type
          from public.entity_embeddings
         where embedding_provider = 'voyage-ai'
           and embedding_model = 'voyage-4'
           and embedding_dimension = 1024
           and embedding_input_version = 'entity-document/v1'
           and embedding_input_type = 'document'
         order by entity_id, entity_version
    """,
    "preferences": """
        select p.entity_id, e.current_version as entity_version,
               p.preference, p.version
          from public.explicit_interest_preferences p
          join public.learning_entities e on e.id = p.entity_id
         where p.user_id = :user_id and e.current_version is not null
           and e.status in ('REVIEWED', 'PUBLISHED')
         order by p.entity_id
    """,
    "explorations": """
        select id as exploration_id, entity_id, entity_version,
               learning_intent, status, started_at, returned_at,
               paused_at, completed_at
          from public.explorations
         where user_id = :user_id order by id
    """,
    "objective_states": """
        select s.objective_id, o.entity_id, o.entity_version,
               s.categorical_state, s.understanding_estimate,
               s.evaluation_confidence, s.support_required,
               s.computed_at, s.model_version
          from public.learner_objective_state s
          join public.learning_objectives o on o.id = s.objective_id
         where s.user_id = :user_id
         order by s.objective_id
    """,
    "interest_states": """
        select s.entity_id, e.current_version as entity_version,
               s.recent_affinity, s.long_term_affinity,
               s.user_initiated_strength, s.algorithm_exposure_strength,
               s.voluntary_revisit_count, s.last_interaction_at,
               s.computed_at, s.model_version
          from public.learner_interest_state s
          join public.learning_entities e on e.id = s.entity_id
         where s.user_id = :user_id and e.current_version is not null
           and e.status in ('REVIEWED', 'PUBLISHED')
         order by s.entity_id
    """,
    "challenge_states": """
        select area_id, ability_estimate, estimate_confidence,
               computed_at, model_version
          from public.learner_challenge_state
         where user_id = :user_id order by area_id
    """,
}


def _json_value(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


@dataclass(frozen=True)
class ProductionInputSnapshot:
    user_id: str
    input_version: str
    fingerprint: str
    entities: tuple[dict[str, Any], ...]
    domains: tuple[dict[str, Any], ...]
    objectives: tuple[dict[str, Any], ...]
    edges: tuple[dict[str, Any], ...]
    embeddings: tuple[dict[str, Any], ...]
    objective_states: tuple[dict[str, Any], ...]
    interest_states: tuple[dict[str, Any], ...]
    challenge_states: tuple[dict[str, Any], ...]
    explicit_preferences: tuple[dict[str, Any], ...]
    explorations: tuple[dict[str, Any], ...]
    anchor_entities: tuple[dict[str, Any], ...]


def build_production_snapshot(
    user_id: UUID, rows: Mapping[str, list[Mapping[str, Any]]]
) -> ProductionInputSnapshot:
    """Map one SQL snapshot without conflating learner-state domains."""
    converted = {
        name: [_json_value(dict(row)) for row in rows[name]] for name in QUERIES
    }
    available = {
        (row["entity_id"], row["entity_version"])
        for row in converted["entities"]
    }
    objective_states = [
        entry
        for row in converted["objective_states"]
        if (entry := objective_state_entry(row)) is not None
    ]
    anchors = select_anchors(
        available, converted["explorations"], converted["preferences"]
    )
    content = {
        "user_id": str(user_id),
        "input_version": INPUT_VERSION,
        **converted,
        "objective_states": objective_states,
        "anchor_entities": anchors,
    }
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), allow_nan=False)
    fingerprint = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return ProductionInputSnapshot(
        user_id=str(user_id), input_version=INPUT_VERSION, fingerprint=fingerprint,
        entities=tuple(converted["entities"]),
        domains=tuple(converted["domains"]),
        objectives=tuple(converted["objectives"]),
        edges=tuple(converted["edges"]),
        embeddings=tuple(converted["embeddings"]),
        objective_states=tuple(objective_states),
        interest_states=tuple(converted["interest_states"]),
        challenge_states=tuple(converted["challenge_states"]),
        explicit_preferences=tuple(converted["preferences"]),
        explorations=tuple(converted["explorations"]),
        anchor_entities=tuple(anchors),
    )


async def assemble_production_snapshot(
    factory: async_sessionmaker[AsyncSession], user_id: UUID
) -> ProductionInputSnapshot:
    """Read all required input domains in one RLS-scoped repeatable-read tx.

    The returned data is detached. No provider or other network call is made
    while the transaction is open.
    """
    async with factory() as session:
        async with session.begin():
            await session.execute(text("set transaction isolation level repeatable read"))
            await set_current_user(session, user_id)
            rows: dict[str, list[Mapping[str, Any]]] = {}
            for name, query in QUERIES.items():
                result = await session.execute(text(query), {"user_id": user_id})
                rows[name] = list(result.mappings().all())
            return build_production_snapshot(user_id, rows)
