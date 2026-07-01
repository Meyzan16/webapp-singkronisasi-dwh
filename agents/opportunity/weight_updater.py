"""
Spot Signal Weight Updater — Adaptive Learning for opportunity_spot.

Healthy-statistics version (§5.1, §5.2, §6.1b, §9.2, §9.4):
  - Training data: closed tp/sl trades from the last 90 days ONLY
  - EXCLUDED from learning: close_reason in ("tp1_breakeven", "max_age_expired")
    (±0 outcomes and timeouts are not signal-quality evidence) and manual closes
  - Recency decay: each sample weighted by exp(-age / half-life), half-life 7 days
    — the market changes; last week's evidence beats last month's
  - Laplace smoothing: win_rate_adj = (wins + 1) / (total + 2) — 3 samples can
    no longer produce extreme weights
  - Confidence scaling: weight moves toward its target proportionally to
    min(1, n_effective / 10) — more evidence, more influence
  - Step cap: a key's weight moves at most ±0.10 per run (anti-oscillation §5.2.7)
  - Zombie prune: keys absent from current data decay toward 1.0 and are deleted
    when stale > 30 days (§6.1b, §9.4)

Weight target dari win-rate (smoothed):
  ≥ 0.70 → 1.5 | ≥ 0.55 → 1.2 | ≥ 0.40 → 1.0 | < 0.40 → 0.7
Scanner additionally BANS auto-open for weight < 0.8 with n ≥ 10 (§14.7).
"""

import json
import re
import time
from typing import Optional

import structlog
from sqlalchemy import select

from app.database import AsyncSessionLocal, is_db_available
from app.models.paper_trade import PaperTrade
from app.models.signal_weight import AgentSignalWeight

logger = structlog.get_logger(__name__)

AGENT_KEY          = "opportunity_spot"
MIN_RUN_INTERVAL   = 30 * 60
TRAINING_WINDOW_D  = 90
DECAY_HALF_LIFE_D  = 7.0
STEP_CAP           = 0.10
STALE_KEY_MAX_D    = 30
EXCLUDED_REASONS   = {"tp1_breakeven", "max_age_expired"}

_last_run:   Optional[float] = None
_last_error: Optional[str]   = None
_last_count: int             = 0


def get_state() -> dict:
    return {
        "last_run":   _last_run,
        "last_error": _last_error,
        "last_count": _last_count,
    }


def _normalize_signal(raw: str) -> str:
    """Convert signal string to a stable short key (strip emojis and numbers)."""
    cleaned = re.sub(r"[^\w\s%+.\-]", "", raw)
    cleaned = re.sub(r"\d+\.?\d*", "N", cleaned)
    words   = cleaned.strip().split()[:4]
    return "_".join(w.lower() for w in words if w)


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
    """Recompute signal weights from recent closed trades. Returns rows touched."""
    global _last_run, _last_error, _last_count, TRAINING_WINDOW_D, DECAY_HALF_LIFE_D, STEP_CAP

    if not is_db_available():
        return 0
    if _last_run and (time.time() - _last_run) < MIN_RUN_INTERVAL:
        return 0

    # PLAN_v5 Group C: pull DB overrides once per run.
    try:
        from agents.shared.config_reader import cfg
        TRAINING_WINDOW_D = await cfg.get("learning", "training_window_days", TRAINING_WINDOW_D)
        DECAY_HALF_LIFE_D = await cfg.get("learning", "decay_half_life_days", DECAY_HALF_LIFE_D)
        STEP_CAP          = await cfg.get("learning", "step_cap", STEP_CAP)
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

        def _add(key: str, is_win: bool, w: float) -> None:
            s = stats.setdefault(key, {"wins": 0.0, "total": 0.0, "raw_n": 0})
            s["total"] += w
            s["raw_n"] += 1
            if is_win:
                s["wins"] += w

        for t in trades:
            meta = {}
            try:
                meta = json.loads(t.signals_json or "{}")
                if not isinstance(meta, dict):
                    meta = {}
            except (json.JSONDecodeError, TypeError):
                pass

            # §5.1: exclude polluted labels from training
            if meta.get("close_reason") in EXCLUDED_REASONS:
                continue

            is_win = (t.status == "tp") and (t.pnl_pct is not None and t.pnl_pct > 0)
            decay  = _decay_factor(t.closed_at, now)

            if t.alert_type:
                _add(f"alert:{t.alert_type}", is_win, decay)

            signals = meta.get("signals", [])
            if isinstance(signals, list):
                for s in signals[:5]:
                    key = _normalize_signal(str(s))
                    if key:
                        _add(f"signal:{key}", is_win, decay)

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
                win_rate = s["wins"] / n_eff if n_eff > 0 else 0.0
                # §5.2: Laplace smoothing — no certainty from tiny samples
                wr_adj   = (s["wins"] + 1.0) / (n_eff + 2.0)
                target   = _target_weight(wr_adj)
                # Confidence scaling: full influence only with ≥10 effective samples
                confidence = min(1.0, n_eff / 10.0)
                desired    = 1.0 + (target - 1.0) * confidence

                row = existing_rows.get(key)
                if row is None:
                    initial = 1.0 + max(-STEP_CAP, min(STEP_CAP, desired - 1.0))
                    session.add(AgentSignalWeight(
                        agent       = AGENT_KEY,
                        signal_key  = key,
                        weight      = round(initial, 3),
                        win_count   = int(round(s["wins"])),
                        total_count = raw_n,
                        win_rate    = round(win_rate, 4),
                        regime      = "all",
                        updated_at  = now,
                    ))
                else:
                    # §5.2.7: anti-oscillation — move at most ±STEP_CAP per run
                    step = max(-STEP_CAP, min(STEP_CAP, desired - row.weight))
                    row.weight      = round(row.weight + step, 3)
                    row.win_count   = int(round(s["wins"]))
                    row.total_count = raw_n
                    row.win_rate    = round(win_rate, 4)
                    row.updated_at  = now
                touched += 1

            # §6.1b + §9.4: zombie keys — decay toward neutral, delete when stale
            for key, row in existing_rows.items():
                if key in stats:
                    continue
                stale_days = (now - (row.updated_at or 0)) / 86400
                if stale_days > STALE_KEY_MAX_D:
                    await session.delete(row)
                    touched += 1
                elif abs(row.weight - 1.0) > 0.01:
                    if row.weight > 1.0:
                        row.weight = round(max(1.0, row.weight - STEP_CAP), 3)
                    else:
                        row.weight = round(min(1.0, row.weight + STEP_CAP), 3)
                    touched += 1
                    # updated_at sengaja TIDAK disentuh — staleness terus berjalan

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
