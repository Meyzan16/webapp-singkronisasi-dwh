"""Tests F1 — futures decision ledger + outcome labels (bagian pure, tanpa DB)."""

import json
import os
import sys

# Repo root ke path (modul `agents` satu level di atas backend/) — lokal di file
# ini supaya pytest.ini bersama milik suite SPOT tidak perlu disentuh.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from agents.futures.decision_ledger import (  # noqa: E402
    FEATURE_SCHEMA_VERSION,
    MODEL_VERSION,
    build_event_rows,
    classify_action,
)
from agents.futures.outcome_tracker import compute_forward_labels  # noqa: E402


def _candidate(**overrides):
    row = {
        "symbol": "TESTUSDT",
        "agent": "futures_agent3",
        "direction": "LONG",
        "setup_type": "momentum",
        "score": 74.0,
        "price": 100.0,
        "change_24h": 9.3,
        "funding_rate": 0.012,
        "oi_change": 2.1,
        "atr_pct": 1.8,
        "risk_pct": 2.2,
        "tp1_pct": 2.2,
        "tp2_pct": 5.5,
        "rr_ratio": 2.5,
        "leverage": 4,
        "signals": ["🚀 Momentum +9.3% — sweet spot entry"],
    }
    row.update(overrides)
    return row


# ── classify_action ───────────────────────────────────────────────────────────

def test_classify_action_mapping():
    assert classify_action("opened", True) == "opened"
    assert classify_action("opened", False) == "opened"
    assert classify_action("daily_gate_blocked", False) == "blocked"
    assert classify_action("risk_gate_blocked", False) == "blocked"
    assert classify_action("consec_sl_global_pause", False) == "blocked"
    assert classify_action("below_auto_threshold", False) == "recommendation"
    assert classify_action("not_evaluated", False) == "recommendation"
    for guard in ["cost_floor_skip", "direction_cap", "lane_quota_full",
                  "funding_hard_skip", "breadth_fade_skip", "bm_daily_sl_stop",
                  "sizing_blocked", "sl_cooldown", "dedup_lost", "profit_lock_skip"]:
        assert classify_action(guard, False) == "rejected", guard


# ── build_event_rows ──────────────────────────────────────────────────────────

def test_rows_deterministic_and_idempotent_key():
    cands = [_candidate()]
    decisions = {("TESTUSDT", "futures_agent3", "LONG"): "opened"}
    rows_a = build_event_rows(cands, decisions, scan_ts=1783700000.0)
    rows_b = build_event_rows(cands, decisions, scan_ts=1783700000.0)
    assert rows_a[0]["decision_key"] == rows_b[0]["decision_key"]     # retry-safe
    rows_c = build_event_rows(cands, decisions, scan_ts=1783700120.0)
    assert rows_c[0]["decision_key"] != rows_a[0]["decision_key"]     # scan lain = key lain


def test_rows_action_reason_and_flags():
    cands = [
        _candidate(),
        _candidate(symbol="AAAUSDT", agent="futures_agent1",
                   setup_type="pre_gainer", score=58.0),
        _candidate(symbol="BBBUSDT", agent="futures_agent_bigmover",
                   setup_type="bigmover", direction="SHORT", score=68.0),
    ]
    decisions = {
        ("TESTUSDT", "futures_agent3", "LONG"): "opened",
        ("AAAUSDT", "futures_agent1", "LONG"): "below_auto_threshold",
        ("BBBUSDT", "futures_agent_bigmover", "SHORT"): "cost_floor_skip",
    }
    rows = {r["symbol"]: r for r in build_event_rows(cands, decisions, scan_ts=1783700000.0)}
    assert rows["TESTUSDT"]["action"] == "opened" and rows["TESTUSDT"]["opened"] is True
    assert rows["AAAUSDT"]["action"] == "recommendation" and rows["AAAUSDT"]["auto_eligible"] is False
    assert rows["BBBUSDT"]["action"] == "rejected" and rows["BBBUSDT"]["auto_eligible"] is True
    assert rows["BBBUSDT"]["direction"] == "SHORT" and rows["BBBUSDT"]["lane"] == "bigmover"
    assert rows["TESTUSDT"]["model_version"] == MODEL_VERSION
    assert rows["TESTUSDT"]["feature_schema_version"] == FEATURE_SCHEMA_VERSION


def test_rows_dedup_keeps_highest_score():
    cands = [_candidate(score=70.0), _candidate(score=82.0)]
    rows = build_event_rows(cands, {}, scan_ts=1783700000.0)
    assert len(rows) == 1
    assert rows[0]["score"] == 82.0
    assert rows[0]["reason_code"] == "not_evaluated"


def test_feature_snapshot_numeric_only_and_breadth():
    cand = _candidate(regime="trending_up", signals=["abc"], cost_floor_pct=0.42)
    rows = build_event_rows([cand], {}, scan_ts=1783700000.0,
                            breadth={"fade_frac": 0.61, "gainers": 12, "fading": 8})
    feats = json.loads(rows[0]["feature_snapshot_json"])
    assert feats["score"] == 74.0
    assert feats["cost_floor_pct"] == 0.42
    assert feats["breadth_fade_frac"] == 0.61
    assert feats["breadth_gainers"] == 12.0
    for value in feats.values():
        assert isinstance(value, float)        # snapshot murni numerik
    assert "signals" not in feats and "regime" not in feats
    assert rows[0]["regime"] == "trending_up"  # regime hidup sebagai kolom
    assert rows[0]["cost_floor_pct"] == 0.42


def test_rows_skip_empty_symbol():
    assert build_event_rows([_candidate(symbol="")], {}, scan_ts=1.0) == []


# ── compute_forward_labels ────────────────────────────────────────────────────

def _klines(scan_ts: float, closes: list[float], step: int = 900) -> list:
    """15m klines mulai tepat di scan_ts."""
    return [[(scan_ts + i * step) * 1000, 0, 0, 0, str(c)] for i, c in enumerate(closes)]


def test_forward_labels_long_and_short():
    scan_ts = 1_783_700_000.0
    # closes: +1% di 30m, +2% di 1h, dst (candle index 2 = menit 30, index 4 = jam 1)
    closes = [100.0, 100.5, 101.0, 101.5, 102.0] + [103.0] * 30
    kl = _klines(scan_ts, closes)
    now = scan_ts + 5 * 3600   # 4h due, 24h belum

    long_lbl = compute_forward_labels("LONG", 100.0, kl, scan_ts, now=now)
    assert long_lbl["pnl_30m_pct"] == 1.0     # close candle yang memuat +30m
    assert long_lbl["pnl_1h_pct"] == 2.0
    assert long_lbl["pnl_4h_pct"] == 3.0
    assert "pnl_24h_pct" not in long_lbl      # belum jatuh tempo

    short_lbl = compute_forward_labels("SHORT", 100.0, kl, scan_ts, now=now)
    assert short_lbl["pnl_30m_pct"] == -1.0   # direction-aware
    assert short_lbl["pnl_4h_pct"] == -3.0


def test_forward_labels_guards():
    assert compute_forward_labels("LONG", 0.0, _klines(1.0, [100]), 1.0) == {}
    assert compute_forward_labels("LONG", 100.0, [], 1.0) == {}
    # klines dimulai SETELAH target (data hilang) → horizon dilewati tanpa label
    scan_ts = 1_783_700_000.0
    late = _klines(scan_ts + 7200, [100.0] * 4)
    lbl = compute_forward_labels("LONG", 100.0, late, scan_ts, now=scan_ts + 3600)
    assert "pnl_30m_pct" not in lbl and "pnl_1h_pct" not in lbl
