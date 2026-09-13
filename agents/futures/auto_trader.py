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

AUTO_OPEN_THRESHOLD = 65   # cadangan bila `agentic_min_score` tak terbaca
MAX_AUTO_POSITIONS  = 6    # plafon GLOBAL posisi terbuka (satu dompet)
FUTURES_COOLDOWN_HOURS = 3 # F55: no re-entry within 3h of an SL on the same symbol (global)

# Semua gaya futures berbagi SATU dompet → dedup & batas bersifat GLOBAL (BUG-L1).
def _semua_gaya_futures() -> tuple[str, ...]:
    """Semua gaya futures — dari registry, termasuk agen aktif.

    Daftar ini dipakai untuk dedup simbol, hitungan posisi terbuka, cooldown SL,
    dan kuota lane. Sampai 9 Sep 2026 isinya hanya EMPAT gaya lama, sehingga
    posisi agen tunggal tak terhitung oleh satu pun batas itu: dua posisi pada
    simbol yang sama jadi mungkin, dan `MAX_AUTO_POSITIONS` bisa terlampaui
    tanpa ada yang menahannya.
    """
    try:
        from app.services.agent_registry import FUTURES_AGENTS
        return tuple(FUTURES_AGENTS)
    except Exception:      # noqa: BLE001
        return ("futures_agent1", "futures_agent2", "futures_agent3",
                "futures_agent_bigmover", "futures_agentic")


_FUTURES_STYLES = _semua_gaya_futures()


def _agen_aktif() -> frozenset[str]:
    try:
        from app.services.agent_registry import ACTIVE_FUTURES_AGENTS
        return frozenset(ACTIVE_FUTURES_AGENTS)
    except Exception:      # noqa: BLE001
        return frozenset({"futures_agentic"})


_AGEN_AKTIF = _agen_aktif()

# Cross-margin wallet utilization cap — total locked margin ≤ 70% wallet
MAX_WALLET_MARGIN_PCT = 70.0

# Gerbang funding, DUA ZONA (PLAN_v6 P4c). Top gainers routinely
# carry elevated funding (crowded) — that's a reason to size down, not to skip
# the move entirely. Soft zone trades at half size; only truly extreme funding vetoes.
MAX_LONG_FUNDING_PCT   = 0.12    # soft threshold: beyond this → size ½
MIN_SHORT_FUNDING_PCT  = -0.12
HARD_LONG_FUNDING_PCT  = 0.25    # hard threshold: beyond this → veto (unsustainable cost)
HARD_SHORT_FUNDING_PCT = -0.25
FUNDING_SOFT_SIZE_MULT = 0.5

# Rezim yang menutup auto-open sepenuhnya. Dulu (BUG-L12) hanya lane pre_move
# yang ditahan dan momentum "menunggangi volatilitas"; sejak agen tunggal, kondisi
# `setup_type != "momentum"` itu selalu benar — jadi perilaku yang BERJALAN
# adalah: rezim volatile menahan semua kandidat. Dinyatakan eksplisit di sini,
# bukan lewat perbandingan nama lane yang sudah tak ada.
AUTO_DISABLED_REGIMES = {"volatile"}  # volatile = immediate SL risk

# ── PLAN_v16 F2/F5 — cost-floor gate & lane throttle ──────────────────────────
MIN_TP1_COST_MULT = 3.0    # F2: TP1 wajib ≥ 3× total biaya round-trip (DB: min_tp1_cost_mult)
# F2: estimasi lama tahan (jam) → estimasi jendela funding untuk lantai biaya.
# Agen tunggal memakai time-stop `exit_max_hold_h`; angka ini cadangannya.
HOLD_EST_H_DEFAULT = 8.0
LANE_THROTTLE_WR      = 0.40   # F5: lane rolling WR di bawah ini (min 10 trade) → ½ size
LANE_THROTTLE_MIN_N   = 10

# ── PLAN_v15 P3/P8 — profit-lock knobs ────────────────────────────────────────
MAX_SAME_DIRECTION      = 4     # P3d: max open positions sharing one direction (of 6 slots)
PROFIT_LOCK_MIN_SCORE   = 80    # P8: after profit lock, only A-grade candidates…
PROFIT_LOCK_SIZE_MULT   = 0.5   #     …at half size ("play with house money")

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


def _ambang_agentic() -> int:
    """Ambang skor agen tunggal (`agentic_min_score`) — satu-satunya penggaris."""
    try:
        from agents.futures.agentic import get as _ag_get
        return int(_ag_get("agentic_min_score"))
    except Exception:      # noqa: BLE001
        return AUTO_OPEN_THRESHOLD


def get_auto_threshold() -> int:
    """Ambang yang DITAMPILKAN/berlaku: override manual (F102) atau ambang agen."""
    return _manual_threshold if _manual_threshold is not None else _ambang_agentic()


def _effective_threshold(agent: str) -> int:
    """Ambang untuk satu kandidat. Skor agen tunggal lahir dari penilai yang
    berbeda skalanya dari lane lama — angka 72 hasil kalibrasi adaptif lama tak
    berarti apa-apa di sini. Override manual (F102) menang bila ada."""
    if _manual_threshold is not None:
        return _manual_threshold
    return _ambang_agentic()


async def auto_open_positions(candidates: list[dict]) -> int:
    """
    Buka posisi terbaik secara global dari kolam kandidat agen tunggal, dibatasi
    SATU dompet bersama:
      - BUG-L1: SATU posisi per simbol (cross-margin menjadikan satu simbol satu
        posisi) — kandidat berskor tertinggi per simbol yang menang.
      - Gerbang: risk gate, gerbang harian, rezim volatile, veto pembelajaran,
        cooldown SL, konsentrasi arah, funding dua zona, lantai biaya, sizing.
    Mengembalikan jumlah posisi yang dibuka.
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
    global MAX_AUTO_POSITIONS, FUTURES_COOLDOWN_HOURS, \
        MAX_WALLET_MARGIN_PCT, MAX_SAME_DIRECTION, MIN_TP1_COST_MULT
    try:
        from agents.shared.config_reader import cfg
        MAX_AUTO_POSITIONS     = int(await cfg.get("futures", "max_auto_positions", MAX_AUTO_POSITIONS))
        FUTURES_COOLDOWN_HOURS = await cfg.get("futures", "cooldown_hours", FUTURES_COOLDOWN_HOURS)
        MAX_WALLET_MARGIN_PCT  = await cfg.get("futures", "max_wallet_margin_pct", MAX_WALLET_MARGIN_PCT)
        MAX_SAME_DIRECTION     = int(await cfg.get("futures", "max_same_direction", MAX_SAME_DIRECTION))
        MIN_TP1_COST_MULT      = await cfg.get("futures", "min_tp1_cost_mult", MIN_TP1_COST_MULT)
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
            _dec(symbol, r.get("agent", ""), r.get("direction", "LONG"),
                 "below_auto_threshold")   # F1
            continue
        # Overekstensi TIDAK diveto di sini: `agentic` memberi `momentum_ekstrem`
        # skor lebih rendah dan memangkas `size_mult` jadi 0,5 — mengecilkan
        # ukuran alih-alih memveto.
        if coin_regime in AUTO_DISABLED_REGIMES:
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

            # PLAN_v6 P4c: two-zone funding gate.
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

            setup = sig.get("setup_type", "")

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
            _hold_h      = _estimasi_hold_h()
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

            # Fase 5: simpan jejak ukuran di kandidat supaya `decision_ledger`
            # bisa mencatatnya sebagai kolom. Tanpa ini ledger tahu KENAPA sebuah
            # kandidat dipilih tapi tidak SEBERAPA BESAR ia dimasuki — dan dua
            # kandidat berskor sama dengan ukuran berbeda punya hasil dolar yang
            # sama sekali berbeda.
            _cost_usd = pos_size * _cost_floor / 100 if pos_size else 0.0
            sig["sizing"] = {
                "risk_usd":    risk_dollar_val,
                "notional":    pos_size,
                "margin":      sizing.get("margin", 0.0),
                "cost_usd":    round(_cost_usd, 4),
                "tp1_net_usd": round(pos_size * _tp1_pct_sig / 100 - _cost_usd, 4),
                "sl_net_usd":  round(-(risk_dollar_val + _cost_usd), 4),
            }

            # PLAN_v11 A2: probe = ½-risk (batasi kerugian saat gate RAR masih aktif)
            if _is_probe:
                pos_size        = round(pos_size * 0.5, 2)
                risk_dollar_val = round(risk_dollar_val * 0.5, 2)

            # Pengurangan ukuran: `size_mult` dari agen (momentum ekstrem) ×
            # pengali zona lunak funding.
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
                "setup_type":   sig.get("setup_type", "agentic"),
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
                # Lane DITULIS SAAT DIBUAT, bukan ditambal belakangan.
                #
                # Sampai 9 Sep 2026 kolom ini dibiarkan NULL di sini dan diisi
                # oleh backfill di loop monitor LAMA. Posisi agen tunggal lewat
                # `_monitor_agentic` — jalur terpisah sejak Fase 7 — jadi tak
                # pernah kebagian backfill itu dan kolomnya kosong selamanya.
                #
                # Akibatnya senyap: `risk_gate` mengelompokkan win-rate per lane
                # lewat `t.setup_type or ""`, sehingga trade agen tunggal tak
                # pernah terhitung — proteksi jeda-lane tak melihatnya sama
                # sekali. Mengisinya di sini menutup seluruh kelas masalah itu,
                # bukan hanya kejadian pada satu jalur.
                setup_type       = sig.get("setup_type") or None,
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


# ── Helpers ────────────────────────────────────────────────────────────────────

def _estimasi_hold_h() -> float:
    """Lama tahan yang diharapkan (jam) — dari time-stop agen (`exit_max_hold_h`)."""
    try:
        from agents.futures import exit_config as _ecfg
        return float(_ecfg.get("exit_max_hold_h"))
    except Exception:      # noqa: BLE001
        return HOLD_EST_H_DEFAULT


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
