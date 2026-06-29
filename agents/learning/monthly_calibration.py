"""
Monthly Threshold Calibration — PLAN_v3 P7 D7.2.

Trigger: 1st of each month (checked by futures scheduler).

Algorithm:
  1. Read resolved predictive_log entries from last 30 days
  2. Compute per-agent 4h hit rate
  3. If hit_rate < 40%: lower effective_min by 2 pts (too strict → missing good entries)
  4. If hit_rate > 70%: raise effective_min by 2 pts (too permissive → too much noise)
  5. Clamp: min 50, max 80
  6. Save adjusted threshold to AgentSignalWeight table (special signal_key = "_threshold_")

NOTE: This nudges the ADAPTIVE threshold stored in weight_updater, not the hard-coded MIN_SCORE.
The adaptive threshold is what `get_adaptive_thresholds()` returns after learning.
"""

import datetime
import time
from typing import Optional

import structlog
from sqlalchemy import select, update

from app.database import AsyncSessionLocal, is_db_available

logger = structlog.get_logger(__name__)

_last_run_month: Optional[str] = None
_ADJUST_STEP = 2.0   # pts per month
_MIN_THRESH  = 50.0
_MAX_THRESH  = 80.0
_MIN_SAMPLES = 20    # need at least 20 resolved entries to trust the hit rate


def _month_label() -> str:
    d = datetime.datetime.utcnow()
    return f"{d.year}-{d.month:02d}"


async def run_monthly_calibration() -> dict:
    """
    Run monthly threshold re-evaluation based on predictive_log hit rates.
    Returns summary of changes made.
    """
    global _last_run_month

    month = _month_label()
    if _last_run_month == month:
        return {"skipped": True, "reason": f"already ran for {month}"}

    if not is_db_available():
        return {"skipped": True, "reason": "db unavailable"}

    try:
        from app.models.predictive_log import PredictiveLog
        from app.models.signal_weight import AgentSignalWeight

        cutoff = time.time() - 30 * 86400
        now    = time.time()

        async with AsyncSessionLocal() as session:
            # Load resolved predictions from last 30 days
            result = await session.execute(
                select(PredictiveLog).where(
                    PredictiveLog.scanned_at >= cutoff,
                    PredictiveLog.resolved_at.is_not(None),
                )
            )
            rows = result.scalars().all()

        if not rows:
            logger.info("monthly_calibration_skip", reason="no resolved predictions")
            return {"skipped": True, "reason": "no resolved predictions in last 30 days"}

        # Aggregate per agent
        stats: dict[str, dict] = {}
        for row in rows:
            key = row.agent
            if key not in stats:
                stats[key] = {"total": 0, "hits_4h": 0}
            stats[key]["total"] += 1
            if row.hit_4h:
                stats[key]["hits_4h"] += 1

        changes = []
        async with AsyncSessionLocal() as session:
            for agent, s in stats.items():
                n      = s["total"]
                if n < _MIN_SAMPLES:
                    continue
                hr4 = s["hits_4h"] / n

                # Load current threshold from AgentSignalWeight
                w_result = await session.execute(
                    select(AgentSignalWeight).where(
                        AgentSignalWeight.agent      == agent,
                        AgentSignalWeight.signal_key == "_threshold_",
                        AgentSignalWeight.regime     == "all",
                    )
                )
                thresh_row = w_result.scalar_one_or_none()
                current = thresh_row.weight if thresh_row else None

                # Load weight_updater's current adaptive threshold as fallback
                if current is None:
                    try:
                        from agents.futures.weight_updater import get_adaptive_thresholds
                        current = get_adaptive_thresholds(agent).get("min_score", 60.0)
                    except Exception:
                        current = 60.0

                # Adjust direction
                if hr4 < 0.40:
                    new_thresh = max(_MIN_THRESH, current - _ADJUST_STEP)
                    direction = "lowered"
                elif hr4 > 0.70:
                    new_thresh = min(_MAX_THRESH, current + _ADJUST_STEP)
                    direction = "raised"
                else:
                    continue   # hit rate is healthy — no change needed

                # Write back to AgentSignalWeight as special threshold record
                if thresh_row:
                    await session.execute(
                        update(AgentSignalWeight)
                        .where(
                            AgentSignalWeight.agent      == agent,
                            AgentSignalWeight.signal_key == "_threshold_",
                            AgentSignalWeight.regime     == "all",
                        )
                        .values(weight=new_thresh, updated_at=now)
                    )
                else:
                    from sqlalchemy.dialects.postgresql import insert as pg_insert
                    await session.execute(
                        pg_insert(AgentSignalWeight).values(
                            agent      = agent,
                            signal_key = "_threshold_",
                            regime     = "all",
                            weight     = new_thresh,
                            win_rate   = hr4,
                            total_count= n,
                            updated_at = now,
                        ).on_conflict_do_update(
                            index_elements=["agent", "signal_key", "regime"],
                            set_={"weight": new_thresh, "win_rate": hr4, "updated_at": now},
                        )
                    )

                changes.append({
                    "agent":        agent,
                    "direction":    direction,
                    "old_thresh":   round(current, 1),
                    "new_thresh":   round(new_thresh, 1),
                    "hit_rate_4h":  round(hr4 * 100, 1),
                    "samples":      n,
                })
                logger.info("monthly_threshold_adjusted", agent=agent, direction=direction,
                            old=current, new=new_thresh, hit_rate_4h=f"{hr4*100:.1f}%")

            await session.commit()

        _last_run_month = month
        return {"month": month, "changes": changes, "agents_checked": len(stats)}

    except Exception as exc:
        logger.error("monthly_calibration_error", error=str(exc)[:120])
        return {"error": str(exc)[:120]}
