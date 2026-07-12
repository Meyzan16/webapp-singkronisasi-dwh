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

# Phase 2 BM1: funding gate (Phase 3 G3-funding pre-applied for bigmover)
# PLAN_v6 P4c: now TWO-ZONE instead of a single hard veto. Top gainers routinely
# carry elevated funding (crowded) — that's a reason to size down, not to skip
# the move entirely. Soft zone trades at half size; only truly extreme funding vetoes.
MAX_LONG_FUNDING_PCT   = 0.12    # soft threshold: beyond this → size ½
MIN_SHORT_FUNDING_PCT  = -0.12
HARD_LONG_FUNDING_PCT  = 0.25    # hard threshold: beyond this → veto (unsustainable cost)
HARD_SHORT_FUNDING_PCT = -0.25
FUNDING_SOFT_SIZE_MULT = 0.5

# Regimes where auto-open is fully disabled
AUTO_DISABLED_REGIMES = {"volatile"}  # volatile = immediate SL risk

# ── PLAN_v16 F2/F5 — cost-floor gate & lane throttle ──────────────────────────
MIN_TP1_COST_MULT = 3.0    # F2: TP1 wajib ≥ 3× total biaya round-trip (DB: min_tp1_cost_mult)
# F2: estimasi hold per lane (jam) → estimasi funding windows utk cost floor
_HOLD_EST_H: dict[str, float] = {
    "momentum": 6.0, "bigmover": 3.0,
    "pre_gainer": 24.0, "pre_move": 24.0, "accumulation": 48.0,
}
LANE_THROTTLE_WR      = 0.40   # F5: lane rolling WR di bawah ini (min 10 trade) → ½ size
LANE_THROTTLE_MIN_N   = 10

# ── PLAN_v15 P3/P8 — fade-day & profit-lock knobs ─────────────────────────────
MAX_SAME_DIRECTION      = 4     # P3d: max open positions sharing one direction (of 6 slots)
BIGMOVER_DAILY_BUDGET   = 6     # P3b: max BM entries per WIB day
BIGMOVER_DAILY_SL_STOP  = 2     # P3b: BM real-SL closes today → BM done for the day
PROFIT_LOCK_MIN_SCORE   = 80    # P8: after profit lock, only A-grade candidates…
PROFIT_LOCK_SIZE_MULT   = 0.5   #     …at half size ("play with house money")
BREADTH_FADE_FRAC       = 0.60  # P3a: ≥60% of top gainers fading on 1h → market is pump-and-fade
BREADTH_MIN_SAMPLE      = 5     # P3a: need ≥5 gainers in sample before the gate can fire

# BC2: hedge mode — when True, allow LONG + SHORT on the same symbol simultaneously.
# Default: False (one-way mode, one position per symbol across all lanes).
HEDGE_MODE: bool = os.getenv("HEDGE_MODE", "false").lower() == "true"

# ── PLAN_ADAPTIVE_LEARNING_FUTURES_10X F1 — peta keputusan per cycle ──────────
# Tiap titik skip/open mencatat SATU alasan per (symbol, agent, direction);
# alasan PERTAMA yang menang (titik keputusan paling awal = penyebab nyata).
# decision_ledger membacanya setelah auto_open_positions selesai.
_cycle_decisions: dict[tuple, str] = {}


def _dec(symbol: str, agent: str, direction: str, reason: str) -> None:
    _cycle_decisions.setdefault((symbol, agent, direction), reason)


def get_cycle_decisions() -> dict[tuple, str]:
    """Snapshot keputusan cycle terakhir — dikonsumsi decision_ledger (F1)."""
    return dict(_cycle_decisions)


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
    _base = get_adaptive_thresholds(agent)["auto_threshold"]
    # PLAN_v14 P2-B1: Pre-Gainer & Accumulation nyaris dormant — setup "quiet coil"
    # skornya 52-72 tapi auto-open butuh 72 (default). Turunkan ke 65 SUPAYA lane ini
    # aktif. Skor 65 sendiri sudah mensyaratkan OI/funding/volume/breakout selaras
    # (konfirmasi B2 inheren). Hanya override default 72 yang belum disentuh adaptif —
    # jika adaptif menaikkan (WR jelek), biarkan (jangan lawan proteksi).
    if agent in ("futures_agent1", "futures_agent2") and _base == 72:
        _base = 65
    return _base


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

    # F1: mulai cycle keputusan baru (ledger membaca peta ini setelah selesai)
    _cycle_decisions.clear()

    def _dec_all(reason: str) -> None:
        for _c in candidates:
            _dec(_c.get("symbol", ""), _c.get("agent", ""), _c.get("direction", "LONG"), reason)

    # PLAN_v5 Group C: pull DB overrides once per cycle — see scanner.py
    # run_opportunity_scan for the `global` rationale (resolved at call time).
    global MAX_AUTO_POSITIONS, MAX_BIGMOVER_POSITIONS, FUTURES_COOLDOWN_HOURS, \
        MAX_WALLET_MARGIN_PCT, LANE_QUOTAS, MAX_SAME_DIRECTION, BIGMOVER_DAILY_SL_STOP
    try:
        from agents.shared.config_reader import cfg
        MAX_AUTO_POSITIONS     = int(await cfg.get("futures", "max_auto_positions", MAX_AUTO_POSITIONS))
        MAX_BIGMOVER_POSITIONS = int(await cfg.get("futures", "max_bigmover_positions", MAX_BIGMOVER_POSITIONS))
        FUTURES_COOLDOWN_HOURS = await cfg.get("futures", "cooldown_hours", FUTURES_COOLDOWN_HOURS)
        MAX_WALLET_MARGIN_PCT  = await cfg.get("futures", "max_wallet_margin_pct", MAX_WALLET_MARGIN_PCT)
        # PLAN_v15 P3b/P3d
        MAX_SAME_DIRECTION     = int(await cfg.get("futures", "max_same_direction", MAX_SAME_DIRECTION))
        BIGMOVER_DAILY_SL_STOP = int(await cfg.get("futures", "bigmover_daily_sl_stop", BIGMOVER_DAILY_SL_STOP))
        # PLAN_v16 F2
        global MIN_TP1_COST_MULT
        MIN_TP1_COST_MULT      = await cfg.get("futures", "min_tp1_cost_mult", MIN_TP1_COST_MULT)
        # LANE_QUOTAS is a dict shared by reference with importers — mutate in
        # place so `from auto_trader import LANE_QUOTAS` bindings elsewhere stay in sync.
        LANE_QUOTAS["momentum"]     = int(await cfg.get("futures", "lane_quota_momentum", LANE_QUOTAS["momentum"]))
        LANE_QUOTAS["pre_gainer"]   = int(await cfg.get("futures", "lane_quota_pre_gainer", LANE_QUOTAS["pre_gainer"]))
        LANE_QUOTAS["accumulation"] = int(await cfg.get("futures", "lane_quota_accumulation", LANE_QUOTAS["accumulation"]))
    except Exception as exc:
        logger.warning("agent_config_pull_failed", scope="auto_trader", error=str(exc)[:120])

    regime = get_cached_regime()

    # Phase 10: risk gate — circuit-breaker (DD > 20%) + RAR gate (Sharpe < −0.5)
    from agents.futures.risk_gate import (
        is_gate_open, is_state_stale, evaluate_risk_gate, probe_allowed, record_probe,
        evaluate_daily_gates,
    )
    if is_state_stale():
        await evaluate_risk_gate()
    gate_open, gate_reason = is_gate_open()
    # PLAN_v11 A2: RAR deadlock breaker — jika gate RAR tertutup tapi probe jatuh
    # tempo, izinkan SATU posisi ½-risk agar ada data baru pemulih Sharpe.
    _is_probe = False
    if not gate_open:
        if probe_allowed():
            _is_probe = True
            logger.info("auto_trade_rar_probe", reason=gate_reason)
        else:
            logger.info("auto_trade_gate_blocked", reason=gate_reason)
            _dec_all("risk_gate_blocked")   # F1
            return 0

    # PLAN_v15 P1/P2/P8 — daily gates (stateless from DB, TTL-cached 60s)
    _dg = await evaluate_daily_gates()
    if _dg["loss_breaker"] or _dg["giveback_stop"]:
        logger.info("auto_trade_daily_gate_blocked", reason=_dg["reason"],
                    day_pnl=_dg["day_pnl"], day_peak=_dg["day_peak_pnl"])
        _dec_all("daily_gate_blocked")   # F1
        return 0
    if _dg["global_pause_until"] > time.time():
        logger.info("auto_trade_consec_sl_global_pause", reason=_dg["reason"])
        _dec_all("consec_sl_global_pause")   # F1
        return 0
    # P8: profit lock — only A-grade at ½ size (checked per candidate below)
    _profit_lock_mode = bool(_dg["profit_lock"])

    # P3a: market breadth — pump-and-fade day detection (computed each scan cycle)
    _breadth = {}
    try:
        from agents.futures import store as _fstore
        _breadth = _fstore.get_market_breadth() or {}
    except Exception:
        pass
    _fade_day = (
        _breadth.get("gainers", 0) >= BREADTH_MIN_SAMPLE
        and _breadth.get("fade_frac", 0.0) >= BREADTH_FADE_FRAC
    )

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
            # PLAN_v14 B3: audit lane dormant — log kenapa Pre-Gainer/Accumulation di-skip
            if r.get("agent") in ("futures_agent1", "futures_agent2"):
                logger.debug("lane_skip_below_threshold", agent=r.get("agent"),
                             symbol=symbol, score=r.get("score", 0), threshold=threshold)
                # PLAN_v15 R0d: persist the near-miss (score passed min but failed
                # auto-open) to rejection_log so P6 calibration has real data on the
                # 52-64 score band. reason distinguishes it from scoring rejects.
                try:
                    from agents.futures.weight_updater import log_rejection
                    log_rejection(symbol, r.get("agent", ""), r.get("direction", ""),
                                  r.get("score", 0), threshold,
                                  regime=coin_regime, reason="below_auto_threshold")
                except Exception:
                    pass
            _dec(symbol, r.get("agent", ""), r.get("direction", "LONG"),
                 "below_auto_threshold")   # F1
            continue
        # BUG-L12: volatile blocks pre_move only — momentum rides the volatility
        if coin_regime in AUTO_DISABLED_REGIMES and r.get("setup_type") != "momentum":
            _dec(symbol, r.get("agent", ""), r.get("direction", "LONG"),
                 "volatile_regime_skip")   # F1
            continue
        # PLAN_ADAPTIVE_LEARNING_FUTURES_10X F2: learning veto (veto-only — TIDAK
        # bisa mempromosikan). Hard-ban (butuh ≥10 sampel) selalu berlaku; veto
        # lunak (adaptive_score < ambang padahal skor ≥ ambang) hanya saat learning
        # sudah "active" (≥60 outcome matang), supaya fase warming tak menahan trade.
        if r.get("banned_by_learning"):
            _dec(symbol, r.get("agent", ""), r.get("direction", "LONG"), "learning_ban")
            continue
        if (r.get("learning_status") == "active"
                and r.get("adaptive_score") is not None
                and float(r.get("adaptive_score", 0)) < threshold):
            _dec(symbol, r.get("agent", ""), r.get("direction", "LONG"), "learning_veto")
            continue

        _dedup_key = (symbol, r.get("direction", "LONG")) if HEDGE_MODE else symbol
        cur = best_by_symbol.get(_dedup_key)
        if cur is None or r.get("score", 0) > cur.get("score", 0):
            if cur is not None:   # F1: kandidat lama kalah dedup
                _dec(cur.get("symbol", ""), cur.get("agent", ""),
                     cur.get("direction", "LONG"), "dedup_lost")
            best_by_symbol[_dedup_key] = r
        else:
            _dec(symbol, r.get("agent", ""), r.get("direction", "LONG"), "dedup_lost")   # F1

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

        # PLAN_v15 P3d: open-position count per direction (alert_type stores it lowercase)
        dir_q = await session.execute(
            select(PaperTrade.alert_type, func.count(PaperTrade.id)).where(
                PaperTrade.style.in_(_FUTURES_STYLES),
                PaperTrade.status == "open",
            ).group_by(PaperTrade.alert_type)
        )
        dir_open_counts: dict[str, int] = {
            (row[0] or "").upper(): row[1] for row in dir_q.fetchall()
        }

        # PLAN_v15 P3b: BM entries opened today (WIB) — daily budget
        from agents.futures.risk_gate import wib_day_start_epoch
        bm_today_q = await session.execute(
            select(func.count(PaperTrade.id)).where(
                PaperTrade.style == "futures_agent_bigmover",
                PaperTrade.entry_at >= wib_day_start_epoch(),
            )
        )
        bm_opened_today: int = bm_today_q.scalar() or 0

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
                _dec(symbol, agent, direction, "already_open")   # F1
                continue   # BUG-L1: already open in some lane → skip (cross-margin = one position)
            if symbol in sl_cooldown_syms:
                logger.debug("auto_trade_cooldown_skip", symbol=symbol)
                _dec(symbol, agent, direction, "sl_cooldown")   # F1
                continue

            # PLAN_v15 P8: profit lock — A-grade only (score ≥ 80), ½ size applied below
            if _profit_lock_mode and sig.get("score", 0) < PROFIT_LOCK_MIN_SCORE:
                logger.debug("auto_trade_profit_lock_skip", symbol=symbol,
                             score=sig.get("score", 0))
                _dec(symbol, agent, direction, "profit_lock_skip")   # F1
                continue

            # PLAN_v15 P3d: direction concentration cap — 4 Juli was 21/22 LONG at once.
            if dir_open_counts.get(direction, 0) >= MAX_SAME_DIRECTION:
                logger.info("auto_trade_direction_cap_skip", symbol=symbol,
                            direction=direction, cap=MAX_SAME_DIRECTION)
                _dec(symbol, agent, direction, "direction_cap")   # F1
                continue

            if agent == "futures_agent_bigmover":
                # PLAN_v15 P3b: BM daily budget + daily real-SL stop
                if bm_opened_today >= BIGMOVER_DAILY_BUDGET:
                    logger.info("bigmover_daily_budget_reached", opened=bm_opened_today)
                    _dec(symbol, agent, direction, "bm_daily_budget")   # F1
                    continue
                if _dg.get("bm_real_sl_today", 0) >= BIGMOVER_DAILY_SL_STOP:
                    logger.info("bigmover_daily_sl_stop", sl_today=_dg.get("bm_real_sl_today"))
                    _dec(symbol, agent, direction, "bm_daily_sl_stop")   # F1
                    continue
                # PLAN_v15 P3a: fade-day breadth gate — chasing pumps LONG on a day
                # where most top gainers are already fading 1h = buying exit liquidity.
                if direction == "LONG" and _fade_day:
                    logger.info("bigmover_fade_day_skip", symbol=symbol,
                                fade_frac=_breadth.get("fade_frac"),
                                gainers=_breadth.get("gainers"))
                    _dec(symbol, agent, direction, "breadth_fade_skip")   # F1
                    continue

            # Phase 3 G3-funding + PLAN_v6 P4c: two-zone funding gate (all lanes).
            # HARD zone (>0.25%) → veto: funding cost eats any realistic profit.
            # SOFT zone (0.12–0.25%) → trade at half size: crowded but tradeable.
            # Cheap scoring-cache check first; revalidate live before order (B3.1).
            scored_funding_pct = sig.get("funding_rate", 0.0)
            funding_mult = 1.0
            if direction == "LONG":
                if scored_funding_pct > HARD_LONG_FUNDING_PCT:
                    logger.debug("auto_trade_funding_skip", symbol=symbol, agent=agent,
                                 direction=direction, funding_pct=scored_funding_pct)
                    _dec(symbol, agent, direction, "funding_hard_skip")   # F1
                    continue
                if scored_funding_pct > MAX_LONG_FUNDING_PCT:
                    funding_mult = FUNDING_SOFT_SIZE_MULT
            else:  # SHORT
                if scored_funding_pct < HARD_SHORT_FUNDING_PCT:
                    logger.debug("auto_trade_funding_skip", symbol=symbol, agent=agent,
                                 direction=direction, funding_pct=scored_funding_pct)
                    _dec(symbol, agent, direction, "funding_hard_skip")   # F1
                    continue
                if scored_funding_pct < MIN_SHORT_FUNDING_PCT:
                    funding_mult = FUNDING_SOFT_SIZE_MULT

            # Phase 2 BM1: dedicated bigmover slot cap
            # bm_open_count starts as DB pre-existing count and is incremented after
            # each BM open in this cycle — no need to re-scan existing_syms here.
            if agent == "futures_agent_bigmover":
                if bm_open_count >= MAX_BIGMOVER_POSITIONS:
                    logger.debug("bigmover_lane_full")
                    _dec(symbol, agent, direction, "bm_lane_full")   # F1
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
                    _dec(symbol, agent, direction, "lane_quota_full")   # F1
                    continue

            # P6.4: per-lane WR auto-pause
            if setup:
                from agents.futures.risk_gate import is_lane_paused
                _lane_paused, _lane_pause_reason = is_lane_paused(setup)
                if _lane_paused:
                    logger.info("auto_trade_lane_paused", setup=setup,
                                reason=_lane_pause_reason)
                    _dec(symbol, agent, direction, "lane_paused")   # F1
                    continue

            # B3.1: revalidate funding LIVE (scan cache up to 2 min old) for ALL lanes.
            # Fail-open on API errors so transient network blips don't block trades.
            if not await _revalidate_funding(symbol, direction):
                logger.info("auto_trade_funding_flip", symbol=symbol, agent=agent)
                _dec(symbol, agent, direction, "funding_flip")   # F1
                continue

            # F13: ensure risk_pct is never None/0 — use 2.0 as safe fallback
            risk_pct  = sig.get("risk_pct") or 2.0
            leverage  = sig.get("leverage", 5)

            # ── PLAN_v16 F2: cost-floor gate — profit target harus mengalahkan
            # SEMUA biaya round-trip SEBELUM posisi dibuka. cost_floor =
            # fee RT + 2× slippage (entry+exit market) + estimasi funding per hold lane.
            from app.services.slippage_sim import calculate_entry_slippage, get_session_label
            from app.services.trading_costs import FUTURES_ROUND_TRIP_FEE_PCT
            _slip_pct = sig.get("entry_slippage_pct") or calculate_entry_slippage(
                sig.get("quote_vol_24h", 0)
            )
            _hold_h      = _HOLD_EST_H.get(setup, 12.0)
            _funding_est = abs(scored_funding_pct) * (_hold_h / 8.0)   # % per 8h window
            _cost_floor  = FUTURES_ROUND_TRIP_FEE_PCT + 2 * _slip_pct + _funding_est
            _tp1_pct_sig = float(sig.get("tp1_pct") or 0.0)
            sig["cost_floor_pct"] = round(_cost_floor, 4)   # F1: ledger snapshot membacanya
            if _tp1_pct_sig < MIN_TP1_COST_MULT * _cost_floor:
                logger.info("auto_trade_cost_floor_skip", symbol=symbol, agent=agent,
                            tp1_pct=_tp1_pct_sig, cost_floor=round(_cost_floor, 3),
                            required=round(MIN_TP1_COST_MULT * _cost_floor, 3))
                _dec(symbol, agent, direction, "cost_floor_skip")   # F1
                continue

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
                _dec(symbol, agent, direction, "sizing_blocked")   # F1
                break   # wallet limit reached (heat / concurrency / margin) — stop this cycle
            pos_size        = sizing["position_size"]
            risk_dollar_val = sizing["risk_dollar"]
            bal_snapshot    = sizing["balance"]

            # PLAN_v11 A2: probe = ½-risk (batasi kerugian saat gate RAR masih aktif)
            if _is_probe:
                pos_size        = round(pos_size * 0.5, 2)
                risk_dollar_val = round(risk_dollar_val * 0.5, 2)

            # PLAN_v6 P4a/P4c: apply size reductions — agent-signal size_mult
            # (bigmover G18 hot-entry / extreme tier) × funding soft-zone mult.
            _size_mult = float(sig.get("size_mult", 1.0) or 1.0) * funding_mult
            # PLAN_v15 P8: profit-lock mode trades at half size (house-money rule)
            if _profit_lock_mode:
                _size_mult *= PROFIT_LOCK_SIZE_MULT

            # PLAN_v16 F5: lane expectancy throttle — lane yang rolling WR-nya buruk
            # trade ½ size sampai membuktikan diri (komplemen WR-pause 35%; upsize
            # A-grade sudah ada via conviction scaling di compute_futures_sizing).
            if setup:
                from agents.futures.risk_gate import get_lane_wr
                _lwr, _ln = get_lane_wr(setup)
                if _ln >= LANE_THROTTLE_MIN_N and _lwr < LANE_THROTTLE_WR:
                    _size_mult *= 0.5
                    logger.info("lane_throttle_half_size", setup=setup,
                                wr=round(_lwr, 3), sample=_ln)
            if _size_mult < 1.0:
                pos_size        = round(pos_size * _size_mult, 2)
                risk_dollar_val = round(risk_dollar_val * _size_mult, 2)
                logger.info("auto_trade_size_reduced", symbol=symbol, agent=agent,
                            size_mult=_size_mult, pos_size=pos_size)

            # BC3: skip if resulting notional is below Binance minimum
            if pos_size < _min_not:
                logger.debug("auto_trade_min_notional_skip",
                             symbol=symbol, pos_size=pos_size, min_notional=_min_not)
                _dec(symbol, agent, direction, "min_notional_skip")   # F1
                continue

            # P1: entry slippage sudah dihitung di gate F2 di atas (_slip_pct) —
            # PLAN_v16 F1 memakainya sungguhan di monitor (dipotong dari pnl saat close).

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
                "atr_pct":      sig.get("atr_pct", 0),   # PLAN_v15: G4 rugpull + P9 fail-fast read this
                "auto_opened":  True,
                # P1 / B4.1 + PLAN_v16 F1: slippage dipotong dari pnl di monitor saat close
                "entry_slippage_pct": round(_slip_pct, 4),
                "entry_session":      get_session_label(),
                # PLAN_v16 F2: total biaya round-trip (%) — dipakai monitor utk
                # breakeven=entry±cost, bank-gate 3×, dan time-stop tighten.
                "cost_floor_pct":     round(_cost_floor, 4),
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
            _dec(symbol, agent, direction, "opened")   # F1
            # PLAN_v15 P3b/P3d: keep in-cycle counters honest for the next candidate
            dir_open_counts[direction] = dir_open_counts.get(direction, 0) + 1
            if agent == "futures_agent_bigmover":
                bm_open_count += 1
                bm_opened_today += 1
            # P4.3: track lane count for quota enforcement within this cycle
            if setup and setup in LANE_QUOTAS:
                lane_opened_this_cycle[setup] = lane_opened_this_cycle.get(setup, 0) + 1

            logger.info(
                "auto_trade_opened",
                agent=agent, symbol=symbol, setup_type=sig.get("setup_type"),
                direction=sig.get("direction"), score=sig.get("score"),
                leverage=sig.get("leverage"), entry=sig.get("entry"),
                pos_size=pos_size, risk_dollar=risk_dollar_val, probe=_is_probe,
            )

            # PLAN_v11 A2: probe = tepat SATU posisi. Catat & hentikan siklus.
            if _is_probe:
                record_probe()
                break

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

    # PLAN_v6 P4c: live re-check enforces the HARD threshold only — the soft zone
    # (0.12–0.25%) is handled by size reduction at gate time, not a veto here.
    if direction == "LONG" and fr_pct > HARD_LONG_FUNDING_PCT:
        return False
    if direction == "SHORT" and fr_pct < HARD_SHORT_FUNDING_PCT:
        return False
    return True
