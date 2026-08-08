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


async def refresh() -> None:
    """Tarik override dari `agent_config` grup "spot". Gagal = diam & pakai nilai
    terakhir — monitor TIDAK boleh berhenti hanya karena config tak terbaca."""
    try:
        from agents.shared.config_reader import cfg
        globs = globals()
        for var, key in _KEYS.items():
            globs[var] = float(await cfg.get("spot", key, globs[var]))
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
