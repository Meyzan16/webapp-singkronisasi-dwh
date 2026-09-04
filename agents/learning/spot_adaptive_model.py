"""Dependency-light calibrated logistic challenger for SPOT decision events."""

from __future__ import annotations

import asyncio
import json
import math
import time
from collections import Counter

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.database import AsyncSessionLocal, is_db_available
from app.models.spot_decision_event import SpotDecisionEvent
from app.models.spot_model_version import SpotModelVersion
from app.services.trading_costs import EXECUTION_COST_PCT
# Ambang gate engine dari satu sumber — lihat app/services/engine_gates.py.
# Dulu angka telanjang (60 / 20) yang terpisah dari gate yang ditampilkan panel
# Engine, sehingga keduanya bisa menyimpang tanpa ketahuan.
from app.services.engine_gates import (
    test_gate as _test_gate,
    MIN_CANARY_OBSERVATIONS as _MIN_CANARY_OBS,
)


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, value))))


def _fit_logistic(x: list[list[float]], y: list[int], epochs: int = 300, lr: float = 0.05) -> tuple[float, list[float]]:
    intercept, weights = 0.0, [0.0] * len(x[0])
    for _ in range(epochs):
        grad_i, grad_w = 0.0, [0.0] * len(weights)
        for row, target in zip(x, y):
            error = _sigmoid(intercept + sum(w * value for w, value in zip(weights, row))) - target
            grad_i += error
            for index, value in enumerate(row):
                grad_w[index] += error * value
        n = max(1, len(x))
        intercept -= lr * grad_i / n
        for index in range(len(weights)):
            weights[index] -= lr * (grad_w[index] / n + 0.01 * weights[index])
    return intercept, weights


def _metrics(probabilities: list[float], labels: list[int], pnls: list[float]) -> dict:
    if not labels:
        return {"n": 0}
    eps = 1e-9
    brier = sum((p - y) ** 2 for p, y in zip(probabilities, labels)) / len(labels)
    logloss = -sum(y * math.log(max(eps, p)) + (1-y) * math.log(max(eps, 1-p)) for p, y in zip(probabilities, labels)) / len(labels)
    selected = [pnl - EXECUTION_COST_PCT for p, pnl in zip(probabilities, pnls) if p >= 0.55]
    wins, losses = sum(v for v in selected if v > 0), abs(sum(v for v in selected if v < 0))
    return {
        "n": len(labels), "brier": round(brier, 5), "log_loss": round(logloss, 5),
        "selected_n": len(selected),
        "selected_expectancy_pct": round(sum(selected) / len(selected), 4) if selected else None,
        "selected_profit_factor": round(wins / losses, 3) if losses > 0 else None,
    }


def train_challenger(samples: list[dict]) -> dict:
    """Chronological 60/20/20 training, Platt calibration, and ablation report."""
    ordered = sorted(samples, key=lambda row: row["scan_ts"])
    # Ambang dari app.services.engine_gates — dulu angka telanjang di sini,
    # terpisah dari gate yang ditampilkan panel Engine.
    from app.services.engine_gates import MIN_TRAIN_SAMPLES
    if len(ordered) < MIN_TRAIN_SAMPLES:
        return {"status": "insufficient_data", "n": len(ordered), "required": MIN_TRAIN_SAMPLES}
    coverage = Counter(key for row in ordered for key, value in row["features"].items() if isinstance(value, (int, float)))
    names = sorted(key for key, count in coverage.items() if count / len(ordered) >= 0.80)[:40]
    if not names:
        return {"status": "no_features", "n": len(ordered)}
    split1, split2 = int(len(ordered) * .60), int(len(ordered) * .80)
    train, validation, test = ordered[:split1], ordered[split1:split2], ordered[split2:]
    means = [sum(float(row["features"].get(name, 0.0)) for row in train) / len(train) for name in names]
    scales = []
    for index, name in enumerate(names):
        variance = sum((float(row["features"].get(name, 0.0)) - means[index]) ** 2 for row in train) / len(train)
        scales.append(math.sqrt(variance) or 1.0)
    vector = lambda row: [(float(row["features"].get(name, 0.0)) - means[i]) / scales[i] for i, name in enumerate(names)]
    x_train, y_train = [vector(row) for row in train], [row["label"] for row in train]
    intercept, weights = _fit_logistic(x_train, y_train)
    raw_val = [intercept + sum(w*v for w, v in zip(weights, vector(row))) for row in validation]
    cal_intercept, cal_weights = _fit_logistic([[value] for value in raw_val], [row["label"] for row in validation], epochs=200)
    cal_slope = cal_weights[0]
    def predict(row: dict, masked: int | None = None) -> float:
        values = vector(row)
        if masked is not None:
            values[masked] = 0.0
        raw = intercept + sum(w*v for w, v in zip(weights, values))
        return _sigmoid(cal_intercept + cal_slope * raw)
    probabilities = [predict(row) for row in test]
    labels, pnls = [row["label"] for row in test], [row["pnl"] for row in test]
    test_metrics = _metrics(probabilities, labels, pnls)
    base_rate = sum(row["label"] for row in train) / len(train)
    baseline = _metrics([base_rate] * len(test), labels, pnls)
    ablation = []
    for index, name in enumerate(names):
        masked_brier = _metrics([predict(row, index) for row in test], labels, pnls).get("brier")
        ablation.append({"feature": name, "brier_delta_without": round((masked_brier or 0) - test_metrics["brier"], 6)})
    promotion_eligible = bool(
        _test_gate(test_metrics["n"]) and test_metrics["brier"] < baseline["brier"]
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
    values = [(float(features.get(name, 0.0)) - model["means"][i]) / model["scales"][i] for i, name in enumerate(model["features"])]
    raw = model["intercept"] + sum(w*v for w, v in zip(model["weights"], values))
    return round(_sigmoid(model["calibration_intercept"] + model["calibration_slope"] * raw), 6)


async def train_and_register() -> dict:
    if not is_db_available():
        return {"status": "db_unavailable"}
    async with AsyncSessionLocal() as session:
        # Ambil HANYA 3 kolom yang dipakai, bukan hydrate ratusan ribu objek ORM
        # penuh (pola yang sama sudah dipakai spot_walkforward.py). Membangun
        # entitas ORM untuk ~322rb baris adalah kerja Python yang terjadi DI event
        # loop — terukur menahan request lain sampai 86 detik. Row hasil select
        # kolom tetap punya akses atribut (.scan_ts, dst) jadi pemakainya tak berubah.
        # ALIRKAN hasilnya, jangan tarik sekaligus. Ledger ini ratusan ribu baris dan
        # tiap baris membawa blob JSON, jadi satu execute() menahan event loop sampai
        # SELURUH hasil masuk memori — terukur 94 detik backend tak menjawab apa pun.
        # `.partitions()` membuat baris datang per potongan, dan `async for` memberi
        # loop kesempatan melayani request lain di sela tiap potongan. Baris dan
        # urutannya SAMA PERSIS seperti sebelumnya — hasil latihan tidak berubah.
        events = []
        stream = await session.stream(
            select(
                SpotDecisionEvent.scan_ts,
                SpotDecisionEvent.pnl_24h_pct,
                SpotDecisionEvent.feature_snapshot_json,
            ).where(SpotDecisionEvent.pnl_24h_pct.isnot(None))
             .order_by(SpotDecisionEvent.scan_ts)
             .execution_options(yield_per=5_000)
        )
        async for partition in stream.partitions(5_000):
            events.extend(partition)
        latest = (await session.execute(select(SpotModelVersion).order_by(
            SpotModelVersion.trained_at.desc()
        ).limit(1))).scalar_one_or_none()
    # Melatih model = kerja CPU murni (json.loads per baris + fitting) atas SELURUH
    # ledger. Dijalankan langsung di event loop, ia MENAHAN seluruh backend selama
    # puluhan detik sampai menit: koneksi DB tergantung "idle in transaction /
    # ClientRead" karena sisi Python berhenti membaca, dan request FE apa pun ikut
    # antre — persis gejala layar menggantung + "socket hang up".
    # Terukur 4 Sep 2026 (ledger 387.390 baris): /balance/futures sampai 119 detik.
    def _build_and_train() -> tuple[list, dict]:
        samples = []
        for event in events:
            try:
                snapshot = json.loads(event.feature_snapshot_json or "{}")
                features = snapshot.get("challenger_features") or {}
            except (TypeError, json.JSONDecodeError):
                continue
            if features:
                pnl = float(event.pnl_24h_pct)
                samples.append({"scan_ts": event.scan_ts, "features": features, "pnl": pnl, "label": int(pnl > EXECUTION_COST_PCT)})
        return samples, train_challenger(samples)

    samples, result = await asyncio.to_thread(_build_and_train)
    if result.get("status") != "trained":
        return result
    if latest is not None:
        try:
            previous_n = int(json.loads(latest.metrics_json).get("training_n", 0))
        except (TypeError, json.JSONDecodeError):
            previous_n = 0
        if len(samples) < previous_n + 50:
            return {"status": "no_new_evidence", "n": len(samples), "next_at": previous_n + 50}
    version = f"spot-logistic-{int(time.time())}"
    metrics = {**result["metrics"], "training_n": len(samples)}
    async with AsyncSessionLocal() as session:
        await session.execute(insert(SpotModelVersion).values(
            version=version, status="shadow", feature_schema_version="spot_features_v1",
            model_json=json.dumps(result["model"]), metrics_json=json.dumps(metrics), trained_at=time.time(),
        ).on_conflict_do_nothing(index_elements=["version"]))
        await session.commit()
    return {"status": "registered", "version": version, "metrics": metrics}


async def score_shadow_candidates(scan_result: dict) -> None:
    """Attach shadow probabilities without affecting production decisions."""
    if not is_db_available():
        return
    async with AsyncSessionLocal() as session:
        row = (await session.execute(
            select(SpotModelVersion).where(
                SpotModelVersion.status.in_(["shadow", "canary"])
            ).order_by(SpotModelVersion.trained_at.desc()).limit(1)
        )).scalar_one_or_none()
    if row is None:
        return
    model = json.loads(row.model_json)
    for candidate in scan_result.get("_decision_events", scan_result.get("results", [])):
        features = candidate.get("challenger_features") or {}
        if features:
            candidate["shadow_probability"] = predict(model, features)
            candidate["shadow_model_version"] = row.version


async def start_canary(version: str) -> dict:
    """Move an eligible shadow to canary; it still cannot control sizing."""
    async with AsyncSessionLocal() as session:
        row = (await session.execute(select(SpotModelVersion).where(SpotModelVersion.version == version))).scalar_one_or_none()
        if row is None:
            return {"status": "not_found"}
        metrics = json.loads(row.metrics_json)
        if not metrics.get("promotion_eligible"):
            return {"status": "blocked", "reason": "offline_gate_failed"}
        row.status = "canary"
        await session.commit()
    return {"status": "canary", "version": version}


async def finalize_canary(version: str, observed: dict) -> dict:
    """Promote only after explicit paper-canary evidence meets every gate."""
    eligible = bool(
        int(observed.get("n", 0)) >= _MIN_CANARY_OBS
        and float(observed.get("expectancy_pct", 0)) > 0
        and float(observed.get("profit_factor", 0)) >= 1.5
        and float(observed.get("max_drawdown_pct", 999)) <= 10.0
    )
    if not eligible:
        return {"status": "blocked", "reason": "canary_gate_failed"}
    now = time.time()
    async with AsyncSessionLocal() as session:
        candidate = (await session.execute(select(SpotModelVersion).where(
            SpotModelVersion.version == version, SpotModelVersion.status == "canary"
        ))).scalar_one_or_none()
        if candidate is None:
            return {"status": "not_found_or_not_canary"}
        champions = list((await session.execute(select(SpotModelVersion).where(SpotModelVersion.status == "champion"))).scalars().all())
        for champion in champions:
            champion.status = "retired"
            champion.retired_at = now
        candidate.status = "champion"
        candidate.promoted_at = now
        metrics = json.loads(candidate.metrics_json)
        metrics["canary"] = observed
        candidate.metrics_json = json.dumps(metrics)
        await session.commit()
    return {"status": "champion", "version": version}


async def rollback_champion(reason: str) -> dict:
    """Rollback to the most recently retired last-known-good champion."""
    now = time.time()
    async with AsyncSessionLocal() as session:
        champion = (await session.execute(select(SpotModelVersion).where(
            SpotModelVersion.status == "champion"
        ).order_by(SpotModelVersion.promoted_at.desc()).limit(1))).scalar_one_or_none()
        previous = (await session.execute(select(SpotModelVersion).where(
            SpotModelVersion.status == "retired"
        ).order_by(SpotModelVersion.retired_at.desc()).limit(1))).scalar_one_or_none()
        if champion is None or previous is None:
            return {"status": "blocked", "reason": "no_rollback_pair"}
        champion.status = "rolled_back"
        champion.retired_at = now
        champion.rollback_reason = reason[:160]
        previous.status = "champion"
        previous.promoted_at = now
        await session.commit()
    return {"status": "rolled_back", "from": champion.version, "to": previous.version}


async def monitor_champion_drift() -> dict:
    """Automatically rollback a champion on sustained calibrated/outcome drift."""
    if not is_db_available():
        return {"status": "db_unavailable"}
    async with AsyncSessionLocal() as session:
        champion = (await session.execute(select(SpotModelVersion).where(
            SpotModelVersion.status == "champion"
        ).order_by(SpotModelVersion.promoted_at.desc()).limit(1))).scalar_one_or_none()
        if champion is None:
            return {"status": "no_champion"}
        events = list((await session.execute(select(SpotDecisionEvent).where(
            SpotDecisionEvent.pnl_24h_pct.isnot(None)
        ).order_by(SpotDecisionEvent.scan_ts.desc()).limit(200))).scalars().all())
    observations = []
    for event in events:
        try:
            snapshot = json.loads(event.feature_snapshot_json or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        if snapshot.get("shadow_model_version") != champion.version:
            continue
        probability = snapshot.get("shadow_probability")
        if probability is not None:
            observations.append((float(probability), float(event.pnl_24h_pct)))
        if len(observations) >= 50:
            break
    if len(observations) < 20:
        return {"status": "insufficient_data", "n": len(observations)}
    brier = sum((p - int(pnl > EXECUTION_COST_PCT)) ** 2 for p, pnl in observations) / len(observations)
    selected = [pnl - EXECUTION_COST_PCT for p, pnl in observations if p >= 0.55]
    expectancy = sum(selected) / len(selected) if selected else -1.0
    if brier > 0.30 or expectancy <= 0:
        return await rollback_champion(f"auto drift: brier={brier:.3f}, expectancy={expectancy:.3f}")
    return {"status": "healthy", "n": len(observations), "brier": round(brier, 4), "expectancy": round(expectancy, 4)}
