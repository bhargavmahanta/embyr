"""A small structured formatter for safe learning-domain LogRecord fields."""

import json
import logging
from datetime import datetime, timezone

FIELDS = (
    "command_id",
    "resource_id",
    "job_id",
    "attempt",
    "queue_age_seconds",
    "expired_lease",
    "worker_contract_version",
    "evaluator_version",
    "rubric_version",
    "event_type",
    "event_contract_version",
    "job_status",
    "failure_category",
    "http_status",
    "result_type",
    "replay",
    "latency_seconds",
)


class LearningJSONFormatter(logging.Formatter):
    def format(self, record):
        data = {
            "timestamp": datetime.fromtimestamp(
                record.created, timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        data.update(
            {key: getattr(record, key) for key in FIELDS if hasattr(record, key)}
        )
        return json.dumps(data, separators=(",", ":"), default=str)
