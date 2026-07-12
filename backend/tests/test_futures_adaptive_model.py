"""Tests F3 — futures challenger model (bagian pure, tanpa DB)."""

import os
import random
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from agents.learning.futures_adaptive_model import (  # noqa: E402
    MIN_TRAIN_SAMPLES, predict, train_challenger,
)


def test_insufficient_data_gate():
    samples = [{"scan_ts": i, "features": {"score": 70.0}, "pnl": 0.1, "label": 1}
               for i in range(MIN_TRAIN_SAMPLES - 1)]
    out = train_challenger(samples)
    assert out["status"] == "insufficient_data"
    assert out["required"] == MIN_TRAIN_SAMPLES


def _learnable_samples(n=200, seed=7):
    """Fitur `edge` berkorelasi kuat dgn label; `noise` tidak."""
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        edge = rng.uniform(-1, 1)
        noise = rng.uniform(-1, 1)
        prob = 1 / (1 + pow(2.718281828, -(3.0 * edge)))
        label = 1 if rng.random() < prob else 0
        net = (0.6 if label else -0.5) + rng.uniform(-0.1, 0.1)
        rows.append({"scan_ts": float(i),
                     "features": {"edge": edge, "noise": noise, "score": 70 + edge * 5},
                     "pnl": round(net, 4), "label": label})
    return rows


def test_trains_and_learns_signal():
    out = train_challenger(_learnable_samples())
    assert out["status"] == "trained", out
    assert "edge" in out["features"]
    m = out["model"]
    # prediksi high-edge > low-edge (arah benar)
    hi = predict(m, {"edge": 0.9, "noise": 0.0, "score": 74.5})
    lo = predict(m, {"edge": -0.9, "noise": 0.0, "score": 65.5})
    assert hi > lo
    # ablation: menutup `edge` menaikkan Brier lebih besar dari `noise`
    abl = {a["feature"]: a["brier_delta_without"] for a in out["metrics"]["ablation"]}
    assert abl["edge"] >= abl.get("noise", -1)


def test_metrics_shape_and_calibration_bounds():
    out = train_challenger(_learnable_samples())
    test = out["metrics"]["test"]
    assert test["n"] >= 1
    assert 0.0 <= test["brier"] <= 1.0
    m = out["model"]
    for feats in [{"edge": 0, "noise": 0, "score": 70}, {"edge": 5, "noise": -5, "score": 99}]:
        p = predict(m, feats)
        assert 0.0 <= p <= 1.0     # kalibrasi selalu probabilitas valid


def test_predict_missing_feature_defaults_zero():
    out = train_challenger(_learnable_samples())
    p = predict(out["model"], {})   # semua fitur absen → default 0, tetap valid
    assert 0.0 <= p <= 1.0


def test_chronological_split_no_shuffle():
    # sampel diberi scan_ts menaik; train_challenger harus mengurutkan by scan_ts.
    rows = _learnable_samples()
    shuffled = list(rows)
    random.Random(1).shuffle(shuffled)
    a = train_challenger(rows)
    b = train_challenger(shuffled)
    # hasil identik karena keduanya diurut ulang by scan_ts sebelum split
    assert a["model"]["intercept"] == b["model"]["intercept"]
    assert a["model"]["weights"] == b["model"]["weights"]
