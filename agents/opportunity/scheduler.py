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
from agents.opportunity.monitor import lane_of

logger = structlog.get_logger(__name__)

INTERVAL_SEC  = 3 * 60    # scan every 3 minutes — catch entries before big moves
STARTUP_DELAY = 20

MAX_OPENS_PER_CYCLE         = 3   # §7B: naik 2→3 agar tidak melewat momentum bersamaan
# Phase 3 G3-regime: REDUCED state cuts cycle quota — system konservatif tapi tetap jalan
MAX_OPENS_PER_CYCLE_REDUCED = 1

# PLAN-BIG-MOVERS Phase 2 BM3: separate quota for bigmover_chase lane
MAX_BIGMOVER_OPENS    = 2     # max concurrent bigmover_chase positions
BIGMOVER_FASTPASS_SEC = 30    # Wave Rider: check every 30s (was 60) — catch early
BIGMOVER_FASTPASS_MIN_PCT = 8.0    # Wave Rider: rescan from 8% change_24h (was 15%)

# §14.4: circuit breaker — rugi harian (WIB) melebihi batas → auto-open jeda
DAILY_LOSS_LIMIT_FRACTION = 0.03
WIB_UTC_OFFSET_H          = 7
# PLAN_SPOT_LANES B-Fix 7: pembatas frekuensi. 12 Juli tercatat 10 entri auto dan
# 13 penutupan dalam satu hari (−$36.44) — itu churn, bukan peluang.
MAX_AUTO_OPENS_PER_DAY    = 6
# PLAN_SPOT_LANES S5: slot yang DISISIHKAN untuk lane non-Accumulation tiap cycle
# selama ada kandidatnya. Bukan memaksa entri — slot yang tak terpakai dikembalikan
# di lintasan kedua. Tujuannya memberi lane kecil kesempatan mengumpulkan sampel.
RESERVED_SLOTS_NON_ACCUM  = 1

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
    p      = coin.get("lower_confidence_probability")
    p      = float(p) if p is not None else 0.5
    reward = coin.get("tp2_net_pct", coin.get("tp2_pct", 0)) or 0
    risk   = coin.get("risk_pct", 0) or 2.0
    ev     = p * reward - (1 - p) * risk
    return ev / risk


async def _lane_risk_multiplier(alert_type: str) -> float:
    """Throttle a lane on negative expectancy or abrupt recent drift."""
    from app.database import AsyncSessionLocal
    from app.models.paper_trade import PaperTrade
    from sqlalchemy import select

    async with AsyncSessionLocal() as session:
        pnls = list((await session.execute(
            select(PaperTrade.pnl_pct).where(
                PaperTrade.style == "opportunity_spot",
                PaperTrade.alert_type == alert_type,
                PaperTrade.status.in_(["tp", "sl", "manual", "expired"]),
                PaperTrade.pnl_pct.isnot(None),
            ).order_by(PaperTrade.closed_at.desc()).limit(40)
        )).scalars().all())
    # B-Fix 6: 10 → 8 sampel supaya rem menyala lebih cepat saat lane berbalik rugi.
    if len(pnls) < 8:
        return 1.0
    recent = pnls[:20]
    multiplier = 0.5 if sum(recent) / len(recent) <= 0 else 1.0
    if len(pnls) >= 30:
        prior = pnls[20:40]
        recent_wr = sum(value > 0 for value in recent) / len(recent)
        prior_wr = sum(value > 0 for value in prior) / len(prior)
        if prior_wr - recent_wr >= 0.20:
            multiplier = min(multiplier, 0.5)
    return multiplier


def _start_of_wib_day() -> float:
    """Epoch UTC untuk awal hari WIB berjalan."""
    now_wib = time.time() + WIB_UTC_OFFSET_H * 3600
    return (int(now_wib) // 86400) * 86400 - WIB_UTC_OFFSET_H * 3600


# B-Fix 7 (perbaikan lanjutan): breaker kini dipanggil dari loop utama (3 mnt) DAN
# fastpass (30 dtk). Tanpa cache, tiap panggilan menembak Binance — 120 request/jam
# hanya untuk membaca harga yang nyaris tak berubah. TTL pendek cukup: rem harian
# tidak perlu presisi detik.
_UNREALIZED_TTL_SEC = 60.0
_unrealized_cache: tuple[float, float] = (0.0, 0.0)   # (dihitung_pada, nilai)


async def _unrealized_loss_today(open_trades: list) -> float:
    """
    PLAN_SPOT_LANES B-Fix 7: total kerugian BELUM terealisasi dari posisi terbuka.

    Hanya sisi RUGI yang dihitung — laba mengambang tidak boleh mengendurkan rem,
    karena ia belum dibukukan dan bisa menguap. Mengembalikan angka ≤ 0.

    Pemanggil bertanggung jawab menyaring posisi mana yang relevan (lihat
    `_daily_loss_breaker_active`: hanya posisi yang DIBUKA hari ini).
    """
    global _unrealized_cache
    if not open_trades:
        return 0.0

    cached_at, cached_val = _unrealized_cache
    if time.time() - cached_at < _UNREALIZED_TTL_SEC:
        return cached_val

    import httpx
    from app.services.binance_urls import spot as _spot
    from app.services.trading_costs import EXECUTION_COST_PCT

    symbols = sorted({t.symbol for t in open_trades})
    prices: dict[str, float] = {}
    try:
        query = json.dumps(symbols, separators=(",", ":"))
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(_spot(f"/api/v3/ticker/price?symbols={query}"))
            if r.status_code == 200:
                for row in r.json():
                    prices[row["symbol"]] = float(row["price"])
    except Exception as exc:
        # Fail-safe: tanpa harga, jangan mengarang angka — rem jatuh kembali ke
        # perilaku lama (realized saja) dan itu terlihat di log. Sengaja TIDAK
        # di-cache supaya percobaan berikutnya langsung mencoba lagi.
        logger.warning("unrealized_price_fetch_failed", error=str(exc)[:80])
        return 0.0

    total = 0.0
    for t in open_trades:
        px = prices.get(t.symbol)
        if not px or not t.entry_price or t.entry_price <= 0:
            continue
        pnl_pct = (px - t.entry_price) / t.entry_price * 100 - EXECUTION_COST_PCT
        if pnl_pct < 0:
            total += pnl_pct / 100 * (t.position_size or 0.0)
    total = round(total, 2)
    _unrealized_cache = (time.time(), total)
    return total


async def _daily_loss_breaker_active() -> bool:
    """
    §14.4: True bila total P&L hari ini (WIB) ≤ −3% balance.

    B-Fix 7: kini realized + kerugian mengambang. Versi lama hanya melihat realized,
    sehingga rem baru menyala SETELAH kerugian dibukukan — 12 Juli tercatat 13
    penutupan dalam satu hari sebelum rem sempat bekerja.

    Sisi mengambang dibatasi ke posisi yang DIBUKA hari ini (WIB). Kalau tidak,
    drawdown posisi kemarin ikut dihitung sebagai "rugi hari ini" dan rem bisa
    menyala di hari yang sebenarnya datar. Drawdown lintas hari sudah punya
    pengaman sendiri: pemotongan risk 50% di compute_spot_sizing saat DD > 10%.

    Manual open tetap boleh (keputusan user).
    """
    from app.database import AsyncSessionLocal
    from app.models.paper_trade import PaperTrade
    from app.models.paper_balance import PaperBalance
    from sqlalchemy import func, select

    start_of_day = _start_of_wib_day()

    async with AsyncSessionLocal() as session:
        realized = (await session.execute(
            select(func.coalesce(func.sum(PaperTrade.pnl_dollar), 0.0)).where(
                PaperTrade.style == "opportunity_spot",
                PaperTrade.status.in_(["tp", "sl", "manual"]),
                PaperTrade.closed_at >= start_of_day,
                PaperTrade.pnl_dollar.isnot(None),
            )
        )).scalar() or 0.0

        open_trades = list((await session.execute(
            select(PaperTrade).where(
                PaperTrade.style   == "opportunity_spot",
                PaperTrade.status  == "open",
                PaperTrade.entry_at >= start_of_day,
            )
        )).scalars().all())

        bal_row = (await session.execute(
            select(PaperBalance).where(PaperBalance.style == "opportunity_spot")
        )).scalar_one_or_none()
        balance = bal_row.balance if bal_row else 1000.0

    unrealized = await _unrealized_loss_today(open_trades)
    today_pnl  = realized + unrealized

    if today_pnl <= -(balance * DAILY_LOSS_LIMIT_FRACTION):
        logger.warning("daily_loss_breaker_active",
                       realized=round(realized, 2),
                       unrealized_loss=unrealized,
                       today_pnl=round(today_pnl, 2),
                       limit=round(-balance * DAILY_LOSS_LIMIT_FRACTION, 2))
        return True
    return False


async def _auto_opens_today() -> int:
    """B-Fix 7: jumlah posisi auto yang dibuka hari ini (WIB) — pembatas churn."""
    from app.database import AsyncSessionLocal
    from app.models.paper_trade import PaperTrade
    from sqlalchemy import func, select

    async with AsyncSessionLocal() as session:
        return int((await session.execute(
            select(func.count(PaperTrade.id)).where(
                PaperTrade.style      == "opportunity_spot",
                PaperTrade.entry_type == "auto",
                PaperTrade.entry_at   >= _start_of_wib_day(),
            )
        )).scalar() or 0)


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


async def _bigmover_open_count() -> int:
    """Phase 2 BM3: count open bigmover_chase positions for quota enforcement."""
    from app.database import AsyncSessionLocal
    from app.models.paper_trade import PaperTrade
    from sqlalchemy import func, select

    async with AsyncSessionLocal() as s:
        # entry_mode is in signals_json meta. Cheaper: filter by alert_type='bigmover_chase'.
        r = await s.execute(
            select(func.count(PaperTrade.id)).where(
                PaperTrade.style      == "opportunity_spot",
                PaperTrade.status     == "open",
                PaperTrade.alert_type == "bigmover_chase",
            )
        )
        return int(r.scalar() or 0)


async def _early_radar_open_count() -> int:
    """PLAN_v5 Group A: count open early_radar positions for quota enforcement."""
    from app.database import AsyncSessionLocal
    from app.models.paper_trade import PaperTrade
    from sqlalchemy import func, select

    async with AsyncSessionLocal() as s:
        r = await s.execute(
            select(func.count(PaperTrade.id)).where(
                PaperTrade.style      == "opportunity_spot",
                PaperTrade.status     == "open",
                PaperTrade.alert_type == "early_radar",
            )
        )
        return int(r.scalar() or 0)


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
    # BigMover/breakout coins move fast — tolerate up to 3% drift; others 1%
    is_bigmover = coin.get("entry_mode") == "bigmover_chase" or coin.get("alert_type") == "breakout_pump"
    drift_limit = 3.0 if is_bigmover else 1.0
    if drift_pct > drift_limit:
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
    # SL: 6 jam (jangan re-entry setup yang baru gagal).
    # §12.7: TP juga 45 menit — jangan langsung beli lagi di puncak pump yang sama.
    # B7: breakout_pump cooldown lebih pendek: 30 menit TP/SL
    # PLAN_SPOT_LANES B-Fix 5: SL beruntun pada simbol yang sama MENGGANDAKAN jeda
    # (6→12→24 jam). Forensik 21 Jul: dengan cooldown 2 jam yang hanya melihat satu
    # penutupan terakhir, 8 dari 9 re-entry pasca-SL rugi lagi (TONUSDT 6x beruntun).
    COOLDOWN_SL_HOURS  = 0.5 if is_breakout else 6.0
    COOLDOWN_TP_HOURS  = 0.5 if is_breakout else 0.75   # 45 menit untuk akumulasi (§12.7)
    SL_STREAK_WINDOW_H = 48.0   # SL di luar window ini tidak lagi dihitung beruntun
    SL_COOLDOWN_MAX_H  = 24.0   # plafon — jangan kunci simbol lebih dari sehari
    async with AsyncSessionLocal() as ck:
        recent_closes = list((await ck.execute(
            select(PaperTrade).where(
                PaperTrade.style  == "opportunity_spot",
                PaperTrade.symbol == symbol,
                PaperTrade.status.in_(["sl", "tp"]),
            ).order_by(PaperTrade.closed_at.desc()).limit(6)
        )).scalars().all())

    last_close = recent_closes[0] if recent_closes else None
    if last_close and last_close.closed_at:
        now       = time.time()
        hrs_since = (now - last_close.closed_at) / 3600
        sl_streak = 0
        if last_close.status == "sl":
            for t in recent_closes:
                if t.status != "sl" or not t.closed_at:
                    break
                if (now - t.closed_at) / 3600 > SL_STREAK_WINDOW_H:
                    break
                sl_streak += 1
            limit_h = min(COOLDOWN_SL_HOURS * (2 ** (sl_streak - 1)), SL_COOLDOWN_MAX_H)
        else:
            limit_h = COOLDOWN_TP_HOURS
        if hrs_since < limit_h:
            logger.info("auto_open_cooldown_db", symbol=symbol,
                        last_status=last_close.status,
                        sl_streak=sl_streak,
                        limit_hours=round(limit_h, 2),
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
    # PLAN_v5 Group A: Early Radar sizing ½ normal (account_risk_pct=0.5%).
    _acct_risk_pct = coin.get("account_risk_pct")
    _risk_frac_override = (_acct_risk_pct / 100.0) if _acct_risk_pct else None
    lower_p = coin.get("lower_confidence_probability")
    kelly_fraction = None
    lane_multiplier = await _lane_risk_multiplier(str(coin.get("alert_type") or "unknown"))
    if lower_p is not None:
        risk_pct = float(coin.get("risk_pct", 0) or 2.0)
        reward_pct = float(coin.get("tp2_net_pct", coin.get("tp2_pct", 0)) or 0)
        payoff = reward_pct / risk_pct if risk_pct > 0 else 0.0
        kelly_fraction = max(0.0, float(lower_p) - (1.0 - float(lower_p)) / payoff) if payoff > 0 else 0.0
        # B-Fix 6: lane_multiplier TIDAK lagi dikalikan di sini. Dulu ia hanya
        # berlaku di cabang ini, sehingga saat `lower_p` None (sinyal belum punya
        # sampel learning) rem lane terlewat diam-diam dan sizing kembali penuh.
        # Sekarang ia diteruskan ke compute_spot_sizing dan selalu berlaku.
        capped_kelly_risk = min(0.01, 0.25 * kelly_fraction)
        _risk_frac_override = min(
            _risk_frac_override if _risk_frac_override is not None else 0.01,
            capped_kelly_risk,
        )
    raw_score = float(coin.get("raw_score", coin.get("opportunity_score", 0)) or 0)
    adaptive_score = float(coin.get("adaptive_score", raw_score) or raw_score)
    sizing = await compute_spot_sizing(
        # Adaptive learning may reduce risk now, but cannot increase sizing
        # before the challenger passes walk-forward promotion gates.
        score    = min(raw_score, adaptive_score),
        risk_pct = coin.get("risk_pct", 0),
        risk_fraction_override = _risk_frac_override,
        risk_multiplier        = lane_multiplier,
        # S7 opsi B: rem portofolio memakai angka yang SAMA dengan rem harian.
        # Dulu portfolio heat 4% vs breaker harian 3% — portofolio boleh dimuati
        # melebihi apa yang sanggup ditanggung batas harian.
        max_portfolio_risk     = DAILY_LOSS_LIMIT_FRACTION,
    )
    if not sizing["can_open"]:
        logger.info("auto_open_blocked", symbol=symbol,
                    score=coin.get("raw_score"), reason=sizing["reason"])
        return False

    # P1: compute entry slippage for meta (informational)
    from app.services.slippage_sim import calculate_entry_slippage as _cslip, get_session_label as _sess
    _slip_pct = _cslip(coin.get("quote_vol_24h", 0))

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
            # PLAN_SPOT_LANES B-Fix 3: identitas lane yang TIDAK pernah berubah.
            # `entry_mode` di atas dimutasi monitor jadi "momentum_chase" begitu
            # TP2/TP3 tersentuh, jadi ia tak bisa dipakai untuk atribusi lane.
            "lane":              lane_of({}, coin.get("alert_type")),
            "change_7d":         coin.get("change_7d", 0.0),
            # P1 / B4.1: slippage info for analytics
            "entry_slippage_pct": round(_slip_pct, 4),
            "entry_session":      _sess(),
            "lower_confidence_probability": lower_p,
            "kelly_fraction":     round(kelly_fraction, 5) if kelly_fraction is not None else None,
            "lane_risk_multiplier": lane_multiplier,
            "shadow_model_version": coin.get("shadow_model_version"),
            "shadow_probability": coin.get("shadow_probability"),
            "feature_schema_version": "spot_features_v1",
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
            # PLAN_v5 Group C: pull DB overrides once per cycle (see scanner.py
            # run_opportunity_scan for the full rationale on `global` here).
            global MAX_OPENS_PER_CYCLE, MAX_BIGMOVER_OPENS, DAILY_LOSS_LIMIT_FRACTION
            try:
                from agents.shared.config_reader import cfg
                MAX_OPENS_PER_CYCLE = int(await cfg.get("spot", "max_opens_per_cycle", MAX_OPENS_PER_CYCLE))
                MAX_BIGMOVER_OPENS  = int(await cfg.get("spot", "max_bigmover_opens", MAX_BIGMOVER_OPENS))
                DAILY_LOSS_LIMIT_FRACTION = await cfg.get(
                    "spot", "daily_loss_limit_pct", DAILY_LOSS_LIMIT_FRACTION * 100
                ) / 100
            except Exception as exc:
                logger.warning("agent_config_pull_failed", scope="spot_scheduler", error=str(exc)[:120])

            opp_store.set_scanning(True)
            result = await opp_scanner.run_opportunity_scan()
            try:
                from agents.learning.spot_adaptive_model import score_shadow_candidates
                await score_shadow_candidates(result)
            except Exception as exc:
                logger.warning("spot_shadow_scoring_failed", error=str(exc)[:120])
            opp_store.set_result({key: value for key, value in result.items() if not key.startswith("_")})
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
            opened_symbols: set[str] = set()
            # Phase 3 G3-regime: REDUCED → throttle quota to 1 open/cycle
            regime_status = result.get("regime_status", "OPEN")
            cycle_quota = (
                MAX_OPENS_PER_CYCLE_REDUCED
                if regime_status == "REDUCED"
                else MAX_OPENS_PER_CYCLE
            )
            if regime_status == "REDUCED":
                logger.info("auto_open_quota_reduced",
                            quota=cycle_quota, candidates=len(auto_candidates))

            # B-Fix 7: sisa jatah entri hari ini (WIB) — batas churn harian.
            opens_today   = await _auto_opens_today() if auto_candidates else 0
            daily_room    = MAX_AUTO_OPENS_PER_DAY - opens_today
            if auto_candidates and daily_room <= 0:
                logger.info("auto_open_paused_daily_cap",
                            opens_today=opens_today,
                            cap=MAX_AUTO_OPENS_PER_DAY,
                            skipped=len(auto_candidates))
            elif auto_candidates and await _daily_loss_breaker_active():
                logger.info("auto_open_paused_daily_breaker",
                            skipped=len(auto_candidates))
            else:
                cycle_quota = min(cycle_quota, max(0, daily_room))
                bm_open_now = await _bigmover_open_count()
                er_open_now = await _early_radar_open_count()

                # PLAN_SPOT_LANES S5 — kuota PENJAMIN, bukan pembatas.
                # Sebelumnya kandidat diurut global by EV lalu dipotong 3; lane
                # Accumulation (skor 99) menyerap semua slot, sehingga lane kecil
                # tak pernah mengumpulkan sampel untuk membuktikan dirinya —
                # lingkaran tertutup. Kalau ada kandidat non-accumulation yang
                # layak, sisakan slot untuk mereka di lintasan pertama.
                lanes_waiting = {lane_of({}, c.get("alert_type")) for c in auto_candidates}
                reserve = (
                    min(RESERVED_SLOTS_NON_ACCUM, max(0, cycle_quota - 1))
                    if any(l != "accumulation" for l in lanes_waiting) else 0
                )
                accum_cap = cycle_quota - reserve
                if reserve:
                    logger.info("auto_open_lane_reserve",
                                reserve=reserve, accum_cap=accum_cap,
                                lanes=sorted(lanes_waiting))

                async def _try_open(coin: dict) -> bool:
                    """Buka satu kandidat bila semua kuota lane mengizinkan."""
                    nonlocal opened, bm_open_now, er_open_now
                    global _auto_opened
                    # Phase 2 BM3: separate quota for bigmover_chase
                    is_bm = coin.get("entry_mode") == "bigmover_chase"
                    if is_bm and bm_open_now >= MAX_BIGMOVER_OPENS:
                        return False
                    # PLAN_v5 Group A: separate quota for early_radar
                    is_er = coin.get("entry_mode") == "early_radar"
                    if is_er and er_open_now >= opp_scanner.EARLY_RADAR_MAX_OPEN:
                        return False
                    if not await _auto_open_position(coin):
                        return False
                    opened += 1
                    opened_symbols.add(str(coin.get("symbol") or ""))
                    _auto_opened += 1
                    if is_bm:
                        bm_open_now += 1
                    if is_er:
                        er_open_now += 1
                    return True

                # Lintasan 1 — hormati slot cadangan.
                accum_opened = 0
                taken: set[int] = set()
                for idx, coin in enumerate(auto_candidates):
                    if opened >= cycle_quota:
                        break
                    is_accum = lane_of({}, coin.get("alert_type")) == "accumulation"
                    if is_accum and accum_opened >= accum_cap:
                        continue
                    if await _try_open(coin):
                        taken.add(idx)
                        if is_accum:
                            accum_opened += 1

                # Lintasan 2 — slot cadangan yang tak terpakai jangan hangus:
                # isi dengan kandidat terbaik yang tersisa, tanpa batas lane.
                if opened < cycle_quota and reserve:
                    for idx, coin in enumerate(auto_candidates):
                        if opened >= cycle_quota:
                            break
                        if idx in taken:
                            continue
                        await _try_open(coin)

            # F1: persist point-in-time evidence for opened and non-opened
            # candidates. Ledger failure is observable but never blocks trading.
            try:
                from agents.opportunity.decision_ledger import log_scan_decisions
                await log_scan_decisions(result, opened_symbols)
            except Exception as exc:
                logger.warning("spot_decision_ledger_failed", error=str(exc)[:120])

            logger.info(
                "opportunity_cycle_done",
                cycle=_cycle_count,
                found=result.get("found", 0),
                auto_opened=opened,
            )

            # SP2/SP3: refresh SPOT signal weights + cross-agent blend after each scan.
            # MIN_RUN_INTERVAL inside each updater guarantees no excessive DB work.
            try:
                from agents.opportunity.weight_updater import update_spot_weights
                from agents.shared.cross_agent_learning import update_cross_agent_weights
                from agents.opportunity.outcome_tracker import update_decision_outcomes
                from agents.opportunity.decision_ledger import backfill_closed_spot_trades
                await update_spot_weights()
                await update_cross_agent_weights()
                await backfill_closed_spot_trades()
                outcomes_updated = await update_decision_outcomes()
                if outcomes_updated:
                    from agents.learning.spot_adaptive_model import train_and_register, monitor_champion_drift
                    training = await train_and_register()
                    if training.get("status") == "registered":
                        logger.info("spot_challenger_registered", version=training.get("version"))
                    drift = await monitor_champion_drift()
                    if drift.get("status") == "rolled_back":
                        logger.warning("spot_model_auto_rollback", **drift)
            except Exception as exc:
                logger.warning("post_scan_learning_error", error=str(exc)[:80])

        except asyncio.CancelledError:
            opp_store.set_scanning(False)
            logger.info("opportunity_agent_stopped")
            _running = False
            raise
        except Exception as exc:
            opp_store.set_scanning(False)
            # str(exc) bisa KOSONG untuk sejumlah exception (mis. httpx/asyncio
            # tanpa message) → error="" tak bisa didiagnosis. Fallback ke repr +
            # simpan tipe supaya penyebab selalu terbaca (Fase 4 verifikasi).
            _last_error = (str(exc) or repr(exc))[:160]
            logger.error("opportunity_agent_error", error=_last_error,
                         exc_type=type(exc).__name__)

        elapsed   = time.time() - (_last_scan_ts or time.time())
        sleep_for = max(60, INTERVAL_SEC - elapsed)
        await asyncio.sleep(sleep_for)


# ── PLAN-BIG-MOVERS Phase 2 BM3 / G13: SPOT bigmover fastpass (60s cadence) ──

_fastpass_running    = False
_fastpass_cycle      = 0
_fastpass_last_ts:   Optional[float] = None
_fastpass_last_error: Optional[str] = None
_fastpass_opened     = 0


def get_fastpass_state() -> dict:
    next_in = None
    if _fastpass_last_ts is not None:
        next_in = max(0, BIGMOVER_FASTPASS_SEC - (time.time() - _fastpass_last_ts))
    return {
        "running":      _fastpass_running,
        "cycle_count":  _fastpass_cycle,
        "last_scan_ts": _fastpass_last_ts,
        "last_error":   _fastpass_last_error,
        "interval_sec": BIGMOVER_FASTPASS_SEC,
        "next_in_sec":  round(next_in, 1) if next_in is not None else None,
        "auto_opened":  _fastpass_opened,
    }


async def _fetch_big_mover_subset() -> list[dict]:
    """Pull only USDT spot tickers with |change_24h| ≥ 15% AND vol ≥ $1M."""
    import httpx
    from app.services.binance_urls import spot as _spot

    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(_spot("/api/v3/ticker/24hr"))
        if r.status_code != 200:
            return []
        all_tickers = r.json() if isinstance(r.json(), list) else []

    out = []
    for t in all_tickers:
        sym = t.get("symbol", "")
        if not sym.endswith("USDT"):
            continue
        try:
            chg = float(t.get("priceChangePercent", 0))
            vol = float(t.get("quoteVolume", 0))
        except (TypeError, ValueError):
            continue
        if abs(chg) >= BIGMOVER_FASTPASS_MIN_PCT and vol >= opp_scanner.BIGMOVER_MIN_VOLUME:
            out.append(t)
    return out


async def _run_fastpass_cycle() -> int:
    """
    Fetch big-mover subset, score only bigmover_chase, auto-open if eligible.
    B2.4 dedup: relies on DB unique index (style,symbol,open) — if main scan or
    previous fastpass already opened, INSERT fails and we skip.
    Returns number of positions opened this cycle.
    """
    import httpx

    subset = await _fetch_big_mover_subset()
    if not subset:
        return 0

    bm_open_now = await _bigmover_open_count()
    if bm_open_now >= MAX_BIGMOVER_OPENS:
        return 0   # quota already full

    # B-Fix 7: fastpass ikut memakai jatah entri harian yang sama — kalau tidak,
    # lane dengan cadence 30 detik ini bisa melewati batas churn lewat pintu belakang.
    if await _auto_opens_today() >= MAX_AUTO_OPENS_PER_DAY:
        logger.info("fastpass_paused_daily_cap", cap=MAX_AUTO_OPENS_PER_DAY)
        return 0

    # B-Fix 7: fastpass juga TIDAK pernah memeriksa circuit breaker harian —
    # di hari rugi, loop 30 detik ini tetap membuka posisi sementara loop utama
    # sudah dijeda. Lubang itu ditutup di sini.
    if await _daily_loss_breaker_active():
        logger.info("fastpass_paused_daily_breaker")
        return 0

    # Sort by abs(change_24h) desc — strongest movers first
    subset.sort(key=lambda t: abs(float(t.get("priceChangePercent", 0))), reverse=True)
    subset = subset[:20]   # cap fetch volume

    # Fetch klines for these
    _sem = asyncio.Semaphore(8)
    async def _fetch_one(client: httpx.AsyncClient, sym: str, tf: str) -> tuple[str, str, list]:
        async with _sem:
            return sym, tf, await opp_scanner._fetch_klines(client, sym, tf)

    klines_map: dict[tuple, list] = {}
    async with httpx.AsyncClient(timeout=20) as client:
        tasks = [
            asyncio.create_task(_fetch_one(client, t["symbol"], tf))
            for t in subset for tf in opp_scanner.TIMEFRAMES
        ]
        for task in tasks:
            sym, tf, kl = await task
            klines_map[(sym, tf)] = kl

    opened_now = 0
    for ticker in subset:
        if bm_open_now + opened_now >= MAX_BIGMOVER_OPENS:
            break
        symbol     = ticker["symbol"]
        change_24h = float(ticker.get("priceChangePercent", 0))
        if change_24h < opp_scanner.BIGMOVER_MIN_CHANGE_24H:
            continue   # SHORT extreme losers not supported (spot LONG-only)

        tf_data: dict = {}
        for tf in opp_scanner.TIMEFRAMES:
            d = opp_scanner._analyze_tf(tf, klines_map.get((symbol, tf), []))
            if d:
                tf_data[tf] = d
        if not tf_data:
            continue

        d1h = tf_data.get("1h")
        change_1h = 0.0
        if d1h and len(d1h.closes) >= 2 and d1h.closes[-2] > 0:
            change_1h = (d1h.closes[-1] - d1h.closes[-2]) / d1h.closes[-2] * 100

        d4h = tf_data.get("4h")
        change_7d = 0.0
        if d4h and len(d4h.closes) >= 42 and d4h.closes[-42] > 0:
            change_7d = (d4h.closes[-1] - d4h.closes[-42]) / d4h.closes[-42] * 100

        res = opp_scanner._score_bigmover_chase(
            symbol, tf_data, change_24h, change_1h, change_7d
        )
        if res is None:
            continue
        levels = opp_scanner._calc_trade_levels_bigmover(
            klines_map.get((symbol, "15m"), []), res["current_price"], change_24h
        )
        if levels is None:
            continue
        res.update(levels)

        if not res.get("auto_open"):
            continue
        if await _auto_open_position(res):
            opened_now += 1

    return opened_now


async def run_bigmover_fastpass() -> None:
    """G13 — SPOT real-time second-pass loop (60s cadence) for big movers."""
    global _fastpass_running, _fastpass_cycle, _fastpass_last_ts, _fastpass_last_error, _fastpass_opened
    _fastpass_running = True
    logger.info("bigmover_fastpass_started", interval_sec=BIGMOVER_FASTPASS_SEC)
    await asyncio.sleep(STARTUP_DELAY + 30)   # let main scan settle first

    while True:
        try:
            opened = await _run_fastpass_cycle()
            _fastpass_cycle += 1
            _fastpass_last_ts = time.time()
            _fastpass_last_error = None
            if opened:
                _fastpass_opened += opened
                logger.info("bigmover_fastpass_opened", cycle=_fastpass_cycle, opened=opened)
        except asyncio.CancelledError:
            _fastpass_running = False
            logger.info("bigmover_fastpass_stopped")
            raise
        except Exception as exc:
            _fastpass_last_error = str(exc)[:120]
            _fastpass_running = False
            logger.warning("bigmover_fastpass_error", error=_fastpass_last_error)

        await asyncio.sleep(BIGMOVER_FASTPASS_SEC)
