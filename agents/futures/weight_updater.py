"""
Signal Weight Updater — runs after each scan cycle.

Reads all closed futures trades, maps signals → win/loss,
then upserts agent_signal_weights table.

Also maintains in-memory caches used synchronously by agents:
  - _weight_cache:       {agent: {signal_key: weight}}
  - _adaptive_thresholds: {agent: {min_score, auto_threshold}}
  - _coin_blacklist:     {symbol: blacklist_until_ts}
"""

import json
import re
import time
from collections import defaultdict
from typing import Optional

import structlog
from sqlalchemy import select

from app.database import AsyncSessionLocal, is_db_available
from app.models.paper_trade import PaperTrade
from app.models.signal_weight import AgentSignalWeight

logger = structlog.get_logger(__name__)

_last_run:   Optional[float] = None
_last_error: Optional[str]   = None
MIN_RUN_INTERVAL = 5 * 60  # don't run more than once every 5 min
# BUG-L10: only learn from RECENT trades so weights/thresholds adapt to the current regime
# instead of being dragged forever by ancient outcomes.
RECENCY_DAYS = 30

# ── In-memory caches (read synchronously by agents during scoring) ─────────────

# F68: signal weight cache  {agent: {signal_key: weight}}
_weight_cache: dict[str, dict[str, float]] = {}

# F69: adaptive thresholds  {agent: {min_score: int, auto_threshold: int}}
_adaptive_thresholds: dict[str, dict] = {}

# F71: per-coin blacklist  {symbol: blacklist_until_ts}
_coin_blacklist: dict[str, float] = {}

# F92: per-coin win rate  {symbol: {"wins": int, "total": int}}
_coin_win_rates: dict[str, dict] = {}


# ── Public cache accessors ─────────────────────────────────────────────────────

def get_weight_cache(agent: str) -> dict[str, float]:
    """F68: Return weight dict for agent — read synchronously during scoring."""
    return _weight_cache.get(agent, {})


def get_adaptive_thresholds(agent: str) -> dict:
    """F69: Return adaptive min_score and auto_threshold for agent."""
    return _adaptive_thresholds.get(agent, {"min_score": 52, "auto_threshold": 72})


def is_blacklisted(symbol: str) -> bool:
    """F71: True if symbol is blacklisted due to consecutive losses."""
    return time.time() < _coin_blacklist.get(symbol, 0)


def normalize_signal_key(raw: str) -> str:
    """F73: Expose normalizer so agents use identical keys to weight_updater."""
    return _normalize_signal(raw)


def get_coin_bonus(symbol: str) -> float:
    """F92: Score bonus/penalty based on per-coin historical win rate.
    Requires ≥3 closed trades to activate — below that, neutral (0.0).
    """
    data = _coin_win_rates.get(symbol, {})
    total = data.get("total", 0)
    if total < 3:
        return 0.0
    wr = data.get("wins", 0) / total
    if wr >= 0.70:
        return 5.0    # proven winner — boost score
    if wr < 0.30:
        return -5.0   # consistently losing — penalise
    return 0.0


# ── Internal helpers ───────────────────────────────────────────────────────────

def _normalize_signal(raw: str) -> str:
    """
    F73: Convert signal string to a stable lookup key.
    Preserves numbers to keep timeframe info: "BB Squeeze 1H" ≠ "BB Squeeze 4H".
    Removes emojis / punctuation, lowercases, joins with underscore.
    """
    # Remove everything that isn't a word char or space (preserves digits)
    cleaned = re.sub(r"[^\w\s]", " ", raw)
    words   = cleaned.strip().lower().split()[:5]
    return "_".join(w for w in words if w)


def _weight_from_rate(win_rate: float, total: int) -> float:
    """F75: Smooth linear interpolation instead of step function.
    win_rate=0   → 0.70  (heavy reduce)
    win_rate=0.5 → 1.10  (slight boost)
    win_rate=1.0 → 1.50  (max boost)
    """
    if total < 3:
        return 1.0  # not enough data → neutral
    return round(max(0.7, min(1.5, 0.7 + win_rate * 0.8)), 3)


def _update_coin_blacklist(trades: list) -> None:
    """F71: Blacklist coins with 3 consecutive SL trades (24h cooldown)."""
    by_symbol: dict = defaultdict(list)
    # B2: sort by closed_at, not entry_at — consecutive means last 3 CLOSED, not opened
    for t in sorted(trades, key=lambda x: x.closed_at or x.entry_at or 0):
        by_symbol[t.symbol].append(t)

    for symbol, sym_trades in by_symbol.items():
        last3 = [t for t in sym_trades if t.status in ("sl", "tp")][-3:]
        if len(last3) >= 3 and all(t.status == "sl" for t in last3):
            until = time.time() + 24 * 3600
            _coin_blacklist[symbol] = until
            logger.info("coin_blacklisted", symbol=symbol, hours=24)


def _compute_coin_win_rates(trades: list) -> None:
    """F92: Build per-coin win rate from closed tp/sl trades."""
    global _coin_win_rates
    by_symbol: dict = defaultdict(lambda: {"wins": 0, "total": 0})
    for t in trades:
        if t.status not in ("tp", "sl"):
            continue  # exclude expired from win rate
        by_symbol[t.symbol]["total"] += 1
        if t.status == "tp" and (t.pnl_pct or 0.0) > 0:
            by_symbol[t.symbol]["wins"] += 1
    _coin_win_rates = dict(by_symbol)


def _compute_adaptive_thresholds(trades: list) -> None:
    """F69: Compute per-agent adaptive thresholds from recent win rate."""
    agent_wins:  dict[str, int] = defaultdict(int)
    agent_total: dict[str, int] = defaultdict(int)

    for t in trades:
        a = t.style
        agent_total[a] += 1
        # Use same is_win definition as weight update (F60: pnl_pct > 0)
        if t.status == "tp" and (t.pnl_pct or 0.0) > 0:
            agent_wins[a] += 1

    for agent_name, total in agent_total.items():
        if total < 10:  # not enough data → defaults
            _adaptive_thresholds[agent_name] = {"min_score": 52, "auto_threshold": 72}
            continue

        wr = agent_wins[agent_name] / total
        if wr < 0.40:
            thresholds = {"min_score": 57, "auto_threshold": 77}
        elif wr < 0.55:
            thresholds = {"min_score": 54, "auto_threshold": 74}
        elif wr <= 0.65:
            thresholds = {"min_score": 52, "auto_threshold": 72}
        else:  # > 0.65 — performing well, slightly lower bar
            thresholds = {"min_score": 50, "auto_threshold": 70}

        _adaptive_thresholds[agent_name] = thresholds
        logger.info("adaptive_thresholds_updated",
                    agent=agent_name, win_rate=round(wr, 3),
                    min_score=thresholds["min_score"],
                    auto_threshold=thresholds["auto_threshold"])


# ── Main update ────────────────────────────────────────────────────────────────

async def update_weights() -> int:
    """
    Re-compute signal weights from all closed futures trades.
    Also updates in-memory caches: weight_cache, adaptive_thresholds, coin_blacklist.
    Returns number of rows upserted.
    """
    global _last_run, _last_error

    if not is_db_available():
        return 0

    now = time.time()
    if _last_run and (now - _last_run) < MIN_RUN_INTERVAL:
        return 0  # too soon

    try:
        async with AsyncSessionLocal() as session:
            # F70: include expired trades as negative signal (was only tp+sl)
            # BUG-L10: only the last RECENCY_DAYS so learning adapts to the current regime
            _cutoff = now - RECENCY_DAYS * 86400
            result = await session.execute(
                select(PaperTrade).where(
                    PaperTrade.style.in_(["futures_agent1", "futures_agent2", "futures_agent3"]),
                    PaperTrade.status.in_(["tp", "sl", "expired"]),
                    PaperTrade.closed_at >= _cutoff,
                )
            )
            trades = list(result.scalars().all())

        if not trades:
            _last_run = now
            return 0

        # ── Update in-memory caches before DB write ─────────────────────────
        _update_coin_blacklist(trades)       # F71
        _compute_coin_win_rates(trades)      # F92
        _compute_adaptive_thresholds(trades) # F69

        # ── Build (agent, signal_key, regime) → {wins, total} map ──────────
        stats: dict[tuple, dict] = {}

        for trade in trades:
            try:
                meta = json.loads(trade.signals_json or "{}")
            except Exception:
                meta = {}

            signals = meta.get("signals", [])
            if not signals:
                continue

            agent  = trade.style
            regime = trade.regime or "all"

            # F60: real win requires status=="tp" AND pnl_pct > 0
            # F70: expired treated as loss (is_win = False)
            is_win = trade.status == "tp" and (trade.pnl_pct or 0.0) > 0

            for raw_sig in signals:
                sig_key    = _normalize_signal(raw_sig)
                if not sig_key:
                    continue
                key_all    = (agent, sig_key, "all")
                key_regime = (agent, sig_key, regime)

                for k in [key_all, key_regime]:
                    entry = stats.setdefault(k, {"wins": 0, "total": 0})
                    entry["total"] += 1
                    if is_win:
                        entry["wins"] += 1

        # ── Update in-memory weight cache (F68: agents read synchronously) ──
        new_cache: dict[str, dict[str, float]] = {}
        for (agent_name, signal_key, regime_key), v in stats.items():
            if regime_key != "all":
                continue  # cache uses aggregate "all" weights
            win_rate = v["wins"] / v["total"] if v["total"] > 0 else 0.5
            w = _weight_from_rate(win_rate, v["total"])
            if agent_name not in new_cache:
                new_cache[agent_name] = {}
            new_cache[agent_name][signal_key] = w
        _weight_cache.update(new_cache)

        # ── Upsert to DB ─────────────────────────────────────────────────────
        upserted = 0
        async with AsyncSessionLocal() as session:
            for (agent, signal_key, regime), v in stats.items():
                win_rate = v["wins"] / v["total"] if v["total"] > 0 else 0.0
                weight   = _weight_from_rate(win_rate, v["total"])

                existing = await session.execute(
                    select(AgentSignalWeight).where(
                        AgentSignalWeight.agent      == agent,
                        AgentSignalWeight.signal_key == signal_key,
                        AgentSignalWeight.regime     == regime,
                    ).limit(1)
                )
                row = existing.scalar_one_or_none()

                if row:
                    row.win_count   = v["wins"]
                    row.total_count = v["total"]
                    row.win_rate    = round(win_rate, 4)
                    row.weight      = round(weight, 4)
                    row.updated_at  = now
                else:
                    session.add(AgentSignalWeight(
                        agent       = agent,
                        signal_key  = signal_key,
                        regime      = regime,
                        win_count   = v["wins"],
                        total_count = v["total"],
                        win_rate    = round(win_rate, 4),
                        weight      = round(weight, 4),
                        updated_at  = now,
                    ))
                upserted += 1

            await session.commit()

        _last_run   = now
        _last_error = None
        logger.info("weights_updated", rows=upserted, trades=len(trades),
                    cache_agents=list(_weight_cache.keys()),
                    blacklisted=len([s for s, t in _coin_blacklist.items()
                                    if time.time() < t]))
        return upserted

    except Exception as exc:
        _last_error = str(exc)[:120]
        logger.error("weight_update_error", error=_last_error)
        return 0


def get_state() -> dict:
    return {
        "last_run":   _last_run,
        "last_error": _last_error,
        "cached_agents": list(_weight_cache.keys()),
        "blacklisted_coins": [s for s, t in _coin_blacklist.items()
                               if time.time() < t],
        "coin_win_rates": {
            s: {"wins": d["wins"], "total": d["total"],
                "wr": round(d["wins"] / d["total"], 3) if d["total"] else 0}
            for s, d in _coin_win_rates.items()
        },
    }
