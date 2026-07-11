"""
Spot Signal Weight Updater — Adaptive Learning for opportunity_spot.

Healthy-statistics version (§5.1, §5.2, §6.1b, §9.2, §9.4):
  - Training data: closed tp/sl trades from the last 90 days ONLY
  - Label truth: realized net pnl_pct; close_reason is diagnostic metadata only
  - Recency decay: each sample weighted by exp(-age / half-life), half-life 7 days
    — the market changes; last week's evidence beats last month's
  - Laplace smoothing: win_rate_adj = (wins + 1) / (total + 2) — 3 samples can
    no longer produce extreme weights
  - Confidence scaling: weight moves toward its target proportionally to
    min(1, n_effective / 10) — more evidence, more influence
  - Deterministic publication: identical evidence always yields identical weights
  - Zombie prune: keys absent from current data decay toward 1.0 and are deleted
    when stale > 30 days (§6.1b, §9.4)

Weight target dari win-rate (smoothed):
  ≥ 0.70 → 1.5 | ≥ 0.55 → 1.2 | ≥ 0.40 → 1.0 | < 0.40 → 0.7
Scanner additionally BANS auto-open for weight < 0.8 with n ≥ 10 (§14.7).
"""

import asyncio
import json
import time
from typing import Optional

import structlog
from sqlalchemy import select

from app.database import AsyncSessionLocal, is_db_available
from app.models.paper_trade import PaperTrade
from app.models.signal_weight import AgentSignalWeight
from app.models.signal_weight_history import SignalWeightHistory
from agents.opportunity.learning_policy import (
    canonical_signal_key,
    deterministic_weight,
    is_profitable_outcome,
    normalize_signal,
)

logger = structlog.get_logger(__name__)

AGENT_KEY          = "opportunity_spot"
MIN_RUN_INTERVAL   = 30 * 60
TRAINING_WINDOW_D  = 90
DECAY_HALF_LIFE_D  = 7.0
STALE_KEY_MAX_D    = 30

_last_run:   Optional[float] = None
_last_error: Optional[str]   = None
_last_count: int             = 0
_update_lock = asyncio.Lock()


def get_state() -> dict:
    return {
        "last_run":   _last_run,
        "last_error": _last_error,
        "last_count": _last_count,
    }


def _normalize_signal(raw: str) -> str:
    """Backward-compatible alias for persisted signal keys."""
    return normalize_signal(raw)


def _target_weight(win_rate_adj: float) -> float:
    if win_rate_adj >= 0.70:
        return 1.5
    if win_rate_adj >= 0.55:
        return 1.2
    if win_rate_adj >= 0.40:
        return 1.0
    return 0.7


def _decay_factor(closed_at: Optional[float], now: float) -> float:
    """exp decay by sample age, half-life DECAY_HALF_LIFE_D days."""
    if not closed_at:
        return 1.0
    age_days = max(0.0, (now - closed_at) / 86400)
    return 0.5 ** (age_days / DECAY_HALF_LIFE_D)


async def update_spot_weights() -> int:
    """Serialize publications so scheduler/monitor cannot race the same rows."""
    async with _update_lock:
        return await _update_spot_weights_unlocked()


async def _update_spot_weights_unlocked() -> int:
    """Recompute signal weights from recent closed trades. Returns rows touched."""
    global _last_run, _last_error, _last_count, TRAINING_WINDOW_D, DECAY_HALF_LIFE_D

    if not is_db_available():
        return 0
    if _last_run and (time.time() - _last_run) < MIN_RUN_INTERVAL:
        return 0

    # PLAN_v5 Group C: pull DB overrides once per run.
    try:
        from agents.shared.config_reader import cfg
        TRAINING_WINDOW_D = await cfg.get("learning", "training_window_days", TRAINING_WINDOW_D)
        DECAY_HALF_LIFE_D = await cfg.get("learning", "decay_half_life_days", DECAY_HALF_LIFE_D)
    except Exception as exc:
        logger.warning("agent_config_pull_failed", scope="spot_weight_updater", error=str(exc)[:120])

    now    = time.time()
    cutoff = now - TRAINING_WINDOW_D * 86400

    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(PaperTrade).where(
                    PaperTrade.style     == AGENT_KEY,
                    PaperTrade.status.in_(["tp", "sl"]),
                    PaperTrade.closed_at >= cutoff,          # §9.2: window, not full scan
                )
            )
            trades = list(result.scalars().all())

        # ── Accumulate decayed win/total per key ──────────────────────────────
        stats: dict[str, dict] = {}

        def _add(key: str, is_win: bool, pnl_pct: float, w: float) -> None:
            s = stats.setdefault(
                key,
                {"wins": 0.0, "total": 0.0, "pnl_sum": 0.0, "raw_n": 0, "raw_wins": 0},
            )
            s["total"] += w
            s["pnl_sum"] += pnl_pct * w
            s["raw_n"] += 1
            if is_win:
                s["wins"] += w
                s["raw_wins"] += 1

        for t in trades:
            meta = {}
            try:
                meta = json.loads(t.signals_json or "{}")
                if not isinstance(meta, dict):
                    meta = {}
            except (json.JSONDecodeError, TypeError):
                pass

            # Realized NET outcome is the source of truth. Close reason is kept
            # for diagnostics only; profitable tp1_breakeven/max-age exits are
            # valid evidence and must not be silently discarded.
            if t.pnl_pct is None:
                continue

            is_win = is_profitable_outcome(t.pnl_pct)
            decay  = _decay_factor(t.closed_at, now)

            if t.alert_type:
                _add(f"alert:{t.alert_type}", is_win, float(t.pnl_pct), decay)

            signals = meta.get("signals", [])
            if isinstance(signals, list):
                for s in signals[:5]:
                    raw_signal = str(s)
                    key = canonical_signal_key(raw_signal)
                    if key is None:
                        normalized = _normalize_signal(raw_signal)
                        key = f"signal:{normalized}" if normalized else ""
                    if key:
                        _add(key, is_win, float(t.pnl_pct), decay)

        # ── Upsert + prune ────────────────────────────────────────────────────
        touched = 0
        async with AsyncSessionLocal() as session:
            existing_rows = {
                row.signal_key: row
                for row in (await session.execute(
                    select(AgentSignalWeight).where(
                        AgentSignalWeight.agent  == AGENT_KEY,
                        AgentSignalWeight.regime == "all",
                    )
                )).scalars().all()
            }

            for key, s in stats.items():
                n_eff    = s["total"]                       # decayed effective n
                raw_n    = s["raw_n"]
                raw_wins = s["raw_wins"]
                win_rate = s["wins"] / n_eff if n_eff > 0 else 0.0
                avg_pnl  = s["pnl_sum"] / n_eff if n_eff > 0 else 0.0
                desired  = deterministic_weight(s["wins"], n_eff)

                row = existing_rows.get(key)
                if row is None:
                    session.add(AgentSignalWeight(
                        agent       = AGENT_KEY,
                        signal_key  = key,
                        weight      = desired,
                        win_count   = raw_wins,
                        total_count = raw_n,
                        win_rate    = round(win_rate, 4),
                        avg_pnl_pct = round(avg_pnl, 3),
                        sample_count_raw = raw_n,
                        regime      = "all",
                        updated_at  = now,
                    ))
                else:
                    next_values = (
                        desired,
                        raw_wins,
                        raw_n,
                        round(win_rate, 4),
                        round(avg_pnl, 3),
                    )
                    current_values = (
                        round(row.weight, 3),
                        row.win_count,
                        row.total_count,
                        round(row.win_rate, 4),
                        round(row.avg_pnl_pct or 0.0, 3),
                    )
                    if next_values == current_values and row.sample_count_raw == raw_n:
                        continue
                    row.weight, row.win_count, row.total_count, row.win_rate, row.avg_pnl_pct = next_values
                    row.sample_count_raw = raw_n
                    row.updated_at = now
                session.add(SignalWeightHistory(
                    agent=AGENT_KEY,
                    signal_key=key,
                    regime="all",
                    weight=desired,
                    win_count=raw_wins,
                    total_count=raw_n,
                    win_rate=round(win_rate, 4),
                    avg_pnl_pct=round(avg_pnl, 3),
                    sample_count_raw=raw_n,
                    snapshot_at=now,
                ))
                touched += 1

            # §6.1b + §9.4: zombie keys — decay toward neutral, delete when stale
            for key, row in existing_rows.items():
                if key in stats:
                    continue
                stale_days = (now - (row.updated_at or 0)) / 86400
                if stale_days > STALE_KEY_MAX_D:
                    await session.delete(row)
                    touched += 1
                # Do not repeatedly move stale weights without new evidence.

            await session.commit()

        _last_run   = now
        _last_error = None
        _last_count = touched
        logger.info("spot_weights_updated", keys=touched, trades=len(trades))
        return touched

    except Exception as exc:
        _last_error = str(exc)[:120]
        logger.error("spot_weight_updater_error", error=_last_error)
        return 0
