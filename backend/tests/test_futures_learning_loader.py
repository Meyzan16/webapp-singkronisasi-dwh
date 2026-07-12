"""Tests F2 — apply_lane_learning + prefix bridge (bagian pure, tanpa DB)."""

import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from agents.futures.learning_loader import _prefixed, apply_lane_learning  # noqa: E402


def _row(**kw):
    r = {
        "symbol": "TESTUSDT", "agent": "futures_agent3", "setup_type": "momentum",
        "direction": "LONG", "score": 80.0,
        "signals": ["🚀 Momentum +9.3% — sweet spot entry",
                    "Sinyal tak terdaftar unik 42%"],
    }
    r.update(kw)
    return r


def test_prefixed_namespacing():
    assert _prefixed("bb_squeeze_nh") == "signal:bb_squeeze_nh"     # legacy bare → fallback ns
    assert _prefixed("signal:x") == "signal:x"                     # sudah ns → biarkan
    assert _prefixed("signal_id:tech.bb_squeeze") == "signal_id:tech.bb_squeeze"
    assert _prefixed("lane:momentum") == "lane:momentum"


def test_apply_lane_sets_status_and_neutral_without_weights():
    rows = [_row()]
    apply_lane_learning(rows, {}, {}, {}, set(), auto_threshold=65.0,
                        learning_status="warming")
    r = rows[0]
    assert r["learning_status"] == "warming"
    assert r["weight_applied"] == 1.0
    assert r["adaptive_score"] == 80.0
    assert r["score"] == 80.0                    # skor dasar TIDAK diubah
    assert r["banned_by_learning"] is False


def test_apply_lane_legacy_fallback_weight_applies_to_noncanonical_signal():
    # Sinyal ke-2 tak punya canonical ID → policy pakai fallback signal:<legacy>.
    from agents.futures.learning_policy import normalize_signal
    legacy = normalize_signal("Sinyal tak terdaftar unik 42%")
    rows = [_row()]
    apply_lane_learning(rows, {f"signal:{legacy}": 1.40}, {}, {}, set(),
                        auto_threshold=65.0, learning_status="active")
    # lane + canonical(mom.sweet_spot) neutral, fallback 1.40 → factor rata-rata > 1.0
    assert rows[0]["weight_applied"] > 1.0
    assert rows[0]["adaptive_score"] > 80.0


def test_apply_lane_ban_flags_row():
    from agents.futures.learning_policy import normalize_signal
    legacy = normalize_signal("Sinyal tak terdaftar unik 42%")
    banned = {f"signal:{legacy}"}
    rows = [_row()]
    apply_lane_learning(rows, {}, {}, {}, banned, auto_threshold=65.0,
                        learning_status="active")
    assert rows[0]["banned_by_learning"] is True
    assert rows[0]["learning_auto_veto"] is True


def test_apply_lane_probability_threaded():
    # canonical mom.sweet_spot punya probability historis → estimated muncul.
    weights = {}
    probs = {"signal_id:tech.rsi_momentum": 0.6}
    # gunakan sinyal yang canonical-nya rsi_momentum
    rows = [_row(signals=["RSI 63 momentum zone — trending kuat belum overbought"])]
    apply_lane_learning(rows, weights, probs, {"signal_id:tech.rsi_momentum": 25},
                        set(), auto_threshold=65.0, learning_status="active")
    assert rows[0]["estimated_win_probability"] == 0.6
    assert rows[0]["probability_sample_count"] == 25
