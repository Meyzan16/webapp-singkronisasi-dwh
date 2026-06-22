"""
Futures Eligibility — Phase 1 T3.

GET /api/v1/futures/eligibility/{symbol}
  → "kenapa coin ini tidak masuk posisi futures?"

Per-symbol verdict ditelusuri end-to-end:
  - futures_perpetual: ada listing USDT PERPETUAL atau tidak (B1.3 cached 30s)
  - in_universe: di-scan oleh scheduler ini cycle atau tidak
  - scoring_max_achievable: max realistic score Agent 3 LONG/SHORT given current data
  - scoring_threshold: adaptive auto_threshold sekarang
  - regime_gate: open / closed / reduced
  - cooldown_until: blacklist timestamp (3-consec SL)
  - funding_rate: current funding (extreme = bayar mahal)
  - actionable_reason: alasan utama tidak open posisi
"""

import time
from typing import Optional

import httpx
import structlog
from fastapi import APIRouter, HTTPException

from app.services.binance_urls import fapi

router = APIRouter(tags=["futures-eligibility"])
logger = structlog.get_logger(__name__)

# B1.3: cache result per-symbol 30s
_PERPETUAL_CACHE: dict[str, bool] = {}
_PERPETUAL_CACHE_TS: float = 0.0
_PERPETUAL_TTL = 60 * 30  # 30 min — exchangeInfo barely changes

_VERDICT_CACHE: dict[str, tuple[float, dict]] = {}
_VERDICT_TTL = 30  # seconds


async def _refresh_perpetual_set() -> set[str]:
    """Fetch full set of USDT PERPETUAL TRADING symbols."""
    global _PERPETUAL_CACHE, _PERPETUAL_CACHE_TS
    now = time.time()
    if _PERPETUAL_CACHE and (now - _PERPETUAL_CACHE_TS) < _PERPETUAL_TTL:
        return {s for s, ok in _PERPETUAL_CACHE.items() if ok}

    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(fapi("/fapi/v1/exchangeInfo"))
        if r.status_code != 200:
            return set()
        data = r.json()

    fresh: dict[str, bool] = {}
    for sym in data.get("symbols", []):
        if (sym.get("contractType") == "PERPETUAL"
                and sym.get("quoteAsset") == "USDT"
                and sym.get("status") == "TRADING"):
            fresh[sym["symbol"]] = True
    _PERPETUAL_CACHE = fresh
    _PERPETUAL_CACHE_TS = now
    return set(fresh.keys())


def _max_achievable_a3(direction: str, change_24h: float) -> tuple[float, str]:
    """
    Simulate Agent 3 max-realistic score given change_24h.
    Returns (max_score, label) — label explains the breakpoint.

    Mirrors logic in agents/futures/agent3.py with PERFECT signals assumption:
      vol +25, OI +15, funding +12, RSI bracket (best case for actual %), breakout +13,
      liq nudge +3, regime trending +8.

    Penalty schedule matches agent3.py (non-stacking).
    """
    abs_chg = abs(change_24h)

    # Sweet-spot bracket — must align with direction (LONG: positive change, SHORT: negative)
    direction_aligned = (change_24h > 0 and direction == "LONG") or (change_24h < 0 and direction == "SHORT")
    if not direction_aligned:
        return 0.0, "Direction salah arah dari change_24h"

    if 8 <= abs_chg <= 12:
        bracket = 20
    elif 5 <= abs_chg < 8:
        bracket = 12
    elif 12 < abs_chg <= 18:
        bracket = 15
    elif 18 < abs_chg <= 25:
        bracket = 8
    elif 25 < abs_chg <= 35:
        bracket = 5
    elif 35 < abs_chg <= 50:
        bracket = 2
    else:
        bracket = 0   # > 50% atau < 5%

    # Penalty (non-stacking, mirror agent3 line 289-296 / 464-471)
    if abs_chg < 5.0:
        penalty = -15
    elif abs_chg > 50.0:
        penalty = -20
    elif abs_chg > 35.0:
        penalty = -8
    elif abs_chg > 25.0:
        penalty = -5
    else:
        penalty = 0

    # Best-case signals (assume RSI di sweet zone 58-70 LONG / 30-42 SHORT)
    vol      = 25
    oi       = 15
    funding  = 12
    rsi      = 15
    breakout = 13
    liq      = 3
    regime   = 8   # trending_up + LONG OR trending_down + SHORT

    max_score = bracket + vol + oi + funding + rsi + breakout + liq + regime + penalty

    if abs_chg > 50:
        label = f"Parabolic >{50}% — bracket sweet-spot 0pt, penalty −20"
    elif abs_chg > 35:
        label = f"Extended {35}-{50}% — bracket +2, penalty −8"
    elif abs_chg > 25:
        label = f"Extended {25}-{35}% — bracket +5, penalty −5"
    else:
        label = "Dalam jangkauan scoring normal"
    return round(max_score, 1), label


async def _fetch_symbol_market(symbol: str) -> Optional[dict]:
    """Get current change_24h, last price, funding rate from Binance."""
    out: dict = {"symbol": symbol}
    async with httpx.AsyncClient(timeout=8) as c:
        try:
            r = await c.get(fapi("/fapi/v1/ticker/24hr"), params={"symbol": symbol})
            if r.status_code == 200:
                d = r.json()
                out["change_24h"] = float(d.get("priceChangePercent", 0))
                out["last_price"] = float(d.get("lastPrice", 0))
                out["quote_vol"]  = float(d.get("quoteVolume", 0))
        except Exception:
            pass
        try:
            pr = await c.get(fapi("/fapi/v1/premiumIndex"), params={"symbol": symbol})
            if pr.status_code == 200:
                pd = pr.json()
                out["funding_rate"] = float(pd.get("lastFundingRate", 0)) * 100   # to %
        except Exception:
            pass
    return out if "change_24h" in out else None


@router.get("/futures/eligibility/{symbol}")
async def get_eligibility(symbol: str) -> dict:
    """
    Per-coin eligibility verdict — kenapa coin ini tidak masuk posisi futures sekarang.
    B1.3: response di-cache 30s per symbol untuk hindari spam.
    """
    sym = symbol.upper().strip()
    if not sym:
        raise HTTPException(status_code=400, detail="symbol required")

    now = time.time()
    cached = _VERDICT_CACHE.get(sym)
    if cached and (now - cached[0]) < _VERDICT_TTL:
        return cached[1]

    # 1) Futures perpetual listing
    perpetual_set = await _refresh_perpetual_set()
    has_perp = sym in perpetual_set

    if not has_perp:
        verdict = {
            "symbol":                sym,
            "futures_perpetual":     False,
            "in_universe":           False,
            "scoring_max_achievable": None,
            "scoring_threshold":     None,
            "scoring_gap":           None,
            "regime_gate":           "n/a",
            "cooldown_until":        None,
            "funding_rate":          None,
            "change_24h":            None,
            "actionable_reason":     "Tidak ada futures perpetual USDT — TIDAK ADA jalur trade futures untuk koin ini",
            "decided_at":            int(now),
        }
        _VERDICT_CACHE[sym] = (now, verdict)
        return verdict

    # 2) Current market data
    market = await _fetch_symbol_market(sym)
    change_24h = market.get("change_24h") if market else None
    funding    = market.get("funding_rate") if market else None

    # 3) In-universe check via scanner store
    from agents.futures import store as fs
    in_universe = False
    matched_score: Optional[float] = None
    for agent_key in ("agent1", "agent2", "agent3"):
        res = fs.get_result(agent_key) or {}
        for r in res.get("results", []):
            if r.get("symbol") == sym:
                in_universe = True
                if matched_score is None or r.get("score", 0) > matched_score:
                    matched_score = r.get("score")
                break

    # Big-movers cache also tells us if symbol was scanned even if it didn't make top results
    if not in_universe:
        for m in fs.get_big_movers():
            if m.get("symbol") == sym:
                in_universe = True
                break

    # 4) Scoring math impossibility for both directions
    long_max,  long_label  = _max_achievable_a3("LONG",  change_24h) if change_24h is not None else (None, "no data")
    short_max, short_label = _max_achievable_a3("SHORT", change_24h) if change_24h is not None else (None, "no data")
    max_score = max(long_max or 0, short_max or 0)

    # 5) Threshold (Agent 3 adaptive)
    from agents.futures import weight_updater
    thr = weight_updater.get_adaptive_thresholds("futures_agent3")
    auto_threshold = thr.get("auto_threshold", 72)

    scoring_gap = round(max_score - auto_threshold, 1) if change_24h is not None else None

    # 6) Cooldown / blacklist
    cooldown_until: Optional[float] = None
    if weight_updater.is_blacklisted(sym):
        cooldown_until = weight_updater._coin_blacklist.get(sym)

    # 7) Regime gate
    from agents.futures.risk_gate import is_gate_open
    gate_open, gate_reason = is_gate_open()
    regime_gate = "open" if gate_open else f"closed: {gate_reason}"

    # 8) Build actionable reason — first failing check wins
    reasons: list[str] = []
    if not gate_open:
        reasons.append(f"Risk gate aktif ({gate_reason})")
    if cooldown_until is not None:
        secs_left = int(cooldown_until - now)
        if secs_left > 0:
            reasons.append(f"Blacklist 3-consec-SL · {secs_left // 60} menit lagi")
    if change_24h is not None and scoring_gap is not None and scoring_gap < 0:
        reasons.append(
            f"Scoring impossible: max {max_score:.0f} vs threshold {auto_threshold} (gap {scoring_gap:+.0f}) · {long_label}"
        )
    if funding is not None:
        if change_24h is not None and change_24h > 0 and funding > 0.12:
            reasons.append(f"Funding extreme +{funding:.3f}% — LONG bayar mahal (hard gate Phase 3)")
        if change_24h is not None and change_24h < 0 and funding < -0.12:
            reasons.append(f"Funding extreme {funding:.3f}% — SHORT bayar mahal (hard gate Phase 3)")
    if not in_universe and change_24h is not None and abs(change_24h) < 10:
        reasons.append(f"Tidak di-universe scanner (|change_24h| {change_24h:+.1f}% < 10% big-mover threshold)")

    if not reasons:
        actionable = "Eligible — auto-trader belum trigger entry, kemungkinan sinyal real belum cukup tinggi"
    else:
        actionable = " · ".join(reasons)

    verdict = {
        "symbol":                 sym,
        "futures_perpetual":      True,
        "in_universe":            in_universe,
        "matched_score":          matched_score,
        "scoring_max_achievable": round(max_score, 1) if change_24h is not None else None,
        "scoring_max_long":       long_max,
        "scoring_max_short":      short_max,
        "scoring_threshold":      auto_threshold,
        "scoring_gap":            scoring_gap,
        "scoring_label":          long_label if (long_max or 0) >= (short_max or 0) else short_label,
        "regime_gate":            regime_gate,
        "cooldown_until":         cooldown_until,
        "funding_rate":           round(funding, 4) if funding is not None else None,
        "change_24h":             round(change_24h, 2) if change_24h is not None else None,
        "actionable_reason":      actionable,
        "decided_at":             int(now),
    }
    _VERDICT_CACHE[sym] = (now, verdict)
    return verdict
