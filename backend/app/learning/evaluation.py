"""Pinned deterministic recognition classification, with no provider or state writes."""

from dataclasses import dataclass

from app.db.models.assessment import SUPPORT_LEVELS
from app.learning.content import validate_assessment


class PermanentEvaluationError(Exception):
    """Pinned content or answer cannot be evaluated by this contract."""


class TransientEvaluationError(Exception):
    """Processing may be retried without changing the learner's answer."""


@dataclass(frozen=True)
class EvaluationResult:
    result: str
    confidence: float
    feedback: str
    produces_evidence: bool


def evaluate(prompt: dict, content: dict, support_used: str | None) -> EvaluationResult:
    try:
        validate_assessment(prompt)
        if support_used is not None and support_used not in SUPPORT_LEVELS:
            raise ValueError("Invalid support snapshot")
        if (
            set(content) != {"option_id"}
            or content["option_id"] not in prompt["option_results"]
        ):
            raise ValueError("Unknown option")
        mapping = prompt["option_results"][content["option_id"]]
        return EvaluationResult(
            mapping["result"],
            float(mapping["confidence"]),
            mapping["feedback"],
            mapping["result"] == "SUPPORTED",
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise PermanentEvaluationError("Invalid pinned evaluation input") from exc
