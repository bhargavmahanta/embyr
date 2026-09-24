"""Production recommendation input mapping, separate from M3 simulation envelopes.

These helpers operate on a coherent database snapshot. They never infer anchors
from arbitrary learner facts or a mastery threshold from numeric evidence.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any
from uuid import UUID

OBJECTIVE_STATES = frozenset({
    "ENCOUNTERED", "EXPLORING", "DEVELOPING", "UNDERSTOOD",
    "REVISITING", "RETAINED", "PAUSED",
})
QUERY_INPUT_VERSION = "semantic-query-text/v1"


def objective_state_entry(row: Mapping[str, Any]) -> dict[str, str | int] | None:
    """Map stored categorical evidence, leaving absent state UNKNOWN to M3.

    The numeric estimates are deliberately unread. A missing categorical value
    is omitted, so M3's objective-relative lookup returns UNKNOWN.
    """
    state = row["categorical_state"]
    if state is None:
        return None
    if state not in OBJECTIVE_STATES:
        raise ValueError(f"unsupported objective state: {state!r}")
    return {
        "objective_id": str(row["objective_id"]),
        "entity_id": str(row["entity_id"]),
        "entity_version": int(row["entity_version"]),
        "state": state,
    }


def select_anchors(
    available_entity_versions: Iterable[tuple[UUID, int]],
    explorations: Iterable[Mapping[str, Any]],
    preferences: Iterable[Mapping[str, Any]],
) -> list[dict[str, str | int]]:
    """Select explicit v1 query anchors in canonical entity/version order."""
    available = set(available_entity_versions)
    keys = {
        (row["entity_id"], row["entity_version"])
        for row in explorations
        if row["status"] == "ACTIVE"
    }
    keys.update(
        (row["entity_id"], row["entity_version"])
        for row in preferences
        if row["preference"] == "MORE"
    )
    return [
        {"entity_id": str(entity_id), "entity_version": version}
        for entity_id, version in sorted(keys & available, key=lambda key: (str(key[0]), key[1]))
    ]


def semantic_query_text(title: str, summary: str) -> str:
    """The deterministic, per-anchor ``semantic-query-text/v1`` recipe."""
    if not title or not summary:
        raise ValueError("semantic query requires an anchor title and summary")
    return f"TITLE: {title}\nSUMMARY: {summary}"
