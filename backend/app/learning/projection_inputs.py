"""Closed projection-input/v1 parser; reference validation/loading is separate."""

from __future__ import annotations

import math
import re
from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID

from app.learning.world_projection import canonical_json

CONTRACTS = {
    "input": "projection-input/v1",
    "worker": "projection-worker/v1",
    "learner": "learner-projection/v1",
    "world": "world-projection/v1",
    "memory": "memory-summary/v1",
    "delta": "world-delta/v1",
}
EVENTS = frozenset(
    [
        "ONBOARDING_COMPLETED",
        "EXPLICIT_INTEREST_CHANGED",
        "RECOMMENDATION_ACCEPTED",
        "RECOMMENDATION_SKIPPED",
        "EXPLORATION_STARTED",
        "EXPLORATION_WORK_PREPARED",
        "USER_RETURNED",
        "EXPLORATION_PAUSED",
        "EXPLORATION_RESUMED",
        "REFLECTION_SUBMITTED",
        "REFLECTION_UPDATED",
        "ASSESSMENT_STARTED",
        "HINT_REQUESTED",
        "ASSESSMENT_RESPONSE_SUBMITTED",
        "ASSESSMENT_EVALUATED",
        "ASSESSMENT_EVALUATION_FAILED",
        "ASSESSMENT_EVALUATION_RETRY_REQUESTED",
        "ASSESSMENT_COMPLETED",
        "ASSESSMENT_ABANDONED",
        "EXPLORATION_COMPLETED",
    ]
)
LEDGER_KEYS = frozenset(
    [
        "event_id",
        "event_type",
        "source_schema_version",
        "entity_id",
        "entity_version",
        "exploration_id",
        "assessment_session_id",
        "response_id",
        "evaluation_run_id",
        "reflection_id",
        "recommendation_id",
        "command_id",
        "event_ordinal",
        "preference",
        "preference_version",
    ]
)
EVIDENCE_KEYS = frozenset(
    [
        "evidence_id",
        "resulting_status",
        "source_type",
        "source_id",
        "evidence_type",
        "evidence_strength",
        "objective_id",
        "entity_id",
        "entity_version",
        "response_id",
        "evaluation_run_id",
        "evaluation_status",
        "evaluation_result",
        "evaluator_version",
        "rubric_version",
        "support_level",
        "classification_confidence",
        "transition_at",
    ]
)
RECEIPT_KEYS = frozenset(
    [
        "contract_version",
        "schema_version",
        "user_id",
        "source_sequence",
        "source_kind",
        "source_key",
        "source_group",
        "source_time",
        "facts",
    ]
)
SUPPORT = frozenset(
    ["SMALL_NUDGE", "STRONG_HINT", "MISSING_CONCEPT", "EXPLANATION", None]
)


class ProjectionError(Exception):
    def __init__(self, code):
        assert re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", code)
        self.code = code
        super().__init__(code)


def require(condition, code="INVALID_RECEIPT"):
    if not condition:
        raise ProjectionError(code)


def uuid_text(value):
    require(isinstance(value, str))
    try:
        require(str(UUID(value)) == value)
    except ValueError:
        raise ProjectionError("INVALID_RECEIPT") from None
    return value


def integer(value, minimum=1, maximum=2**63 - 1):
    require(type(value) is int and minimum <= value <= maximum)
    return value


def timestamp(value):
    if isinstance(value, datetime):
        require(value.tzinfo is not None)
        dt = value.astimezone(timezone.utc)
    else:
        require(isinstance(value, str) and value.endswith("Z"))
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ProjectionError("INVALID_RECEIPT") from None
    return dt.isoformat().replace("+00:00", "Z")


def _parse_receipt(user_id, raw):
    require(isinstance(raw, dict) and set(raw) == RECEIPT_KEYS)
    r = deepcopy(raw)
    require(
        r["contract_version"] == CONTRACTS["input"]
        and type(r["schema_version"]) is int
        and r["schema_version"] == 1
    )
    require(uuid_text(r["user_id"]) == user_id, "RECEIPT_OWNER")
    integer(r["source_sequence"])
    require(
        isinstance(r["source_group"], str)
        and re.fullmatch(r"[0-9]{1,20}", r["source_group"])
    )
    r["source_time"] = timestamp(r["source_time"])
    f = r["facts"]
    require(isinstance(f, dict))
    kind = r["source_kind"]
    if kind == "LEDGER":
        require(set(f) == LEDGER_KEYS and f["event_type"] in EVENTS)
        require(
            type(f["source_schema_version"]) is int and f["source_schema_version"] == 1
        )
        require(r["source_key"] == uuid_text(f["event_id"]))
        for k in [
            "entity_id",
            "exploration_id",
            "assessment_session_id",
            "response_id",
            "evaluation_run_id",
            "reflection_id",
            "recommendation_id",
            "command_id",
        ]:
            if f[k] is not None:
                uuid_text(f[k])
        for k in ["entity_version", "preference_version"]:
            if f[k] is not None:
                integer(f[k])
        require((f["command_id"] is None) == (f["event_ordinal"] is None))
        if f["event_ordinal"] is not None:
            integer(f["event_ordinal"], 0, 32767)
        require(
            f["preference"]
            in ["NEUTRAL", "MORE", "LESS", "PAUSED", "NOT_INTERESTED", None]
        )
        e = f["event_type"]
        if e not in [
            "ONBOARDING_COMPLETED",
            "EXPLICIT_INTEREST_CHANGED",
            "RECOMMENDATION_SKIPPED",
        ]:
            require(
                all(
                    f[k] is not None
                    for k in ["exploration_id", "entity_id", "entity_version"]
                ),
                "RECEIPT_LINEAGE",
            )
        if e.startswith("ASSESSMENT_") or e == "HINT_REQUESTED":
            require(f["assessment_session_id"] is not None, "RECEIPT_LINEAGE")
        if e in [
            "ASSESSMENT_RESPONSE_SUBMITTED",
            "ASSESSMENT_EVALUATED",
            "ASSESSMENT_EVALUATION_FAILED",
            "ASSESSMENT_EVALUATION_RETRY_REQUESTED",
            "ASSESSMENT_COMPLETED",
        ]:
            require(
                f["response_id"] is not None and f["evaluation_run_id"] is not None,
                "RECEIPT_LINEAGE",
            )
        if e in ["REFLECTION_SUBMITTED", "REFLECTION_UPDATED"]:
            require(f["reflection_id"] is not None, "RECEIPT_LINEAGE")
        if e in ["RECOMMENDATION_ACCEPTED", "RECOMMENDATION_SKIPPED"]:
            require(f["recommendation_id"] is not None, "RECEIPT_LINEAGE")
        if e == "ONBOARDING_COMPLETED":
            require(f["preference_version"] is not None, "RECEIPT_LINEAGE")
        if e == "EXPLICIT_INTEREST_CHANGED":
            require(
                f["entity_id"] and f["preference_version"] and f["preference"],
                "RECEIPT_LINEAGE",
            )
    elif kind == "EVIDENCE":
        require(set(f) == EVIDENCE_KEYS)
        for k in [
            "evidence_id",
            "source_id",
            "response_id",
            "evaluation_run_id",
            "objective_id",
            "entity_id",
        ]:
            uuid_text(f[k])
        require(
            f["source_id"] == f["response_id"]
            and f["source_type"] == "ASSESSMENT_RESPONSE"
            and f["evidence_type"] == "RECOGNITION"
            and f["evidence_strength"] == "WEAK",
            "RECEIPT_LINEAGE",
        )
        integer(f["entity_version"])
        require(f["resulting_status"] in ["ACTIVE", "SUPERSEDED", "REVOKED"])
        require(r["source_key"] == f"{f['evidence_id']}:{f['resulting_status']}")
        require(
            f["evaluation_status"]
            in ["PENDING", "SUCCEEDED", "FAILED", "SUPERSEDED", "REVOKED"]
        )
        require(
            f["evaluation_result"]
            in [
                "SUPPORTED",
                "PARTIAL",
                "MISCONCEPTION",
                "INSUFFICIENT_EVIDENCE",
                "UNCERTAIN",
                None,
            ]
        )
        require(f["support_level"] in SUPPORT)
        for k in ["evaluator_version", "rubric_version"]:
            require(isinstance(f[k], str) and 1 <= len(f[k]) <= 64)
        c = f["classification_confidence"]
        require(
            c is None or (type(c) in [int, float] and math.isfinite(c) and 0 <= c <= 1)
        )
        if f["transition_at"] is not None:
            f["transition_at"] = timestamp(f["transition_at"])
    elif kind == "BOOTSTRAP":
        require(
            set(f) == {"cutoff_source_sequence", "cutoff_at"}
            and r["source_key"] == "learner-projection/v1:baseline"
        )
        integer(f["cutoff_source_sequence"], 0)
        f["cutoff_at"] = timestamp(f["cutoff_at"])
        require(f["cutoff_at"] == r["source_time"])
    else:
        raise ProjectionError("INVALID_RECEIPT")
    require(len(canonical_json(r).encode("utf-8")) <= 8192, "RECEIPT_TOO_LARGE")
    return r


def parse_receipt(user_id, raw):
    try:
        return _parse_receipt(user_id, raw)
    except (TypeError, KeyError, ValueError, AttributeError, OverflowError):
        raise ProjectionError("INVALID_RECEIPT") from None
