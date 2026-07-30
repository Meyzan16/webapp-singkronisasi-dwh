"""Regression tests for the FUTURES adaptive learning policy (F0).

Pola mengikuti test_spot_learning_policy.py. Semua string sinyal di sini adalah
COPY PERSIS dari agent1/agent2/agent3/agent_bigmover (pasca item H) — kalau copy
di agent berubah, canonical ID TIDAK boleh ikut berubah; kalau test ini gagal
karena copy baru, tambahkan rule baru di _SIGNAL_ID_RULES, jangan ubah ID lama.
"""

import os
import sys

# Repo root ke path — modul `agents` hidup satu level di atas backend/, dan
# test harus jalan sama baiknya dari backend/ maupun repo root (tanpa
# menyentuh pytest.ini bersama milik suite SPOT).
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from agents.futures.learning_policy import (  # noqa: E402
    MAX_WEIGHT,
    MIN_WEIGHT,
    apply_learning_policy,
    canonical_signal_key,
    deterministic_weight,
    is_profitable_outcome,
    learning_keys,
    normalize_signal,
    signal_key,
    wilson_lower_bound,
)
from agents.futures import weight_updater as futures_weight_updater  # noqa: E402


# ── Canonical signal IDs — mapping copy nyata per agent ───────────────────────

AGENT1_CASES = [
    ("🔵 BB Squeeze 4h (3.1% width) — energi terkompresi", "signal_id:tech.bb_squeeze"),
    ("BB Squeeze 1h (5.2%) — kompresi sedang", "signal_id:tech.bb_squeeze"),
    ("🟢 Flat +1.2% + BB Squeeze — pre-gainer coiling ideal", "signal_id:tech.flat_coil"),
    ("📦 Volume Akumulasi 1h 2.7× — smart money masuk diam-diam", "signal_id:flow.volume_accumulation"),
    ("Volume naik 1.9× 4h — akumulasi terbentuk", "signal_id:flow.volume_accumulation"),
    ("🚀 Volume spike +3.1σ vs baseline 200 candle — surge institusional", "signal_id:flow.volume_zscore"),
    ("Volume +1.7σ di atas baseline 1h — akumulasi di atas normal", "signal_id:flow.volume_zscore"),
    ("🔴 Funding -0.045% negatif ekstrem — short squeeze fuel siap", "signal_id:fund.negative_funding"),
    ("Funding -0.015% negatif — shorts bayar, fuel untuk pump", "signal_id:fund.negative_funding"),
    ("📊 OI +3.4% — posisi baru masuk, konviksi meningkat", "signal_id:flow.oi_rising"),
    ("📈 OI acceleration 1.2% → 2.8% — momentum institusional membangun", "signal_id:flow.oi_acceleration"),
    ("🎯 Dekat resistance 1h — 1.8% lagi ke breakout", "signal_id:tech.near_resistance"),
    ("RSI 48 sweet spot — momentum naik, belum overbought", "signal_id:tech.rsi_sweet"),
    ("RSI 39 recovering — reversal bias naik", "signal_id:tech.rsi_recovering"),
    ("Short squeeze terdeteksi (proxy arah) — bias bullish", "signal_id:flow.liq_short_proxy"),
    ("🚀 Break 7d ATH +0.8% vol 1.7× — fresh leg up", "signal_id:tech.ath_break"),
    ("⚠️ Near 7d ATH (+0.2%) — late entry risk", "signal_id:tech.near_ath_risk"),
    # pre-dump (SHORT)
    ("🔴 BB Squeeze 4h (3.2%) di puncak — energi dump terkompres", "signal_id:tech.bb_squeeze_top"),
    ("BB Squeeze 1h (4.4%) — kompresi di area resistance", "signal_id:tech.bb_squeeze_top"),
    ("📤 Volume distribusi 1h 2.6× — smart money exit diam-diam", "signal_id:flow.volume_distribution"),
    ("Volume naik 1.9× 1h di area tinggi — potensi distribusi", "signal_id:flow.volume_distribution"),
    ("🔴 Funding +0.085% ekstrem — longs overcrowded, long squeeze fuel", "signal_id:fund.high_funding"),
    ("📊 OI +3.1% saat harga naik — long trap forming, forced unwind imminent", "signal_id:flow.oi_long_trap"),
    ("🎯 Di zona resistance 1h — 0.8% dari rejection level", "signal_id:tech.at_resistance"),
    ("RSI 62 fading zone — momentum stalling, reversal approaching", "signal_id:tech.rsi_fading"),
    ("RSI 75 overbought — extended, rawan koreksi tajam", "signal_id:tech.rsi_overbought"),
    ("💥 Long liquidation terdeteksi (proxy arah) — bias bearish", "signal_id:flow.liq_long_proxy"),
]

AGENT2_CASES = [
    ("📦 Wyckoff Accumulation — vol 1.4× saat harga flat (pre-markup)", "signal_id:wyckoff.accumulation"),
    ("📈 Wyckoff Markup awal — masih bisa entry jika baru mulai", "signal_id:wyckoff.markup"),
    ("🔵 Wyckoff Accumulation 4H+1H konfirmasi — dual-TF pre-markup conviction", "signal_id:wyckoff.dual_tf"),
    ("📊 OI +2.4% selama akumulasi — institusi masuk diam-diam", "signal_id:flow.oi_rising"),
    ("📊 OI +3.4% tanpa pergerakan harga — akumulasi tersembunyi", "signal_id:flow.oi_rising"),
    ("⚡ Trend recovering 4h — EMA9 baru cross EMA21 ke atas", "signal_id:tech.trend_recovering"),
    ("Trend sideways 4h — fase akumulasi terkonfirmasi", "signal_id:tech.trend_sideways"),
    ("💰 Funding -0.035% sangat negatif — short squeeze fuel siap meledak", "signal_id:fund.negative_funding"),
    ("📍 Bouncing dari support 4h — entry akumulasi dengan SL jelas", "signal_id:tech.support_bounce"),
    ("Vol 1.8× di zona S/R — level sedang diuji aktif", "signal_id:flow.volume_at_zone"),
    ("🔵 BB Squeeze multi-TF (4H 3.1% / 1H 3.8%) — BREAKOUT IMMINENT", "signal_id:tech.bb_squeeze"),
    ("🔵 Squeeze 9 candle beruntun (1H) — energi terkompresi lama", "signal_id:tech.squeeze_persistence"),
    ("📦 Volume akumulasi 2.7× — smart money entry senyap", "signal_id:flow.volume_accumulation"),
    ("🟢 Buy pressure +24% — buyer mengambil alih pasar", "signal_id:flow.buy_pressure"),
    # distribution (SHORT)
    ("📤 Wyckoff Distribution — vol 1.3× saat harga flat di puncak", "signal_id:wyckoff.distribution"),
    ("📉 Wyckoff Markdown — trend turun vol 1.4× terkonfirmasi", "signal_id:wyckoff.markdown"),
    ("🔴 BB Squeeze multi-TF di area puncak — dump semakin dekat", "signal_id:tech.bb_squeeze_top"),
    ("Price dekat recent high — zona distribusi aktif", "signal_id:tech.near_recent_high"),
    ("🔴 Sell pressure -26% — seller mengambil alih", "signal_id:flow.sell_pressure"),
]

AGENT3_CASES = [
    ("🚀 Momentum +9.3% — sweet spot entry: terbangun tapi belum exhausted", "signal_id:mom.sweet_spot"),
    ("Momentum early +6.1% — awal terbentuk, masih ada room", "signal_id:mom.early"),
    ("⚡ Momentum kuat +13.2% — wave sudah jelas, SL sadar-leverage", "signal_id:mom.strong"),
    ("💥 Volume 2.7× 1h saat naik — buyer aggression dikonfirmasi", "signal_id:flow.volume_momentum"),
    ("Volume 2.1× 4h — momentum terkonfirmasi pembeli", "signal_id:flow.volume_momentum"),
    ("📊 OI +5.2% — massive new LONG positioning masuk", "signal_id:flow.oi_rising"),
    ("⚠️ OI turun -2.5% saat naik — kemungkinan short squeeze saja", "signal_id:flow.oi_divergence"),
    ("⚠️ Funding 0.120% terlalu tinggi — longs sudah crowded", "signal_id:fund.high_funding"),
    ("RSI 63 momentum zone — trending kuat belum overbought", "signal_id:tech.rsi_momentum"),
    ("RSI 55 — momentum building, waktu entry bagus", "signal_id:tech.rsi_momentum"),
    ("RSI 76 extended — momentum kuat, SL di swing terakhir", "signal_id:tech.rsi_extended"),
    ("🔓 Breakout 4h +2.4% vol 1.9× — breakout dikonfirmasi volume", "signal_id:tech.breakout_volume"),
    ("⚡ Early breakout 1h +4.2% vol 1.8× OI +1.5% — pre-momentum detected", "signal_id:tech.early_breakout"),
    ("RSI 77 overbought tapi market trending_up kuat — relaxed", "signal_id:tech.rsi_relaxed_trend"),
    # SHORT
    ("📉 Dump -9.1% — sweet spot short entry: momen tapi belum oversold", "signal_id:mom.dump_sweet_spot"),
    ("Dump early -6.4% — awal turun, momentum SHORT terbentuk", "signal_id:mom.dump_early"),
    ("⚡ Dump kuat -13.5% — wave turun jelas, short SL sadar-leverage", "signal_id:mom.dump_strong"),
    ("💥 Volume 2.8× 1h saat turun — seller aggression dikonfirmasi", "signal_id:flow.volume_momentum"),
    ("Volume 2.3× 1h — momentum SHORT terkonfirmasi", "signal_id:flow.volume_momentum"),
    ("📊 OI +4.1% saat harga turun — new SHORT positioning masuk kuat", "signal_id:flow.oi_short_conviction"),
    ("OI +2.2% saat dump — short conviction nyata, bukan sekedar liq", "signal_id:flow.oi_short_conviction"),
    ("RSI 38 falling zone — downward momentum, belum oversold", "signal_id:tech.rsi_falling"),
    ("RSI 47 breaking down — momentum bearish terbentuk", "signal_id:tech.rsi_falling"),
    ("📉 Breakdown 4h -2.1% di bawah 30-candle low — support dijebol", "signal_id:tech.breakdown"),
    ("RSI 25 oversold tapi market trending_down kuat — relaxed", "signal_id:tech.rsi_relaxed_trend"),
    ("Long liq terdeteksi (proxy arah) — forced selling = bearish fuel", "signal_id:flow.liq_long_proxy"),
]

BIGMOVER_CASES = [
    ("Δ24h +18.3% — early-stage big-mover", "signal_id:bm.magnitude"),
    ("💥 Δ24h +45.1% — momentum kuat, wave matang", "signal_id:bm.magnitude"),
    ("🔥 Δ24h +182.0% — EXTREME tier: size ½, time-stop ketat", "signal_id:bm.magnitude"),
    ("1h +2.1% confirm — masih searah momentum", "signal_id:bm.confirm_1h"),
    ("1h -3.2% confirm — masih dump", "signal_id:bm.confirm_1h"),
    ("1h -0.5% sideways pullback — re-entry zone", "signal_id:bm.pullback_1h"),
    ("1h +0.4% bounce — re-entry zone SHORT", "signal_id:bm.pullback_1h"),
    ("⚠ 1h -6.2% reverse — kontra arah", "signal_id:bm.reverse_1h"),
    ("Volume 3.2× 1h — pressure dikonfirmasi", "signal_id:flow.volume_momentum"),
    ("OI +6.1% — new longs masuk", "signal_id:flow.oi_rising"),
    ("⚠ OI -3.4% turun — short squeeze, bukan real long", "signal_id:flow.oi_divergence"),
    ("Funding -0.012% negatif — shorts bayar LONG, squeeze fuel", "signal_id:fund.negative_funding"),
    ("RSI 82 overbought tapi big-mover lane masih ride", "signal_id:tech.rsi_overbought_ride"),
]


def test_canonical_ids_agent1():
    for raw, expected in AGENT1_CASES:
        assert canonical_signal_key(raw) == expected, raw


def test_canonical_ids_agent2():
    for raw, expected in AGENT2_CASES:
        assert canonical_signal_key(raw) == expected, raw


def test_canonical_ids_agent3():
    for raw, expected in AGENT3_CASES:
        assert canonical_signal_key(raw) == expected, raw


def test_canonical_ids_bigmover():
    for raw, expected in BIGMOVER_CASES:
        assert canonical_signal_key(raw) == expected, raw


def test_canonical_id_stable_when_numbers_and_emoji_change():
    """ID fitur tak boleh bergeser saat angka/TF/emoji di copy berubah."""
    variants = [
        "🔵 BB Squeeze 4h (3.1% width) — energi terkompresi",
        "BB Squeeze 15m (9.9% width) — energi terkompresi",
        "⚡🔵 BB Squeeze 1h (0.4% width) — energi terkompresi!!",
    ]
    ids = {canonical_signal_key(v) for v in variants}
    assert ids == {"signal_id:tech.bb_squeeze"}


def test_conflict_ordering():
    """Kasus copy yang mengandung kata kunci dua rule — yang spesifik harus menang."""
    # "negatif ekstrem" = funding negatif, bukan high_funding
    assert canonical_signal_key(
        "🔴 Funding -0.045% negatif ekstrem — short squeeze fuel siap"
    ) == "signal_id:fund.negative_funding"
    # relaxed menang atas overbought
    assert canonical_signal_key(
        "RSI 77 overbought tapi market trending_up kuat — relaxed"
    ) == "signal_id:tech.rsi_relaxed_trend"
    # dual-TF menang atas wyckoff accumulation
    assert canonical_signal_key(
        "🔵 Wyckoff Accumulation 4H+1H konfirmasi — dual-TF pre-markup conviction"
    ) == "signal_id:wyckoff.dual_tf"
    # Δ24h BM menang atas "momentum kuat" a3
    assert canonical_signal_key(
        "💥 Δ24h +45.1% — momentum kuat, wave matang"
    ) == "signal_id:bm.magnitude"
    # early breakout menang atas "OI +" generik
    assert canonical_signal_key(
        "⚡ Early breakout 1h +4.2% vol 1.8× OI +1.5% — pre-momentum detected"
    ) == "signal_id:tech.early_breakout"


def test_unknown_signal_falls_back_to_legacy_key():
    raw = "Sinyal baru yang belum terdaftar 42%"
    assert canonical_signal_key(raw) is None
    assert signal_key(raw).startswith("signal:")


def test_lookup_key_matches_scoring_key():
    """Kunci lookup bobot HARUS identik dgn kunci yang dipakai scoring.

    Dulu invariannya `normalize_signal(raw) == normalize_signal_key(raw)` (kunci
    telanjang). Sejak namespace disatukan (29 Jul), bobot disimpan & dibaca dengan
    kunci scoring `canonical_signal_key(raw) or signal_key(raw)`. Invarian inilah
    yang menjaga agar lookup di agent1/2/3 tidak meleset diam-diam ke 1.0.
    """
    samples = [raw for raw, _ in AGENT1_CASES + AGENT3_CASES + BIGMOVER_CASES]
    for raw in samples:
        expected = canonical_signal_key(raw) or signal_key(raw)
        assert futures_weight_updater.normalize_signal_key(raw) == expected, raw


# ── Weight math ────────────────────────────────────────────────────────────────

def test_deterministic_weight_bounds_and_idempotence():
    assert deterministic_weight(0, 0) == 1.0
    for wins, total in [(0, 20), (10, 20), (19, 20), (2, 3), (50, 50)]:
        w1 = deterministic_weight(wins, total)
        w2 = deterministic_weight(wins, total)
        assert w1 == w2                       # tak bisa drift
        assert MIN_WEIGHT <= w1 <= MAX_WEIGHT


def test_deterministic_weight_monotonic_in_wins():
    low = deterministic_weight(2, 20)
    high = deterministic_weight(16, 20)
    assert high > low
    assert deterministic_weight(0, 20) == MIN_WEIGHT or deterministic_weight(0, 20) >= MIN_WEIGHT


def test_small_sample_stays_near_neutral():
    """Laplace + confidence: 1/1 tidak boleh langsung 1.5."""
    assert deterministic_weight(1, 1) < 1.10


def test_wilson_lower_bound_properties():
    assert wilson_lower_bound(0.8, 0) == 0.0
    small = wilson_lower_bound(0.8, 5)
    large = wilson_lower_bound(0.8, 100)
    assert 0.0 <= small < large < 0.8   # makin banyak sampel makin dekat ke p


def test_is_profitable_outcome_uses_net_pnl():
    assert is_profitable_outcome(0.4)
    assert not is_profitable_outcome(0.0)
    assert not is_profitable_outcome(-1.2)
    assert not is_profitable_outcome(None)


# ── apply_learning_policy ─────────────────────────────────────────────────────

def _candidate(**overrides):
    row = {
        "symbol": "TESTUSDT",
        "agent": "futures_agent3",
        "setup_type": "momentum",
        "direction": "LONG",
        "score": 80.0,
        "signals": [
            "🚀 Momentum +9.3% — sweet spot entry: terbangun tapi belum exhausted",
            "💥 Volume 2.7× 1h saat naik — buyer aggression dikonfirmasi",
        ],
    }
    row.update(overrides)
    return row


def test_learning_keys_contains_lane_and_canonical_ids():
    keys = learning_keys(_candidate())
    assert keys[0] == "lane:momentum"
    assert "signal_id:mom.sweet_spot" in keys
    assert "signal_id:flow.volume_momentum" in keys


def test_policy_neutral_without_weights():
    result = apply_learning_policy(_candidate(), {}, set(), auto_threshold=65.0)
    assert result["weight_applied"] == 1.0
    assert result["adaptive_score"] == 80.0
    assert result["score"] == 80.0            # score dasar TIDAK ditimpa
    assert result["learning_auto_eligible"] is True
    assert result["learning_auto_veto"] is False
    assert result["estimated_win_probability"] is None
    assert result["probability_source"] == "unavailable"


def test_policy_factor_average_of_lane_and_signals():
    weights = {
        "lane:momentum": 1.20,
        "signal_id:mom.sweet_spot": 1.40,
        "signal_id:flow.volume_momentum": 1.00,
    }
    result = apply_learning_policy(_candidate(), weights, set(), auto_threshold=65.0)
    # lane 1.20; signals avg 1.20 → factor 1.20
    assert result["weight_applied"] == 1.2
    assert result["adaptive_score"] == 96.0
    assert len(result["learning_contributions"]) == 3


def test_policy_veto_only_cannot_promote():
    """Bobot tinggi TIDAK boleh mempromosikan kandidat di bawah ambang."""
    weights = {"lane:momentum": 1.50, "signal_id:mom.sweet_spot": 1.50}
    result = apply_learning_policy(
        _candidate(score=60.0), weights, set(), auto_threshold=65.0
    )
    assert result["adaptive_score"] > 65.0     # adaptive naik…
    assert result["learning_auto_eligible"] is False   # …tapi tetap tidak eligible
    assert result["learning_auto_veto"] is False       # dan bukan pula "veto"


def test_policy_ban_vetoes_auto_open():
    result = apply_learning_policy(
        _candidate(), {}, {"signal_id:mom.sweet_spot"}, auto_threshold=65.0
    )
    assert result["banned_by_learning"] is True
    assert result["learning_blocked_keys"] == ["signal_id:mom.sweet_spot"]
    assert result["learning_auto_eligible"] is False
    assert result["learning_auto_veto"] is True


def test_policy_low_weight_vetoes_when_adaptive_drops_below_threshold():
    weights = {"lane:momentum": 0.70, "signal_id:mom.sweet_spot": 0.70,
               "signal_id:flow.volume_momentum": 0.70}
    result = apply_learning_policy(_candidate(score=70.0), weights, set(), auto_threshold=65.0)
    assert result["adaptive_score"] == 49.0
    assert result["learning_auto_veto"] is True


def test_policy_probability_and_wilson():
    probabilities = {
        "signal_id:mom.sweet_spot": 0.62,
        "signal_id:flow.volume_momentum": 0.58,
    }
    samples = {"signal_id:mom.sweet_spot": 30, "signal_id:flow.volume_momentum": 12}
    result = apply_learning_policy(
        _candidate(), {}, set(), auto_threshold=65.0,
        probabilities=probabilities, sample_counts=samples,
    )
    assert result["estimated_win_probability"] == 0.6
    assert result["probability_source"] == "historical_laplace"
    assert result["probability_sample_count"] == 12     # konservatif: min sampel
    assert 0.0 < result["lower_confidence_probability"] < 0.6


def test_policy_factor_clamped_to_bounds():
    weights = {"lane:momentum": 9.0}   # nilai korup di DB tak boleh lolos
    result = apply_learning_policy(_candidate(), weights, set(), auto_threshold=65.0)
    assert result["weight_applied"] == MAX_WEIGHT
