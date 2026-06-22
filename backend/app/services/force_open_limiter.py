"""
Force-open rate limiter — Phase 1 B1.2.

5 force-opens/jam per session (DB-persistent, restart-survivable).
"""

import time

from sqlalchemy import select, func

from app.database import AsyncSessionLocal, is_db_available
from app.models.force_open_log import ForceOpenLog

WINDOW_SEC = 3600        # 1 hour
MAX_PER_WINDOW = 5


async def can_force_open(session_id: str) -> tuple[bool, int, int]:
    """
    Check if force-open allowed for this session.
    Returns (allowed, used, remaining).
    """
    if not is_db_available():
        return True, 0, MAX_PER_WINDOW

    cutoff = time.time() - WINDOW_SEC
    async with AsyncSessionLocal() as s:
        r = await s.execute(
            select(func.count(ForceOpenLog.id)).where(
                ForceOpenLog.session == session_id,
                ForceOpenLog.ts >= cutoff,
                ForceOpenLog.accepted.is_(True),
            )
        )
        used = int(r.scalar() or 0)
    remaining = max(0, MAX_PER_WINDOW - used)
    return used < MAX_PER_WINDOW, used, remaining


async def record_force_open(
    session_id: str,
    symbol: str,
    direction: str,
    market: str,
    accepted: bool,
) -> None:
    """Log every attempt, accepted or rejected."""
    if not is_db_available():
        return
    async with AsyncSessionLocal() as s:
        s.add(ForceOpenLog(
            ts=time.time(),
            session=session_id,
            market=market,
            symbol=symbol.upper(),
            direction=direction.upper(),
            accepted=accepted,
        ))
        await s.commit()
