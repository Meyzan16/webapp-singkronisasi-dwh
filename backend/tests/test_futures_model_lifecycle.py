"""Tests F5 — gate lifecycle canary/champion (bagian pure yg bisa diuji tanpa DB)."""

import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from agents.learning import futures_adaptive_model as fam  # noqa: E402
from agents.learning.futures_adaptive_model import (  # noqa: E402
    CANARY_MAX_DD_PCT, CANARY_MIN_OUTCOMES, CANARY_MIN_PF,
    _features_for_predict, finalize_canary,
)


def test_shadow_probability_excluded_from_features():
    """shadow_probability & field turunan learning tak boleh jadi fitur (anti-bocor)."""
    snap = {"score": 70.0, "atr_pct": 1.8, "shadow_probability": 0.9,
            "adaptive_score": 88.0, "cost_floor_pct": 0.3,
            "shadow_model_version": "futures-logistic-1", "rr_ratio": 2.5}
    feats = _features_for_predict(snap)
    assert "score" in feats and "atr_pct" in feats and "rr_ratio" in feats
    for banned in ("shadow_probability", "adaptive_score", "cost_floor_pct",
                   "shadow_model_version"):
        assert banned not in feats


# Cabang "blocked" finalize_canary return SEBELUM sentuh DB → aman tanpa DB.
async def test_finalize_canary_blocks_insufficient_outcomes():
    out = await finalize_canary("v", {"n": CANARY_MIN_OUTCOMES - 1,
                                      "expectancy_pct": 1.0, "profit_factor": 3.0,
                                      "max_drawdown_pct": 1.0})
    assert out["status"] == "blocked" and out["reason"] == "canary_gate_failed"


async def test_finalize_canary_blocks_negative_expectancy():
    out = await finalize_canary("v", {"n": CANARY_MIN_OUTCOMES + 5,
                                      "expectancy_pct": -0.1, "profit_factor": 3.0,
                                      "max_drawdown_pct": 1.0})
    assert out["status"] == "blocked"


async def test_finalize_canary_blocks_low_profit_factor():
    out = await finalize_canary("v", {"n": 30, "expectancy_pct": 0.5,
                                      "profit_factor": CANARY_MIN_PF - 0.1,
                                      "max_drawdown_pct": 1.0})
    assert out["status"] == "blocked"


async def test_finalize_canary_blocks_high_drawdown():
    out = await finalize_canary("v", {"n": 30, "expectancy_pct": 0.5,
                                      "profit_factor": 3.0,
                                      "max_drawdown_pct": CANARY_MAX_DD_PCT + 1})
    assert out["status"] == "blocked"


def test_lifecycle_constants_match_plan_gates():
    # Gate §4: canary ≥20 outcomes, PF≥1.5, DD≤10%
    assert fam.CANARY_MIN_OUTCOMES == 20
    assert fam.CANARY_MIN_PF == 1.5
    assert fam.CANARY_MAX_DD_PCT == 10.0
    assert fam.DRIFT_BRIER_MAX == 0.30
