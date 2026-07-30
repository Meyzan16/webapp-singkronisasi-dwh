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


# Daftar agen dari registry tunggal (app/services/agent_registry.py) — lane baru
# cukup didaftarkan sekali di layer agent, tak perlu menyunting file ini lagi.
from app.services.agent_registry import FUTURES_AGENTS, SPOT_AGENT  # noqa: E402

_FUTURES_STYLES = FUTURES_AGENTS
_SPOT_STYLES    = [SPOT_AGENT]


class ResetBody(BaseModel):
    confirm: str = Field(..., description=f"Must equal {CONFIRM_TOKEN!r}")
    preserve_initial_deposit: bool = Field(
        default=True,
        description="Keep paper_balances rows; reset balance to initial_balance + deposits - withdrawals.",
    )
    # PLAN_v12 P4 — batasi reset ke satu market. "all" = perilaku lama (kompat).
    scope: str = Field(
        default="all",
        description="'all' | 'spot' | 'futures' — which market's trades+balance to wipe.",
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

    scope = body.scope if body.scope in ("all", "spot", "futures") else "all"
    summary: dict[str, int] = {"scope": scope}

    async with AsyncSessionLocal() as session:
        # 1. paper_trades — scoped ke market yang diminta (SPOT aman saat scope=futures)
        if scope == "all":
            r = await session.execute(delete(PaperTrade))
        else:
            _styles = _FUTURES_STYLES if scope == "futures" else _SPOT_STYLES
            r = await session.execute(delete(PaperTrade).where(PaperTrade.style.in_(_styles)))
        summary["paper_trades"] = r.rowcount or 0

        # 2-5. Wipe learning/log tables HANYA saat scope=all (shared antar-market —
        # jangan sentuh saat reset satu market agar market lain tak terganggu).
        if scope == "all":
            r = await session.execute(delete(AgentSignalWeight))
            summary["agent_signal_weights"] = r.rowcount or 0
            r = await session.execute(delete(SignalWeightHistory))
            summary["signal_weight_history"] = r.rowcount or 0
            r = await session.execute(delete(HealthEvent))
            summary["health_events"] = r.rowcount or 0
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
                    logger.warning("reset_table_skipped", sql=sql, error=str(exc)[:80])
                    summary[sql.split()[-1]] = -1

        # 6. paper_balances — reset ke base equity (scoped ke market bila bukan all)
        _bal_where = "" if scope == "all" else " WHERE style = :style"
        _params: dict = {"now": time.time()}
        if scope != "all":
            _params["style"] = scope
        if body.preserve_initial_deposit:
            r = await session.execute(
                text(
                    "UPDATE paper_balances "
                    "SET balance = initial_balance + deposited_total - withdrawn_total, "
                    "    realized_pnl = 0.0, "
                    "    updated_at = :now" + _bal_where
                ),
                _params,
            )
            summary["paper_balances_reset"] = r.rowcount or 0
        else:
            r = await session.execute(
                text("DELETE FROM paper_balances" + _bal_where), _params
            )
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

    # PLAN_v11 P4: clear RAR/lane-pause gate state — metrik lama tak boleh
    # menahan gate tetap tertutup setelah DB direset (anti-deadlock).
    try:
        from agents.futures import risk_gate
        risk_gate.reset_state()
        cleared.append("futures.risk_gate")
    except Exception as exc:
        logger.warning("cache_clear_skipped", target="futures.risk_gate", error=str(exc)[:80])

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
