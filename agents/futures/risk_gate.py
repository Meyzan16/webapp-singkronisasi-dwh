"""
Risk Gate — circuit-breaker and RAR gate for futures position opens.

Two independent guards:
  1. Drawdown circuit-breaker: portfolio drawdown from peak > DD_HARD_STOP_PCT
     → hard stop, no new positions until drawdown recovers below DD_RECOVER_PCT.
  2. Risk-Adjusted Return gate: Sharpe proxy < RAR_GATE_THRESHOLD and >= RAR_MIN_TRADES
     → gate closed (strategy is producing negative risk-adjusted returns).

State is refreshed by the risk dashboard endpoint (polled by frontend every 15 s).
auto_trader and POST /futures/trade evaluate inline when state is stale (backend restart,
no frontend polling yet).
"""

import time

import structlog

logger = structlog.get_logger(__name__)

# ── Thresholds ─────────────────────────────────────────────────────────────────
DD_HARD_STOP_PCT   = 20.0   # drawdown from peak > 20% → circuit breaker trips
DD_RECOVER_PCT     = 10.0   # drawdown must fall below this before breaker resets (hysteresis)
RAR_GATE_THRESHOLD = -0.5   # Sharpe proxy < −0.5 → RAR gate closes
RAR_MIN_TRADES     = 5      # need >= 5 closed trades for Sharpe to be meaningful
STATE_TTL          = 5 * 60 # state older than 5 min is considered stale

# ── In-memory state ────────────────────────────────────────────────────────────
_state: dict = {
    "active":        False,  # True = gate CLOSED (no new positions allowed)
    "gate_type":     "none", # "none" | "circuit_breaker" | "rar" | "override"
    "reason":        "ok",
    "drawdown_pct":  0.0,
    "rar":           0.0,
    "n_trades":      0,
    "updated_at":    0.0,
    "override":      None,   # None = auto | True = force-open | False = force-closed
}


def update_gate_state(drawdown_pct: float, rar: float, n_trades: int) -> None:
    """
    Refresh gate state from pre-computed metrics.
    Called from get_risk_dashboard() — frontend polls this every 15 s.
    """
    global _state
    _state["drawdown_pct"] = drawdown_pct
    _state["rar"]          = rar
    _state["n_trades"]     = n_trades
    _state["updated_at"]   = time.time()

    # Manual override wins over auto-logic
    if _state["override"] is not None:
        _state["active"]    = not _state["override"]   # override=True → gate open → active=False
        _state["gate_type"] = "override"
        _state["reason"]    = f"manual override: gate {'open' if _state['override'] else 'closed'}"
        return

    if drawdown_pct > DD_HARD_STOP_PCT:
        _state["active"]    = True
        _state["gate_type"] = "circuit_breaker"
        _state["reason"]    = (
            f"Circuit breaker aktif: drawdown {drawdown_pct:.1f}% "
            f"melampaui batas keras {DD_HARD_STOP_PCT:.0f}%. "
            f"Agen berhenti buka posisi baru hingga drawdown < {DD_RECOVER_PCT:.0f}%."
        )
    elif n_trades >= RAR_MIN_TRADES and rar < RAR_GATE_THRESHOLD:
        _state["active"]    = True
        _state["gate_type"] = "rar"
        _state["reason"]    = (
            f"RAR gate aktif: Sharpe {rar:.3f} di bawah threshold "
            f"{RAR_GATE_THRESHOLD} ({n_trades} trade tertutup). "
            f"Strategi sedang negatif risk-adjusted."
        )
    else:
        _state["active"]    = False
        _state["gate_type"] = "none"
        _state["reason"]    = "ok"

    logger.debug(
        "risk_gate_updated",
        active=_state["active"], gate_type=_state["gate_type"],
        dd=round(drawdown_pct, 2), rar=round(rar, 3), trades=n_trades,
    )


async def evaluate_risk_gate() -> None:
    """
    Fallback: query DB directly to refresh gate state.
    Called by auto_trader / trade endpoint when state is stale.
    """
    import statistics

    from sqlalchemy import select
    from app.database import AsyncSessionLocal, is_db_available
    from app.models.paper_trade import PaperTrade
    from app.api.v1.balance import get_or_create_balance
    from app.services.trading_costs import FUTURES_BALANCE_STATUSES

    if not is_db_available():
        return  # keep existing state; don't block on DB unavailability

    try:
        _wallet     = await get_or_create_balance("futures")
        wallet_base = _wallet.initial_balance + _wallet.deposited_total - _wallet.withdrawn_total

        async with AsyncSessionLocal() as session:
            closed_trades = list((await session.execute(
                select(PaperTrade).where(
                    PaperTrade.style.in_(["futures_agent1", "futures_agent2", "futures_agent3"]),
                    PaperTrade.status.in_(list(FUTURES_BALANCE_STATUSES)),   # BUG-L19: include expired
                    PaperTrade.pnl_dollar.isnot(None),
                ).order_by(PaperTrade.closed_at.asc())
            )).scalars().all())

        pnl_series: list[float] = []
        balance  = wallet_base
        peak_bal = wallet_base
        max_dd   = 0.0

        for t in closed_trades:
            pnl_d    = t.pnl_dollar or 0.0
            balance += pnl_d
            pnl_series.append(pnl_d)
            peak_bal = max(peak_bal, balance)
            dd = (peak_bal - balance) / peak_bal * 100 if peak_bal > 0 else 0.0
            if dd > max_dd:
                max_dd = dd

        sharpe = 0.0
        if len(pnl_series) >= RAR_MIN_TRADES:
            try:
                mu     = statistics.mean(pnl_series)
                std    = statistics.stdev(pnl_series)
                sharpe = round(mu / std, 3) if std > 0 else 0.0
            except Exception:
                pass

        update_gate_state(max_dd, sharpe, len(pnl_series))

    except Exception as exc:
        logger.warning("risk_gate_evaluate_failed", error=str(exc))


def is_gate_open() -> tuple[bool, str]:
    """
    Synchronous check — True = gate open (new positions allowed).
    Returns (can_open, reason). Called from auto_trader and trade endpoint.
    """
    if _state["active"]:
        return False, _state["reason"]
    return True, "ok"


def is_state_stale() -> bool:
    """True if gate state has never been evaluated or is older than STATE_TTL."""
    return _state["updated_at"] == 0.0 or (time.time() - _state["updated_at"]) > STATE_TTL


def set_override(value) -> None:
    """
    Manual override:
      value=True  → force gate OPEN (allow positions even if circuit breaker would fire)
      value=False → force gate CLOSED (block all new positions regardless of metrics)
      value=None  → revert to auto (cleared override; next evaluate_risk_gate re-computes)
    """
    _state["override"] = value
    if value is True:
        _state["active"]    = False
        _state["gate_type"] = "override"
        _state["reason"]    = "manual override: gate dipaksa terbuka"
    elif value is False:
        _state["active"]    = True
        _state["gate_type"] = "override"
        _state["reason"]    = "manual override: gate dipaksa tertutup"
    else:
        _state["gate_type"] = "none"
        _state["reason"]    = "ok (override cleared)"
        # Don't update active yet — let next evaluate_risk_gate decide
    logger.info("risk_gate_override", value=value)


def get_gate_state() -> dict:
    """Full gate state dict for API exposure."""
    return {
        "active":        _state["active"],
        "gate_type":     _state["gate_type"],   # none | circuit_breaker | rar | override
        "reason":        _state["reason"],
        "drawdown_pct":  round(_state["drawdown_pct"], 2),
        "rar":           round(_state["rar"], 3),
        "n_trades":      _state["n_trades"],
        "updated_at":    _state["updated_at"],
        "override":      _state["override"],
        "dd_threshold":  DD_HARD_STOP_PCT,
        "dd_recover":    DD_RECOVER_PCT,
        "rar_threshold": RAR_GATE_THRESHOLD,
        "rar_min_trades": RAR_MIN_TRADES,
        "stale":         is_state_stale(),
    }
