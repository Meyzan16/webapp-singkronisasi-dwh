"""Calibrated logistic challenger untuk FUTURES decision events (F3).

Mirror agents/learning/spot_adaptive_model.py (engine SPOT tidak disentuh),
dengan kekhususan futures dari plan:
  - Label horizon = 4h (posisi futures hidup jam-an; SPOT pakai 24h).
  - Label = profitable-NET: pnl_4h_pct − cost_floor per-sampel (true-cost v16),
    bukan cost flat.
  - Feature = feature_snapshot_json F1 (flat numeric) DIKURANGI field turunan
    learning (adaptive_score/weight/probability) & cost (dipakai utk label) →
    hindari kebocoran/sirkularitas.

Model TIDAK memengaruhi keputusan/sizing sampai gate F5 (canary) lolos — ini
hanya melatih shadow. Dependency-light: tanpa numpy/sklearn (identik SPOT).
"""

from __future__ import annotations

import json
import math
import time
from collections import Counter

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.database import AsyncSessionLocal, is_db_available
from app.models.futures_decision_event import FuturesDecisionEvent
from app.models.futures_model_version import FuturesModelVersion

FEATURE_SCHEMA_VERSION = "futures_features_v1"
# Field yang DIKELUARKAN dari fitur challenger — output learning (sirkular) atau
# komponen biaya (dipakai mendefinisikan label, jadi bocor bila jadi fitur).
_EXCLUDE_FEATURES = {
    "adaptive_score", "weight_applied",
    "estimated_win_probability", "lower_confidence_probability",
    "cost_floor_pct", "entry_slippage_pct",
}
_DEFAULT_COST_PCT = 0.20   # fallback net-cost bila cost_floor_pct absen di snapshot
MIN_TRAIN_SAMPLES = 60     # gate data §4
NEW_EVIDENCE_STEP = 50     # latih ulang hanya setelah +50 sampel baru


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, value))))


def _fit_logistic(x: list[list[float]], y: list[int], epochs: int = 300, lr: float = 0.05) -> tuple[float, list[float]]:
    intercept, weights = 0.0, [0.0] * len(x[0])
    for _ in range(epochs):
        grad_i, grad_w = 0.0, [0.0] * len(weights)
        for row, target in zip(x, y):
            error = _sigmoid(intercept + sum(w * v for w, v in zip(weights, row))) - target
            grad_i += error
            for index, value in enumerate(row):
                grad_w[index] += error * value
        n = max(1, len(x))
        intercept -= lr * grad_i / n
        for index in range(len(weights)):
            weights[index] -= lr * (grad_w[index] / n + 0.01 * weights[index])
    return intercept, weights


def _metrics(probabilities: list[float], labels: list[int], net_pnls: list[float]) -> dict:
    """net_pnls sudah NET biaya — selected expectancy tak mengurangi biaya lagi."""
    if not labels:
        return {"n": 0}
    eps = 1e-9
    brier = sum((p - y) ** 2 for p, y in zip(probabilities, labels)) / len(labels)
    logloss = -sum(y * math.log(max(eps, p)) + (1 - y) * math.log(max(eps, 1 - p))
                   for p, y in zip(probabilities, labels)) / len(labels)
    selected = [pnl for p, pnl in zip(probabilities, net_pnls) if p >= 0.55]
    wins = sum(v for v in selected if v > 0)
    losses = abs(sum(v for v in selected if v < 0))
    return {
        "n": len(labels), "brier": round(brier, 5), "log_loss": round(logloss, 5),
        "selected_n": len(selected),
        "selected_expectancy_pct": round(sum(selected) / len(selected), 4) if selected else None,
        "selected_profit_factor": round(wins / losses, 3) if losses > 0 else None,
    }


def train_challenger(samples: list[dict]) -> dict:
    """Chronological 60/20/20, standardisasi, logistic, Platt calibration, ablation.
    samples: [{scan_ts, features:{...}, pnl:net_pct, label:int}]."""
    ordered = sorted(samples, key=lambda row: row["scan_ts"])
    if len(ordered) < MIN_TRAIN_SAMPLES:
        return {"status": "insufficient_data", "n": len(ordered), "required": MIN_TRAIN_SAMPLES}
    coverage = Counter(
        key for row in ordered for key, value in row["features"].items()
        if isinstance(value, (int, float))
    )
    names = sorted(key for key, count in coverage.items() if count / len(ordered) >= 0.80)[:40]
    if not names:
        return {"status": "no_features", "n": len(ordered)}
    split1, split2 = int(len(ordered) * .60), int(len(ordered) * .80)
    train, validation, test = ordered[:split1], ordered[split1:split2], ordered[split2:]
    if not train or not validation or not test:
        return {"status": "insufficient_split", "n": len(ordered)}
    means = [sum(float(row["features"].get(name, 0.0)) for row in train) / len(train) for name in names]
    scales = []
    for index, name in enumerate(names):
        variance = sum((float(row["features"].get(name, 0.0)) - means[index]) ** 2 for row in train) / len(train)
        scales.append(math.sqrt(variance) or 1.0)
    vector = lambda row: [(float(row["features"].get(name, 0.0)) - means[i]) / scales[i]
                          for i, name in enumerate(names)]
    x_train, y_train = [vector(row) for row in train], [row["label"] for row in train]
    intercept, weights = _fit_logistic(x_train, y_train)
    raw_val = [intercept + sum(w * v for w, v in zip(weights, vector(row))) for row in validation]
    cal_intercept, cal_weights = _fit_logistic(
        [[value] for value in raw_val], [row["label"] for row in validation], epochs=200)
    cal_slope = cal_weights[0]

    def predict_row(row: dict, masked: int | None = None) -> float:
        values = vector(row)
        if masked is not None:
            values[masked] = 0.0
        raw = intercept + sum(w * v for w, v in zip(weights, values))
        return _sigmoid(cal_intercept + cal_slope * raw)

    probabilities = [predict_row(row) for row in test]
    labels = [row["label"] for row in test]
    net_pnls = [row["pnl"] for row in test]
    test_metrics = _metrics(probabilities, labels, net_pnls)
    base_rate = sum(row["label"] for row in train) / len(train)
    baseline = _metrics([base_rate] * len(test), labels, net_pnls)
    ablation = []
    for index, name in enumerate(names):
        masked_brier = _metrics([predict_row(row, index) for row in test], labels, net_pnls).get("brier")
        ablation.append({"feature": name, "brier_delta_without": round((masked_brier or 0) - (test_metrics.get("brier") or 0), 6)})
    promotion_eligible = bool(
        test_metrics["n"] >= 20 and test_metrics.get("brier") is not None
        and baseline.get("brier") is not None and test_metrics["brier"] < baseline["brier"]
        and (test_metrics.get("selected_expectancy_pct") or 0) > 0
        and (test_metrics.get("selected_profit_factor") or 0) >= 1.5
    )
    return {
        "status": "trained", "n": len(ordered), "features": names,
        "model": {"features": names, "means": means, "scales": scales,
                  "intercept": intercept, "weights": weights,
                  "calibration_intercept": cal_intercept, "calibration_slope": cal_slope},
        "metrics": {"test": test_metrics, "baseline": baseline,
                    "promotion_eligible": promotion_eligible,
                    "ablation": sorted(ablation, key=lambda row: row["brier_delta_without"], reverse=True)},
    }


def predict(model: dict, features: dict) -> float:
    values = [(float(features.get(name, 0.0)) - model["means"][i]) / model["scales"][i]
              for i, name in enumerate(model["features"])]
    raw = model["intercept"] + sum(w * v for w, v in zip(model["weights"], values))
    return round(_sigmoid(model["calibration_intercept"] + model["calibration_slope"] * raw), 6)


def _sample_from_event(event) -> dict | None:
    """Bangun sampel training dari satu FuturesDecisionEvent ber-outcome-4h."""
    if event.pnl_4h_pct is None:
        return None
    try:
        snapshot = json.loads(event.feature_snapshot_json or "{}")
    except (TypeError, json.JSONDecodeError):
        return None
    features = {
        k: v for k, v in snapshot.items()
        if k not in _EXCLUDE_FEATURES and isinstance(v, (int, float)) and not isinstance(v, bool)
    }
    if not features:
        return None
    cost = float(snapshot.get("cost_floor_pct") or _DEFAULT_COST_PCT)
    net = float(event.pnl_4h_pct) - cost
    return {"scan_ts": event.scan_ts, "features": features, "pnl": round(net, 4),
            "label": int(net > 0)}


async def train_and_register() -> dict:
    """Self-gating: latih hanya bila ≥60 sampel 4h-matang & ada +50 evidence baru.
    Model baru selalu berstatus 'shadow' (tak memengaruhi keputusan sampai F5)."""
    if not is_db_available():
        return {"status": "db_unavailable"}
    async with AsyncSessionLocal() as session:
        events = list((await session.execute(
            select(FuturesDecisionEvent).where(
                FuturesDecisionEvent.pnl_4h_pct.isnot(None)
            ).order_by(FuturesDecisionEvent.scan_ts)
        )).scalars().all())
        latest = (await session.execute(
            select(FuturesModelVersion).order_by(FuturesModelVersion.trained_at.desc()).limit(1)
        )).scalar_one_or_none()

    samples = [s for s in (_sample_from_event(e) for e in events) if s]
    result = train_challenger(samples)
    if result.get("status") != "trained":
        return result
    if latest is not None:
        try:
            previous_n = int(json.loads(latest.metrics_json).get("training_n", 0))
        except (TypeError, json.JSONDecodeError):
            previous_n = 0
        if len(samples) < previous_n + NEW_EVIDENCE_STEP:
            return {"status": "no_new_evidence", "n": len(samples), "next_at": previous_n + NEW_EVIDENCE_STEP}

    version = f"futures-logistic-{int(time.time())}"
    metrics = {**result["metrics"], "training_n": len(samples), "label_horizon": "4h"}
    async with AsyncSessionLocal() as session:
        await session.execute(insert(FuturesModelVersion).values(
            version=version, status="shadow", feature_schema_version=FEATURE_SCHEMA_VERSION,
            model_json=json.dumps(result["model"]), metrics_json=json.dumps(metrics),
            parent_version=(latest.version if latest else None), trained_at=time.time(),
        ).on_conflict_do_nothing(index_elements=["version"]))
        await session.commit()
    return {"status": "registered", "version": version, "metrics": metrics}
