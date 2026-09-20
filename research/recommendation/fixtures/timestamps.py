"""Deterministic simulation time.

The approved simulation epoch is ``2026-01-01T00:00:00Z``. Fixture builders
derive every timestamp from it with deterministic offsets; they never read the
wall clock.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

SIM_EPOCH = "2026-01-01T00:00:00Z"

_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)


def sim_time(minutes: int = 0, seconds: int = 0) -> str:
    """Return an RFC3339 ``Z`` timestamp at the epoch plus a fixed offset."""
    moment = _EPOCH + timedelta(minutes=minutes, seconds=seconds)
    return moment.isoformat().replace("+00:00", "Z")
