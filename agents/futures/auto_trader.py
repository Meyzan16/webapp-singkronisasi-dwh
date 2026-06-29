"""
Auto Trader — auto-opens paper positions for high-score futures signals.

Rules:
  score >= AUTO_OPEN_THRESHOLD → auto open (both agents independently)
  Max MAX_AUTO_POSITIONS open per agent at a time
  Dedup: one open trade per symbol+agent
  Auto-opened trades are tagged with "auto_opened": True in signals_json
"""

import json
import os
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

# P4.3: Lane quota — 40/30/20/10 split prevents momentum from monopolizing all 6 slots.
# Map: setup_type → max concurrent open positions in that lane (not counting bigmover).
LANE_QUOTAS: dict[str, int] = {
    "momentum":     2,   # 40% of 6 = 2.4 → 2 (floor to avoid over-expose)
    "pre_gainer":   2,   # 30% of 6 = 1.8 → 2
    "accumulation": 1,   # 20% of 6 = 1.2 → 1
}

# P2: all futures lane styles share ONE wallet → dedup & limits are GLOBAL (BUG-L1).
# Phase 2 BM3: include futures_agent_bigmover — shares wallet but has separate slot quota.
_FUTURES_STYLES = (
    "futures_agent1", "futures_agent2", "futures_agent3", "futures_agent_bigmover",
)

# Phase 2 BM1: dedicated quota for Big Mover lane (separate from MAX_AUTO_POSITIONS=6).
MAX_BIGMOVER_POSITIONS = 2

# Phase 2 BM1: cross-margin wallet utilization cap — total locked margin ≤ 70% wallet
MAX_WALLET_MARGIN_PCT = 70.0

# Phase 2 BM1: funding hard gate (Phase 3 G3-funding pre-applied for bigmover)
MAX_LONG_FUNDING_PCT  = 0.12
MIN_SHORT_FUNDING_PCT = -0.12

# Regimes where auto-open is fully disabled
AUTO_DISABLED_REGIMES = {"volatile"}  # volatile = immediate SL risk

# BC2: hedge mode — when True, allow LONG + SHORT on the same symbol simultaneously.
# Default: False (one-way mode, one position per symbol across all lanes).
HEDGE_MODE: bool = os.getenv("HEDGE_MODE", "false").lower() == "true"

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
    """Base threshold for an agent: manual override wins, else adaptive (F69).
    Phase 2 BM1: bigmover lane uses FIXED threshold (60) to avoid the A2 death-spiral.
    """
    if agent == "futures_agent_bigmover":
        # P4.6: BigMover threshold adaptive based on 14d win rate
        # 60 (WR≥45%), 65 (35–45%), 70 (<35%) — prevents fixed threshold death spiral
        from agents.futures.weight_updater import get_state as _wstate
        from agents.futures.agent_bigmover import MIN_SCORE
        try:
            wst      = _wstate()
            bm_wr    = wst.get("coin_win_rates", {})
            # Rough BM win rate: use global futures win rate as proxy when BM-specific absent
            from agents.futures.weight_updater import _coin_win_rates as _cwr
            total    = sum(d.get("total", 0) for d in _cwr.values())
            wins     = sum(d.get("wins", 0)  for d in _cwr.values())
            wr_14d   = wins / total if total >= 10 else 0.45  # fallback neutral
            if wr_14d >= 0.45:
                return 60
            elif wr_14d >= 0.35:
                return 65
            else:
                return 70
        except Exception:
            return int(MIN_SCORE)
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
    # BC2: when HEDGE_MODE=True, dedup key is (symbol, direction) to allow simultaneous
    # LONG+SHORT; in one-way mode (default) the key is symbol alone.
    best_by_symbol: dict = {}
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
        _dedup_key = (symbol, r.get("direction", "LONG")) if HEDGE_MODE else symbol
        cur = best_by_symbol.get(_dedup_key)
        if cur is None or r.get("score", 0) > cur.get("score", 0):
            best_by_symbol[_dedup_key] = r

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

        # Phase 2 BM1: separate slot count for Big Mover lane
        bm_count_q = await session.execute(
            select(func.count(PaperTrade.id)).where(
                PaperTrade.style == "futures_agent_bigmover",
                PaperTrade.status == "open",
            )
        )
        bm_open_count: int = bm_count_q.scalar() or 0

        # P4.3: per-setup_type lane quota — count open positions per setup_type
        lane_q = await session.execute(
            select(PaperTrade.setup_type, func.count(PaperTrade.id)).where(
                PaperTrade.style.in_(_FUTURES_STYLES),
                PaperTrade.status == "open",
            ).group_by(PaperTrade.setup_type)
        )
        lane_open_counts: dict[str, int] = {row[0]: row[1] for row in lane_q.fetchall() if row[0]}
        # Track newly opened per lane during this cycle
        lane_opened_this_cycle: dict[str, int] = {}

        # GLOBAL open symbols + SL cooldown across all lanes (BUG-L1).
        # BC2: in HEDGE_MODE, dedup on (symbol, direction) tuples so LONG+SHORT coexist.
        if HEDGE_MODE:
            existing_q = await session.execute(
                select(PaperTrade.symbol, PaperTrade.alert_type).where(
                    PaperTrade.style.in_(_FUTURES_STYLES),
                    PaperTrade.status == "open",
                )
            )
            # alert_type stores direction as lowercase ("long"/"short")
            existing_syms: set = {(r[0], r[1].upper()) for r in existing_q.fetchall()}
        else:
            existing_q = await session.execute(
                select(PaperTrade.symbol).where(
                    PaperTrade.style.in_(_FUTURES_STYLES),
                    PaperTrade.status == "open",
                )
            )
            existing_syms: set = {row[0] for row in existing_q.fetchall()}

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
            direction = sig.get("direction", "LONG")
            # BC2: dedup check uses (symbol, direction) in hedge mode, symbol alone otherwise
            _open_key = (symbol, direction) if HEDGE_MODE else symbol
            if not symbol or _open_key in existing_syms:
                continue   # BUG-L1: already open in some lane → skip (cross-margin = one position)
            if symbol in sl_cooldown_syms:
                logger.debug("auto_trade_cooldown_skip", symbol=symbol)
                continue

            # Phase 3 G3-funding: GLOBAL funding hard gate (all lanes — not just BM).
            # Cheap scoring-cache check first; revalidate live before order (B3.1).
            scored_funding_pct = sig.get("funding_rate", 0.0)
            if direction == "LONG" and scored_funding_pct > MAX_LONG_FUNDING_PCT:
                logger.debug("auto_trade_funding_skip",
                             symbol=symbol, agent=agent, direction=direction,
                             funding_pct=scored_funding_pct)
                continue
            if direction == "SHORT" and scored_funding_pct < MIN_SHORT_FUNDING_PCT:
                logger.debug("auto_trade_funding_skip",
                             symbol=symbol, agent=agent, direction=direction,
                             funding_pct=scored_funding_pct)
                continue

            # Phase 2 BM1: dedicated bigmover slot cap
            # bm_open_count starts as DB pre-existing count and is incremented after
            # each BM open in this cycle — no need to re-scan existing_syms here.
            if agent == "futures_agent_bigmover":
                if bm_open_count >= MAX_BIGMOVER_POSITIONS:
                    logger.debug("bigmover_lane_full")
                    continue

            # P4.3: per-lane quota — prevent momentum from taking all 6 slots
            setup = sig.get("setup_type", "")
            if setup and setup in LANE_QUOTAS:
                lane_db_count    = lane_open_counts.get(setup, 0)
                lane_cycle_count = lane_opened_this_cycle.get(setup, 0)
                if lane_db_count + lane_cycle_count >= LANE_QUOTAS[setup]:
                    logger.debug("lane_quota_full", setup=setup,
                                 db=lane_db_count, cycle=lane_cycle_count,
                                 quota=LANE_QUOTAS[setup])
                    continue

            # P6.4: per-lane WR auto-pause
            if setup:
                from agents.futures.risk_gate import is_lane_paused
                _lane_paused, _lane_pause_reason = is_lane_paused(setup)
                if _lane_paused:
                    logger.info("auto_trade_lane_paused", setup=setup,
                                reason=_lane_pause_reason)
                    continue

            # B3.1: revalidate funding LIVE (scan cache up to 2 min old) for ALL lanes.
            # Fail-open on API errors so transient network blips don't block trades.
            if not await _revalidate_funding(symbol, direction):
                logger.info("auto_trade_funding_flip", symbol=symbol, agent=agent)
                continue

            # F13: ensure risk_pct is never None/0 — use 2.0 as safe fallback
            risk_pct  = sig.get("risk_pct") or 2.0
            leverage  = sig.get("leverage", 5)

            # BC3: validate symbol constraints from Binance exchangeInfo.
            # Round entry/SL/TP to tickSize; skip if notional < minNotional; cap leverage.
            from agents.futures.exchange_info import get_symbol_constraints, round_to_tick as _rtt
            _cst      = await get_symbol_constraints(symbol)
            _tick     = _cst["tick_size"]
            _min_not  = float(_cst["min_notional"])
            leverage  = min(leverage, _cst["max_leverage"])
            # Shallow-copy sig so we don't mutate the shared candidate dict
            sig = dict(sig)
            sig["entry"] = _rtt(sig.get("entry", sig.get("price", 0)), _tick)
            sig["sl"]    = _rtt(sig.get("sl", 0), _tick)
            sig["tp1"]   = _rtt(sig.get("tp1", 0), _tick)
            sig["tp2"]   = _rtt(sig.get("tp2", 0), _tick)
            sig["tp3"]   = _rtt(sig.get("tp3", 0), _tick)

            # Phase 9: size from the REAL shared futures wallet (balance-aware + portfolio heat).
            from app.api.v1.balance import compute_futures_sizing
            sizing = await compute_futures_sizing(sig.get("score", 0), risk_pct, leverage)
            if not sizing["can_open"]:
                logger.info("auto_trade_sizing_blocked", symbol=symbol, reason=sizing["reason"])
                break   # wallet limit reached (heat / concurrency / margin) — stop this cycle
            pos_size        = sizing["position_size"]
            risk_dollar_val = sizing["risk_dollar"]
            bal_snapshot    = sizing["balance"]

            # BC3: skip if resulting notional is below Binance minimum
            if pos_size < _min_not:
                logger.debug("auto_trade_min_notional_skip",
                             symbol=symbol, pos_size=pos_size, min_notional=_min_not)
                continue

            # P1: compute entry slippage for meta (informational — does not adjust stored price)
            from app.services.slippage_sim import calculate_entry_slippage, get_session_label
            _slip_pct = sig.get("entry_slippage_pct") or calculate_entry_slippage(
                sig.get("quote_vol_24h", 0)
            )

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
                # P1 / B4.1: slippage info for analytics (not applied to entry_price)
                "entry_slippage_pct": round(_slip_pct, 4),
                "entry_session":      get_session_label(),
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
                leverage         = leverage,
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
            existing_syms.add(_open_key)  # BC2: add (symbol, direction) or symbol
            opened += 1
            if agent == "futures_agent_bigmover":
                bm_open_count += 1
            # P4.3: track lane count for quota enforcement within this cycle
            if setup and setup in LANE_QUOTAS:
                lane_opened_this_cycle[setup] = lane_opened_this_cycle.get(setup, 0) + 1

            logger.info(
                "auto_trade_opened",
                agent=agent, symbol=symbol, setup_type=sig.get("setup_type"),
                direction=sig.get("direction"), score=sig.get("score"),
                leverage=sig.get("leverage"), entry=sig.get("entry"),
                pos_size=pos_size, risk_dollar=risk_dollar_val,
            )

    return opened


# ── Phase 2 BM1 helpers ────────────────────────────────────────────────────────

async def _revalidate_funding(symbol: str, direction: str) -> bool:
    """
    Phase 2 BM1: re-fetch live funding 30s before order — scan cache can be 2 min stale.
    Returns True if still within hard gate, False otherwise.
    """
    import httpx
    from app.services.binance_urls import fapi
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(fapi("/fapi/v1/premiumIndex"), params={"symbol": symbol})
            if r.status_code != 200:
                return True  # fail-open — don't block on transient API errors
            fr_pct = float(r.json().get("lastFundingRate", 0)) * 100
    except Exception:
        return True

    if direction == "LONG" and fr_pct > MAX_LONG_FUNDING_PCT:
        return False
    if direction == "SHORT" and fr_pct < MIN_SHORT_FUNDING_PCT:
        return False
    return True
