"""Narrow ledger recapture boundary.

Ordinary writes are captured by deferred source triggers at commit, including
M4 raw SQL and worker evidence transitions. This helper retries capture from an
authoritative owned ledger row; it never accepts caller-provided receipt facts.
The database compares immutable facts and owns allocation and queue references.
"""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def recapture_ledger(session: AsyncSession, user_id: UUID, event_id: UUID) -> int:
    """Capture/reuse within the caller's source transaction; never commit here."""
    return (
        await session.execute(
            text("select public.m6_recapture_event(:user_id,:event_id)"),
            {"user_id": user_id, "event_id": event_id},
        )
    ).scalar_one()


async def lock_source_owner(session: AsyncSession, user_id: UUID) -> bool:
    """Fence deletion before mutable worker sources, preserving M5 lock order."""
    return (
        await session.execute(
            text("select public.m6_lock_source_owner(:user_id)"), {"user_id": user_id}
        )
    ).scalar_one()
