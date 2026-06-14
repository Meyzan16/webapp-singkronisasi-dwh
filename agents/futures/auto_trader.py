"""
Auto Trader — auto-opens paper positions for high-score futures signals.

Rules:
  score >= AUTO_OPEN_THRESHOLD → auto open (both agents independently)
  Max MAX_AUTO_POSITIONS open per agent at a time
  Dedup: one open trade per symbol+agent
  Auto-opened trades are tagged with "auto_opened": True in signals_json
"""

import json
import time
from typing import Optional

import structlog
from sqlalchemy import func, select

from app.database import AsyncSessionLocal, is_db_available
from app.models.paper_trade import PaperTrade
from agents.futures.regime import get_cached_regime

logger = structlog.get_logger(__name__)

AUTO_OPEN_THRESHOLD = 72   # fallback when no adaptive threshold yet
MAX_AUTO_POSITIONS  = 6    # P2: GLOBAL cap across all lanes (one shared wallet)
FUTURES_COOLDOWN_HOURS = 3 # F55: no re-entry within 3h of an SL on the same symbol (global)

# P2: all futures lane styles share ONE wallet → dedup & limits are GLOBAL (BUG-L1).
_FUTURES_STYLES = ("futures_agent1", "futures_agent2", "futures_agent3")

# Regimes where auto-open is fully disabled
AUTO_DISABLED_REGIMES = {"volatile"}  # volatile = immediate SL risk

# Global toggle — can be changed via API at runtime
_auto_enabled = True

# F102: manual threshold override set via API. When None, adaptive threshold is used.
_manual_threshold: Optional[int] = None


def set_auto_enabled(flag: bool) -> None:
    global _auto_enabled
    _auto_enabled = flag
    logger.info("auto_trade_toggled", enabled=flag)


def is_auto_enabled() -> bool:
    return _auto_enabled


def set_auto_threshold(threshold: Optional[int]) -> None:
    """F102: manual override for auto-open threshold. Pass None to revert to adaptive."""
    global _manual_threshold
    _manual_threshold = threshold
    logger.info("auto_threshold_set", threshold=threshold)


def get_auto_threshold() -> int:
    """F102: displayed/effective base threshold — manual override or default fallback."""
    return _manual_threshold if _manual_threshold is not None else AUTO_OPEN_THRESHOLD


def _effective_threshold(agent: str) -> int:
    """Base threshold for an agent: manual override wins, else adaptive (F69)."""
    if _manual_threshold is not None:
        return _manual_threshold
    from agents.futures.weight_updater import get_adaptive_thresholds
    return get_adaptive_thresholds(agent)["auto_threshold"]


async def auto_open_positions(candidates: list[dict]) -> int:
    """
    P2 — UNIFIED global auto-open across ALL futures lanes (pre_move + momentum).

    Takes the combined candidate pool from every lane and opens the globally best
    setups, capped by ONE shared wallet:
      - BUG-L1: ONE position per symbol across all lanes (cross-margin nets to one
        position per symbol) — the highest-score candidate per symbol wins.
      - BUG-L12: in a volatile regime, momentum setups are still allowed; only
        pre_move setups are skipped (was a blanket block of all lanes).
    Returns count of positions opened.
    """
    if not _auto_enabled or not is_db_available():
        return 0

    regime = get_cached_regime()

    # Phase 10: risk gate — circuit-breaker (DD > 20%) + RAR gate (Sharpe < −0.5)
    from agents.futures.risk_gate import is_gate_open, is_state_stale, evaluate_risk_gate
    if is_state_stale():
        await evaluate_risk_gate()
    gate_open, gate_reason = is_gate_open()
    if not gate_open:
        logger.info("auto_trade_gate_blocked", reason=gate_reason)
        return 0

    # Dedup by symbol — keep the highest-score candidate (global ranking, BUG-L1).
    # Per-candidate adaptive threshold (its own lane) + ranging bar; BUG-L12 volatile gate.
    best_by_symbol: dict[str, dict] = {}
    for r in candidates:
        symbol = r.get("symbol", "")
        if not symbol:
            continue
        # BUG-L13: gate each candidate by ITS OWN coin regime (falls back to BTC market regime)
        coin_regime = r.get("regime", regime)
        threshold = _effective_threshold(r.get("agent", ""))
        if coin_regime == "ranging":
            threshold += 5
        if r.get("score", 0) < threshold:
            continue
        # BUG-L12: volatile blocks pre_move only — momentum rides the volatility
        if coin_regime in AUTO_DISABLED_REGIMES and r.get("setup_type") != "momentum":
            continue
        cur = best_by_symbol.get(symbol)
        if cur is None or r.get("score", 0) > cur.get("score", 0):
            best_by_symbol[symbol] = r

    ranked = sorted(best_by_symbol.values(), key=lambda x: x.get("score", 0), reverse=True)
    if not ranked:
        return 0

    opened = 0

    async with AsyncSessionLocal() as session:
        # GLOBAL open count across all lanes (BUG-L1)
        count_q = await session.execute(
            select(func.count(PaperTrade.id)).where(
                PaperTrade.style.in_(_FUTURES_STYLES),
                PaperTrade.status == "open",
            )
        )
        open_count: int = count_q.scalar() or 0
        if open_count >= MAX_AUTO_POSITIONS:
            logger.debug("auto_trader_at_max", open=open_count)
            return 0

        # GLOBAL open symbols + SL cooldown across all lanes (BUG-L1)
        existing_q = await session.execute(
            select(PaperTrade.symbol).where(
                PaperTrade.style.in_(_FUTURES_STYLES),
                PaperTrade.status == "open",
            )
        )
        existing_syms: set[str] = {row[0] for row in existing_q.fetchall()}

        sl_cooldown_q = await session.execute(
            select(PaperTrade.symbol).where(
                PaperTrade.style.in_(_FUTURES_STYLES),
                PaperTrade.status == "sl",
                PaperTrade.closed_at > (time.time() - FUTURES_COOLDOWN_HOURS * 3600),
            )
        )
        sl_cooldown_syms: set[str] = {row[0] for row in sl_cooldown_q.fetchall()}

        now = time.time()

        for sig in ranked:
            if open_count + opened >= MAX_AUTO_POSITIONS:
                break

            symbol = sig.get("symbol", "")
            agent  = sig.get("agent", "")
            if not symbol or symbol in existing_syms:
                continue   # BUG-L1: already open in some lane → skip (cross-margin = one position)
            if symbol in sl_cooldown_syms:
                logger.debug("auto_trade_cooldown_skip", symbol=symbol)
                continue

            # F13: ensure risk_pct is never None/0 — use 2.0 as safe fallback
            risk_pct  = sig.get("risk_pct") or 2.0
            leverage  = sig.get("leverage", 5)

            # Phase 9: size from the REAL shared futures wallet (balance-aware + portfolio heat).
            from app.api.v1.balance import compute_futures_sizing
            sizing = await compute_futures_sizing(sig.get("score", 0), risk_pct, leverage)
            if not sizing["can_open"]:
                logger.info("auto_trade_sizing_blocked", symbol=symbol, reason=sizing["reason"])
                break   # wallet limit reached (heat / concurrency / margin) — stop this cycle
            pos_size        = sizing["position_size"]
            risk_dollar_val = sizing["risk_dollar"]
            bal_snapshot    = sizing["balance"]

            meta = {
                "signals":      sig.get("signals", []),
                "tp1":          sig.get("tp1"),
                "tp2":          sig.get("tp2"),
                "tp3":          sig.get("tp3"),
                "tp1_pct":      sig.get("tp1_pct", 0),
                "tp2_pct":      sig.get("tp2_pct", 0),
                "tp3_pct":      sig.get("tp3_pct", 0),
                "risk_pct":     risk_pct,
                "rr_ratio":     sig.get("rr_ratio", 0),
                "leverage":     sig.get("leverage", 5),
                "score":        sig.get("score", 0),
                "funding_rate": sig.get("funding_rate", 0),
                "oi_change":    sig.get("oi_change", 0),
                "liq_long":     sig.get("liq_long", 0),
                "liq_short":    sig.get("liq_short", 0),
                "margin_type":  "cross",
                "setup_type":   sig.get("setup_type", "pre_move"),   # P2: lane tag
                "auto_opened":  True,
            }

            trade = PaperTrade(
                symbol           = symbol,
                direction        = sig.get("direction", "LONG"),
                style            = agent,                # lane identity preserved for win-rate
                entry_price      = sig.get("entry", sig.get("price", 0)),
                stop_loss        = sig.get("sl", 0),
                take_profit      = sig.get("tp2", 0),
                risk_reward      = f"1:{sig.get('rr_ratio', 0)}",
                probability      = sig.get("score", 0),
                alert_type       = sig.get("direction", "").lower(),
                sl_method        = f"Auto: ATR swing | SL {sig.get('sl', 0)}",
                tp_method        = f"Auto TP2 +{sig.get('tp2_pct', 0)}%",
                signals_json     = json.dumps(meta, ensure_ascii=False),
                entry_type       = "market",
                entry_at         = now,
                status           = "open",
                leverage         = sig.get("leverage", 5),
                margin_type      = "cross",
                regime           = sig.get("regime", regime),   # BUG-L13: per-coin regime if present
                trail_active     = False,
                position_size    = pos_size,
                risk_dollar      = risk_dollar_val,
                balance_snapshot = bal_snapshot,
            )
            session.add(trade)
            # Commit per open so the next compute_futures_sizing sees this position's
            # margin/risk (portfolio heat must account for trades opened earlier this cycle).
            await session.commit()
            existing_syms.add(symbol)
            opened += 1

            logger.info(
                "auto_trade_opened",
                agent=agent, symbol=symbol, setup_type=sig.get("setup_type"),
                direction=sig.get("direction"), score=sig.get("score"),
                leverage=sig.get("leverage"), entry=sig.get("entry"),
                pos_size=pos_size, risk_dollar=risk_dollar_val,
            )

    return opened
