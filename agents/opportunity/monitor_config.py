"""Ambang keputusan MONITOR SPOT — satu sumber, bisa ditala tanpa deploy.

Padanan `agents/futures/monitor_config.py` untuk sisi SPOT, dibuat 8 Agu 2026
setelah audit menemukan rantai belajar sisi keluar SPOT **terbuka di ujungnya**:

    ledger keluar SPOT  ✓ terisi (67 baris)
    analisa exit_learning ✓ jalan (sadar-market sejak M7)
    penerapan ke monitor  ✗ NOL — monitor SPOT tak membaca satu pun config

Diukur: `agents/opportunity/monitor.py` punya **0** titik baca config, sementara
monitor futures punya 41. Artinya apa pun yang dipelajari engine tentang keputusan
keluar SPOT tak punya jalan untuk sampai ke agen yang membuat keputusan itu —
persis pola yang di sisi futures butuh M2 untuk ditutup.

Yang dikumpulkan di sini hanya ambang KEPUTUSAN (kapan & kenapa posisi ditutup),
bukan konstanta struktural seperti interval loop atau jendela wick. Nilai bawaan
WAJIB sama dengan perilaku lama, sehingga tanpa override apa pun monitor berjalan
persis seperti sebelumnya.

Cara memakai dari monitor:
    from agents.opportunity import monitor_config as scfg
    await scfg.refresh()          # sekali per siklus, murah (TTL di config_reader)
    if drift <= scfg.STAGNANT_DRIFT_PCT: ...
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)

# ── Rotasi (stagnan & mendesak) ───────────────────────────────────────────────
STAGNANT_CHECK_DAYS = 2.0      # baru dinilai stagnan setelah 2 hari
STAGNANT_DRIFT_PCT = 3.0       # ±3% dari entry = koin tak bergerak
STAGNANT_SCORE_GAP = 10.0      # kandidat pengganti harus unggul segini
URGENT_ROTATION_DAYS = 1.0     # rotasi mendesak boleh sejak 1 hari
URGENT_SCORE_GAP = 25.0        # unggul ≥25 = biaya peluang jelas
URGENT_SCORE_MIN = 90.0        # skor minimum kandidat untuk rotasi mendesak
ROTATION_MIN_PNL_PCT = -0.5    # lantai P&L: rotasi tak boleh membukukan rugi

# ── Umur maksimum per mode entri ──────────────────────────────────────────────
MAX_AGE_DAYS_FRESH_SETUP = 10.0
MAX_AGE_DAYS_MOMENTUM_CHASE = 5.0
MAX_AGE_DAYS_BIGMOVER = 3.0

# ── Gerbang "masih kuat" (dipakai runner trailing) ────────────────────────────
GATE_MIN_SCORE = 50.0
GATE_MIN_TAKER = 0.50
GATE_MIN_VOL_RATIO = 1.2

# ── Tangga rung dinamis ───────────────────────────────────────────────────────
DYN_RUNG_ATR_MULT = 1.0
DYN_RUNG_STEP_PCT = 8.0

MIN_HOLD_MINUTES = 30.0        # exit risk-adjusted baru boleh sesudah ini

# ── Pemicu keluar dini: trend_reversal ────────────────────────────────────────
# BUKTI 9 Agu 2026 dari ledger keluar SPOT (per lane × pemicu):
#
#   accumulation / trend_reversal    n=10  WR 10,0%  expectancy −1,191%
#   accumulation / urgent_rotation   n=19  WR 57,9%  expectancy +1,757%
#   accumulation / profit_protection n= 3  WR 100%   expectancy +7,357%
#   bigmover     / tp1_breakeven     n= 9  WR 100%   expectancy +3,863%
#
# `trend_reversal` satu-satunya pemicu yang benar-benar merugikan — ia merealisasi
# kerugian pada 9 dari 10 posisi. Ia sengaja dirancang TANPA lantai profit karena
# dianggap "sinyal struktur" (EMA silang = alasan masuk sudah patah), tapi
# hasilnya menunjukkan silang EMA saja terlalu sering keliru.
#
# Tiga angka di bawah dulu terkunci di tengah fungsi. Dikeluarkan supaya bisa
# ditala dan diuji dengan data — persis jalan yang dipakai memperbaiki `fail_fast`
# di futures, yang juga 0% menang sebelum diberi syarat tambahan.
#
# Nilai bawaan = perilaku lama persis.
TREND_REVERSAL_MIN_HOLD_MIN = 60.0   # jangan bereaksi pada derau candle pembuka
TREND_REVERSAL_EMA_BUFFER = 0.998    # ema9 harus di bawah ema21 × ini
#: Lantai profit untuk trend_reversal, sebagai porsi jarak ke TP2.
#: 0 = perilaku lama (tanpa lantai). Dinaikkan berarti: hanya keluar saat posisi
#: sudah cukup untung, dan biarkan SL yang mengurus struktur yang patah saat rugi.
TREND_REVERSAL_PROFIT_FLOOR_FRAC = 0.0

# ── Trailing: penggeseran SL sesudah posisi untung ────────────────────────────
# Padanan SPOT dari dua parameter trailing futures. Semua bawaan = perilaku lama
# PERSIS — menaikkannya mengubah keputusan trading, jadi itu harus pilihan sadar.

#: Porsi keuntungan TP1 yang dikunci saat TP1 tersentuh (SL → entry + frac×gain).
#: Futures memakai 0,75; SPOT sejak awal 0,5, dulu tertanam di tengah fungsi.
TRAIL_LOCK_AFTER_TP1_FRAC = 0.5

#: Kemajuan TP1→TP2 yang memicu SL naik ke TP1.
#: 1,0 = perilaku lama: lantai baru naik ke TP1 saat TP2 BENAR-BENAR tersentuh.
#: Diturunkan berarti keuntungan TP1 diamankan lebih awal. Futures memakai 0,5.
TRAIL_ADVANCE_TP1_TP2_FRAC = 1.0

#: Batas anti-wick: lantai baru tak boleh dipasang di atas harga × ini, kalau
#: tidak SL akan langsung tersentuh oleh sumbu candle yang sedang berjalan.
TRAIL_FLOOR_MAX_OF_PRICE = 0.999

#: Buffer di bawah struktur (EMA21 4h / swing-low 10 candle) saat menghitung
#: trailing SL. 0,99 = 1% di bawah — memberi ruang agar sumbu candle tak
#: langsung menyentuh SL yang baru dipasang.
#: Dulu `ema21 * 0.99` telanjang, padahal angka ini menentukan LETAK SL.
STRUCT_SL_BUFFER_FRAC = 0.99

#: Breakeven `momentum_entry`: dipicu di +3% dan dipasang 0,1% di atas entry.
#: Buffer-nya ADA supaya keluar di breakeven tak justru rugi ongkos.
MOMENTUM_BE_TRIGGER_PCT = 3.0
MOMENTUM_BE_BUFFER_FRAC = 1.001

_KEYS: dict[str, str] = {
    # nama variabel modul -> kunci config (grup "spot")
    "STAGNANT_CHECK_DAYS":          "monitor_stagnant_check_days",
    "STAGNANT_DRIFT_PCT":           "monitor_stagnant_drift_pct",
    "STAGNANT_SCORE_GAP":           "monitor_stagnant_score_gap",
    "URGENT_ROTATION_DAYS":         "monitor_urgent_rotation_days",
    "URGENT_SCORE_GAP":             "monitor_urgent_score_gap",
    "URGENT_SCORE_MIN":             "monitor_urgent_score_min",
    "ROTATION_MIN_PNL_PCT":         "monitor_rotation_min_pnl_pct",
    "MAX_AGE_DAYS_FRESH_SETUP":     "monitor_max_age_fresh_setup",
    "MAX_AGE_DAYS_MOMENTUM_CHASE":  "monitor_max_age_momentum_chase",
    "MAX_AGE_DAYS_BIGMOVER":        "monitor_max_age_bigmover",
    "GATE_MIN_SCORE":               "monitor_gate_min_score",
    "GATE_MIN_TAKER":               "monitor_gate_min_taker",
    "GATE_MIN_VOL_RATIO":           "monitor_gate_min_vol_ratio",
    "DYN_RUNG_ATR_MULT":            "monitor_dyn_rung_atr_mult",
    "DYN_RUNG_STEP_PCT":            "monitor_dyn_rung_step_pct",
    "MIN_HOLD_MINUTES":             "monitor_min_hold_minutes",
    "TREND_REVERSAL_MIN_HOLD_MIN":  "monitor_trend_reversal_min_hold_min",
    "TREND_REVERSAL_EMA_BUFFER":    "monitor_trend_reversal_ema_buffer",
    "TREND_REVERSAL_PROFIT_FLOOR_FRAC": "monitor_trend_reversal_profit_floor_frac",
    "STRUCT_SL_BUFFER_FRAC":        "monitor_struct_sl_buffer_frac",
    "TRAIL_LOCK_AFTER_TP1_FRAC":    "monitor_trail_lock_after_tp1_frac",
    "TRAIL_ADVANCE_TP1_TP2_FRAC":   "monitor_trail_advance_tp1_tp2_frac",
    "TRAIL_FLOOR_MAX_OF_PRICE":     "monitor_trail_floor_max_of_price",
    "MOMENTUM_BE_TRIGGER_PCT":      "monitor_momentum_be_trigger_pct",
    "MOMENTUM_BE_BUFFER_FRAC":      "monitor_momentum_be_buffer_frac",
    "EXIT_LEARNING_ENABLED":        "monitor_exit_learning_enabled",
}

# ── Hasil belajar sisi keluar (default MATI) ──────────────────────────────────
# Saklar SPOT sengaja TERPISAH dari saklar futures. Disiplin M5 menuntut satu
# perubahan diuji pada satu tempat: kalau dua market dinyalakan oleh satu saklar
# dan hasilnya membaik, tak ada cara tahu market mana penyebabnya.
EXIT_LEARNING_ENABLED = 0.0

#: Batas jarak TP per lane dalam kelipatan ATR, hasil belajar dari ledger keluar.
#: Kosong = belum ada; lane tanpa angka sendiri TIDAK meminjam angka lane lain.
TP_ATR_BY_LANE: dict[str, float] = {}
TP_LANE_KEY_PREFIX = "monitor_tp_atr_mult_lane_"


def tp_lane_key(lane: str) -> str:
    """Kunci `agent_config` (grup spot) untuk batas TP sebuah lane."""
    return f"{TP_LANE_KEY_PREFIX}{lane}"


def tunable_lanes() -> list[str]:
    """Lane SPOT yang wajib punya baris config sendiri.

    Diturunkan dari `lane_of()` di monitor — satu sumber, jadi lane SPOT baru
    cukup didaftarkan di sana untuk ikut bisa ditala.
    """
    return ["accumulation", "breakout", "bigmover", "early_radar"]


def tp_atr_limit(lane: str = "") -> float:
    """Batas TP (kelipatan ATR) yang berlaku untuk sebuah lane SPOT.

    Angka hasil belajar hanya dipakai bila saklar belajar SPOT menyala. Tanpa itu
    ia tersimpan dan bisa diamati, tapi tak menyentuh satu pun keputusan.
    """
    if EXIT_LEARNING_ENABLED > 0 and lane:
        learned = TP_ATR_BY_LANE.get(lane, 0.0)
        if learned > 0:
            return learned
    return 0.0


def effective_take_profit(entry: float, take_profit: float, atr_pct: float,
                          lane: str = "") -> tuple[float, bool]:
    """TP efektif setelah dibatasi kelipatan ATR.

    Return `(tp, dikompresi)`. Saat batas = 0 (default) TP dikembalikan apa adanya
    sehingga perilaku identik dengan sebelumnya. Kompresi HANYA mendekatkan
    target — tak pernah menjauhkannya, supaya tak memperburuk R:R.

    SPOT selalu LONG, jadi tak ada cabang arah seperti di futures.
    """
    limit = tp_atr_limit(lane)
    if limit <= 0 or atr_pct <= 0 or entry <= 0 or not take_profit:
        return take_profit, False
    max_dist = entry * (atr_pct / 100.0) * limit
    if abs(take_profit - entry) <= max_dist:
        return take_profit, False
    return round(entry + max_dist, 8), True


#: Nilai bawaan dibekukan saat impor — SEBELUM override mana pun sempat masuk.
#: Tanpa ini, penyemaian baris `agent_config` yang membaca nilai modul akan
#: mencatat nilai yang SEDANG berlaku sebagai "bawaan", sehingga bawaan hanyut
#: mengikuti override dan tak ada lagi titik pulang yang benar. Pola ini sudah
#: dipakai sisi futures; SPOT belum punya.
_FROZEN: dict[str, float] = {var: globals()[var] for var in _KEYS}


def default_of(var: str) -> float:
    """Nilai bawaan asli sebuah ambang, kebal terhadap override yang sudah masuk."""
    return _FROZEN[var]


async def refresh() -> None:
    """Tarik override dari `agent_config` grup "spot". Gagal = diam & pakai nilai
    terakhir — monitor TIDAK boleh berhenti hanya karena config tak terbaca."""
    try:
        from agents.shared.config_reader import cfg
        globs = globals()
        for var, key in _KEYS.items():
            globs[var] = float(await cfg.get("spot", key, _FROZEN[var]))
        globs["TP_ATR_BY_LANE"] = {
            lane: mult
            for lane in tunable_lanes()
            if (mult := await cfg.get("spot", tp_lane_key(lane), 0.0)) > 0
        }
    except Exception as exc:
        logger.warning("spot_monitor_config_refresh_failed", error=str(exc)[:120])


def snapshot() -> dict:
    """Nilai ambang yang sedang berlaku — untuk endpoint/diagnostik."""
    globs = globals()
    snap = {key: globs[var] for var, key in _KEYS.items()}
    snap["tp_atr_mult_by_lane"] = dict(TP_ATR_BY_LANE)
    return snap
