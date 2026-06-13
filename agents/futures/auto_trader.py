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
from app.services.trading_costs import FUTURES_STARTING_BALANCE, FUTURES_RISK_PCT
from agents.futures.regime import get_cached_regime

logger = structlog.get_logger(__name__)

AUTO_OPEN_THRESHOLD = 72   # fallback when no adaptive threshold yet
MAX_AUTO_POSITIONS  = 5    # max concurrent auto positions per agent

# Regimes where auto-open is fully disabled
AUTO_DISABLED_REGIMES = {"volatile"}  # volatile = immediate SL risk

# Global toggle — can be changed via API at runtime
_auto_enabled = True


def set_auto_enabled(flag: bool) -> None:
    global _auto_enabled
    _auto_enabled = flag
    logger.info("auto_trade_toggled", enabled=flag)


def is_auto_enabled() -> bool:
    return _auto_enabled


async def auto_open_positions(results: list[dict], agent: str) -> int:
    """
    Auto-open paper trades for signals where score >= threshold.
    Returns count of positions opened.
    """
    if not _auto_enabled or not is_db_available():
        return 0

    # BUG FIX: block auto-open in disabled regimes (volatile = immediate SL risk)
    regime = get_cached_regime()
    if regime in AUTO_DISABLED_REGIMES:
        logger.info("auto_trade_blocked_regime", agent=agent, regime=regime)
        return 0

    # F69: use adaptive threshold based on per-agent rolling win rate
    from agents.futures.weight_updater import get_adaptive_thresholds
    effective_threshold = get_adaptive_thresholds(agent)["auto_threshold"]
    if regime == "ranging":
        effective_threshold += 5   # extra bar in ranging (trend signals unreliable)

    # Filter: score >= threshold, sorted best first
    candidates = sorted(
        [r for r in results if r.get("score", 0) >= effective_threshold],
        key=lambda x: x.get("score", 0),
        reverse=True,
    )
    if not candidates:
        return 0

    opened = 0

    async with AsyncSessionLocal() as session:
        # Count current open positions for this agent
        count_q = await session.execute(
            select(func.count(PaperTrade.id)).where(
                PaperTrade.style  == agent,
                PaperTrade.status == "open",
            )
        )
        open_count: int = count_q.scalar() or 0

        if open_count >= MAX_AUTO_POSITIONS:
            logger.debug("auto_trader_at_max", agent=agent, open=open_count)
            return 0

        # Existing open symbols for this agent
        existing_q = await session.execute(
            select(PaperTrade.symbol).where(
                PaperTrade.style  == agent,
                PaperTrade.status == "open",
            )
        )
        existing_syms: set[str] = {row[0] for row in existing_q.fetchall()}

        # DB-based cooldown: skip if last trade for symbol+agent was SL within 3h
        FUTURES_COOLDOWN_HOURS = 3
        sl_cooldown_q = await session.execute(
            select(PaperTrade.symbol, PaperTrade.closed_at).where(
                PaperTrade.style  == agent,
                PaperTrade.status == "sl",
                PaperTrade.closed_at > (time.time() - FUTURES_COOLDOWN_HOURS * 3600),
            )
        )
        sl_cooldown_syms: set[str] = {row[0] for row in sl_cooldown_q.fetchall()}

        now    = time.time()
        regime = get_cached_regime()

        for sig in candidates:
            if open_count + opened >= MAX_AUTO_POSITIONS:
                break

            symbol = sig.get("symbol", "")
            if not symbol or symbol in existing_syms:
                continue
            # DB cooldown check
            if symbol in sl_cooldown_syms:
                logger.debug("auto_trade_cooldown_skip", agent=agent, symbol=symbol)
                continue

            # F13: ensure risk_pct is never None/0 — use 2.0 as safe fallback
            risk_pct = sig.get("risk_pct") or 2.0

            # F51: compute position sizing at open time
            notional         = FUTURES_STARTING_BALANCE * FUTURES_RISK_PCT / (risk_pct / 100)
            pos_size         = round(notional, 2)
            risk_dollar_val  = round(notional * (risk_pct / 100), 2)

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
                "auto_opened":  True,             # ← tagged as auto
            }

            trade = PaperTrade(
                symbol           = symbol,
                direction        = sig.get("direction", "LONG"),
                style            = agent,
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
                regime           = regime,
                trail_active     = False,
                position_size    = pos_size,
                risk_dollar      = risk_dollar_val,
                balance_snapshot = FUTURES_STARTING_BALANCE,
            )
            session.add(trade)
            existing_syms.add(symbol)
            opened += 1

            logger.info(
                "auto_trade_opened",
                agent=agent, symbol=symbol,
                direction=sig.get("direction"),
                score=sig.get("score"),
                leverage=sig.get("leverage"),
                entry=sig.get("entry"),
            )

        if opened > 0:
            await session.commit()

    return opened
