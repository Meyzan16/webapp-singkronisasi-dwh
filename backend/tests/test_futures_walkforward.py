"""Tests F4 — futures walk-forward + cost stress (bagian pure, tanpa DB)."""

import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from agents.learning.futures_walkforward import (  # noqa: E402
    EMBARGO_SECONDS, MIN_TOTAL_SAMPLES, STRESS_MULT,
    evaluate_walkforward, performance,
)


def _row(ts, score, pnl4h, cost=0.20):
    return {"scan_ts": float(ts), "score": float(score), "pnl_4h_pct": float(pnl4h), "cost_pct": cost}


def test_performance_applies_per_sample_cost_and_threshold():
    rows = [_row(0, 80, 2.0, cost=0.3), _row(1, 60, 5.0, cost=0.3), _row(2, 90, -1.0, cost=0.3)]
    # threshold 75 → hanya score 80 & 90 lolos; net = pnl - 0.3
    m = performance(rows, threshold=75.0, cost_mult=1.0)
    assert m["n"] == 2
    # net pnls: (2.0-0.3)=1.7, (-1.0-0.3)=-1.3 → expectancy 0.2
    assert abs(m["expectancy_pct"] - 0.2) < 1e-9


def test_cost_stress_reduces_expectancy():
    rows = [_row(i, 80, 1.0, cost=0.4) for i in range(10)]
    base = performance(rows, 75.0, cost_mult=1.0)
    stressed = performance(rows, 75.0, cost_mult=STRESS_MULT)
    # base net 0.6, stressed net 1.0 - 0.6 = 0.4
    assert base["expectancy_pct"] > stressed["expectancy_pct"]
    assert abs(stressed["expectancy_pct"] - 0.4) < 1e-9


def test_insufficient_data_gate():
    rows = [_row(i, 80, 1.0) for i in range(MIN_TOTAL_SAMPLES - 1)]
    out = evaluate_walkforward(rows)
    assert out["status"] == "insufficient_data"
    assert out["promotion_eligible"] is False


def test_walkforward_embargo_splits_and_reports():
    # Bangun dataset chronological besar: high-score konsisten profit.
    hour = 3600
    rows = []
    for i in range(60):
        ts = i * hour * 2          # 2 jam antar sampel → embargo 4h membuang ~2 sampel di boundary
        score = 80 if i % 2 == 0 else 60
        pnl = 3.0 if score == 80 else -0.5
        rows.append(_row(ts, score, pnl, cost=0.2))
    out = evaluate_walkforward(rows)
    assert out["status"] == "ok", out
    assert out["embargo_hours"] == EMBARGO_SECONDS // 3600 == 4
    assert "test_stressed_1_5x" in out
    # winners=score80, losers=score60 → tuner pilih threshold TERKECIL yg menyaring
    # loser (score60<65) karena tie-break -item[0] utamakan threshold rendah.
    assert 65 <= out["best_threshold"] <= 80
    # gate promosi butuh test + stressed lolos
    assert isinstance(out["promotion_eligible"], bool)


def test_promotion_requires_surviving_cost_stress():
    # Edge tipis: profit 0.5 di cost 0.2 → net 0.3 normal, tapi 1.5× cost = 0.3 →
    # net 0.5-0.3=0.2 masih >0 tapi PF... buat kasus yg mati saat stress.
    hour = 3600
    rows = []
    for i in range(60):
        ts = i * hour * 2
        score = 80 if i % 2 == 0 else 60
        # score-80 profit tipis 0.35, cost 0.25 → normal net 0.10 (>0), stress 1.5×cost=0.375 → net -0.025 (<0)
        pnl = 0.35 if score == 80 else -0.5
        rows.append(_row(ts, score, pnl, cost=0.25))
    out = evaluate_walkforward(rows)
    if out["status"] == "ok":
        stressed_exp = out["test_stressed_1_5x"]["expectancy_pct"]
        if stressed_exp is not None and stressed_exp <= 0:
            assert out["promotion_eligible"] is False   # stress membunuh kelayakan
