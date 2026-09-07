"""Pure policy helpers for FUTURES adaptive learning (PLAN_ADAPTIVE_LEARNING_FUTURES_10X F0).

Mirror of agents/opportunity/learning_policy.py (SPOT) — module SPOT tidak disentuh.
Sengaja tanpa import database/network supaya kontrak learning bisa diregresi-test
tanpa menjalankan aplikasi trading.

Prinsip terkunci (sama dengan SPOT): learning boleh MEM-VETO auto-open, tidak boleh
MEMPROMOSIKAN kandidat yang ditolak strategi deterministik.
"""

from __future__ import annotations

import re
from typing import Mapping, MutableMapping, Sequence


MIN_WEIGHT = 0.70
MAX_WEIGHT = 1.50


def normalize_signal(raw: str) -> str:
    """Legacy-stable key — identik dgn weight_updater._normalize_signal supaya
    bobot futures yang sudah tersimpan tetap terbaca (dual-read)."""
    cleaned = re.sub(r"[^\w\s%+.\-]", "", raw)
    cleaned = re.sub(r"\d+\.?\d*", "N", cleaned)
    words = cleaned.strip().split()[:4]
    return "_".join(word.lower() for word in words if word)


def signal_key(raw: str) -> str:
    """Namespaced fallback key untuk sinyal yang belum punya canonical ID."""
    return f"signal:{normalize_signal(raw)}"


# Stable feature IDs — SENGAJA independen dari copy UI, angka, emoji, dan nilai TF.
# Identitas fitur TIDAK boleh ikut berubah ketika teks sinyal di agent diedit
# (akar bug lama: normalize regex dari copy → ganti kalimat = bobot ter-reset).
# Urutan PENTING: rule paling spesifik dulu (first match wins).
# Sumber copy: agent1 (pre-gainer/pre-dump), agent2 (accumulation/distribution),
# agent3 (momentum LONG/SHORT), agent_bigmover — kondisi pasca item H.
_SIGNAL_ID_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    # ── Agentic (Fase 3) — PALING ATAS, sebelum rule generik ────────────────
    # Kenapa harus punya identitasnya sendiri, diukur 6 Sep 2026:
    #   * tiga tingkat momentum semuanya jatuh ke `bm.magnitude` karena teksnya
    #     memuat "Δ24h" — resolusi tingkat hilang, padahal justru itu yang
    #     membedakan gerak awal dari yang sudah parabolik;
    #   * `arah_1h_konfirmasi +2,5%` dan `-2,5%` menghasilkan DUA kunci berbeda
    #     lewat jalur fallback (`+n%` vs `-n%`), sehingga sampel LONG dan SHORT
    #     tak pernah menyatu;
    #   * sisanya sama sekali tak punya canonical ID, jadi TAK TERLIHAT oleh
    #     Predictive Repair — persis bug 29 Jul 2026 ketika 49 aksi perbaikan
    #     tercatat "berhasil" tapi berdampak nol karena namespace-nya tak
    #     beririsan.
    # Urutan di dalam blok ini juga penting: yang lebih spesifik lebih dulu
    # (`oi_naik_tipis` sebelum `oi_naik`, `volume_naik` sesudah `volume_konfirmasi`).
    (("momentum_awal",),      "ag.momentum_awal"),
    (("momentum_mapan",),     "ag.momentum_mapan"),
    (("momentum_kuat",),      "ag.momentum_kuat"),
    (("momentum_ekstrem",),   "ag.momentum_ekstrem"),
    (("arah_1h_konfirmasi",), "ag.arah_konfirmasi"),
    (("arah_1h_datar",),      "ag.arah_datar"),
    (("arah_1h_berlawanan",), "ag.arah_berlawanan"),
    (("volume_konfirmasi",),  "ag.volume_konfirmasi"),
    (("volume_memudar",),     "ag.volume_memudar"),
    (("volume_naik",),        "ag.volume_naik"),
    (("oi_naik_tipis",),      "ag.oi_naik_tipis"),
    (("oi_turun",),           "ag.oi_turun"),
    (("oi_naik",),            "ag.oi_naik"),
    (("funding_netral",),     "ag.funding_netral"),
    (("funding_wajar",),      "ag.funding_wajar"),
    (("funding_sesak",),      "ag.funding_sesak"),
    (("rsi_sehat",),          "ag.rsi_sehat"),
    (("rsi_jenuh",),          "ag.rsi_jenuh"),
    # ── BigMover (Δ24h khas lane ini — sebelum rule momentum generik) ────────
    (("δ24h",), "bm.magnitude"),
    (("kontra arah",), "bm.reverse_1h"),
    (("re-entry zone",), "bm.pullback_1h"),
    (("masih dump",), "bm.confirm_1h"),
    (("confirm", "searah momentum"), "bm.confirm_1h"),
    # ── Early breakout a3 — SEBELUM blok OI (string-nya mengandung "OI +") ───
    (("early breakout",), "tech.early_breakout"),
    # ── Wyckoff (dual-TF sebelum accumulation generik) ───────────────────────
    (("4h+1h konfirmasi",), "wyckoff.dual_tf"),
    (("wyckoff accumulation",), "wyckoff.accumulation"),
    (("wyckoff markup",), "wyckoff.markup"),
    (("wyckoff distribution",), "wyckoff.distribution"),
    (("wyckoff markdown",), "wyckoff.markdown"),
    # ── BB squeeze (varian puncak/persistence sebelum generik) ────────────────
    (("squeeze", "beruntun"), "tech.squeeze_persistence"),
    (("coiling ideal",), "tech.flat_coil"),   # sebelum bb generik: copy-nya memuat "BB Squeeze"
    (("bb squeeze", "puncak"), "tech.bb_squeeze_top"),
    (("kompresi di area resistance",), "tech.bb_squeeze_top"),
    (("bb squeeze",), "tech.bb_squeeze"),
    (("kompresi sedang",), "tech.bb_squeeze"),
    # ── Volume / order flow ───────────────────────────────────────────────────
    (("volume akumulasi",), "flow.volume_accumulation"),
    (("akumulasi terbentuk",), "flow.volume_accumulation"),
    (("volume distribusi",), "flow.volume_distribution"),
    (("potensi distribusi",), "flow.volume_distribution"),
    (("baseline",), "flow.volume_zscore"),          # "…σ vs baseline 200 candle" / "di atas baseline 1h"
    (("saat naik", "volume"), "flow.volume_momentum"),
    (("saat turun", "volume"), "flow.volume_momentum"),
    (("momentum terkonfirmasi",), "flow.volume_momentum"),
    (("short terkonfirmasi",), "flow.volume_momentum"),   # "momentum SHORT terkonfirmasi"
    (("pressure dikonfirmasi",), "flow.volume_momentum"),
    (("zona s/r",), "flow.volume_at_zone"),
    (("buy pressure",), "flow.buy_pressure"),
    (("sell pressure",), "flow.sell_pressure"),
    # ── Open interest ─────────────────────────────────────────────────────────
    (("oi acceleration",), "flow.oi_acceleration"),
    (("long trap",), "flow.oi_long_trap"),
    (("oi turun",), "flow.oi_divergence"),
    (("bukan real long",), "flow.oi_divergence"),
    (("short positioning",), "flow.oi_short_conviction"),
    (("short conviction",), "flow.oi_short_conviction"),
    (("oi +",), "flow.oi_rising"),
    # ── Funding (negatif SEBELUM tinggi/ekstrem: "negatif ekstrem" = negatif) ─
    (("funding", "negatif"), "fund.negative_funding"),
    (("funding", "ekstrem"), "fund.high_funding"),
    (("funding", "tinggi"), "fund.high_funding"),
    (("funding", "crowded"), "fund.high_funding"),
    # ── Liquidation proxy ─────────────────────────────────────────────────────
    (("short squeeze terdeteksi",), "flow.liq_short_proxy"),
    (("long liquidation",), "flow.liq_long_proxy"),
    (("long liq",), "flow.liq_long_proxy"),
    # ── Level / struktur harga ───────────────────────────────────────────────
    (("break", "ath"), "tech.ath_break"),
    (("near", "ath"), "tech.near_ath_risk"),
    (("dekat", "ath"), "tech.near_ath_risk"),
    (("dekat resistance",), "tech.near_resistance"),
    (("zona resistance",), "tech.at_resistance"),
    (("bouncing dari support",), "tech.support_bounce"),
    (("recent high",), "tech.near_recent_high"),
    (("early breakout",), "tech.early_breakout"),
    (("breakdown",), "tech.breakdown"),
    (("dijebol",), "tech.breakdown"),
    (("breakout",), "tech.breakout_volume"),
    (("trend recovering",), "tech.trend_recovering"),
    (("trend sideways",), "tech.trend_sideways"),
    # ── RSI (spesifik sebelum overbought generik) ─────────────────────────────
    (("rsi", "relaxed"), "tech.rsi_relaxed_trend"),
    (("rsi", "masih ride"), "tech.rsi_overbought_ride"),
    (("rsi", "sweet spot"), "tech.rsi_sweet"),
    (("rsi", "recovering"), "tech.rsi_recovering"),
    (("rsi", "fading"), "tech.rsi_fading"),
    (("rsi", "momentum zone"), "tech.rsi_momentum"),
    (("rsi", "momentum building"), "tech.rsi_momentum"),
    (("rsi", "falling zone"), "tech.rsi_falling"),
    (("rsi", "breaking down"), "tech.rsi_falling"),
    (("rsi", "nearly oversold"), "tech.rsi_falling"),
    (("rsi", "swing terakhir"), "tech.rsi_extended"),     # a3: "extended — momentum kuat, SL di swing terakhir"
    (("rsi", "overbought"), "tech.rsi_overbought"),
    # ── Momentum brackets a3 (SETELAH rule BM δ24h di atas) ──────────────────
    (("momentum", "sweet spot"), "mom.sweet_spot"),
    (("momentum early",), "mom.early"),
    (("momentum kuat",), "mom.strong"),
    (("dump", "sweet spot"), "mom.dump_sweet_spot"),
    (("dump early",), "mom.dump_early"),
    (("dump kuat",), "mom.dump_strong"),
)


def canonical_signal_key(raw: str) -> str | None:
    """Map copy sinyal (display text) ke feature ID immutable, atau None."""
    normalized = raw.casefold()
    for required_parts, stable_id in _SIGNAL_ID_RULES:
        if all(part in normalized for part in required_parts):
            return f"signal_id:{stable_id}"
    return None


def is_profitable_outcome(pnl_pct: float | None) -> bool:
    """Kebenaran = realized NET pnl (v16 true-cost), bukan close-reason/status."""
    return pnl_pct is not None and pnl_pct > 0


def target_weight(adjusted_win_rate: float) -> float:
    """Map smoothed win-rate ke bobot policy ber-bound (identik SPOT)."""
    if adjusted_win_rate >= 0.70:
        return 1.50
    if adjusted_win_rate >= 0.55:
        return 1.20
    if adjusted_win_rate >= 0.40:
        return 1.00
    return 0.70


def deterministic_weight(effective_wins: float, effective_total: float) -> float:
    """Bobot langsung dari evidence — run berulang tidak bisa men-drift-kannya."""
    if effective_total <= 0:
        return 1.0
    adjusted = (effective_wins + 1.0) / (effective_total + 2.0)
    confidence = min(1.0, effective_total / 10.0)
    desired = 1.0 + (target_weight(adjusted) - 1.0) * confidence
    return round(max(MIN_WEIGHT, min(MAX_WEIGHT, desired)), 3)


def wilson_lower_bound(probability: float, sample_count: int, z: float = 1.64) -> float:
    """Batas bawah konservatif ~95% satu sisi — dipakai untuk keputusan kapital."""
    if sample_count <= 0:
        return 0.0
    n = float(sample_count)
    denominator = 1 + z * z / n
    center = probability + z * z / (2 * n)
    margin = z * ((probability * (1 - probability) / n + z * z / (4 * n * n)) ** 0.5)
    return round(max(0.0, (center - margin) / denominator), 4)


def learning_keys(result: Mapping[str, object]) -> list[str]:
    """Key lane + tiap sinyal yang berkontribusi pada satu kandidat futures."""
    keys: list[str] = []
    lane = str(result.get("setup_type") or "").strip()
    if lane:
        keys.append(f"lane:{lane}")
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
    """Tempelkan adaptive score + probability yang explainable, gate auto-open aman.

    Berbeda dgn SPOT, field `score` futures TIDAK ditimpa (dipakai pipeline lain);
    hasil learning hidup di field terpisah dan `learning_auto_veto` — F2 yang
    memutuskan konsumsinya di auto_trader. Veto-only: kandidat yang raw-nya di
    bawah `auto_threshold` tidak pernah bisa dipromosikan oleh bobot tinggi.
    """
    keys = learning_keys(result)
    learned = [(key, float(weights[key])) for key in keys if key in weights]

    lane_weights = [weight for key, weight in learned if key.startswith("lane:")]
    signal_weights = [weight for key, weight in learned if not key.startswith("lane:")]
    components: list[float] = []
    if lane_weights:
        components.append(sum(lane_weights) / len(lane_weights))
    if signal_weights:
        components.append(sum(signal_weights) / len(signal_weights))
    factor = sum(components) / len(components) if components else 1.0
    factor = round(max(MIN_WEIGHT, min(MAX_WEIGHT, factor)), 3)

    raw_score = float(result.get("score") or 0.0)
    adaptive_score = round(raw_score * factor, 1)
    blocked_keys = sorted(set(keys).intersection(banned_keys))

    probabilities = probabilities or {}
    sample_counts = sample_counts or {}
    learned_probabilities = [float(probabilities[key]) for key in keys if key in probabilities]
    estimated_probability = (
        round(max(0.05, min(0.95, sum(learned_probabilities) / len(learned_probabilities))), 4)
        if learned_probabilities else None
    )
    evidence_counts = [
        int(sample_counts[key]) for key in keys
        if key in probabilities and key in sample_counts
    ]
    conservative_n = min(evidence_counts) if evidence_counts else 0
    lower_probability = (
        wilson_lower_bound(estimated_probability, conservative_n)
        if estimated_probability is not None else None
    )

    original_eligible = raw_score >= auto_threshold
    final_eligible = bool(
        original_eligible and not blocked_keys and adaptive_score >= auto_threshold
    )

    result["weight_applied"] = factor
    result["adaptive_score"] = adaptive_score
    result["learning_keys"] = keys
    result["learning_contributions"] = [
        {"key": key, "weight": round(weight, 3)} for key, weight in learned
    ]
    result["banned_by_learning"] = bool(blocked_keys)
    result["learning_blocked_keys"] = blocked_keys
    result["estimated_win_probability"] = estimated_probability
    result["probability_source"] = (
        "historical_laplace" if estimated_probability is not None else "unavailable"
    )
    result["probability_sample_count"] = conservative_n
    result["lower_confidence_probability"] = lower_probability
    result["learning_auto_eligible"] = final_eligible
    result["learning_auto_veto"] = bool(original_eligible and not final_eligible)
    return result
