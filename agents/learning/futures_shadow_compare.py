"""Shadow-compare FUTURES (Fase 1, READ-ONLY — nol perubahan keputusan trading).

Menjawab pertanyaan flip Fase 1: "Kalau scanner FUTURES memakai adaptive_score
(hasil learning), bukan veto-only, apakah expectancy realized membaik?" dan
"Apakah veto learning benar-benar menghindari loser?".

Sumber: futures_decision_events yang sudah matang (pnl_4h_pct terisi). Ledger
sudah menyimpan `score` (raw deterministik) DAN `adaptive_score` (raw × factor
learning) — lihat futures/decision_ledger.py:124-126. Modul ini hanya membaca +
membandingkan; tidak menyentuh scanner/policy/auto_trader.
"""

from __future__ import annotations

import time as _time
from statistics import mean

from sqlalchemy import select

from app.database import AsyncSessionLocal, is_db_available
from app.models.futures_decision_event import FuturesDecisionEvent
from app.services.trading_costs import EXECUTION_COST_PCT

# Ambang representatif (mirror per-agent auto_threshold: 65/70/72).
THRESHOLDS = (65.0, 70.0, 72.0)
MIN_SAMPLES = 20

_CACHE: dict = {"ts": 0.0, "data": None}
_TTL = 300.0


def _perf(pnls: list[float]) -> dict:
    if not pnls:
        return {"n": 0, "win_rate": None, "expectancy_pct": None, "profit_factor": None}
    wins = sum(1 for p in pnls if p > 0)
    gross_win = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    return {
        "n": len(pnls),
        "win_rate": round(wins / len(pnls), 4),
        "expectancy_pct": round(mean(pnls), 4),
        "profit_factor": round(gross_win / gross_loss, 3) if gross_loss > 0 else None,
    }


async def run_futures_shadow_compare(force: bool = False) -> dict:
    """Bandingkan seleksi by raw `score` vs `adaptive_score` pada outcome nyata."""
    if not force and _CACHE["data"] is not None and (_time.time() - _CACHE["ts"]) < _TTL:
        return _CACHE["data"]
    if not is_db_available():
        return {"status": "db_unavailable"}

    async with AsyncSessionLocal() as session:
        raw = (await session.execute(
            select(
                FuturesDecisionEvent.score,
                FuturesDecisionEvent.adaptive_score,
                FuturesDecisionEvent.pnl_4h_pct,
                FuturesDecisionEvent.direction,
            ).where(FuturesDecisionEvent.pnl_4h_pct.isnot(None))
        )).all()

    rows = [
        {
            "score": float(s or 0.0),
            "adaptive": float(a or s or 0.0),
            "pnl": float(p) - EXECUTION_COST_PCT,   # net true-cost
            "direction": (d or "?"),
        }
        for s, a, p, d in raw
    ]

    if len(rows) < MIN_SAMPLES:
        result = {"status": "insufficient_data", "n": len(rows), "required": MIN_SAMPLES}
    else:
        by_threshold = []
        for thr in THRESHOLDS:
            baseline = _perf([r["pnl"] for r in rows if r["score"] >= thr])
            learned = _perf([r["pnl"] for r in rows if r["adaptive"] >= thr])
            # Slice yang AKAN diveto: raw lolos tapi adaptive jatuh di bawah ambang.
            # Kalau expectancy slice ini negatif -> veto learning menghindari loser (bagus).
            vetoed = _perf([r["pnl"] for r in rows if r["score"] >= thr and r["adaptive"] < thr])
            lift = (
                None if baseline["expectancy_pct"] is None or learned["expectancy_pct"] is None
                else round(learned["expectancy_pct"] - baseline["expectancy_pct"], 4)
            )
            by_threshold.append({
                "threshold": thr,
                "baseline_raw": baseline,
                "learned_adaptive": learned,
                "vetoed_slice": vetoed,
                "expectancy_lift_pct": lift,
            })
        # Pelacak arah pada pool auto-eligible pasca-fix (skor 70-80): apakah edge
        # LONG/SHORT BERTAHAN forward atau artefak periode (mis. short-squeeze).
        # READ-ONLY — hanya bukti untuk keputusan arah nanti, TIDAK dipakai memutus.
        elig = [r for r in rows if 70.0 <= r["score"] < 80.0]
        by_direction = {
            d: _perf([r["pnl"] for r in elig if r["direction"] == d])
            for d in ("LONG", "SHORT")
        }
        result = {
            "status": "ok",
            "n": len(rows),
            "by_threshold": by_threshold,
            "by_direction_eligible": by_direction,
            "note": "Counterfactual read-only; overlap portfolio & kunci kapital belum disimulasi.",
        }

    _CACHE["ts"] = _time.time()
    _CACHE["data"] = result
    return result
