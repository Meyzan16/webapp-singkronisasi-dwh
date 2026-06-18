"""
Opportunity Scanner Scheduler — runs every 15 minutes.

After each scan:
  - Results stored in opp_store (for frontend)
  - Coins with score ≥ 85 → AUTO-OPEN posisi (high conviction only)
  - Others → recommendation only (manual open)
"""

import asyncio
import json
import time
from typing import Optional

import structlog

from agents.opportunity import scanner as opp_scanner
from agents.opportunity import store as opp_store

logger = structlog.get_logger(__name__)

INTERVAL_SEC  = 3 * 60    # scan every 3 minutes — catch entries before big moves
STARTUP_DELAY = 20

MAX_OPENS_PER_CYCLE = 3   # §7B: naik 2→3 agar tidak melewat momentum bersamaan

# §14.4: circuit breaker — rugi harian (WIB) melebihi batas → auto-open jeda
DAILY_LOSS_LIMIT_FRACTION = 0.03
WIB_UTC_OFFSET_H          = 7

# §14.5: koin beta-BTC tinggi bergerak serentak — maksimal 1 posisi dari grup ini
HIGH_BETA_GROUP = {
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT",
    "DOGEUSDT", "LTCUSDT", "LINKUSDT", "AVAXUSDT", "DOTUSDT", "BCHUSDT",
}

_running       = False
_cycle_count   = 0
_last_scan_ts: Optional[float] = None
_last_error:   Optional[str]   = None
_auto_opened   = 0   # cumulative auto-opens this session


def get_state() -> dict:
    next_scan_in_min = None
    if _last_scan_ts is not None:
        remaining = max(0.0, INTERVAL_SEC - (time.time() - _last_scan_ts))
        next_scan_in_min = round(remaining / 60, 1)
    return {
        "running":           _running,
        "cycle_count":       _cycle_count,
        "last_scan_ts":      _last_scan_ts,
        "last_error":        _last_error,
        "interval_minutes":  INTERVAL_SEC // 60,
        "auto_opened":       _auto_opened,
        "next_scan_in_min":  next_scan_in_min,
    }


def _risk_adjusted_score(coin: dict) -> float:
    """
    EV per unit risk — scanner sudah menghitung `ev_per_risk` dengan rumus yang
    sama (§11.4, satu sumber ranking); ini fallback bila field tidak ada.
    p_win dari RAW pre-weight score (§7.4).
    """
    if "ev_per_risk" in coin:
        return coin["ev_per_risk"]
    p      = min(coin.get("raw_score", coin.get("opportunity_score", 0)), 99) / 100
    reward = coin.get("tp2_net_pct", coin.get("tp2_pct", 0)) or 0
    risk   = coin.get("risk_pct", 0) or 2.0
    ev     = p * reward - (1 - p) * risk
    return ev / risk


async def _daily_loss_breaker_active() -> bool:
    """
    §14.4: True bila total pnl_dollar hari ini (WIB) ≤ −3% balance.
    Auto-open jeda sampai hari berganti; manual open tetap boleh (keputusan user).
    """
    from app.database import AsyncSessionLocal
    from app.models.paper_trade import PaperTrade
    from app.models.paper_balance import PaperBalance
    from sqlalchemy import func, select

    # Awal hari WIB dalam epoch UTC
    now_wib       = time.time() + WIB_UTC_OFFSET_H * 3600
    start_of_day  = (int(now_wib) // 86400) * 86400 - WIB_UTC_OFFSET_H * 3600

    async with AsyncSessionLocal() as session:
        today_pnl = (await session.execute(
            select(func.coalesce(func.sum(PaperTrade.pnl_dollar), 0.0)).where(
                PaperTrade.style == "opportunity_spot",
                PaperTrade.status.in_(["tp", "sl", "manual"]),
                PaperTrade.closed_at >= start_of_day,
                PaperTrade.pnl_dollar.isnot(None),
            )
        )).scalar() or 0.0

        bal_row = (await session.execute(
            select(PaperBalance).where(PaperBalance.style == "opportunity_spot")
        )).scalar_one_or_none()
        balance = bal_row.balance if bal_row else 1000.0

    if today_pnl <= -(balance * DAILY_LOSS_LIMIT_FRACTION):
        logger.warning("daily_loss_breaker_active",
                       today_pnl=round(today_pnl, 2),
                       limit=round(-balance * DAILY_LOSS_LIMIT_FRACTION, 2))
        return True
    return False


async def _fetch_live_price(symbol: str) -> Optional[float]:
    """Harga live untuk validasi entry (§13.4 — scan price bisa basi ~25 dtk)."""
    import httpx
    from app.services.binance_urls import spot as _spot
    try:
        async with httpx.AsyncClient(timeout=6) as client:
            r = await client.get(_spot(f"/api/v3/ticker/price?symbol={symbol}"))
            if r.status_code == 200:
                return float(r.json()["price"])
    except Exception:
        pass
    return None


async def _auto_open_position(coin: dict) -> bool:
    """
    Auto-open a SPOT paper trade for high-conviction opportunities (score ≥ 95).
    Returns True if opened, False if skipped (already open / cooldown /
    missing levels / insufficient balance).

    Balance-aware (BUG FIX v3):
      - Position size computed from REAL paper balance (fixed-fractional risk,
        conviction-scaled 1%→2%) via compute_spot_sizing
      - Entry BLOCKED when available balance can't fund the full notional —
        no partial entries (big opportunity + small margin = biased returns)
      - position_size / risk_dollar / balance_snapshot stored on the trade
    """
    from app.database import AsyncSessionLocal, is_db_available
    from app.models.paper_trade import PaperTrade
    from app.api.v1.balance import compute_spot_sizing
    from sqlalchemy import select

    if not is_db_available():
        return False

    symbol = coin["symbol"]
    entry  = coin.get("entry")
    sl     = coin.get("sl")
    tp2    = coin.get("tp2")

    if not all([entry, sl, tp2]):
        return False

    # §13.4: harga scan bisa basi — validasi terhadap harga live.
    # Selisih ≤ 1% → re-anchor semua level secara proporsional (pct tetap sama);
    # selisih > 1% → setup sudah lari, skip.
    live = await _fetch_live_price(symbol)
    if live is None:
        logger.info("auto_open_no_live_price", symbol=symbol)
        return False
    drift_pct = abs(live - entry) / entry * 100
    if drift_pct > 1.0:
        logger.info("auto_open_price_drift_skip", symbol=symbol,
                    scan_price=entry, live=live, drift_pct=round(drift_pct, 2))
        return False
    if drift_pct > 0.05:
        factor = live / entry
        entry  = live
        sl     = sl * factor
        tp2    = tp2 * factor
        for key in ("tp1", "tp3"):
            if coin.get(key):
                coin[key] = coin[key] * factor
        coin["entry"], coin["sl"], coin["tp2"] = entry, sl, tp2

    is_breakout = coin.get("alert_type") == "breakout_pump"

    # B7: breakout_pump — skip auto-open jika change_24h > 100% (parabolic)
    if is_breakout and coin.get("change_24h", 0) > 100.0:
        logger.info("auto_open_parabolic_skip", symbol=symbol,
                    change_24h=coin.get("change_24h"))
        return False

    # B7: max 1 breakout_pump position open at a time
    if is_breakout:
        async with AsyncSessionLocal() as bck:
            bp_open = (await bck.execute(
                select(PaperTrade).where(
                    PaperTrade.style      == "opportunity_spot",
                    PaperTrade.status     == "open",
                    PaperTrade.alert_type == "breakout_pump",
                ).limit(1)
            )).scalar_one_or_none()
            if bp_open is not None:
                logger.info("auto_open_breakout_limit", symbol=symbol,
                            already_open=bp_open.symbol)
                return False

    # Cooldown via DB — survives restarts.
    # SL: 2 jam (jangan re-entry setup yang baru gagal).
    # §12.7: TP juga 45 menit — jangan langsung beli lagi di puncak pump yang sama.
    # B7: breakout_pump cooldown lebih pendek: 30 menit TP/SL
    COOLDOWN_SL_HOURS = 0.5  if is_breakout else 2.0
    COOLDOWN_TP_HOURS = 0.5  if is_breakout else 0.33   # 30 menit untuk breakout
    async with AsyncSessionLocal() as ck:
        last_close_q = await ck.execute(
            select(PaperTrade).where(
                PaperTrade.style  == "opportunity_spot",
                PaperTrade.symbol == symbol,
                PaperTrade.status.in_(["sl", "tp"]),
            ).order_by(PaperTrade.closed_at.desc()).limit(1)
        )
        last_close = last_close_q.scalar_one_or_none()
        if last_close and last_close.closed_at:
            hrs_since = (time.time() - last_close.closed_at) / 3600
            limit_h   = COOLDOWN_SL_HOURS if last_close.status == "sl" else COOLDOWN_TP_HOURS
            if hrs_since < limit_h:
                logger.info("auto_open_cooldown_db", symbol=symbol,
                            last_status=last_close.status,
                            hours_since=round(hrs_since, 1))
                return False

    async with AsyncSessionLocal() as session:
        existing = await session.execute(
            select(PaperTrade).where(
                PaperTrade.style  == "opportunity_spot",
                PaperTrade.status == "open",
                PaperTrade.symbol == symbol,
            ).limit(1)
        )
        if existing.scalar_one_or_none():
            return False

    # §14.5: batas korelasi — grup beta-BTC tinggi maksimal 1 posisi
    if symbol in HIGH_BETA_GROUP:
        async with AsyncSessionLocal() as corr_session:
            beta_open = (await corr_session.execute(
                select(PaperTrade).where(
                    PaperTrade.style  == "opportunity_spot",
                    PaperTrade.status == "open",
                    PaperTrade.symbol.in_(list(HIGH_BETA_GROUP)),
                ).limit(1)
            )).scalar_one_or_none()
            if beta_open is not None:
                logger.info("auto_open_correlation_skip", symbol=symbol,
                            already_open=beta_open.symbol)
                return False

    # ── Balance check: size from real balance (§7.4: RAW pre-weight score) ───
    sizing = await compute_spot_sizing(
        score    = coin.get("raw_score", coin.get("opportunity_score", 0)),
        risk_pct = coin.get("risk_pct", 0),
    )
    if not sizing["can_open"]:
        logger.info("auto_open_blocked", symbol=symbol,
                    score=coin.get("raw_score"), reason=sizing["reason"])
        return False

    async with AsyncSessionLocal() as session:
        meta = {
            "signals":           coin.get("signals", []),
            "tp1":               coin.get("tp1"),
            "tp2":               coin.get("tp2"),
            "tp3":               coin.get("tp3"),
            "tp1_pct":           coin.get("tp1_pct", 0),
            "tp2_pct":           coin.get("tp2_pct", 0),
            "tp3_pct":           coin.get("tp3_pct", 0),
            "risk_pct":          coin.get("risk_pct", 0),
            "rr_ratio":          coin.get("rr_ratio", 0),
            "vol_ratio":         coin.get("vol_ratio", 1),
            "avg_taker":         coin.get("avg_taker", 0.5),
            "auto_open":         True,
            # BUG FIX: store EMA state at entry so monitor can detect REAL reversals
            "entry_ema_bullish": coin.get("ema_bullish", True),
            # §5.1: konteks lengkap saat open — setiap close jadi baris training utuh
            "raw_score":         coin.get("raw_score"),
            "weight_applied":    coin.get("weight_applied", 1.0),
            "ev_per_risk":       coin.get("ev_per_risk"),
            "direction_confirmed": coin.get("direction_confirmed"),
            "entry_hour_wib":    int((time.time() / 3600 + 7) % 24),
            # PLAN-SPOT-GAP: entry_mode menentukan exit logic di monitor.py —
            # "momentum_chase" trades pakai trailing-structure-stop (return
            # maksimal), "fresh_setup" tetap pakai TP1/TP2/TP3 tetap (existing).
            "entry_mode":        coin.get("entry_mode", "fresh_setup"),
            "change_7d":         coin.get("change_7d", 0.0),
        }

        trade = PaperTrade(
            symbol       = symbol,
            direction    = "LONG",
            style        = "opportunity_spot",
            entry_price  = entry,
            stop_loss    = sl,
            take_profit  = tp2,
            risk_reward  = f"1:{coin.get('rr_ratio', 0)}",
            probability  = coin.get("opportunity_score", 0),
            alert_type   = coin.get("alert_type", "auto"),
            sl_method    = f"Swing low + buffer | AUTO-OPEN score={coin.get('opportunity_score')}",
            tp_method    = f"TP1 +{coin.get('tp1_pct',0):.1f}% | TP2 +{coin.get('tp2_pct',0):.1f}% | TP3 +{coin.get('tp3_pct',0):.1f}%",
            signals_json = json.dumps(meta, ensure_ascii=False),
            entry_type   = "auto",   # distinguishes from manual opens
            entry_at     = time.time(),
            status       = "open",
            position_size    = sizing["position_size"],
            risk_dollar      = sizing["risk_dollar"],
            balance_snapshot = sizing["balance"],
        )
        session.add(trade)
        try:
            await session.commit()
        except Exception as ie:
            # §13.5: unique index (style,symbol,open) — race dengan manual open
            await session.rollback()
            logger.info("auto_open_duplicate_blocked", symbol=symbol,
                        error=str(ie)[:60])
            return False

    logger.info(
        "opportunity_auto_opened",
        symbol=symbol,
        score=coin.get("opportunity_score"),
        entry=entry, sl=sl, tp2=tp2,
        notional=sizing["position_size"],
        risk_dollar=sizing["risk_dollar"],
        available_after=round(sizing["available"] - sizing["position_size"], 2),
    )
    return True


async def run_opportunity_loop() -> None:
    global _running, _cycle_count, _last_scan_ts, _last_error, _auto_opened

    _running = True
    logger.info("opportunity_agent_started", interval_min=INTERVAL_SEC // 60)
    await asyncio.sleep(STARTUP_DELAY)

    while True:
        try:
            opp_store.set_scanning(True)
            result = await opp_scanner.run_opportunity_scan()
            opp_store.set_result(result)
            _last_scan_ts = time.time()
            _cycle_count += 1
            _last_error   = None

            # Auto-open: kandidat ber-gerbang-arah, ranked by EV per unit risk.
            # Maks 2 entry per siklus (§7B) — ambil puncak ranking saja.
            auto_candidates = sorted(
                (
                    c for c in result.get("results", [])
                    if c.get("auto_open") and c.get("entry")
                ),
                key=_risk_adjusted_score,
                reverse=True,
            )

            opened = 0
            if auto_candidates and await _daily_loss_breaker_active():
                logger.info("auto_open_paused_daily_breaker",
                            skipped=len(auto_candidates))
            else:
                for coin in auto_candidates:
                    if opened >= MAX_OPENS_PER_CYCLE:
                        break
                    if await _auto_open_position(coin):
                        opened += 1
                        _auto_opened += 1

            logger.info(
                "opportunity_cycle_done",
                cycle=_cycle_count,
                found=result.get("found", 0),
                auto_opened=opened,
            )

        except asyncio.CancelledError:
            opp_store.set_scanning(False)
            logger.info("opportunity_agent_stopped")
            _running = False
            raise
        except Exception as exc:
            opp_store.set_scanning(False)
            _last_error = str(exc)[:120]
            logger.error("opportunity_agent_error", error=_last_error)

        elapsed   = time.time() - (_last_scan_ts or time.time())
        sleep_for = max(60, INTERVAL_SEC - elapsed)
        await asyncio.sleep(sleep_for)
