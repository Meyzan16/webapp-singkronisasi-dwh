"""Purged chronological evaluation for SPOT decision-event challengers."""

from __future__ import annotations

from statistics import mean

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.spot_decision_event import SpotDecisionEvent
from app.services.trading_costs import EXECUTION_COST_PCT

THRESHOLDS = (55.0, 60.0, 65.0, 70.0, 72.0, 75.0, 80.0, 85.0, 90.0)
MIN_TOTAL_SAMPLES = 20
MIN_TRAIN_ELIGIBLE = 5
EMBARGO_SECONDS = 24 * 3600


def performance(rows: list[dict], threshold: float) -> dict:
    eligible = [row for row in rows if row["score"] >= threshold]
    pnls = [float(row["pnl_24h_pct"]) - EXECUTION_COST_PCT for row in eligible]
    if not pnls:
        return {"n": 0, "win_rate": None, "expectancy_pct": None, "profit_factor": None, "max_drawdown_pct": None}
    gross_win = sum(pnl for pnl in pnls if pnl > 0)
    gross_loss = abs(sum(pnl for pnl in pnls if pnl < 0))
    equity = peak = max_drawdown = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    return {
        "n": len(pnls),
        "win_rate": round(sum(pnl > 0 for pnl in pnls) / len(pnls), 4),
        "expectancy_pct": round(mean(pnls), 4),
        "profit_factor": round(gross_win / gross_loss, 3) if gross_loss > 0 else None,
        "max_drawdown_pct": round(max_drawdown, 4),
    }


def evaluate_walkforward(rows: list[dict]) -> dict:
    """Tune on the past, embargo the boundary, and report only future results."""
    ordered = sorted(rows, key=lambda row: row["scan_ts"])
    if len(ordered) < MIN_TOTAL_SAMPLES:
        return {
            "status": "insufficient_data",
            "n": len(ordered),
            "required": MIN_TOTAL_SAMPLES,
            "promotion_eligible": False,
        }
    boundary = ordered[int(len(ordered) * 0.60)]["scan_ts"]
    train = [row for row in ordered if row["scan_ts"] < boundary - EMBARGO_SECONDS]
    test = [row for row in ordered if row["scan_ts"] >= boundary + EMBARGO_SECONDS]
    candidates: list[tuple[float, dict]] = []
    for threshold in THRESHOLDS:
        metrics = performance(train, threshold)
        if metrics["n"] >= MIN_TRAIN_ELIGIBLE:
            candidates.append((threshold, metrics))
    if not candidates or not test:
        return {
            "status": "insufficient_after_purge",
            "n": len(ordered),
            "train_n": len(train),
            "test_n": len(test),
            "promotion_eligible": False,
        }
    threshold, train_metrics = max(
        candidates,
        key=lambda item: (item[1]["expectancy_pct"], item[1]["profit_factor"] or 0.0, -item[0]),
    )
    test_metrics = performance(test, threshold)
    baseline_metrics = performance(test, min(THRESHOLDS))
    promotion_eligible = bool(
        test_metrics["n"] >= 5
        and (test_metrics["expectancy_pct"] or 0.0) > (baseline_metrics["expectancy_pct"] or 0.0)
        and (test_metrics["profit_factor"] or 0.0) >= 1.5
    )
    return {
        "status": "ok",
        "n": len(ordered),
        "boundary_ts": boundary,
        "embargo_hours": EMBARGO_SECONDS // 3600,
        "best_threshold": threshold,
        "train": train_metrics,
        "test": test_metrics,
        "test_baseline": baseline_metrics,
        "promotion_eligible": promotion_eligible,
        "warning": "Diagnostic counterfactual replay; portfolio overlap and capital lock are not yet simulated.",
    }


async def run_spot_walkforward() -> dict:
    async with AsyncSessionLocal() as session:
        events = list((await session.execute(
            select(SpotDecisionEvent).where(
                SpotDecisionEvent.pnl_24h_pct.isnot(None),
                SpotDecisionEvent.outcome_status.in_(["partial", "complete"]),
            ).order_by(SpotDecisionEvent.scan_ts)
        )).scalars().all())
    rows = [
        {
            "scan_ts": event.scan_ts,
            "score": event.adaptive_score,
            "pnl_24h_pct": event.pnl_24h_pct,
        }
        for event in events
    ]
    return evaluate_walkforward(rows)
