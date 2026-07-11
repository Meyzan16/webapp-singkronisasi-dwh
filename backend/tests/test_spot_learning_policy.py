import math
import asyncio

from agents.opportunity.learning_policy import (
    apply_learning_policy,
    canonical_signal_key,
    deterministic_weight,
    is_profitable_outcome,
    learning_keys,
    normalize_signal,
    wilson_lower_bound,
)
from agents.opportunity.decision_ledger import build_event_rows
from agents.opportunity.outcome_tracker import compute_forward_labels
from agents.learning.spot_walkforward import evaluate_walkforward
from agents.learning.spot_portfolio_replay import replay_portfolio, simulate_trade
from agents.learning.spot_adaptive_model import predict as predict_challenger, train_challenger
from agents.opportunity.feature_engineering import OnchainSnapshot, extract_technical_features
from agents.opportunity import weight_updater as spot_weight_updater
from agents.opportunity.onchain_provider import _base_symbol


def _candidate(**overrides):
    row = {
        "alert_type": "bigmover_chase",
        "signals": ["EMA9 > EMA21 di 1h", "Volume 5x rata-rata"],
        "raw_score": 80.0,
        "opportunity_score": 80.0,
        "auto_open": True,
    }
    row.update(overrides)
    return row


def test_realized_net_pnl_is_outcome_truth() -> None:
    assert is_profitable_outcome(3.505) is True
    assert is_profitable_outcome(-0.01) is False
    assert is_profitable_outcome(0.0) is False
    assert is_profitable_outcome(None) is False


def test_deterministic_weight_does_not_drift_between_runs() -> None:
    first = deterministic_weight(effective_wins=7.0, effective_total=10.0)
    second = deterministic_weight(effective_wins=7.0, effective_total=10.0)

    assert first == second == 1.2


def test_signal_normalization_remains_compatible_with_persisted_keys() -> None:
    assert normalize_signal("EMA9 > EMA21 di 1h") == "eman_eman_di_nh"
    assert canonical_signal_key("EMA9 > EMA21 di 1h") == "signal_id:tech.ema_alignment"


def test_learning_keys_include_alert_and_each_signal() -> None:
    keys = learning_keys(_candidate())

    assert keys[0] == "alert:bigmover_chase"
    assert "signal_id:tech.ema_alignment" in keys
    assert "signal:volume_nx_rata-rata" in keys


def test_learning_can_veto_but_cannot_promote_auto_open() -> None:
    penalized = _candidate()
    apply_learning_policy(
        penalized,
        {"alert:bigmover_chase": 0.7},
        set(),
        auto_threshold=72.0,
    )
    assert penalized["adaptive_score"] == 56.0
    assert penalized["auto_open"] is False

    rejected_by_strategy = _candidate(auto_open=False, raw_score=99.0)
    apply_learning_policy(
        rejected_by_strategy,
        {"alert:bigmover_chase": 1.5},
        set(),
        auto_threshold=72.0,
    )
    assert rejected_by_strategy["auto_open"] is False


def test_probability_uses_empirical_history_not_raw_score() -> None:
    candidate = _candidate(raw_score=99.0)
    apply_learning_policy(
        candidate,
        {"alert:bigmover_chase": 1.0},
        set(),
        auto_threshold=72.0,
        probabilities={"alert:bigmover_chase": 0.58},
        sample_counts={"alert:bigmover_chase": 20},
    )

    assert candidate["estimated_win_probability"] == 0.58
    assert candidate["estimated_win_probability"] != 0.99
    assert candidate["lower_confidence_probability"] < 0.58


def test_wilson_lower_bound_is_more_conservative_for_small_samples() -> None:
    assert wilson_lower_bound(0.7, 10) < wilson_lower_bound(0.7, 100)


def test_signal_level_ban_blocks_auto_open_and_is_explainable() -> None:
    candidate = _candidate()
    banned_key = "signal_id:tech.ema_alignment"

    apply_learning_policy(candidate, {}, {banned_key}, auto_threshold=72.0)

    assert candidate["banned_by_learning"] is True
    assert candidate["learning_blocked_keys"] == [banned_key]
    assert candidate["auto_open"] is False


def test_alert_and_signal_weights_are_combined_without_multiplication() -> None:
    candidate = _candidate()
    apply_learning_policy(
        candidate,
        {
            "alert:bigmover_chase": 1.2,
            "signal_id:tech.ema_alignment": 0.8,
            "signal:volume_nx_rata-rata": 1.0,
        },
        set(),
        auto_threshold=72.0,
    )

    # alert component=1.2; mean signal component=0.9; final=(1.2+0.9)/2
    assert candidate["weight_applied"] == 1.05
    assert candidate["adaptive_score"] == 84.0
    assert len(candidate["learning_contributions"]) == 3


def test_decision_ledger_is_deterministic_and_captures_non_opened_candidates() -> None:
    scan = {
        "generated_at": 1_700_000_000,
        "btc_regime": "ranging",
        "regime_status": "OPEN",
        "learning_status": "active",
        "results": [_candidate(symbol="TESTUSDT", adaptive_score=84.0)],
    }

    first = build_event_rows(scan, set())
    second = build_event_rows(scan, set())

    assert first[0]["decision_key"] == second[0]["decision_key"]
    assert first[0]["action"] == "eligible_not_opened"
    assert first[0]["reason_code"] == "portfolio_or_quota_gate"
    assert first[0]["outcome_status"] == "pending"

    reordered = {**scan, "results": [
        _candidate(symbol="OTHERUSDT", adaptive_score=75.0),
        _candidate(symbol="TESTUSDT", adaptive_score=84.0),
    ]}
    test_row = next(row for row in build_event_rows(reordered, set()) if row["symbol"] == "TESTUSDT")
    assert test_row["decision_key"] == first[0]["decision_key"]


def test_decision_ledger_marks_actual_open_separately_from_eligibility() -> None:
    scan = {
        "generated_at": 1_700_000_001,
        "learning_status": "active",
        "results": [_candidate(symbol="OPENUSDT")],
    }

    row = build_event_rows(scan, {"OPENUSDT"})[0]

    assert row["opened"] is True
    assert row["action"] == "opened"
    assert row["reason_code"] == "opened"


def test_forward_labels_do_not_use_immature_horizons() -> None:
    scan_ts = 1_700_000_000.0
    klines = [
        [
            int((scan_ts + hour * 3600) * 1000),
            100,
            102 + hour,
            98,
            101 + hour,
            1000,
            int((scan_ts + (hour + 1) * 3600 - 0.001) * 1000),
        ]
        for hour in range(5)
    ]

    labels = compute_forward_labels(100.0, scan_ts, klines, scan_ts + 4 * 3600)

    assert labels["pnl_1h_pct"] == 1.0
    assert labels["pnl_4h_pct"] == 4.0
    assert labels["pnl_24h_pct"] is None
    assert labels["outcome_status"] == "partial"
    assert labels["mae_pct"] == -2.0
    assert labels["mfe_pct"] == 5.0


def test_forward_labels_never_use_a_candle_that_closes_after_target() -> None:
    scan_ts = 1_700_000_000.0
    klines = [[
        int(scan_ts * 1000), 100, 150, 90, 140, 1000,
        int((scan_ts + 2 * 3600) * 1000),
    ]]

    labels = compute_forward_labels(100.0, scan_ts, klines, scan_ts + 3600)

    assert labels["pnl_1h_pct"] is None


def test_walkforward_is_purged_and_never_promotes_insufficient_data() -> None:
    small = [
        {"scan_ts": i * 86400.0, "score": 80.0, "pnl_24h_pct": 1.0}
        for i in range(10)
    ]
    assert evaluate_walkforward(small)["promotion_eligible"] is False

    rows = [
        {
            "scan_ts": i * 86400.0,
            "score": 90.0 if i % 2 == 0 else 60.0,
            "pnl_24h_pct": 3.0 if i % 2 == 0 else -2.0,
        }
        for i in range(40)
    ]
    result = evaluate_walkforward(rows)

    assert result["status"] == "ok"
    assert result["embargo_hours"] == 24
    assert result["best_threshold"] > 60.0
    assert result["test"]["expectancy_pct"] > 0


def test_onchain_snapshot_drops_stale_metrics_instead_of_turning_them_to_zero() -> None:
    snapshot = OnchainSnapshot(
        symbol="TESTUSDT",
        observed_at=1_000.0,
        provider="test",
        metrics={"exchange_netflow": -10.0},
        coverage=0.8,
    )

    stale = snapshot.as_features(now=10_000.0, max_age_seconds=60)

    assert stale["fresh"] is False
    assert stale["metrics"] == {}


def test_continuous_technical_features_are_finite() -> None:
    class Data:
        closes = [100.0 + i for i in range(30)]
        highs = [value + 1 for value in closes]
        lows = [value - 1 for value in closes]
        volumes = [1000.0 + i * 10 for i in range(30)]
        ema9 = 126.0
        ema21 = 120.0
        rsi = 61.0
        bb_width = 0.04
        taker_ratio = 0.57

    features = extract_technical_features({"1h": Data()})

    assert features["1h.return_5_pct"] > 0
    assert features["1h.trend_efficiency"] == 1.0
    assert math.isfinite(features["1h.volume_zscore"])


async def test_weight_publications_are_serialized(monkeypatch) -> None:
    active = 0
    max_active = 0

    async def fake_update() -> int:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return 1

    monkeypatch.setattr(spot_weight_updater, "_update_spot_weights_unlocked", fake_update)
    results = await asyncio.gather(
        spot_weight_updater.update_spot_weights(),
        spot_weight_updater.update_spot_weights(),
    )

    assert results == [1, 1]
    assert max_active == 1


def _replay_event(symbol: str, scan_ts: float, candle_high: float, candle_low: float) -> dict:
    return {
        "symbol": symbol, "scan_ts": scan_ts, "entry": 100.0,
        "stop_loss": 95.0, "tp1": 105.0, "tp2": 110.0, "tp3": 120.0,
        "candles": [[scan_ts * 1000, 100, candle_high, candle_low, 102, 1000,
                     (scan_ts + 3600) * 1000]],
    }


def test_replay_uses_conservative_sl_first_and_cost_stress() -> None:
    event = _replay_event("TESTUSDT", 1000.0, candle_high=110.0, candle_low=94.0)
    _, pnl_normal, reason = simulate_trade(event, cost_stress=1.0)
    _, pnl_stressed, _ = simulate_trade(event, cost_stress=1.5)

    assert reason == "sl_hit"
    assert pnl_normal < 0
    assert pnl_stressed < pnl_normal


def test_portfolio_replay_enforces_symbol_dedup_and_capital_slots() -> None:
    events = [
        _replay_event("AAAUSDT", 1000.0, 106.0, 99.0),
        _replay_event("AAAUSDT", 1100.0, 106.0, 99.0),
        _replay_event("BBBUSDT", 1100.0, 106.0, 99.0),
    ]
    result = replay_portfolio(events, max_positions=1)

    assert result["trades"] == 1
    assert result["skipped"]["duplicate_symbol"] == 1
    assert result["skipped"]["slots"] == 1


def test_calibrated_challenger_trains_chronologically_and_predicts() -> None:
    samples = []
    for index in range(100):
        strength = (index % 10) / 10
        label = int(strength >= 0.5)
        samples.append({
            "scan_ts": float(index),
            "features": {"strength": strength, "noise": float(index % 3)},
            "label": label,
            "pnl": 2.0 if label else -1.0,
        })
    result = train_challenger(samples)

    assert result["status"] == "trained"
    low = predict_challenger(result["model"], {"strength": 0.1, "noise": 0.0})
    high = predict_challenger(result["model"], {"strength": 0.9, "noise": 0.0})
    assert 0 <= low <= 1
    assert high > low
    assert result["metrics"]["ablation"]


def test_onchain_symbol_mapping_is_stable() -> None:
    assert _base_symbol("BTCUSDT") == "BTC"
    assert _base_symbol("ETH") == "ETH"
