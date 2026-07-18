"""
Risk Gate — circuit-breaker and RAR gate for futures position opens.

Independent guards:
  1. Drawdown circuit-breaker: portfolio drawdown from peak > DD_HARD_STOP_PCT
     → hard stop, no new positions until drawdown recovers below DD_RECOVER_PCT.
  2. Risk-Adjusted Return gate: Sharpe proxy < RAR_GATE_THRESHOLD and >= RAR_MIN_TRADES
     → gate closed (strategy is producing negative risk-adjusted returns).
  3. Per-lane WR auto-pause (P6.4): if any lane has WR < 35% in rolling 20 trades
     → that lane is paused for 24h to prevent death-spirals in a single style.
  4. PLAN_v15 P1 — daily loss breaker: realized futures PnL today (WIB) below
     −daily_loss_limit_pct × balance → no new positions until the WIB day rolls over.
  5. PLAN_v15 P8 — daily profit lock: once today's realized PnL PEAKS above
     +daily_profit_lock_pct × balance, only A-grade (score ≥ 80) candidates open at
     ½ size; if realized PnL then gives back to ≤ +GIVEBACK floor → stop opens.
  6. PLAN_v15 P2 — consecutive-loss breaker: 3 real losses in a row in one lane
     (window 6h) → lane paused 12h; 5 in a row across lanes → all lanes paused 6h.

All PLAN_v15 gates are computed STATELESS from the DB (closed trades of the current
WIB day / rolling window) so a backend restart can never forget an active breaker.

State is refreshed by the risk dashboard endpoint (polled by frontend every 15 s).
auto_trader and POST /futures/trade evaluate inline when state is stale (backend restart,
no frontend polling yet).
"""

import json
import time

import structlog

logger = structlog.get_logger(__name__)

# ── Thresholds ─────────────────────────────────────────────────────────────────
# P6.2: DD threshold is now scaled per wallet size in evaluate_risk_gate; the constant
# below is the default for ~$1000 wallet.
DD_HARD_STOP_PCT   = 15.0   # P6.2: was 20%; scaled in evaluate_risk_gate by wallet size
DD_RECOVER_PCT     = 8.0    # P6.2: scaled hysteresis (was 10%)
RAR_GATE_THRESHOLD = -0.5   # Sharpe proxy < −0.5 → RAR gate closes
RAR_MIN_TRADES     = 10     # P6.3: was 12 → 10 (more responsive to early bad runs)
STATE_TTL          = 5 * 60 # state older than 5 min is considered stale

# ── PLAN_v11 P1 — RAR anti-deadlock ─────────────────────────────────────────
# Bug lama: Sharpe dihitung dari SEMUA trade closed (kumulatif). Begitu gate
# tutup, agent stop buka posisi → tak ada trade baru → Sharpe beku negatif →
# gate tak pernah pulih (deadlock). Perbaikan:
RAR_ROLLING_WINDOW  = 20        # A1: Sharpe hanya dari N trade TERAKHIR (bukan kumulatif)
RAR_RELAX_THRESHOLD = -0.8      # A3: ambang lebih longgar saat regime bullish & DD rendah
PROBE_INTERVAL_SEC  = 6 * 3600  # A2: izinkan 1 posisi probe (½-risk) tiap 6 jam saat RAR aktif
_last_probe_at      = 0.0       # A2: kapan probe terakhir dibuka

# P6.4: per-lane WR auto-pause
LANE_WR_PAUSE_THRESHOLD = 0.35   # WR < 35% → pause lane
LANE_WR_MIN_SAMPLE      = 20     # rolling N=20 trades before judging lane
LANE_PAUSE_HOURS        = 24     # pause duration (hours)

# ── PLAN_v15 P1/P2/P8 — daily gates & consecutive-loss breaker ────────────────
WIB_UTC_OFFSET_H          = 7      # daily boundaries follow WIB (UTC+7), same as spot
DAILY_LOSS_LIMIT_PCT      = 2.5    # P1: realized day loss ≥ this % of balance → stop opens
DAILY_PROFIT_LOCK_PCT     = 1.0    # P8: day peak ≥ this % → A-grade-only at ½ size
PROFIT_GIVEBACK_FLOOR_PCT = 0.3    # P8: after lock, day PnL back at ≤ this % → stop opens
CONSEC_SL_LANE_LIMIT      = 3      # P2: real losses in a row per lane…
CONSEC_SL_LANE_PAUSE_H    = 12.0   #     → lane paused this long
CONSEC_SL_GLOBAL_LIMIT    = 5      # P2: real losses in a row across ALL lanes…
CONSEC_SL_GLOBAL_PAUSE_H  = 6.0    #     → everything paused this long
CONSEC_SL_WINDOW_H        = 6.0    # streak only counts losses inside this rolling window
DAILY_GATES_TTL_SEC       = 60.0   # cached evaluation validity

# P2: close reasons that count as a REAL loss (full-size damage). breakeven_stop,
# time_stop_scratch, sl_plus etc. neither count toward nor break a streak — only a
# PROFITABLE close breaks it (a scratch between two SLs doesn't mean the bleeding stopped).
REAL_LOSS_REASONS = {
    "sl_hit", "sl_hit_fast_loop",
    "max_margin_loss", "max_margin_loss_fast_loop",
    "liq_guard",
    "flash_dump_exit", "flash_pump_exit",
    "fail_fast",                      # PLAN_v15 P9
    "offline_reconcile_sl",           # PLAN_v15 P5
    "emergency_close_circuit_breaker",
}

_FUTURES_STYLES_RG = (
    "futures_agent1", "futures_agent2", "futures_agent3", "futures_agent_bigmover",
)

# Cached result of evaluate_daily_gates() — recomputed from DB when older than TTL.
_daily_gates: dict = {
    "updated_at":          0.0,
    "day_pnl":             0.0,
    "day_peak_pnl":        0.0,
    "balance":             0.0,
    "loss_breaker":        False,   # P1
    "profit_lock":         False,   # P8 (latched via day PEAK — restart-safe)
    "giveback_stop":       False,   # P8
    "bm_real_sl_today":    0,       # P3b input for auto_trader
    "lane_pause_until":    {},      # P2 {lane: epoch}
    "global_pause_until":  0.0,     # P2
    "reason":              "ok",
}


def wib_day_start_epoch(now: float | None = None) -> float:
    """Epoch of 00:00 WIB (UTC+7) of the current WIB day."""
    now = now if now is not None else time.time()
    off = WIB_UTC_OFFSET_H * 3600
    return (int(now + off) // 86400) * 86400 - off


def _close_reason_of(trade) -> str:
    try:
        return (json.loads(trade.signals_json or "{}") or {}).get("close_reason") or ""
    except Exception:
        return ""


def _consec_pauses(trades_window: list) -> tuple[dict, float]:
    """
    P2: compute {lane: pause_until} + global pause_until from trades closed inside
    the rolling window (ordered by closed_at ASC). Streak rules per lane and global:
    walk newest→oldest; profitable close breaks the streak; real loss counts;
    scratches are transparent (neither count nor break).
    """
    now = time.time()

    def _streak(trades_desc: list) -> tuple[int, float]:
        count, newest_loss_at = 0, 0.0
        for t in trades_desc:
            pnl = t.pnl_dollar or 0.0
            if pnl > 0:
                break
            if _close_reason_of(t) in REAL_LOSS_REASONS and pnl < 0:
                count += 1
                if not newest_loss_at:
                    newest_loss_at = t.closed_at or 0.0
        return count, newest_loss_at

    desc = sorted(trades_window, key=lambda t: t.closed_at or 0.0, reverse=True)

    lane_until: dict[str, float] = {}
    lanes = {(t.setup_type or "") for t in desc}
    for lane in lanes:
        if not lane:
            continue
        n, newest = _streak([t for t in desc if (t.setup_type or "") == lane])
        if n >= CONSEC_SL_LANE_LIMIT:
            until = newest + CONSEC_SL_LANE_PAUSE_H * 3600
            if until > now:
                lane_until[lane] = until

    g_n, g_newest = _streak(desc)
    global_until = g_newest + CONSEC_SL_GLOBAL_PAUSE_H * 3600 if g_n >= CONSEC_SL_GLOBAL_LIMIT else 0.0
    if global_until <= now:
        global_until = 0.0
    return lane_until, global_until


async def evaluate_daily_gates(force: bool = False) -> dict:
    """
    PLAN_v15 P1/P2/P8 — recompute the daily gates from the DB (TTL-cached).
    Fully stateless: day PnL, day PEAK PnL (max prefix sum over today's closes,
    floored at 0) and loss streaks are all derived from closed trades, so the
    flags survive restarts and never need manual reset.
    Fail-open: on DB error the previous cached state is returned unchanged.
    """
    global DAILY_LOSS_LIMIT_PCT, DAILY_PROFIT_LOCK_PCT, CONSEC_SL_LANE_LIMIT

    now = time.time()
    if not force and (now - _daily_gates["updated_at"]) < DAILY_GATES_TTL_SEC:
        return _daily_gates

    from sqlalchemy import select
    from app.database import AsyncSessionLocal, is_db_available
    from app.models.paper_trade import PaperTrade
    from app.models.paper_balance import PaperBalance

    if not is_db_available():
        return _daily_gates

    try:
        from agents.shared.config_reader import cfg
        DAILY_LOSS_LIMIT_PCT  = await cfg.get("futures", "daily_loss_limit_pct", DAILY_LOSS_LIMIT_PCT)
        DAILY_PROFIT_LOCK_PCT = await cfg.get("futures", "daily_profit_lock_pct", DAILY_PROFIT_LOCK_PCT)
        CONSEC_SL_LANE_LIMIT  = int(await cfg.get("futures", "lane_consec_sl_pause", CONSEC_SL_LANE_LIMIT))
    except Exception as exc:
        logger.warning("agent_config_pull_failed", scope="daily_gates", error=str(exc)[:120])

    day_start    = wib_day_start_epoch(now)
    window_start = min(day_start, now - CONSEC_SL_WINDOW_H * 3600)

    try:
        async with AsyncSessionLocal() as session:
            rows = list((await session.execute(
                select(PaperTrade).where(
                    PaperTrade.style.in_(list(_FUTURES_STYLES_RG)),
                    PaperTrade.status.in_(["tp", "sl", "expired", "manual"]),
                    PaperTrade.pnl_dollar.isnot(None),
                    PaperTrade.closed_at >= window_start,
                ).order_by(PaperTrade.closed_at.asc())
            )).scalars().all())

            bal_row = (await session.execute(
                select(PaperBalance).where(PaperBalance.style == "futures")
            )).scalar_one_or_none()
            balance = max(bal_row.balance, 1.0) if bal_row else 1000.0

        today = [t for t in rows if (t.closed_at or 0) >= day_start]

        day_pnl, day_peak, cum = 0.0, 0.0, 0.0
        bm_real_sl_today = 0
        for t in today:
            cum += t.pnl_dollar or 0.0
            day_peak = max(day_peak, cum)
            if (t.setup_type or "") == "bigmover" and \
               (t.pnl_dollar or 0.0) < 0 and _close_reason_of(t) in REAL_LOSS_REASONS:
                bm_real_sl_today += 1
        day_pnl = cum

        loss_breaker = day_pnl <= -(balance * DAILY_LOSS_LIMIT_PCT / 100.0)
        profit_lock  = day_peak >= (balance * DAILY_PROFIT_LOCK_PCT / 100.0)
        giveback     = profit_lock and day_pnl <= (balance * PROFIT_GIVEBACK_FLOOR_PCT / 100.0)

        in_window = [t for t in rows if (t.closed_at or 0) >= now - CONSEC_SL_WINDOW_H * 3600]
        lane_until, global_until = _consec_pauses(in_window)

        # PLAN_SIGNAL_REPAIR_LIVE R1: catat pause lane BARU ke repair ledger
        # (transisi saja — pause yang sama tidak dicatat ulang tiap evaluasi).
        _prev_pauses = _daily_gates.get("lane_pause_until") or {}
        for _lane, _until in lane_until.items():
            if abs(_prev_pauses.get(_lane, 0.0) - _until) > 1.0:
                try:
                    from agents.futures.repair_log import record_action
                    await record_action(
                        source="lane_pause", target_key=f"lane:{_lane}",
                        issue="lane_consec_sl", action="pause",
                        evidence={"until": _until, "limit": CONSEC_SL_LANE_LIMIT,
                                  "window_h": CONSEC_SL_WINDOW_H},
                        note=f"pause {CONSEC_SL_LANE_PAUSE_H:.0f} jam",
                    )
                except Exception as exc:
                    logger.warning("lane_pause_repair_log_failed", error=str(exc)[:100])

        if loss_breaker:
            reason = (f"Daily loss breaker: realized {day_pnl:+.2f} USD hari ini (WIB) "
                      f"melewati batas −{DAILY_LOSS_LIMIT_PCT}% dari balance {balance:.0f}. "
                      f"Auto-open berhenti sampai ganti hari.")
        elif giveback:
            reason = (f"Profit giveback stop: day peak {day_peak:+.2f} → sisa {day_pnl:+.2f}. "
                      f"Sisa profit dilindungi — auto-open berhenti sampai ganti hari.")
        elif global_until:
            reason = (f"{CONSEC_SL_GLOBAL_LIMIT} loss nyata beruntun lintas lane — "
                      f"semua lane pause s/d {time.strftime('%H:%M', time.localtime(global_until))}.")
        elif profit_lock:
            reason = (f"Profit lock aktif (day peak {day_peak:+.2f}): "
                      f"hanya kandidat score ≥ 80 @ ½ size.")
        else:
            reason = "ok"

        _daily_gates.update({
            "updated_at":         now,
            "day_pnl":            round(day_pnl, 2),
            "day_peak_pnl":       round(day_peak, 2),
            "balance":            round(balance, 2),
            "loss_breaker":       loss_breaker,
            "profit_lock":        profit_lock,
            "giveback_stop":      giveback,
            "bm_real_sl_today":   bm_real_sl_today,
            "lane_pause_until":   lane_until,
            "global_pause_until": global_until,
            "reason":             reason,
        })
        if loss_breaker or giveback or global_until or lane_until:
            logger.warning("plan_v15_daily_gates", **{k: v for k, v in _daily_gates.items()
                                                      if k != "updated_at"})
    except Exception as exc:
        logger.warning("daily_gates_evaluate_failed", error=str(exc)[:160])

    return _daily_gates


def get_daily_gates() -> dict:
    """Last evaluated daily-gate state (call evaluate_daily_gates() to refresh)."""
    return dict(_daily_gates)

# ── In-memory state ────────────────────────────────────────────────────────────
_state: dict = {
    "active":        False,  # True = gate CLOSED (no new positions allowed)
    "gate_type":     "none", # "none" | "circuit_breaker" | "rar" | "override" | "lane_pause"
    "reason":        "ok",
    "drawdown_pct":  0.0,
    "rar":           0.0,
    "n_trades":      0,
    "updated_at":    0.0,
    "override":      None,   # None = auto | True = force-open | False = force-closed
}

# G10: emergency close-all flag — set on NEW circuit breaker activation, consumed by monitor.
_emergency_tighten_pending = False
_prev_circuit_breaker_active = False   # tracks transition to avoid re-firing

# P6.4: per-lane pause state — {lane: pause_until_ts}
_lane_paused_until: dict[str, float] = {}
# P6.4: per-lane rolling WR state — {lane: {wins, total}}
_lane_wr: dict[str, dict] = {}


def update_gate_state(drawdown_pct: float, rar: float, n_trades: int,
                      regime: str = "ranging") -> None:
    """
    Refresh gate state from pre-computed metrics.
    Called from get_risk_dashboard() — frontend polls this every 15 s.
    G10: fires emergency_tighten on NEW circuit breaker activation (transition only).
    PLAN_v11 A3: `regime` melonggarkan ambang RAR saat market bullish & DD rendah.
    """
    global _state, _emergency_tighten_pending, _prev_circuit_breaker_active
    _state["drawdown_pct"] = drawdown_pct
    _state["rar"]          = rar
    _state["n_trades"]     = n_trades
    _state["updated_at"]   = time.time()

    # PLAN_v11 A3: di regime trending_up dengan DD < ½ batas, pakai ambang longgar.
    _rar_thr = RAR_GATE_THRESHOLD
    if (regime == "trending_up" and drawdown_pct is not None
            and drawdown_pct < DD_HARD_STOP_PCT / 2):
        _rar_thr = RAR_RELAX_THRESHOLD

    # Manual override wins over auto-logic
    if _state["override"] is not None:
        _state["active"]    = not _state["override"]   # override=True → gate open → active=False
        _state["gate_type"] = "override"
        _state["reason"]    = f"manual override: gate {'open' if _state['override'] else 'closed'}"
        _prev_circuit_breaker_active = False
        return

    # PLAN_v2 P0 cleanup — drawdown_pct is None when 0 closed trades exist.
    if drawdown_pct is not None and drawdown_pct > DD_HARD_STOP_PCT:
        # G10: fire emergency tighten only on the FIRST transition into circuit breaker
        if not _prev_circuit_breaker_active:
            _emergency_tighten_pending = True
            logger.warning("emergency_tighten_requested", drawdown_pct=round(drawdown_pct, 2))
        _prev_circuit_breaker_active = True
        _state["active"]    = True
        _state["gate_type"] = "circuit_breaker"
        _state["reason"]    = (
            f"Circuit breaker aktif: drawdown {drawdown_pct:.1f}% "
            f"melampaui batas keras {DD_HARD_STOP_PCT:.0f}%. "
            f"Agen berhenti buka posisi baru hingga drawdown < {DD_RECOVER_PCT:.0f}%."
        )
    elif n_trades >= RAR_MIN_TRADES and rar < _rar_thr:
        _state["active"]    = True
        _state["gate_type"] = "rar"
        _state["reason"]    = (
            f"RAR gate aktif: Sharpe {rar:.3f} di bawah threshold "
            f"{_rar_thr} (rolling {n_trades} trade). Strategi sedang negatif "
            f"risk-adjusted. Probe ½-risk diizinkan tiap "
            f"{int(PROBE_INTERVAL_SEC // 3600)}h untuk memulihkan gate."
        )
    else:
        _prev_circuit_breaker_active = False
        _state["active"]    = False
        _state["gate_type"] = "none"
        _state["reason"]    = "ok"

    # PLAN_v2 P0 cleanup — `rar` and `drawdown_pct` can be None when there are
    # too few closed trades to compute Sharpe; guard the round() to avoid
    # TypeError spam in the log on a freshly-reset DB.
    logger.debug(
        "risk_gate_updated",
        active=_state["active"], gate_type=_state["gate_type"],
        dd=round(drawdown_pct, 2) if drawdown_pct is not None else None,
        rar=round(rar, 3) if rar is not None else None,
        trades=n_trades,
    )


def _scaled_dd_threshold(wallet_balance: float) -> tuple[float, float]:
    """P6.2: scale DD thresholds based on wallet size.
    Smaller wallets have tighter stops (bigger %loss = can't recover).
    Returns (hard_stop_pct, recover_pct).
    """
    if wallet_balance < 500:
        return 10.0, 5.0    # very tight for micro wallets
    if wallet_balance < 750:
        return 12.0, 6.0
    if wallet_balance < 1500:
        return 15.0, 8.0    # default range
    return 20.0, 10.0       # larger wallets can absorb more


async def evaluate_risk_gate() -> None:
    """
    Fallback: query DB directly to refresh gate state.
    Called by auto_trader / trade endpoint when state is stale.
    Also computes per-lane WR for P6.4 auto-pause.
    """
    import statistics

    from sqlalchemy import select
    from app.database import AsyncSessionLocal, is_db_available
    from app.models.paper_trade import PaperTrade
    from app.api.v1.balance import get_or_create_balance
    from app.services.trading_costs import FUTURES_BALANCE_STATUSES

    if not is_db_available():
        return  # keep existing state; don't block on DB unavailability

    # PLAN_v5 Group C: pull DB overrides once per evaluation. NOTE: DD_HARD_STOP_PCT/
    # DD_RECOVER_PCT are deliberately NOT wired here — _scaled_dd_threshold() below
    # computes them fresh from wallet size on every call and would immediately
    # clobber any DB override, so exposing them as editable would be misleading.
    global RAR_GATE_THRESHOLD, LANE_WR_PAUSE_THRESHOLD, LANE_WR_MIN_SAMPLE
    try:
        from agents.shared.config_reader import cfg
        RAR_GATE_THRESHOLD      = await cfg.get("futures", "rar_threshold", RAR_GATE_THRESHOLD)
        LANE_WR_PAUSE_THRESHOLD = await cfg.get("futures", "lane_wr_pause_threshold", LANE_WR_PAUSE_THRESHOLD)
        LANE_WR_MIN_SAMPLE      = int(await cfg.get("futures", "lane_wr_min_sample", LANE_WR_MIN_SAMPLE))
    except Exception as exc:
        logger.warning("agent_config_pull_failed", scope="risk_gate", error=str(exc)[:120])

    try:
        _wallet     = await get_or_create_balance("futures")
        wallet_base = _wallet.initial_balance + _wallet.deposited_total - _wallet.withdrawn_total
        current_bal = max(_wallet.balance, 0.0)

        # P6.2: scale DD threshold to wallet size
        _hard_stop, _recover = _scaled_dd_threshold(current_bal)

        async with AsyncSessionLocal() as session:
            closed_trades = list((await session.execute(
                select(PaperTrade).where(
                    PaperTrade.style.in_([
                        "futures_agent1", "futures_agent2", "futures_agent3",
                        "futures_agent_bigmover",   # Phase 2 BM1
                    ]),
                    PaperTrade.status.in_(list(FUTURES_BALANCE_STATUSES)),   # BUG-L19: include expired
                    PaperTrade.pnl_dollar.isnot(None),
                ).order_by(PaperTrade.closed_at.asc())
            )).scalars().all())

        pnl_series: list[float] = []
        balance  = wallet_base
        peak_bal = wallet_base
        max_dd   = 0.0

        # P6.4: per-lane rolling WR (last LANE_WR_MIN_SAMPLE trades per lane)
        from collections import defaultdict
        lane_trades: dict = defaultdict(list)

        for t in closed_trades:
            pnl_d    = t.pnl_dollar or 0.0
            balance += pnl_d
            pnl_series.append(pnl_d)
            peak_bal = max(peak_bal, balance)
            dd = (peak_bal - balance) / peak_bal * 100 if peak_bal > 0 else 0.0
            if dd > max_dd:
                max_dd = dd
            # Lane WR tracking
            _lane = t.setup_type or ""
            if _lane:
                lane_trades[_lane].append(t)

        # P6.4: compute per-lane WR and trigger pauses
        for lane_name, lts in lane_trades.items():
            recent = lts[-LANE_WR_MIN_SAMPLE:]
            wins  = sum(1 for t in recent if t.status == "tp" and (t.pnl_pct or 0) > 0)
            update_lane_wr(lane_name, wins, len(recent))

        # PLAN_v11 A1: Sharpe dari window rolling (N terakhir), bukan kumulatif —
        # supaya performa terbaru bisa MEMBUKA kembali gate (keluar dari deadlock).
        sharpe = 0.0
        _window = pnl_series[-RAR_ROLLING_WINDOW:]
        if len(_window) >= RAR_MIN_TRADES:
            try:
                mu     = statistics.mean(_window)
                std    = statistics.stdev(_window)
                sharpe = round(mu / std, 3) if std > 0 else 0.0
            except Exception:
                pass

        # P6.2: temporarily override thresholds for this evaluation
        global DD_HARD_STOP_PCT, DD_RECOVER_PCT
        DD_HARD_STOP_PCT = _hard_stop
        DD_RECOVER_PCT   = _recover

        # PLAN_v11 A3: regime-aware — jangan matikan strategi saat market jelas bullish
        _regime = "ranging"
        try:
            from agents.futures.regime import get_cached_regime
            _regime = get_cached_regime()
        except Exception:
            pass
        update_gate_state(max_dd, sharpe, len(_window), regime=_regime)

    except Exception as exc:
        logger.warning("risk_gate_evaluate_failed", error=str(exc))


def consume_emergency_tighten() -> bool:
    """
    G10: returns True and clears the flag if an emergency tighten is pending.
    Called at the start of each futures monitor cycle.
    """
    global _emergency_tighten_pending
    if _emergency_tighten_pending:
        _emergency_tighten_pending = False
        return True
    return False


def is_gate_open() -> tuple[bool, str]:
    """
    Synchronous check — True = gate open (new positions allowed).
    Returns (can_open, reason). Called from auto_trader and trade endpoint.
    """
    if _state["active"]:
        return False, _state["reason"]
    return True, "ok"


def is_lane_paused(lane: str) -> tuple[bool, str]:
    """P6.4 + PLAN_v15 P2: True if the lane (setup_type) is on a WR-based auto-pause
    OR a consecutive-loss pause (whichever is active)."""
    until = _lane_paused_until.get(lane, 0.0)
    if time.time() < until:
        hrs_left = round((until - time.time()) / 3600, 1)
        wr_data  = _lane_wr.get(lane, {})
        wr       = wr_data.get("wins", 0) / wr_data["total"] if wr_data.get("total") else 0
        return True, (
            f"Lane '{lane}' auto-paused: WR {wr:.0%} < {LANE_WR_PAUSE_THRESHOLD:.0%} "
            f"({wr_data.get('total', 0)} trades). Resumes in {hrs_left}h."
        )
    # PLAN_v15 P2: consecutive-real-loss pause (computed by evaluate_daily_gates)
    consec_until = _daily_gates["lane_pause_until"].get(lane, 0.0)
    if time.time() < consec_until:
        hrs_left = round((consec_until - time.time()) / 3600, 1)
        return True, (
            f"Lane '{lane}' pause {CONSEC_SL_LANE_LIMIT} loss beruntun "
            f"(window {CONSEC_SL_WINDOW_H:.0f}h). Resumes in {hrs_left}h."
        )
    return False, "ok"


def get_lane_wr(lane: str) -> tuple[float, int]:
    """PLAN_v16 F5: rolling WR lane (dari evaluate_risk_gate). Returns (wr, sample)."""
    d = _lane_wr.get(lane) or {}
    total = int(d.get("total", 0))
    wr = (d.get("wins", 0) / total) if total else 0.0
    return wr, total


def update_lane_wr(lane: str, wins: int, total: int) -> None:
    """P6.4: Update per-lane rolling WR and trigger pause if threshold crossed."""
    global _lane_wr, _lane_paused_until
    _lane_wr[lane] = {"wins": wins, "total": total}
    if total >= LANE_WR_MIN_SAMPLE:
        wr = wins / total
        if wr < LANE_WR_PAUSE_THRESHOLD:
            until = time.time() + LANE_PAUSE_HOURS * 3600
            prev_until = _lane_paused_until.get(lane, 0.0)
            if time.time() >= prev_until:   # only fire once per pause cycle
                _lane_paused_until[lane] = until
                logger.warning("lane_auto_paused", lane=lane, wr=round(wr, 3),
                               total=total, pause_hours=LANE_PAUSE_HOURS)
        elif time.time() >= _lane_paused_until.get(lane, 0.0):
            _lane_paused_until.pop(lane, None)  # clear expired entry to keep dict clean


def is_state_stale() -> bool:
    """True if gate state has never been evaluated or is older than STATE_TTL."""
    return _state["updated_at"] == 0.0 or (time.time() - _state["updated_at"]) > STATE_TTL


def probe_allowed() -> bool:
    """
    PLAN_v11 A2 — saat RAR gate aktif (BUKAN circuit-breaker DD), izinkan SATU
    posisi probe ½-risk tiap PROBE_INTERVAL_SEC. Tujuannya menghasilkan data
    trade baru agar Sharpe rolling bisa memulihkan gate — memecah deadlock.
    Circuit-breaker DD & override-closed TIDAK boleh diprobe (risiko nyata).
    """
    if not _state["active"] or _state["gate_type"] != "rar":
        return False
    return (time.time() - _last_probe_at) >= PROBE_INTERVAL_SEC


def record_probe() -> None:
    """PLAN_v11 A2 — tandai probe terakhir dibuka (dipanggil auto_trader)."""
    global _last_probe_at
    _last_probe_at = time.time()
    logger.info("rar_probe_opened", rar=_state.get("rar"), n=_state.get("n_trades"))


def reset_state() -> None:
    """
    PLAN_v11 P4 — clear seluruh state gate in-memory (dipanggil reset_simulation).
    Setelah reset DB, metrik lama tak boleh menahan gate tetap tertutup.
    """
    global _state, _last_probe_at, _lane_paused_until, _lane_wr
    global _emergency_tighten_pending, _prev_circuit_breaker_active
    _state.update({
        "active": False, "gate_type": "none", "reason": "ok",
        "drawdown_pct": 0.0, "rar": 0.0, "n_trades": 0,
        "updated_at": 0.0, "override": None,
    })
    _last_probe_at = 0.0
    _lane_paused_until = {}
    _lane_wr = {}
    _emergency_tighten_pending = False
    _prev_circuit_breaker_active = False
    # PLAN_v15: daily gates are DB-derived, but clear the cache so a reset DB
    # is re-evaluated immediately instead of serving pre-reset flags for TTL secs.
    _daily_gates.update({
        "updated_at": 0.0, "day_pnl": 0.0, "day_peak_pnl": 0.0,
        "loss_breaker": False, "profit_lock": False, "giveback_stop": False,
        "bm_real_sl_today": 0, "lane_pause_until": {}, "global_pause_until": 0.0,
        "reason": "ok",
    })
    logger.info("risk_gate_state_reset")


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
    _dd  = _state["drawdown_pct"]
    _rar = _state["rar"]
    now  = time.time()
    lane_pause_info = {
        lane: {
            "paused": now < until,
            "pause_until": until,
            "wr": round(_lane_wr.get(lane, {}).get("wins", 0) /
                        max(_lane_wr.get(lane, {}).get("total", 1), 1), 3),
            "total": _lane_wr.get(lane, {}).get("total", 0),
        }
        for lane, until in _lane_paused_until.items()
    }
    return {
        "active":        _state["active"],
        "gate_type":     _state["gate_type"],   # none | circuit_breaker | rar | override | lane_pause
        "reason":        _state["reason"],
        # PLAN_v2 P0 cleanup — both can be None on a freshly-reset DB.
        "drawdown_pct":  round(_dd, 2)  if _dd  is not None else None,
        "rar":           round(_rar, 3) if _rar is not None else None,
        "n_trades":      _state["n_trades"],
        "updated_at":    _state["updated_at"],
        "override":      _state["override"],
        "dd_threshold":  DD_HARD_STOP_PCT,
        "dd_recover":    DD_RECOVER_PCT,
        "rar_threshold": RAR_GATE_THRESHOLD,
        "rar_min_trades": RAR_MIN_TRADES,
        # PLAN_v11 A1/A2 — transparansi anti-deadlock
        "rar_window":     RAR_ROLLING_WINDOW,
        "probe_allowed":  probe_allowed(),
        "next_probe_in_sec": max(0, int(PROBE_INTERVAL_SEC - (time.time() - _last_probe_at)))
                             if (_state["active"] and _state["gate_type"] == "rar") else None,
        "stale":         is_state_stale(),
        "daily_gates":   get_daily_gates(),  # PLAN_v15 P1/P2/P8
        "lane_pauses":   lane_pause_info,  # P6.4
        "lane_wr":       {
            lane: {"wins": d["wins"], "total": d["total"],
                   "wr": round(d["wins"] / max(d["total"], 1), 3)}
            for lane, d in _lane_wr.items()
        },
    }
