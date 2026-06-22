"""
Weekly Auto-Backtest — B4.2 rolling 3-week forward-walk.

Trigger: Sunday 00:00 UTC (checked by futures scheduler each cycle).

Data source: big_mover_log table (forward PnL at 1h/4h/24h/7d horizons).

Algorithm:
  1. Week N   = current week (report)
  2. Week N-1 = test week (validate threshold)
  3. Week N-2 = train week (tune threshold)

  On train week (N-2):
    - For each score threshold in [55, 60, 65, 70, 72, 75]:
        count entries with max_score >= threshold that have 24h PnL > 0 / total
    - best_thresh = threshold with highest WR (break ties: pick higher threshold)

  On test week (N-1):
    - Apply best_thresh, compute WR at 24h horizon
    - This is the forward-validated estimate

  For current week N:
    - Report raw WR so far + project forward_pred = test_wr (prior)
"""

import datetime
import time
from typing import Optional

import structlog
from sqlalchemy import select

from app.database import AsyncSessionLocal, is_db_available
from app.models.big_mover_log import BigMoverLog
from app.models.backtest_result import WeeklyBacktestResult

logger = structlog.get_logger(__name__)

_THRESHOLDS = [55.0, 60.0, 65.0, 70.0, 72.0, 75.0]
_DEFAULT_THRESH = 72.0

# Cache: avoid re-running the same week
_last_run_week: Optional[str] = None


def _week_label(ts: float) -> str:
    """ISO week label, e.g. '2026-W25'."""
    d = datetime.datetime.utcfromtimestamp(ts)
    return f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"


def _week_start(ts: float) -> float:
    """Return epoch of the Sunday 00:00 UTC for the week containing ts."""
    d    = datetime.datetime.utcfromtimestamp(ts)
    days = (d.weekday() + 1) % 7   # Monday=0, so Sunday=6 → offset by 1
    sunday = d - datetime.timedelta(days=days, hours=d.hour,
                                    minutes=d.minute, seconds=d.second,
                                    microseconds=d.microsecond)
    return sunday.timestamp()


def _week_range(ts: float) -> tuple[float, float]:
    """Return (start, end) epoch for the ISO week containing ts."""
    start = _week_start(ts)
    return start, start + 7 * 86400


def _best_threshold_for_week(rows: list) -> tuple[float, float, int]:
    """
    Find threshold that maximizes WR at 24h horizon on given rows.
    Returns (best_thresh, best_wr, sample_n).
    """
    best_thresh, best_wr, best_n = _DEFAULT_THRESH, 0.0, 0

    for t in _THRESHOLDS:
        eligible = [r for r in rows
                    if (r.max_score or 0) >= t
                    and r.pnl_24h_pct is not None]
        if not eligible:
            continue
        wins = sum(1 for r in eligible if r.pnl_24h_pct > 0)
        wr   = wins / len(eligible)
        # Prefer higher WR; break ties by picking lower threshold (more trades)
        if wr > best_wr or (wr == best_wr and t < best_thresh):
            best_thresh, best_wr, best_n = t, wr, len(eligible)

    return best_thresh, best_wr, best_n


def _compute_win_rates(rows: list) -> dict:
    """Compute WR per horizon for a set of rows."""
    out: dict = {}
    for col, label in [
        ("pnl_1h_pct",  "wr_1h"),
        ("pnl_4h_pct",  "wr_4h"),
        ("pnl_24h_pct", "wr_24h"),
        ("pnl_7d_pct",  "wr_7d"),
    ]:
        filled = [r for r in rows if getattr(r, col) is not None]
        if not filled:
            out[label] = None
            continue
        wins       = sum(1 for r in filled if getattr(r, col) > 0)
        out[label] = round(wins / len(filled), 4)

    pnl24 = [r.pnl_24h_pct for r in rows if r.pnl_24h_pct is not None]
    out["avg_pnl_24h"] = round(sum(pnl24) / len(pnl24), 2) if pnl24 else None
    return out


def is_sunday_00utc() -> bool:
    """True if current UTC time is Sunday between 00:00 and 00:02."""
    now = datetime.datetime.utcnow()
    return now.weekday() == 6 and now.hour == 0 and now.minute < 2


async def run_weekly_backtest(force: bool = False) -> Optional[dict]:
    """
    Run the weekly backtest. Called by futures scheduler on Sunday 00:00 UTC.

    Args:
        force: skip the day-of-week check (useful for manual trigger via API).

    Returns:
        Result dict or None if no data / already ran this week.
    """
    global _last_run_week

    if not force and not is_sunday_00utc():
        return None

    if not is_db_available():
        return None

    now          = time.time()
    current_week = _week_label(now)

    # Guard: only run once per week (restarts safe)
    if not force and _last_run_week == current_week:
        return None

    logger.info("weekly_backtest_start", week=current_week)

    # Define the 3-week window
    w_n_start,   w_n_end   = _week_range(now)
    w_n1_start,  w_n1_end  = _week_range(now - 7 * 86400)
    w_n2_start,  w_n2_end  = _week_range(now - 14 * 86400)

    async with AsyncSessionLocal() as session:
        def _fetch_rows(start: float, end: float):
            return session.execute(
                select(BigMoverLog).where(
                    BigMoverLog.ts >= start,
                    BigMoverLog.ts <  end,
                    BigMoverLog.market == "futures",
                )
            )

        r_n2 = list((await _fetch_rows(w_n2_start, w_n2_end)).scalars().all())
        r_n1 = list((await _fetch_rows(w_n1_start, w_n1_end)).scalars().all())
        r_n  = list((await _fetch_rows(w_n_start,  w_n_end)).scalars().all())

    if len(r_n2) < 5:
        logger.info("weekly_backtest_skip", reason="insufficient data", n_train=len(r_n2))
        return None

    # Train week N-2: find best threshold
    best_thresh, train_wr, train_n = _best_threshold_for_week(r_n2)

    # Test week N-1: apply best_thresh, compute WR
    r_n1_filtered = [r for r in r_n1
                     if (r.max_score or 0) >= best_thresh
                     and r.pnl_24h_pct is not None]
    test_wr = 0.0
    if r_n1_filtered:
        wins   = sum(1 for r in r_n1_filtered if r.pnl_24h_pct > 0)
        test_wr = round(wins / len(r_n1_filtered), 4)

    # Week N: raw WR so far + forward prediction
    wrs_n       = _compute_win_rates(r_n)
    forward_pred = test_wr   # B4.2: test WR is the best prior for current week

    note = (
        f"Train {_week_label(w_n2_start)}: thresh={best_thresh:.0f}, WR={train_wr:.0%} (n={train_n}). "
        f"Test  {_week_label(w_n1_start)}: WR={test_wr:.0%} (n={len(r_n1_filtered)}). "
        f"Pred week N: {forward_pred:.0%}."
    )
    logger.info("weekly_backtest_result", week=current_week, note=note,
                best_thresh=best_thresh, test_wr=test_wr)

    # Upsert to DB (replace existing row for same week)
    async with AsyncSessionLocal() as session:
        existing = (await session.execute(
            select(WeeklyBacktestResult).where(
                WeeklyBacktestResult.week_label == current_week
            )
        )).scalar_one_or_none()

        payload = {
            "week_label":   current_week,
            "week_start":   w_n_start,
            "market":       "futures",
            "computed_at":  now,
            "n_entries":    len(r_n),
            "n_with_pnl":   len([r for r in r_n if r.pnl_24h_pct is not None]),
            "wr_1h":        wrs_n.get("wr_1h"),
            "wr_4h":        wrs_n.get("wr_4h"),
            "wr_24h":       wrs_n.get("wr_24h"),
            "wr_7d":        wrs_n.get("wr_7d"),
            "avg_pnl_24h":  wrs_n.get("avg_pnl_24h"),
            "train_week":   _week_label(w_n2_start),
            "best_thresh":  best_thresh,
            "train_wr":     round(train_wr, 4),
            "test_week":    _week_label(w_n1_start),
            "test_wr":      test_wr,
            "test_n":       len(r_n1_filtered),
            "forward_pred": forward_pred,
            "forward_note": note[:200],
        }

        if existing:
            for k, v in payload.items():
                setattr(existing, k, v)
        else:
            session.add(WeeklyBacktestResult(**payload))
        await session.commit()

    _last_run_week = current_week
    return payload
