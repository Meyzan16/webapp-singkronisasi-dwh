"""
Admin endpoints — destructive operations gated by ALLOW_DB_RESET=true.

PLAN_v2 P0.2 — POST /admin/reset_simulation
  Wipes simulated trading data so the agent learning loop can re-train on
  clean evidence after monitor/scanner hardening lands. Preserves the user's
  initial deposit configuration on paper_balances by default.
"""

import time

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, text

from app.config import get_settings
from app.database import AsyncSessionLocal, require_db
from app.models.paper_trade import PaperTrade
from app.models.signal_weight import AgentSignalWeight
from app.models.signal_weight_history import SignalWeightHistory
from app.models.health_event import HealthEvent

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["admin"])

CONFIRM_TOKEN = "RESET_ALL"


class ResetBody(BaseModel):
    confirm: str = Field(..., description=f"Must equal {CONFIRM_TOKEN!r}")
    preserve_initial_deposit: bool = Field(
        default=True,
        description="Keep paper_balances rows; reset balance to initial_balance + deposits - withdrawals.",
    )


def _require_reset_enabled() -> None:
    if not get_settings().allow_db_reset:
        raise HTTPException(
            status_code=403,
            detail="DB reset disabled. Set ALLOW_DB_RESET=true in .env to enable.",
        )


@router.post("/admin/reset_simulation", dependencies=[Depends(require_db)])
async def reset_simulation(body: ResetBody) -> dict:
    """
    Wipe all simulated trade data, weights, and ancillary logs.

    By default the paper_balances row is kept but reset to
    initial_balance + deposited_total - withdrawn_total (i.e. cash position
    after deposits/withdrawals but with all PnL zeroed). When
    preserve_initial_deposit=False the rows are deleted entirely and recreated
    by the balance API on next access.
    """
    _require_reset_enabled()
    if body.confirm != CONFIRM_TOKEN:
        raise HTTPException(status_code=400, detail=f"confirm must equal {CONFIRM_TOKEN!r}")

    summary: dict[str, int] = {}

    async with AsyncSessionLocal() as session:
        # 1. paper_trades — all styles (futures + spot + legacy scanner)
        r = await session.execute(delete(PaperTrade))
        summary["paper_trades"] = r.rowcount or 0

        # 2. agent_signal_weights
        r = await session.execute(delete(AgentSignalWeight))
        summary["agent_signal_weights"] = r.rowcount or 0

        # 3. signal_weight_history
        r = await session.execute(delete(SignalWeightHistory))
        summary["signal_weight_history"] = r.rowcount or 0

        # 4. health_events
        r = await session.execute(delete(HealthEvent))
        summary["health_events"] = r.rowcount or 0

        # 5. Ancillary tables that may not have ORM classes loaded here — raw SQL.
        for sql in [
            "DELETE FROM balance_transactions",
            "DELETE FROM weekly_backtest_result",
            "DELETE FROM force_open_log",
            "DELETE FROM big_mover_log",
        ]:
            try:
                r = await session.execute(text(sql))
                summary[sql.split()[-1]] = r.rowcount or 0
            except Exception as exc:
                # Table may not exist on a fresh DB — log and continue.
                logger.warning("reset_table_skipped", sql=sql, error=str(exc)[:80])
                summary[sql.split()[-1]] = -1

        # 6. paper_balances — reset to base equity or delete entirely
        if body.preserve_initial_deposit:
            r = await session.execute(
                text(
                    "UPDATE paper_balances "
                    "SET balance = initial_balance + deposited_total - withdrawn_total, "
                    "    realized_pnl = 0.0, "
                    "    updated_at = :now"
                ),
                {"now": time.time()},
            )
            summary["paper_balances_reset"] = r.rowcount or 0
        else:
            r = await session.execute(text("DELETE FROM paper_balances"))
            summary["paper_balances_deleted"] = r.rowcount or 0

        await session.commit()

    # 7. Clear in-memory caches so agents don't keep stale weights/blacklists.
    cleared: list[str] = []
    try:
        from agents.futures import weight_updater as fwu
        fwu._weight_cache.clear()
        fwu._adaptive_thresholds.clear()
        fwu._coin_blacklist.clear()
        fwu._coin_win_rates.clear()
        fwu._last_run = None
        cleared.append("futures.weight_updater")
    except Exception as exc:
        logger.warning("cache_clear_skipped", target="futures.weight_updater", error=str(exc)[:80])

    try:
        from agents.opportunity import weight_updater as swu
        swu._last_run = None
        swu._last_count = 0
        cleared.append("opportunity.weight_updater")
    except Exception as exc:
        logger.warning("cache_clear_skipped", target="opportunity.weight_updater", error=str(exc)[:80])

    try:
        from agents.shared import cross_agent_learning as cal
        cal._cross_cache.clear()
        cal._last_run = None
        cleared.append("shared.cross_agent_learning")
    except Exception as exc:
        logger.warning("cache_clear_skipped", target="shared.cross_agent_learning", error=str(exc)[:80])

    logger.warning(
        "simulation_reset_executed",
        preserve_initial=body.preserve_initial_deposit,
        wiped=summary,
        caches_cleared=cleared,
    )
    return {
        "ok":               True,
        "preserve_initial": body.preserve_initial_deposit,
        "wiped":            summary,
        "caches_cleared":   cleared,
        "ts":               time.time(),
    }
