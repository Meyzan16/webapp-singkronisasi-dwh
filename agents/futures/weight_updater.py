"""
Signal Weight Updater — runs after each scan cycle.

Reads all closed futures trades, maps signals → win/loss,
then upserts agent_signal_weights table.

Weight formula:
  win_rate >= 0.70 → weight = 1.5  (boost)
  win_rate >= 0.55 → weight = 1.2
  win_rate >= 0.40 → weight = 1.0  (neutral)
  win_rate <  0.40 → weight = 0.7  (reduce)
  total_count < 3  → weight = 1.0  (not enough data yet)
"""

import json
import re
import time
from typing import Optional

import structlog
from sqlalchemy import select

from app.database import AsyncSessionLocal, is_db_available
from app.models.paper_trade import PaperTrade
from app.models.signal_weight import AgentSignalWeight

logger = structlog.get_logger(__name__)

_last_run:   Optional[float] = None
_last_error: Optional[str]   = None
MIN_RUN_INTERVAL = 5 * 60  # don't run more than once every 5 min


def _normalize_signal(raw: str) -> str:
    """
    Convert a human-readable signal string to a stable key.
    Strip emojis, numbers, and reduce to 5-word normalized form.
    """
    cleaned = re.sub(r"[^\w\s%+.\-]", "", raw)
    cleaned = re.sub(r"\d+\.?\d*", "N", cleaned)
    words   = cleaned.strip().split()[:5]
    return "_".join(w.lower() for w in words if w)


def _weight_from_rate(win_rate: float, total: int) -> float:
    if total < 3:
        return 1.0
    if win_rate >= 0.70:
        return 1.5
    if win_rate >= 0.55:
        return 1.2
    if win_rate >= 0.40:
        return 1.0
    return 0.7


async def update_weights() -> int:
    """
    Re-compute signal weights from all closed futures trades.
    Returns number of rows upserted.
    """
    global _last_run, _last_error

    if not is_db_available():
        return 0

    now = time.time()
    if _last_run and (now - _last_run) < MIN_RUN_INTERVAL:
        return 0  # too soon

    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(PaperTrade).where(
                    PaperTrade.style.in_(["futures_agent1", "futures_agent2"]),
                    PaperTrade.status.in_(["tp", "sl"]),
                )
            )
            trades = list(result.scalars().all())

        if not trades:
            _last_run = now
            return 0

        # ── Build (agent, signal_key, regime) → {wins, total} map ─────────
        # key: (agent, signal_key, regime)
        stats: dict[tuple, dict] = {}

        for trade in trades:
            try:
                meta = json.loads(trade.signals_json or "{}")
            except Exception:
                meta = {}

            signals = meta.get("signals", [])
            if not signals:
                continue

            agent  = trade.style
            is_win = trade.status == "tp"
            regime = trade.regime or "all"

            for raw_sig in signals:
                key_all    = (agent, _normalize_signal(raw_sig), "all")
                key_regime = (agent, _normalize_signal(raw_sig), regime)

                for k in [key_all, key_regime]:
                    if k[1] == "":
                        continue
                    entry = stats.setdefault(k, {"wins": 0, "total": 0})
                    entry["total"] += 1
                    if is_win:
                        entry["wins"] += 1

        # ── Upsert to DB ──────────────────────────────────────────────────
        upserted = 0
        async with AsyncSessionLocal() as session:
            for (agent, signal_key, regime), v in stats.items():
                win_rate = v["wins"] / v["total"] if v["total"] > 0 else 0.0
                weight   = _weight_from_rate(win_rate, v["total"])

                existing = await session.execute(
                    select(AgentSignalWeight).where(
                        AgentSignalWeight.agent      == agent,
                        AgentSignalWeight.signal_key == signal_key,
                        AgentSignalWeight.regime     == regime,
                    ).limit(1)
                )
                row = existing.scalar_one_or_none()

                if row:
                    row.win_count   = v["wins"]
                    row.total_count = v["total"]
                    row.win_rate    = round(win_rate, 4)
                    row.weight      = round(weight, 2)
                    row.updated_at  = now
                else:
                    session.add(AgentSignalWeight(
                        agent       = agent,
                        signal_key  = signal_key,
                        regime      = regime,
                        win_count   = v["wins"],
                        total_count = v["total"],
                        win_rate    = round(win_rate, 4),
                        weight      = round(weight, 2),
                        updated_at  = now,
                    ))
                upserted += 1

            await session.commit()

        _last_run   = now
        _last_error = None
        logger.info("weights_updated", rows=upserted, trades=len(trades))
        return upserted

    except Exception as exc:
        _last_error = str(exc)[:120]
        logger.error("weight_update_error", error=_last_error)
        return 0


def get_state() -> dict:
    return {"last_run": _last_run, "last_error": _last_error}
