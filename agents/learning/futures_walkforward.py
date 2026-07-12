"""Purged chronological walk-forward untuk FUTURES challenger (F4).

Mirror agents/learning/spot_walkforward.py (engine SPOT tidak disentuh), dgn
kekhususan futures dari plan:
  - Horizon = 4h (pnl_4h_pct); embargo = 4h (= horizon, cegah bocor lintas boundary).
  - Biaya = cost_floor per-sampel (true-cost v16: fee + 2×slippage + funding_est) —
    bukan biaya flat. Fallback default bila snapshot tak punya cost_floor.
  - COST STRESS 1.5× WAJIB: promotion_eligible menuntut expectancy tetap > 0 dan
    PF ≥ 1.5 pada biaya 1.5× (funding ikut ter-scale karena masuk cost_floor).

Diagnostik counterfactual: overlap portfolio & kunci kapital belum disimulasi
(sama caveat dgn SPOT) — dipakai sebagai salah satu gate promosi, bukan sizing.
"""

from __future__ import annotations

import json
from statistics import mean

from sqlalchemy import select

from app.database import AsyncSessionLocal, is_db_available
from app.models.futures_decision_event import FuturesDecisionEvent

THRESHOLDS = (55.0, 60.0, 65.0, 70.0, 72.0, 75.0, 80.0, 85.0, 90.0)
MIN_TOTAL_SAMPLES = 20
MIN_TRAIN_ELIGIBLE = 5
EMBARGO_SECONDS = 4 * 3600     # = horizon label (4h)
STRESS_MULT = 1.5
DEFAULT_COST_PCT = 0.20        # fallback bila cost_floor absen (fee+slip+funding kasar)


def _net_pnls(rows: list[dict], threshold: float, cost_mult: float) -> list[float]:
    out = []
    for row in rows:
        if row["score"] < threshold:
            continue
        out.append(float(row["pnl_4h_pct"]) - float(row["cost_pct"]) * cost_mult)
    return out


def _stats(pnls: list[float]) -> dict:
    if not pnls:
        return {"n": 0, "win_rate": None, "expectancy_pct": None,
                "profit_factor": None, "max_drawdown_pct": None}
    gross_win = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    equity = peak = max_dd = 0.0
    for p in pnls:
        equity += p
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return {
        "n": len(pnls),
        "win_rate": round(sum(p > 0 for p in pnls) / len(pnls), 4),
        "expectancy_pct": round(mean(pnls), 4),
        "profit_factor": round(gross_win / gross_loss, 3) if gross_loss > 0 else None,
        "max_drawdown_pct": round(max_dd, 4),
    }


def performance(rows: list[dict], threshold: float, cost_mult: float = 1.0) -> dict:
    return _stats(_net_pnls(rows, threshold, cost_mult))


def evaluate_walkforward(rows: list[dict]) -> dict:
    """Tune threshold di masa lalu, embargo boundary, laporkan hanya masa depan +
    cost-stress 1.5×."""
    ordered = sorted(rows, key=lambda row: row["scan_ts"])
    if len(ordered) < MIN_TOTAL_SAMPLES:
        return {"status": "insufficient_data", "n": len(ordered),
                "required": MIN_TOTAL_SAMPLES, "promotion_eligible": False}
    boundary = ordered[int(len(ordered) * 0.60)]["scan_ts"]
    train = [r for r in ordered if r["scan_ts"] < boundary - EMBARGO_SECONDS]
    test = [r for r in ordered if r["scan_ts"] >= boundary + EMBARGO_SECONDS]
    candidates: list[tuple[float, dict]] = []
    for threshold in THRESHOLDS:
        m = performance(train, threshold)
        if m["n"] >= MIN_TRAIN_ELIGIBLE and m["expectancy_pct"] is not None:
            candidates.append((threshold, m))
    if not candidates or not test:
        return {"status": "insufficient_after_purge", "n": len(ordered),
                "train_n": len(train), "test_n": len(test), "promotion_eligible": False}
    threshold, train_metrics = max(
        candidates,
        key=lambda item: (item[1]["expectancy_pct"], item[1]["profit_factor"] or 0.0, -item[0]),
    )
    test_metrics = performance(test, threshold)
    test_stressed = performance(test, threshold, cost_mult=STRESS_MULT)
    baseline_metrics = performance(test, min(THRESHOLDS))
    promotion_eligible = bool(
        test_metrics["n"] >= 5
        and (test_metrics["expectancy_pct"] or 0.0) > (baseline_metrics["expectancy_pct"] or 0.0)
        and (test_metrics["profit_factor"] or 0.0) >= 1.5
        # cost-stress 1.5× WAJIB tahan (funding ikut ter-scale via cost_floor)
        and (test_stressed["expectancy_pct"] or -1.0) > 0.0
        and (test_stressed["profit_factor"] or 0.0) >= 1.5
    )
    return {
        "status": "ok",
        "n": len(ordered),
        "boundary_ts": boundary,
        "embargo_hours": EMBARGO_SECONDS // 3600,
        "best_threshold": threshold,
        "train": train_metrics,
        "test": test_metrics,
        "test_stressed_1_5x": test_stressed,
        "test_baseline": baseline_metrics,
        "promotion_eligible": promotion_eligible,
        "warning": "Counterfactual replay diagnostik; overlap portfolio & kunci kapital belum disimulasi.",
    }


async def run_futures_walkforward() -> dict:
    if not is_db_available():
        return {"status": "db_unavailable", "promotion_eligible": False}
    async with AsyncSessionLocal() as session:
        events = list((await session.execute(
            select(FuturesDecisionEvent).where(
                FuturesDecisionEvent.pnl_4h_pct.isnot(None),
            ).order_by(FuturesDecisionEvent.scan_ts)
        )).scalars().all())
    rows = []
    for ev in events:
        try:
            snap = json.loads(ev.feature_snapshot_json or "{}")
        except (TypeError, json.JSONDecodeError):
            snap = {}
        cost = snap.get("cost_floor_pct")
        rows.append({
            "scan_ts": ev.scan_ts,
            "score": float(ev.adaptive_score or ev.score or 0.0),
            "pnl_4h_pct": ev.pnl_4h_pct,
            "cost_pct": float(cost) if isinstance(cost, (int, float)) else DEFAULT_COST_PCT,
        })
    return evaluate_walkforward(rows)
