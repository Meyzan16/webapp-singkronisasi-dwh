"""
Signal Weight Updater — Adaptive Learning for futures agents.

SP2: Upgraded to match SPOT updater sophistication:
  - Training data: closed tp/sl/expired from last RECENCY_DAYS (30d)
  - Recency decay: each sample weighted by exp(-age / half_life), half_life 14d
    (futures trades run longer than SPOT — slower decay appropriate)
  - Laplace smoothing: win_rate_adj = (wins+1)/(total+2) — tiny samples stay neutral
  - Confidence scaling: weight influence grows proportionally to min(1, n/10)
  - Step cap: weight moves at most ±STEP_CAP per run (anti-oscillation)
  - Zombie pruning: keys absent from current data decay → neutral, deleted after 45d
  - avg_pnl_pct: tracks average realized PnL% of winning trades per signal

Also maintains in-memory caches used synchronously by agents:
  - _weight_cache:        {agent: {signal_key: weight}}
  - _adaptive_thresholds: {agent: {min_score, auto_threshold}}
  - _coin_blacklist:      {symbol: blacklist_until_ts}
  - _coin_win_rates:      {symbol: {wins, total}}
"""

import json
import re
import time
from collections import defaultdict
from typing import Optional

import structlog
from sqlalchemy import delete as sql_delete, select

from app.database import AsyncSessionLocal, is_db_available
from app.models.paper_trade import PaperTrade
from app.models.signal_weight import AgentSignalWeight
from app.models.signal_weight_history import SignalWeightHistory
# learning_policy murni (hanya re+typing) — tak ada risiko circular import.
from agents.shared.trade_outcome import is_win as _is_win
from agents.futures.learning_policy import (
    canonical_signal_key as _canonical_signal_key,
    signal_key as _namespaced_signal_key,
)

logger = structlog.get_logger(__name__)

_last_run:   Optional[float] = None
_last_error: Optional[str]   = None

# P7.1: rejection log queue — agents append here, scheduler flushes to DB
_rejection_queue: list[dict] = []
_REJECTION_QUEUE_MAX = 500   # cap to avoid unbounded growth if scheduler stalls


def log_rejection(
    symbol:       str,
    agent:        str,
    direction:    str,
    score:        float,
    threshold:    float,
    regime:       str = "all",
    weak_signals: list | None = None,
    reason:       str = "score_below_threshold",
) -> None:
    """P7.1: Queue a signal rejection for later DB flush. Synchronous — safe to call from scoring."""
    # PLAN_FUTURES H1.5: skor sangat rendah tidak informatif untuk kalibrasi —
    # logging semuanya membanjiri tabel ~75rb baris/hari. Reason lain (mis.
    # below_auto_threshold untuk near-miss R0d) tidak difilter.
    if reason == "score_below_threshold" and score < 40.0:
        return
    if len(_rejection_queue) >= _REJECTION_QUEUE_MAX:
        return
    import json as _json
    _rejection_queue.append({
        "symbol":        symbol,
        "agent":         agent,
        "direction":     direction,
        "score":         round(score, 2),
        "threshold":     round(threshold, 2),
        "regime":        regime,
        "reject_reason": reason,
        "weak_signals":  _json.dumps(weak_signals or [], ensure_ascii=False),
        "rejected_at":   time.time(),
    })


def flush_rejection_queue() -> list[dict]:
    """P7.1: Return and clear the rejection queue. Called by scheduler after each scan."""
    global _rejection_queue
    rows, _rejection_queue = _rejection_queue, []
    return rows

MIN_RUN_INTERVAL  = 5 * 60
RECENCY_DAYS      = 30
DECAY_HALF_LIFE_D = 14.0   # futures trades longer-lived → slower decay than SPOT (7d)
STEP_CAP          = 0.10   # max weight move per run
STALE_KEY_MAX_D   = 45     # zombie pruning threshold
MIN_SAMPLE_RAW    = 3      # raw trades required before weight moves from neutral

# PLAN_FUTURES "era data baru": reset + scanner overhaul item H (10 Jul 22:42 WIB).
# SEMUA kalibrasi berbasis skor (predictive/rejection) WAJIB filter ≥ epoch ini —
# skor sebelum itu dihasilkan sistem lama. (Keputusan terkunci SCHEDULE_FUTURES.md)
DATA_ERA_EPOCH = 1783698144.0

# PLAN_FUTURES item C (v4 P2.3): blend predictive → cache. Dihitung ulang tiap
# PRED_BLEND_TTL (parse JSON ribuan baris — jangan tiap cycle 2 menit).
PRED_BLEND_TTL_SEC = 15 * 60
PRED_MIN_N         = 20      # keputusan terkunci: gate sampel per sinyal
PRED_TRADE_FRAC    = 0.85    # keputusan terkunci: 0.85×trade + 0.15×predictive
_pred_blend_stats: dict[tuple, float] = {}   # {(agent, signal_key): pred_w}
_pred_blend_at:    float = 0.0

FUTURES_AGENTS = [
    "futures_agent1", "futures_agent2", "futures_agent3",
    "futures_agent_bigmover",   # Phase 2 BM1 — tracked but uses fixed threshold (no death spiral)
]

# ── In-memory caches (read synchronously by agents during scoring) ─────────────

_weight_cache:        dict[str, dict[str, float]]             = {}
_regime_weight_cache: dict[str, dict[str, dict[str, float]]] = {}  # {agent:{regime:{sig:w}}}
_adaptive_thresholds: dict[str, dict]                         = {}
_coin_blacklist:      dict[str, float]                        = {}   # symbol-level (direction-blind fallback)
_coin_blacklist_dir:  dict[tuple, float]                      = {}   # P4.8: {(symbol, direction): until_ts}
_coin_win_rates:      dict[str, dict]                         = {}   # symbol-level (direction-blind fallback)
_coin_win_rates_dir:  dict[tuple, dict]                       = {}   # P4.8: {(symbol, direction): {wins, total}}


# ── Public cache accessors ─────────────────────────────────────────────────────

def get_weight_cache(agent: str, regime: str = "all") -> dict[str, float]:
    """Return signal weight cache for agent, optionally filtered to a regime.

    Falls back to "all" for signals that have insufficient per-regime data.
    P3.5 (PLAN_v2): regime-conditional scoring — unused regime data was a known gap.
    """
    if regime == "all":
        return _weight_cache.get(agent, {})
    regime_map    = _regime_weight_cache.get(agent, {})
    regime_weights = regime_map.get(regime, {})
    all_weights   = _weight_cache.get(agent, {})
    if not regime_weights:
        return all_weights
    # Regime-specific overrides "all" for keys that have per-regime data
    return {**all_weights, **regime_weights}


def get_adaptive_thresholds(agent: str) -> dict:
    return _adaptive_thresholds.get(agent, {"min_score": 52, "auto_threshold": 72})


def is_blacklisted(symbol: str, direction: str = "") -> bool:
    """P4.8: directional blacklist — check (symbol, direction) first, fallback to symbol-only."""
    if direction and time.time() < _coin_blacklist_dir.get((symbol, direction), 0):
        return True
    return time.time() < _coin_blacklist.get(symbol, 0)


def normalize_signal_key(raw: str) -> str:
    """Kunci untuk MENCARI/MENYIMPAN bobot sebuah sinyal.

    Dipakai agent1/2/3/bigmover (`weight_cache.get(...)`), predictive blend, dan
    weekly_signal_review. Wajib mengikuti namespace yang sama dengan isi cache —
    kalau tidak, lookup selalu meleset dan bobot jadi 1.0 diam-diam (persis bug
    namespace 29 Jul). Karena itu ia mengikuti UNIFIED_SIGNAL_KEYS, bukan lagi
    mengembalikan kunci telanjang.
    """
    return _scoring_key(raw) if UNIFIED_SIGNAL_KEYS else _normalize_signal(raw)


def get_coin_bonus(symbol: str, direction: str = "") -> float:
    """P4.8: directional bonus/penalty — directional data takes priority over symbol-level."""
    # Prefer directional data if available
    if direction:
        dir_data = _coin_win_rates_dir.get((symbol, direction), {})
        if dir_data.get("total", 0) >= 3:
            wr = dir_data.get("wins", 0) / dir_data["total"]
            if wr >= 0.70:
                return 5.0
            if wr < 0.30:
                return -5.0
            return 0.0
    # Fall back to direction-blind data
    data  = _coin_win_rates.get(symbol, {})
    total = data.get("total", 0)
    if total < 3:
        return 0.0
    wr = data.get("wins", 0) / total
    if wr >= 0.70:
        return 5.0
    if wr < 0.30:
        return -5.0
    return 0.0


# ── Internal helpers ───────────────────────────────────────────────────────────

def _normalize_signal(raw: str) -> str:
    """
    Convert signal string to stable lookup key.
    Strips numbers (like SPOT updater) so "BB Squeeze 4H" == "BB Squeeze 1H"
    at the cross-agent level. Preserves signal semantics.
    """
    cleaned = re.sub(r"[^\w\s%+.\-]", "", raw)
    cleaned = re.sub(r"\d+\.?\d*", "N", cleaned)
    words   = cleaned.strip().split()[:4]
    return "_".join(w.lower() for w in words if w)


def _decay_factor(closed_at: Optional[float], now: float) -> float:
    if not closed_at:
        return 1.0
    age_days = max(0.0, (now - closed_at) / 86400)
    return 0.5 ** (age_days / DECAY_HALF_LIFE_D)


def _target_weight(win_rate_adj: float) -> float:
    if win_rate_adj >= 0.70: return 1.5
    if win_rate_adj >= 0.55: return 1.2
    if win_rate_adj >= 0.40: return 1.0
    return 0.7


# B1 (PLAN_ADAPTIVE_ENGINE_BOOST): target bobot berbasis EXPECTANCY, bukan win-rate.
# Default OFF → perilaku IDENTIK lama. Override DB: futures.expectancy_aware_weights.
# Alasan: strategi futures R:R 1:3 → win-rate rendah (9–17%) NORMAL & bisa profit,
# tapi _target_weight win-rate-murni mengunci semua bobot ≤1.0 (tak pernah reward
# sinyal profit) → adaptive_score ≈ raw → engine inert (shadow lift ~0). Saat ON,
# sinyal dgn expectancy realized positif dapat target >1.0 sehingga bobot menyimpang
# ke atas dan adaptive_score benar-benar bisa mengangkat ranking.
EXPECTANCY_AWARE_WEIGHTS = False

# BUGFIX zombie-pruning (29 Jul): 1 = bobot kunci canonical yang dikelola
# predictive_repair / weekly_signal_review TIDAK ditarik balik ke 1.0 tiap run,
# sehingga hasil repair benar-benar dipakai agent. 0 = perilaku lama (repair
# terhapus dalam 1 run). Override DB: futures.repair_weights_persist.
REPAIR_WEIGHTS_PERSIST = True

# BUGFIX namespace (29 Jul): bobot dari trade disimpan pakai _normalize_signal
# (kunci telanjang, mis. "wyckoff_markup_awal_masih") sementara SCORING membaca
# `canonical_signal_key(raw) or signal_key(raw)` (mis. "signal_id:wyckoff.markup"
# / "signal:..."). Kedua namespace TAK PERNAH beririsan → SELURUH bobot hasil
# belajar dari trade tak pernah dibaca saat scoring (factor selalu 1.0).
# 1 = simpan memakai kunci scoring (nyambung); 0 = perilaku lama. Bobot dihitung
# ulang dari trades tiap run, jadi peralihan tak kehilangan pembelajaran —
# statistik yang sama sekadar diberi label kunci yang benar.
# Override DB: futures.unified_signal_keys.
UNIFIED_SIGNAL_KEYS = True


def _scoring_key(raw: str) -> str:
    """Kunci bobot IDENTIK dengan `learning_keys()` di learning_policy.

    Inilah satu-satunya kunci yang dibaca `apply_learning_policy` saat menilai
    kandidat, sehingga bobot yang disimpan dengan kunci ini benar-benar terpakai.
    """
    return _canonical_signal_key(raw) or _namespaced_signal_key(raw)

# Prefix kunci yang TIDAK berasal dari statistik trade (namespace canonical
# scoring + lane). Sumber pengisinya: predictive_repair, weekly_signal_review.
_EXTERNAL_KEY_PREFIXES = ("signal_id:", "lane:")


def _is_externally_managed(signal_key: str) -> bool:
    """True bila bobot kunci ini diisi agen repair/review, bukan agregasi trade."""
    return str(signal_key or "").startswith(_EXTERNAL_KEY_PREFIXES)


def _target_weight_expectancy(exp_pct: float) -> float:
    """Target dari expectancy realized (rata-rata PnL% per trade, SEMUA trade).

    Simetris dgn _target_weight tapi sadar R:R: sinyal profit walau WR rendah tetap
    di-reward. Ambang konservatif — clamp akhir [0.70,1.50] + STEP_CAP tetap berlaku.
    """
    if exp_pct >=  1.0: return 1.5
    if exp_pct >=  0.3: return 1.2
    if exp_pct >= -0.3: return 1.0
    return 0.7


def _target_from_stats(v: dict, n_eff: float) -> float:
    """Target bobot dari stats satu sinyal. EXPECTANCY_AWARE_WEIGHTS ON → berbasis
    expectancy realized; OFF (default) → win-rate Laplace seperti semula."""
    if EXPECTANCY_AWARE_WEIGHTS:
        total = v.get("total", 0.0)
        exp_pct = (v.get("pnl_sum_all", 0.0) / total) if total > 0 else 0.0
        return _target_weight_expectancy(exp_pct)
    wr_adj = (v["wins"] + 1.0) / (n_eff + 2.0)
    return _target_weight(wr_adj)


def _update_coin_blacklist(trades: list) -> None:
    global _coin_blacklist_dir
    by_symbol: dict = defaultdict(list)
    for t in sorted(trades, key=lambda x: x.closed_at or x.entry_at or 0):
        by_symbol[t.symbol].append(t)

    for symbol, sym_trades in by_symbol.items():
        last3 = [t for t in sym_trades if t.status in ("sl", "tp")][-3:]
        if len(last3) >= 3 and all(t.status == "sl" for t in last3):
            until = time.time() + 24 * 3600
            _coin_blacklist[symbol] = until
            logger.info("coin_blacklisted", symbol=symbol, hours=24)

        # P4.8: directional blacklist — track (symbol, direction) separately
        by_direction: dict = defaultdict(list)
        for t in sym_trades:
            if t.direction:
                by_direction[t.direction].append(t)
        for direction, dir_trades in by_direction.items():
            dir_last3 = [t for t in dir_trades if t.status in ("sl", "tp")][-3:]
            if len(dir_last3) >= 3 and all(t.status == "sl" for t in dir_last3):
                until_dir = time.time() + 24 * 3600
                _coin_blacklist_dir[(symbol, direction)] = until_dir
                logger.info("coin_blacklisted_directional", symbol=symbol,
                            direction=direction, hours=24)

    # G23: prune stale blacklist entries (expired >30d ago) — prevents unbounded growth
    _cutoff = time.time() - 30 * 86400
    stale_bl = [s for s, until in _coin_blacklist.items() if until < _cutoff]
    for s in stale_bl:
        del _coin_blacklist[s]
    if stale_bl:
        logger.debug("blacklist_pruned", count=len(stale_bl))

    stale_dir = [k for k, until in _coin_blacklist_dir.items() if until < _cutoff]
    for k in stale_dir:
        del _coin_blacklist_dir[k]


def _compute_coin_win_rates(trades: list) -> None:
    global _coin_win_rates, _coin_win_rates_dir
    by_symbol: dict = defaultdict(lambda: {"wins": 0, "total": 0})
    by_symbol_dir: dict = defaultdict(lambda: {"wins": 0, "total": 0})
    for t in trades:
        if t.status not in ("tp", "sl"):
            continue
        by_symbol[t.symbol]["total"] += 1
        is_win = _is_win(t)
        if is_win:
            by_symbol[t.symbol]["wins"] += 1
        # P4.8: directional tracking
        if t.direction:
            key = (t.symbol, t.direction)
            by_symbol_dir[key]["total"] += 1
            if is_win:
                by_symbol_dir[key]["wins"] += 1
    _coin_win_rates = dict(by_symbol)
    _coin_win_rates_dir = dict(by_symbol_dir)

    # G23: prune _coin_win_rates for symbols absent from the current training window —
    # avoids unbounded growth as new symbols rotate in/out of the universe.
    active_symbols = {t.symbol for t in trades}
    stale_wr = [s for s in list(_coin_win_rates) if s not in active_symbols]
    for s in stale_wr:
        del _coin_win_rates[s]
    if stale_wr:
        logger.debug("coin_win_rates_pruned", count=len(stale_wr))

    active_keys = {(t.symbol, t.direction) for t in trades if t.direction}
    stale_dir_wr = [k for k in list(_coin_win_rates_dir) if k not in active_keys]
    for k in stale_dir_wr:
        del _coin_win_rates_dir[k]


def _compute_adaptive_thresholds(trades: list) -> None:
    """
    Phase 3 G3-threshold (anti death-spiral):
      - cap auto_threshold at 75 (was 77 — A2 death spiral could push it higher)
      - skip recompute if n < 30 trades (statistical significance, was 10)
      - B3.2 rollback rule: high-WR threshold (70 / 50) only when n ≥ 50 AND WR > 60%
        — prevents stuck-at-70 with tiny samples skewing WR up
    """
    agent_wins:  dict[str, int] = defaultdict(int)
    agent_total: dict[str, int] = defaultdict(int)

    for t in trades:
        a = t.style
        agent_total[a] += 1
        if _is_win(t):
            agent_wins[a] += 1

    for agent_name, total in agent_total.items():
        # Phase 3 G3-threshold: require n ≥ 30 for statistical significance
        # (was 10 — tiny sample WR is too noisy to drive threshold changes)
        if total < 30:
            _adaptive_thresholds[agent_name] = {"min_score": 52, "auto_threshold": 72}
            continue

        wr = agent_wins[agent_name] / total
        if wr < 0.40:
            # Cap 75 (was 77) — A2 death spiral safeguard
            thresholds = {"min_score": 56, "auto_threshold": 75}
        elif wr < 0.55:
            thresholds = {"min_score": 54, "auto_threshold": 74}
        elif wr <= 0.65:
            thresholds = {"min_score": 52, "auto_threshold": 72}
        elif total >= 50 and wr > 0.60:
            # B3.2: only roll back to the most-relaxed bracket when sample is solid
            # AND WR demonstrably > 60% (not 70%). Old WR>0.65 was too strict for n=10.
            thresholds = {"min_score": 50, "auto_threshold": 70}
        else:
            # Solid WR but small sample → stay at default to keep flow
            thresholds = {"min_score": 52, "auto_threshold": 72}

        _adaptive_thresholds[agent_name] = thresholds
        logger.info("adaptive_thresholds_updated", agent=agent_name,
                    n=total, win_rate=round(wr, 3), **thresholds)


# ── Main update ────────────────────────────────────────────────────────────────

async def update_weights() -> int:
    """
    Re-compute signal weights from recent closed futures trades.
    SP2: upgraded with recency decay, Laplace smoothing, step cap, zombie pruning.
    Returns number of rows upserted.
    """
    global _last_run, _last_error, STEP_CAP, EXPECTANCY_AWARE_WEIGHTS
    global REPAIR_WEIGHTS_PERSIST, UNIFIED_SIGNAL_KEYS

    if not is_db_available():
        return 0

    now = time.time()
    if _last_run and (now - _last_run) < MIN_RUN_INTERVAL:
        return 0

    # PLAN_v5 Group C: step_cap shared with SPOT (same "learning.step_cap" key —
    # both currently 0.10). decay_half_life_days is NOT wired here — futures uses
    # 14d vs SPOT's 7d, wiring both to one key would let one overwrite the other.
    try:
        from agents.shared.config_reader import cfg
        STEP_CAP = await cfg.get("learning", "step_cap", STEP_CAP)
        # B1: target bobot expectancy-aware — default OFF (perilaku identik lama).
        EXPECTANCY_AWARE_WEIGHTS = bool(await cfg.get(
            "futures", "expectancy_aware_weights", EXPECTANCY_AWARE_WEIGHTS))
        # Bobot hasil repair bertahan (tidak dinetralkan zombie-pruning).
        REPAIR_WEIGHTS_PERSIST = bool(await cfg.get(
            "futures", "repair_weights_persist", REPAIR_WEIGHTS_PERSIST))
        # Kunci bobot memakai namespace scoring (nyambung ke apply_learning_policy).
        UNIFIED_SIGNAL_KEYS = bool(await cfg.get(
            "futures", "unified_signal_keys", UNIFIED_SIGNAL_KEYS))
    except Exception as exc:
        logger.warning("agent_config_pull_failed", scope="futures_weight_updater", error=str(exc)[:120])

    try:
        async with AsyncSessionLocal() as session:
            cutoff = now - RECENCY_DAYS * 86400
            result = await session.execute(
                select(PaperTrade).where(
                    PaperTrade.style.in_(FUTURES_AGENTS),
                    PaperTrade.status.in_(["tp", "sl", "expired"]),
                    PaperTrade.closed_at >= cutoff,
                )
            )
            trades = list(result.scalars().all())

        if not trades:
            _last_run = now
            return 0

        _update_coin_blacklist(trades)
        _compute_coin_win_rates(trades)
        _compute_adaptive_thresholds(trades)

        # ── Build (agent, signal_key, regime) → stats with recency decay ──────
        # stats[key] = {wins: float, total: float, raw_n: int, pnl_sum: float, win_n: int}
        stats: dict[tuple, dict] = {}

        def _add(key: tuple, is_win: bool, decay: float, pnl_pct: float) -> None:
            s = stats.setdefault(key, {"wins": 0.0, "total": 0.0, "raw_n": 0,
                                       "pnl_sum": 0.0, "win_n": 0, "pnl_sum_all": 0.0})
            s["total"] += decay
            s["raw_n"] += 1
            # B1: numerator expectancy = PnL SEMUA trade (winner+loser), decay-tertimbang
            # konsisten dgn `total`. Dipakai hanya saat EXPECTANCY_AWARE_WEIGHTS ON.
            s["pnl_sum_all"] += pnl_pct * decay
            if is_win:
                s["wins"]    += decay
                s["pnl_sum"] += pnl_pct
                s["win_n"]   += 1

        for trade in trades:
            try:
                meta = json.loads(trade.signals_json or "{}")
            except Exception:
                meta = {}

            signals = meta.get("signals", [])
            if not signals:
                continue

            agent   = trade.style
            regime  = trade.regime or "all"
            is_win  = _is_win(trade)
            decay   = _decay_factor(trade.closed_at, now)
            pnl_pct = trade.pnl_pct or 0.0

            for raw_sig in signals:
                # Kunci scoring (canonical) supaya bobot hasil belajar benar-benar
                # dibaca saat menilai kandidat — lihat UNIFIED_SIGNAL_KEYS.
                sig_key = (_scoring_key(raw_sig) if UNIFIED_SIGNAL_KEYS
                           else _normalize_signal(raw_sig))
                if not sig_key:
                    continue
                for key in [(agent, sig_key, "all"), (agent, sig_key, regime)]:
                    _add(key, is_win, decay, pnl_pct)

        # ── Update in-memory weight cache ("all" + per-regime) ───────────────
        new_cache:        dict[str, dict[str, float]]             = {}
        new_regime_cache: dict[str, dict[str, dict[str, float]]] = {}
        for (agent_name, signal_key, regime_key), v in stats.items():
            if v["raw_n"] < MIN_SAMPLE_RAW:
                continue
            n_eff   = v["total"]
            target  = _target_from_stats(v, n_eff)   # B1: expectancy-aware bila ON
            conf    = min(1.0, n_eff / 10.0)
            desired = 1.0 + (target - 1.0) * conf
            weight  = round(max(0.70, min(1.50, desired)), 3)
            if regime_key == "all":
                new_cache.setdefault(agent_name, {})[signal_key] = weight
            # P3.5: per-regime cache (override "all" for regime-specific scoring)
            new_regime_cache.setdefault(agent_name, {}).setdefault(regime_key, {})[signal_key] = weight
        _weight_cache.update(new_cache)
        _regime_weight_cache.update(new_regime_cache)

        # ── PLAN_FUTURES item C — dua lapis pasca-trade-cache ─────────────────
        # (1) Seed dari DB: cache dibangun HANYA dari trades, sehingga bobot hasil
        #     weekly_signal_review untuk sinyal yang belum pernah di-trade (kasus
        #     a1 dormant) tidak akan pernah sampai ke scoring. Baris regime='all'
        #     yang key-nya tak ada di cache disemai dari DB. (Setelah purge 10 Jul,
        #     semua baris DB adalah era baru — aman.)
        try:
            async with AsyncSessionLocal() as _seed_sess:
                _db_rows = (await _seed_sess.execute(
                    select(AgentSignalWeight).where(
                        AgentSignalWeight.agent.in_(FUTURES_AGENTS),
                        AgentSignalWeight.regime == "all",
                    )
                )).scalars().all()
            for _row in _db_rows:
                _agent_cache = _weight_cache.setdefault(_row.agent, {})
                if _row.signal_key not in _agent_cache:
                    _agent_cache[_row.signal_key] = _row.weight
        except Exception as exc:
            logger.warning("weight_cache_seed_failed", error=str(exc)[:80])

        # (2) P2.3 predictive blend (soft, in-memory saja — baris DB tetap murni
        #     trade-based): new_w = 0.85×cur + 0.15×pred, pred = 1+(hit4h−0.5)×0.05,
        #     gate n≥20, era-H filter. Statistik di-refresh tiap 15 menit; hasil
        #     blend diterapkan ulang tiap run karena cache dibangun ulang dari trades.
        global _pred_blend_stats, _pred_blend_at
        try:
            if now - _pred_blend_at > PRED_BLEND_TTL_SEC:
                from app.models.predictive_log import PredictiveLog
                async with AsyncSessionLocal() as _psess:
                    _prows = (await _psess.execute(
                        select(PredictiveLog.agent, PredictiveLog.signals_json,
                               PredictiveLog.hit_4h).where(
                            PredictiveLog.agent.in_(FUTURES_AGENTS),
                            PredictiveLog.resolved_at.is_not(None),
                            PredictiveLog.scanned_at >= max(DATA_ERA_EPOCH,
                                                            now - RECENCY_DAYS * 86400),
                        )
                    )).all()
                _pstats: dict[tuple, list] = {}
                for _pagent, _sjson, _hit in _prows:
                    try:
                        _sigs = json.loads(_sjson or "[]")
                    except Exception:
                        continue
                    for _s in _sigs:
                        if not isinstance(_s, str):
                            continue
                        _pk = (_pagent, normalize_signal_key(_s))
                        _pd = _pstats.setdefault(_pk, [0, 0])
                        _pd[1] += 1
                        if _hit:
                            _pd[0] += 1
                _pred_blend_stats = {
                    k: 1.0 + (h / n - 0.5) * 0.05
                    for k, (h, n) in _pstats.items() if n >= PRED_MIN_N
                }
                _pred_blend_at = now
            for (_pagent, _pkey), _pred_w in _pred_blend_stats.items():
                _agent_cache = _weight_cache.setdefault(_pagent, {})
                _cur = _agent_cache.get(_pkey, 1.0)
                _agent_cache[_pkey] = round(
                    max(0.70, min(1.50, PRED_TRADE_FRAC * _cur
                                  + (1 - PRED_TRADE_FRAC) * _pred_w)), 3)
        except Exception as exc:
            logger.warning("predictive_blend_failed", error=str(exc)[:80])

        # ── Upsert to DB with step cap ────────────────────────────────────────
        upserted = 0
        async with AsyncSessionLocal() as session:
            # Load existing rows for step cap
            existing_map: dict[tuple, AgentSignalWeight] = {}
            ex_result = await session.execute(
                select(AgentSignalWeight).where(
                    AgentSignalWeight.agent.in_(FUTURES_AGENTS)
                )
            )
            for row in ex_result.scalars().all():
                existing_map[(row.agent, row.signal_key, row.regime)] = row

            # P3.1: collect history snapshots to insert in same commit
            history_rows: list[SignalWeightHistory] = []

            for (agent, signal_key, regime), v in stats.items():
                if v["raw_n"] < MIN_SAMPLE_RAW:
                    continue  # not enough data — apply to all regimes, not just "all"
                n_eff      = v["total"]
                target     = _target_from_stats(v, n_eff)   # B1: expectancy-aware bila ON
                conf       = min(1.0, n_eff / 10.0)
                desired    = 1.0 + (target - 1.0) * conf
                win_rate   = v["wins"] / n_eff if n_eff > 0 else 0.0
                avg_pnl    = v["pnl_sum"] / v["win_n"] if v["win_n"] > 0 else 0.0

                key = (agent, signal_key, regime)
                row = existing_map.get(key)

                if row is None:
                    initial      = round(1.0 + max(-STEP_CAP, min(STEP_CAP, desired - 1.0)), 3)
                    final_weight = initial
                    session.add(AgentSignalWeight(
                        agent            = agent,
                        signal_key       = signal_key,
                        regime           = regime,
                        weight           = initial,
                        win_count        = int(round(v["wins"])),
                        total_count      = v["raw_n"],
                        win_rate         = round(win_rate, 4),
                        avg_pnl_pct      = round(avg_pnl, 3),
                        sample_count_raw = v["raw_n"],
                        updated_at       = now,
                    ))
                else:
                    step                 = max(-STEP_CAP, min(STEP_CAP, desired - row.weight))
                    row.weight           = round(row.weight + step, 3)
                    row.win_count        = int(round(v["wins"]))
                    row.total_count      = v["raw_n"]
                    row.win_rate         = round(win_rate, 4)
                    row.avg_pnl_pct      = round(avg_pnl, 3)
                    row.sample_count_raw = v["raw_n"]
                    row.updated_at       = now
                    final_weight         = row.weight
                upserted += 1

                # P3.1: snapshot "all" regime weights for trajectory visualization
                if regime == "all" and v["raw_n"] >= MIN_SAMPLE_RAW:
                    history_rows.append(SignalWeightHistory(
                        agent            = agent,
                        signal_key       = signal_key,
                        regime           = "all",
                        weight           = final_weight,
                        win_count        = int(round(v["wins"])),
                        total_count      = v["raw_n"],
                        win_rate         = round(win_rate, 4),
                        avg_pnl_pct      = round(avg_pnl, 3),
                        sample_count_raw = v["raw_n"],
                        snapshot_at      = now,
                    ))

            # Zombie pruning: keys absent from current data
            for key, row in existing_map.items():
                if key in stats:
                    continue
                stale_days = (now - (row.updated_at or 0)) / 86400
                if stale_days > STALE_KEY_MAX_D:
                    await session.delete(row)
                    upserted += 1
                    continue
                # BUGFIX 29 Jul 2026 — kunci CANONICAL (`signal_id:*`, `lane:*`)
                # TIDAK PERNAH muncul di `stats`: stats dibangun dari
                # _normalize_signal(sinyal trade) yang menghasilkan kunci
                # natural-language ("wyckoff_markup_awal_masih"), sedangkan
                # scoring (learning_keys) & predictive_repair memakai canonical.
                # Dua namespace ini tak pernah beririsan, jadi setiap bobot
                # canonical selalu dianggap "zombie" dan ditarik +0.10/run ke 1.0
                # — persis membatalkan repair yang -0.10 dalam SATU run (5 mnt).
                # Akibatnya SEMUA 49 bobot canonical futures terkunci 1.0 →
                # factor selalu 1.0 → adaptive_score = raw → seluruh subsistem
                # repair NIHIL efek (padahal ledger melaporkan "terbukti membaik").
                # Kunci canonical dikelola sumber non-trade (predictive_repair,
                # weekly_signal_review) sehingga TIDAK boleh dinetralkan di sini.
                # Penghapusan stale >45 hari di atas tetap berlaku.
                if REPAIR_WEIGHTS_PERSIST and _is_externally_managed(row.signal_key):
                    continue
                if abs(row.weight - 1.0) > 0.01:
                    row.weight = round(
                        max(1.0, row.weight - STEP_CAP) if row.weight > 1.0
                        else min(1.0, row.weight + STEP_CAP),
                        3
                    )
                    upserted += 1

            # Insert history snapshots + prune old (>90d)
            for hr in history_rows:
                session.add(hr)
            await session.execute(
                sql_delete(SignalWeightHistory).where(
                    SignalWeightHistory.snapshot_at < now - 90 * 86400
                )
            )
            await session.commit()

        _last_run   = now
        _last_error = None
        logger.info("futures_weights_updated", rows=upserted, trades=len(trades),
                    cache_agents=list(_weight_cache.keys()))
        return upserted

    except Exception as exc:
        _last_error = str(exc)[:120]
        logger.error("weight_update_error", error=_last_error)
        return 0


def get_state() -> dict:
    regime_keys = {
        agent: list(regimes.keys())
        for agent, regimes in _regime_weight_cache.items()
    }
    now = time.time()
    return {
        "last_run":       _last_run,
        "last_error":     _last_error,
        "cached_agents":  list(_weight_cache.keys()),
        "cached_keys":    sum(len(v) for v in _weight_cache.values()),
        "regime_keys":    regime_keys,
        "blacklisted_coins": [s for s, t in _coin_blacklist.items() if now < t],
        "blacklisted_directional": [
            {"symbol": s, "direction": d}
            for (s, d), t in _coin_blacklist_dir.items() if now < t
        ],
        "coin_win_rates": {
            s: {"wins": d["wins"], "total": d["total"],
                "wr": round(d["wins"] / d["total"], 3) if d["total"] else 0}
            for s, d in _coin_win_rates.items()
        },
        "coin_win_rates_directional": {
            f"{s}_{dr}": {"wins": d["wins"], "total": d["total"],
                          "wr": round(d["wins"] / d["total"], 3) if d["total"] else 0}
            for (s, dr), d in _coin_win_rates_dir.items()
        },
    }
