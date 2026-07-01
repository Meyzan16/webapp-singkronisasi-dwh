"""
Agent Config Reader — TTL-cached DB overrides for critical runtime constants
(PLAN_v5 Group C).

Usage pattern: at the top of each agent's periodic entry point (once per scan
or monitor cycle — NOT once per symbol), reassign the module-level constant via
`global`:

    global MIN_QUOTE_VOLUME
    MIN_QUOTE_VOLUME = await cfg.get("spot", "min_quote_volume", MIN_QUOTE_VOLUME)

Because Python resolves bare global names at CALL time (not def time), every
function in that module — including ones defined earlier in the file, or
nested closures — sees the updated value for the rest of that cycle, with no
need to thread the value through every call site. The cache has a 60s TTL, so
in practice this is a cheap in-memory dict lookup on every cycle except the
one that happens to straddle the TTL boundary.

Falls back to the caller-supplied default when: the DB is unavailable, the row
doesn't exist yet, or the reload itself fails — an operator's misconfiguration
or a DB outage can never stop the trading agents from running.
"""

import time

import structlog

logger = structlog.get_logger(__name__)


class AgentConfigReader:
    TTL = 60.0  # seconds — matches PLAN_v5 "Keputusan Terkunci"

    def __init__(self) -> None:
        self._cache: dict[str, float] = {}
        self._loaded_at: float = 0.0

    async def _reload(self) -> None:
        from app.database import AsyncSessionLocal, is_db_available
        from app.models.agent_config import AgentConfig
        from sqlalchemy import select

        if not is_db_available():
            return
        try:
            async with AsyncSessionLocal() as session:
                rows = (await session.execute(select(AgentConfig))).scalars().all()
                self._cache = {f"{r.agent_group}.{r.key}": r.value_num for r in rows}
                self._loaded_at = time.time()
        except Exception as exc:
            logger.warning("agent_config_reload_failed", error=str(exc)[:120])

    async def get(self, group: str, key: str, default: float) -> float:
        """Async read — triggers a reload if the cache is stale (>60s old)."""
        if time.time() - self._loaded_at > self.TTL:
            await self._reload()
        return self._cache.get(f"{group}.{key}", default)

    def peek(self, group: str, key: str, default: float) -> float:
        """Non-blocking read of whatever is currently cached — no reload, no await.
        Use only where an `await` isn't available; prefer `get()` elsewhere."""
        return self._cache.get(f"{group}.{key}", default)


cfg = AgentConfigReader()
