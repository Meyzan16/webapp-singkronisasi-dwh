"""Pure policy helpers for SPOT adaptive learning.

This module deliberately has no database or network imports so the learning
contract can be regression-tested without starting the trading application.
"""

from __future__ import annotations

import re
from typing import Mapping, MutableMapping, Sequence


MIN_WEIGHT = 0.70
MAX_WEIGHT = 1.50


def normalize_signal(raw: str) -> str:
    """Return the legacy-stable key used by existing persisted SPOT weights."""
    cleaned = re.sub(r"[^\w\s%+.\-]", "", raw)
    cleaned = re.sub(r"\d+\.?\d*", "N", cleaned)
    words = cleaned.strip().split()[:4]
    return "_".join(word.lower() for word in words if word)


def signal_key(raw: str) -> str:
    """Return a namespaced signal key for a human-readable signal."""
    return f"signal:{normalize_signal(raw)}"


# Stable IDs are deliberately independent from UI copy, numbers, emoji, and TF
# values. Add new rules when a genuinely new feature is introduced; do not derive
# model identity from translated display text.
_SIGNAL_ID_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("bb squeeze",), "tech.bb_squeeze"),
    (("akumulasi:", "volume"), "flow.volume_accumulation"),
    (("taker buy",), "flow.taker_buy_ratio"),
    (("buy pressure meningkat",), "flow.buy_pressure_surge"),
    (("buy pressure membaik",), "flow.buy_pressure_recovery"),
    (("breakout level",), "tech.near_breakout"),
    (("rsi(15m)", "oversold"), "tech.rsi_15m_oversold"),
    (("rsi(15m)", "zona energi"), "tech.rsi_15m_energy"),
    (("rsi(1h)",), "tech.rsi_1h_energy"),
    (("rsi(4h)",), "tech.rsi_4h_energy"),
    (("rsi", "extended"), "tech.rsi_extended"),
    (("rsi", "momentum zone"), "tech.rsi_momentum"),
    (("ema bullish",), "tech.ema_bullish_multi_tf"),
    (("ema9", "ema21"), "tech.ema_alignment"),
    (("volume naik saat harga turun",), "flow.hidden_strength"),
    (("volume spike",), "flow.volume_spike"),
    (("institutional surge",), "flow.institutional_surge"),
    (("pressure dikonfirmasi",), "flow.volume_pressure"),
    (("konsolidasi kuat",), "flow.consolidation_volume"),
    (("wave awal",), "momentum.wave_early"),
    (("wave matang",), "momentum.wave_mature"),
    (("weekly momentum",), "momentum.weekly"),
    (("masih chasing",), "momentum.chasing_1h"),
    (("early mover",), "momentum.early_mover"),
    (("momentum kuat",), "momentum.strong"),
    # ── Ditambahkan 30 Jul 2026 ────────────────────────────────────────────
    # Audit menemukan 3 keluarga sinyal SPOT masih jatuh ke kunci berbasis TEKS
    # ("Volume 15m 2.3× rata-rata", "Candle 15m +11.0% — breakout candle",
    # "RSI 84 elevated — wave riding"). Kunci teks rapuh: begitu kalimatnya
    # diedit, identitas sinyal berubah dan bobot yang sudah dipelajari jadi
    # yatim (akar bug lama "ganti kalimat = bobot ter-reset").
    # SENGAJA ditaruh di AKHIR: pencocokan first-match-wins, jadi menambah di
    # sini tak menggeser satu pun aturan yang sudah ada.
    (("volume", "rata-rata"), "flow.volume_vs_average"),
    (("breakout candle",), "tech.breakout_candle"),
    (("rsi", "elevated"), "tech.rsi_elevated"),
)


def canonical_signal_key(raw: str) -> str | None:
    """Map display copy to a maintained immutable feature ID."""
    normalized = raw.casefold()
    for required_parts, stable_id in _SIGNAL_ID_RULES:
        if all(part in normalized for part in required_parts):
            return f"signal_id:{stable_id}"
    return None


def is_profitable_outcome(pnl_pct: float | None) -> bool:
    """Use realized net outcome as truth, independent of close-reason/status."""
    return pnl_pct is not None and pnl_pct > 0


def target_weight(adjusted_win_rate: float) -> float:
    """Map a smoothed win rate to the current bounded policy weight."""
    if adjusted_win_rate >= 0.70:
        return 1.50
    if adjusted_win_rate >= 0.55:
        return 1.20
    if adjusted_win_rate >= 0.40:
        return 1.00
    return 0.70


def deterministic_weight(effective_wins: float, effective_total: float) -> float:
    """Compute weight directly from evidence; repeated runs cannot drift it."""
    if effective_total <= 0:
        return 1.0
    adjusted = (effective_wins + 1.0) / (effective_total + 2.0)
    confidence = min(1.0, effective_total / 10.0)
    desired = 1.0 + (target_weight(adjusted) - 1.0) * confidence
    return round(max(MIN_WEIGHT, min(MAX_WEIGHT, desired)), 3)


def wilson_lower_bound(probability: float, sample_count: int, z: float = 1.64) -> float:
    """One-sided ~95% conservative bound used for capital decisions."""
    if sample_count <= 0:
        return 0.0
    n = float(sample_count)
    denominator = 1 + z * z / n
    center = probability + z * z / (2 * n)
    margin = z * ((probability * (1 - probability) / n + z * z / (4 * n * n)) ** 0.5)
    return round(max(0.0, (center - margin) / denominator), 4)


def learning_keys(result: Mapping[str, object]) -> list[str]:
    """Return alert + individual signal keys contributing to a decision."""
    keys: list[str] = []
    alert_type = str(result.get("alert_type") or "").strip()
    if alert_type:
        keys.append(f"alert:{alert_type}")
    signals = result.get("signals")
    if isinstance(signals, Sequence) and not isinstance(signals, (str, bytes)):
        for signal in signals[:5]:
            raw = str(signal)
            if not raw.strip():
                continue
            keys.append(canonical_signal_key(raw) or signal_key(raw))
    return keys


def apply_learning_policy(
    result: MutableMapping[str, object],
    weights: Mapping[str, float],
    banned_keys: set[str],
    auto_threshold: float,
    probabilities: Mapping[str, float] | None = None,
    sample_counts: Mapping[str, int] | None = None,
) -> MutableMapping[str, object]:
    """Attach an explainable adaptive score and safely gate auto-open.

    During the pre-validation phase learning may veto an existing auto-open, but
    it may not promote a candidate that the deterministic strategy rejected.
    """
    keys = learning_keys(result)
    learned = [(key, float(weights[key])) for key in keys if key in weights]

    alert_weights = [weight for key, weight in learned if key.startswith("alert:")]
    signal_weights = [weight for key, weight in learned if not key.startswith("alert:")]
    components: list[float] = []
    if alert_weights:
        components.append(sum(alert_weights) / len(alert_weights))
    if signal_weights:
        components.append(sum(signal_weights) / len(signal_weights))
    factor = sum(components) / len(components) if components else 1.0
    factor = round(max(MIN_WEIGHT, min(MAX_WEIGHT, factor)), 3)

    raw_score = float(result.get("raw_score") or result.get("opportunity_score") or 0.0)
    adaptive_score = round(raw_score * factor, 1)
    blocked_keys = sorted(set(keys).intersection(banned_keys))
    original_auto_open = bool(result.get("auto_open"))
    probabilities = probabilities or {}
    sample_counts = sample_counts or {}
    learned_probabilities = [float(probabilities[key]) for key in keys if key in probabilities]
    estimated_probability = (
        round(max(0.05, min(0.95, sum(learned_probabilities) / len(learned_probabilities))), 4)
        if learned_probabilities else None
    )
    evidence_counts = [int(sample_counts[key]) for key in keys if key in probabilities and key in sample_counts]
    conservative_n = min(evidence_counts) if evidence_counts else 0
    lower_probability = (
        wilson_lower_bound(estimated_probability, conservative_n)
        if estimated_probability is not None else None
    )

    result["weight_applied"] = factor
    result["adaptive_score"] = adaptive_score
    result["opportunity_score"] = round(min(adaptive_score, 99.0), 1)
    result["learning_keys"] = keys
    result["learning_contributions"] = [
        {"key": key, "weight": round(weight, 3)} for key, weight in learned
    ]
    result["banned_by_learning"] = bool(blocked_keys)
    result["learning_blocked_keys"] = blocked_keys
    result["estimated_win_probability"] = estimated_probability
    result["probability_source"] = "historical_laplace" if estimated_probability is not None else "unavailable"
    result["probability_sample_count"] = conservative_n
    result["lower_confidence_probability"] = lower_probability
    result["auto_open"] = bool(
        original_auto_open and not blocked_keys and adaptive_score >= auto_threshold
    )
    return result
