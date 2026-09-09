"""
Shared TA math helpers for the futures agents.

F112: `_ema` and `_atr` were duplicated identically in agent1.py and regime.py.
Both now import from here so a formula change happens in one place only.

PLAN_v2 P1.2/P1.3: leverage sizing safety constants — single source of truth so
agent + monitor + risk_gate all reason about the same caps.
"""


# ── PLAN_v2 P1.3 — per-lane max margin loss at SL hit ─────────────────────────
# Tighter caps for lanes that hold longer (more black-swan window).
MAX_SL_MARGIN_PCT_BY_LANE: dict[str, float] = {
    "accumulation":  15.0,
    "pre_gainer":    18.0,
    "pre_move":      18.0,    # legacy alias
    "momentum":      25.0,
    "bigmover":      20.0,
}
DEFAULT_LANE_CAP = 25.0


# ── PLAN_v2 P1.2 — liquidation-safe sizing multiplier ─────────────────────────
# liq_dist_pct ≈ 95 / leverage (1% MMR). Require liq_dist ≥ SL_dist × SAFETY_MULT
# so a wick to SL never lands the trade inside liquidation territory.
LIQ_SAFETY_MULT = 2.0


# ── PLAN_v6 P1a — HARD leverage ceiling per lane ──────────────────────────────
# BUG-fix: the margin-based cap alone allowed e.g. accumulation 10× (15% / 1.5% SL),
# far too high for a slow "hold" lane — one of those SL'd at −16% margin. This is an
# ABSOLUTE ceiling applied on top of the margin/liq caps: leverage never exceeds this
# regardless of how tight the SL is.
MAX_LEVERAGE_BY_LANE: dict[str, int] = {
    "accumulation":  5,
    "pre_gainer":    5,
    "pre_move":      5,    # legacy alias
    "momentum":      6,
    "bigmover":      3,
}
DEFAULT_MAX_LEVERAGE = 6

# ── PLAN_v6 P1b — extended-entry leverage cut ─────────────────────────────────
# Entry into an already-extended move (high |change_24h|) carries higher reversal
# risk, so halve leverage there — smaller margin loss when the late entry reverses.
EXTENDED_CHANGE_24H_PCT = 15.0


def cap_leverage_by_lane(
    base_lev: int,
    risk_pct: float,
    lane: str = "momentum",
    change_24h: float = 0.0,
) -> int:
    """
    Apply caps to a base leverage choice, smallest wins:
      1. Lane SL-margin cap   → L ≤ MAX_SL_MARGIN_PCT_LANE / risk_pct
      2. Liquidation safety   → L ≤ (95 / SAFETY_MULT) / risk_pct  = 47.5 / risk_pct
      3. PLAN_v6 P1a hard ceiling → L ≤ MAX_LEVERAGE_BY_LANE[lane]  (absolute)
      4. PLAN_v6 P1b → halve when entering an already-extended move (|change_24h| high)
    """
    # Fase 1a: angka-angka di bawah datang dari `sizing_config` (dapat ditala
    # lewat agent_config tanpa deploy). Konstanta modul di atas TETAP ada sebagai
    # cadangan beku — dipakai persis saat DB tak terbaca, sehingga nilainya
    # identik dengan perilaku sebelum fase ini.
    #
    # Kenapa lewat modul sendiri, bukan membaca dict `MAX_SL_MARGIN_PCT_BY_LANE`
    # yang dimutasi monitor: plafon leverage milik SCANNER tak boleh bergantung
    # pada loop MONITOR yang kebetulan sudah jalan. Sampai 5 Sep 2026 memang
    # begitu — dan saat monitor belum menyelesaikan siklus pertamanya, scanner
    # diam-diam memakai angka hardcode sementara UI menampilkan angka lain.
    from agents.futures import sizing_config as szcfg

    hard_cap = szcfg.lev_max_for_lane(lane)

    if not risk_pct or risk_pct <= 0:
        lev = min(int(base_lev), hard_cap)
    else:
        lane_cap = MAX_SL_MARGIN_PCT_BY_LANE.get(lane, szcfg.get("lev_lane_cap_default"))
        sl_cap   = max(1, int(lane_cap / risk_pct))
        # liq_dist_pct ≈ 95 / leverage; syaratnya liq_dist ≥ SL_dist × safety
        liq_cap  = max(1, int(95.0 / szcfg.get("lev_liq_safety_mult") / risk_pct))
        lev      = min(int(base_lev), sl_cap, liq_cap, hard_cap)

    # P1b: extended-entry → halve (late entry = higher reversal risk)
    if abs(change_24h) >= szcfg.get("lev_extended_change_24h_pct"):
        lev = lev // 2

    return max(1, lev)


# ── PLAN_v2 P1.1 / P1.5 — per-lane max margin loss (live-monitor gate) ────────
# Stricter than the entry sizing caps because slippage past SL or regime-widened
# SL can blow through the static sizing assumption.
MAX_LOSS_PCT_OF_MARGIN_BY_LANE: dict[str, float] = {
    "accumulation":  35.0,
    "pre_gainer":    30.0,
    "pre_move":      30.0,    # legacy alias
    "momentum":      50.0,
    "bigmover":      40.0,
}
DEFAULT_MAX_LOSS_PCT = 50.0


# ── PLAN_v2 — agent style → lane mapping (used by monitor) ────────────────────
STYLE_TO_LANE: dict[str, str] = {
    "futures_agent1":          "pre_gainer",
    "futures_agent2":          "accumulation",
    "futures_agent3":          "momentum",
    "futures_agent_bigmover":  "bigmover",
}


def lane_for_style(style: str) -> str:
    return STYLE_TO_LANE.get(style, "momentum")


# ── PLAN_v6 P4b — momentum health check ───────────────────────────────────────
# Replaces BLIND change_24h penalties: a +30% coin with new money flowing in (OI up),
# sane funding, and strong volume is a VALID momentum signal — not something to punish.
# Only punish when the move shows exhaustion evidence. This is half of fixing the
# anti-momentum paradox (agents systematically rejected every real top gainer).
HEALTH_OI_STRONG_PCT     = 1.0    # OI up ≥ 1%/1h  = new money agrees with the move
HEALTH_OI_EXHAUSTED_PCT  = -1.0   # OI down ≥ 1%/1h = hollow move (covering/capitulation)
HEALTH_FUNDING_EXTREME   = 0.15   # |funding| beyond this in entry direction = crowded
HEALTH_VOL_FADING_RATIO  = 0.7    # last-candle volume < 0.7× avg = interest fading
HEALTH_VOL_STRONG_RATIO  = 1.0


def momentum_health(tf_map, direction: str) -> str:
    """
    PLAN_v6 P4b — classify an in-progress move as "healthy" | "neutral" | "exhausted"
    from live on-chain + volume evidence (1h preferred, 15m fallback).

    healthy   → OI rising, funding not crowded, volume holding → momentum is REAL.
    exhausted → OI draining, or crowded funding in entry direction, or volume fading.
    neutral   → everything else (or missing data — never classify blind data as healthy).
    """
    ref = None
    if hasattr(tf_map, "get"):
        ref = tf_map.get("1h") or tf_map.get("15m")
    if ref is None:
        return "neutral"

    oi_chg  = getattr(ref, "oi_change_pct", 0.0) or 0.0
    fr_pct  = (getattr(ref, "funding_rate", 0.0) or 0.0) * 100
    is_long = direction == "LONG"

    vol_ratio = 1.0
    vols = getattr(ref, "volumes", None)
    if vols and len(vols) >= 21:
        avg = sum(vols[-21:-1]) / 20
        vol_ratio = vols[-1] / avg if avg > 0 else 1.0

    crowded = (is_long and fr_pct > HEALTH_FUNDING_EXTREME) or \
              (not is_long and fr_pct < -HEALTH_FUNDING_EXTREME)

    if oi_chg <= HEALTH_OI_EXHAUSTED_PCT or vol_ratio < HEALTH_VOL_FADING_RATIO or crowded:
        return "exhausted"
    if oi_chg >= HEALTH_OI_STRONG_PCT and vol_ratio >= HEALTH_VOL_STRONG_RATIO and not crowded:
        return "healthy"
    return "neutral"


def health_scaled_penalty(base_penalty: float, health: str, healthy_frac: float = 0.0) -> float:
    """
    PLAN_v6 P4b — scale a change_24h penalty by momentum health.
    healthy   → base × healthy_frac (0.0 for momentum lane, 0.5 for pre-move lanes
                which keep their flat-coin identity but stop punishing blindly)
    neutral   → base × 0.5
    exhausted → full penalty (the situation the penalty was actually written for)
    """
    if health == "healthy":
        return base_penalty * healthy_frac
    if health == "neutral":
        return base_penalty * 0.5
    return base_penalty


# ── PLAN_v6 P3 — entry timing gate (anti-exhaustion) ──────────────────────────
# Root cause of the all-SL pattern: composite score is a SNAPSHOT — it says the
# setup is good, but nothing checked the ENTRY CANDLE itself. All 3 SL'd momentum
# trades had pnl ≈ −sl_dist (zero favorable excursion) = entered at the local top.
# This gate rejects entries at exhaustion points regardless of how high the score is.
EXHAUSTION_WICK_ATR_MULT   = 2.0    # 15m candle range > 2×ATR = climax candle
EXHAUSTION_CLOSE_FRAC      = 0.30   # close in the 30% adverse end of that candle
CHASE_MATURE_CHANGE_24H    = 15.0   # |change_24h| ≥ this = mature move → pullback required
CHASE_HARD_CHANGE_1H       = 3.0    # still running > 3%/1h in entry direction = chasing
OI_CONFIRM_ADVERSE_PCT     = 1.0    # momentum only: OI moving >1% AGAINST the entry = hollow move


def entry_timing_ok(
    tf_map,
    direction:  str,
    change_24h: float,
    require_oi_confirm: bool = False,
) -> tuple[bool, str]:
    """
    PLAN_v6 P3a/P3b — candle-level timing gate, run AFTER scoring passes.
    Returns (ok, reason). Fail-open on missing data: a data gap must not silently
    disable an agent, so only reject on POSITIVE evidence of bad timing.

    Checks:
      1. Exhaustion wick  — last 15m candle range > 2×ATR AND close in the 30%
         adverse extreme (price already rejected) → entering into a climax reversal.
      2. Fresh-pullback   — move already mature (|change_24h| ≥ 15%): require a
         breather. Reject if 1h still running hard (>3% in entry direction) or the
         last 15m close IS the 3-candle extreme (literal edge, no pullback yet).
      3. OI live confirm  — momentum lanes only: price up but OI dropping >1% =
         short-covering rally (hollow); mirror for SHORT. New money must agree.
    """
    d15 = tf_map.get("15m") if hasattr(tf_map, "get") else None
    d1h = tf_map.get("1h")  if hasattr(tf_map, "get") else None
    is_long = direction == "LONG"

    # ── 1. Exhaustion wick on the entry candle (15m) ──────────────────────────
    if d15 is not None and len(d15.closes) >= 16 and len(d15.highs) >= 16:
        atr15 = _atr(d15.highs, d15.lows, d15.closes, 14)
        hi, lo, cl = d15.highs[-1], d15.lows[-1], d15.closes[-1]
        rng = hi - lo
        if atr15 > 0 and rng > EXHAUSTION_WICK_ATR_MULT * atr15:
            # Close position within the candle range (0 = low, 1 = high)
            pos = (cl - lo) / rng if rng > 0 else 0.5
            # Adverse extreme: LONG entering while close sank to the bottom 30%
            # of a climax candle (spike already rejected); SHORT mirror at top.
            if (is_long and pos <= EXHAUSTION_CLOSE_FRAC) or \
               (not is_long and pos >= 1.0 - EXHAUSTION_CLOSE_FRAC):
                return False, "exhaustion_wick"

    # ── 2. Fresh-pullback requirement for mature moves ────────────────────────
    move_aligned = (change_24h if is_long else -change_24h)
    if move_aligned >= CHASE_MATURE_CHANGE_24H:
        change_1h = 0.0
        if d1h is not None and len(d1h.closes) >= 2 and d1h.closes[-2] > 0:
            change_1h = (d1h.closes[-1] - d1h.closes[-2]) / d1h.closes[-2] * 100
        run_1h = change_1h if is_long else -change_1h
        if run_1h > CHASE_HARD_CHANGE_1H:
            return False, "chasing_hard"          # still sprinting — wait for a breather
        if d15 is not None and len(d15.closes) >= 3:
            if is_long and d15.closes[-1] >= max(d15.highs[-3:]) * 0.999:
                return False, "no_pullback_top"   # buying the literal 3-candle high
            if not is_long and d15.closes[-1] <= min(d15.lows[-3:]) * 1.001:
                return False, "no_pullback_bottom"

    # ── 3. OI live confirmation (momentum lanes only) ─────────────────────────
    if require_oi_confirm:
        ref = d1h or d15
        oi_chg = getattr(ref, "oi_change_pct", 0.0) if ref is not None else 0.0
        if is_long and oi_chg < -OI_CONFIRM_ADVERSE_PCT:
            return False, "oi_falling_long"       # short-covering rally, no new money
        if not is_long and oi_chg > OI_CONFIRM_ADVERSE_PCT:
            return False, "oi_rising_short"       # fresh longs piling in against the short

    return True, "ok"


def _ema(values: list[float], period: int) -> float:
    """Exponential moving average of the last `period` values."""
    if len(values) < period:
        return values[-1] if values else 0.0
    k = 2 / (period + 1)
    e = sum(values[:period]) / period
    for v in values[period:]:
        e = v * k + e * (1 - k)
    return e


def _atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
    """Average True Range over the last `period` candles."""
    if len(closes) < 2:
        return 0.0
    trs = [
        max(highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]))
        for i in range(1, len(closes))
    ]
    tail = trs[-period:] if len(trs) >= period else trs
    return sum(tail) / len(tail) if tail else 0.0


# ── Helper harga & momentum ───────────────────────────────────────────────────
# Dipindah dari `agent1.py` saat Fase 8 membongkar lane lama. Keduanya dipakai
# agen tunggal, jadi membiarkannya di modul agen yang dihapus akan menyeret
# agen aktif ikut mati — sekaligus alasan kenapa `agent1.py` tak bisa sekadar
# dihapus tanpa langkah ini.

def _rsi(closes: list[float], period: int = 14) -> float:
    """RSI sederhana. Data kurang -> 50 (netral), bukan menebak."""
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(len(closes) - period, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains) / period
    al = sum(losses) / period
    return 100 - (100 / (1 + ag / al)) if al > 0 else 100.0


def _round_price(price: float, ref: float) -> float:
    """Bulatkan harga mengikuti besaran acuannya — koin $0,00001 dan $60.000
    tak bisa dibulatkan dengan jumlah desimal yang sama."""
    if ref >= 1000:  return round(price, 2)
    if ref >= 10:    return round(price, 4)
    if ref >= 0.1:   return round(price, 5)
    if ref >= 0.001: return round(price, 7)
    return round(price, 8)
