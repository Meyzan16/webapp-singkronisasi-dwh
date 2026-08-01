"""Ambang keputusan MONITOR futures — satu sumber, bisa diubah tanpa deploy.

Latar (audit 1 Agu 2026): monitor punya ~40 konstanta yang menentukan KAPAN dan
KENAPA posisi ditutup (TP/SL/SL+/trail/fail-fast/rotasi/umur), tapi hanya 5 yang
bisa di-override lewat DB. Sisanya terkunci di kode — tak bisa ditala, tak bisa
diaudit dari UI, dan yang terpenting: **tak bisa disentuh Adaptive Learning
Engine** bila nanti mesin belajar dikhususkan untuk MONITOR.

Modul ini mengumpulkan ambang KEPUTUSAN itu (bukan konstanta struktural seperti
interval loop) dan menyediakan `refresh()` yang menariknya dari `agent_config`.
Nilai default di sini WAJIB sama dengan perilaku lama, sehingga tanpa override
apa pun monitor berjalan persis seperti sebelumnya.

Cara memakai dari monitor:
    from agents.futures import monitor_config as mcfg
    await mcfg.refresh()          # sekali per siklus, murah (TTL di config_reader)
    if age_days > mcfg.MAX_AGE_DAYS: ...
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)

# ── Umur & rotasi ─────────────────────────────────────────────────────────────
MAX_AGE_DAYS = 3.0                 # posisi futures harus selesai lebih cepat dari spot
MAX_AGE_EXTENSIONS = 2             # maks 2 perpanjangan 1 hari untuk posisi menang
ROTATION_MIN_DAYS = 1.0            # baru dicek setelah 1 hari
ROTATION_DRIFT_PCT = 3.0           # ≤3% dari entry = stagnan
ROTATION_SCORE_GAP = 10.0          # kandidat pengganti harus unggul minimal segini

# ── Time-stop ─────────────────────────────────────────────────────────────────
TIME_STOP_PROGRESS_FRAC = 0.5      # harus capai ≥0.5×risk untuk lolos time-stop
TIME_STOP_LOSS_GUARD_FRAC = 0.5    # bila ≤ −0.5×risk, serahkan ke SL (jangan scratch)

# ── Rug-pull / flash dump ─────────────────────────────────────────────────────
RUGPULL_BASE_PCT = 5.0             # ambang minimum gerak melawan
RUGPULL_MIN_HOLD_MIN = 10.0        # hindari panic-exit di derau pembukaan posisi
RUGPULL_CONFIRM_MULT = 1.2         # gerak harus 1.2× ambang → flash asli

# ── Fail-fast ─────────────────────────────────────────────────────────────────
FAILFAST_MIN_HOLD_MIN = 10.0
FAILFAST_MAX_HOLD_MIN = 45.0       # sesudah ini time-stop yang berwenang
FAILFAST_ATR_MULT = 1.0
FAILFAST_PROGRESS_FRAC = 0.3       # tak pernah capai +0.3×risk = tesis tak jalan
FAILFAST_CONFIRM_FRAC = 0.8        # candle sebelumnya harus ikut melawan (bukan 1 wick)

# ── Bank profit & biaya ───────────────────────────────────────────────────────
MIN_BANK_COST_MULT = 3.0           # dilarang bank profit sukarela < 3× cost floor
COST_TO_PROFIT_GATE = 0.30         # tutup bila biaya kumulatif > 30% profit
COST_ABS_LOSS_GATE_PCT = 0.003     # tutup posisi rugi bila biaya > 0.3% notional

# ── BigMover ──────────────────────────────────────────────────────────────────
BM_BE_ARM_ABS_PCT = 1.5            # jarak minimum sebelum breakeven diaktifkan
BM_HALF_PARTIAL_FRAC = 0.5         # de-risk 50% di separuh jalan ke TP1

# ── PRIORITAS 1: target TP relatif volatilitas ────────────────────────────────
# TEMUAN 1 Agu 2026 (44 trade futures tertutup): TP dipasang **4–13× ATR** jauhnya
# sementara gerak menguntungkan terjauh (MFE) hanya bermedian **0,41× ATR**.
# Akibatnya TP praktis tak pernah tersentuh — **1 dari 44** — dan setiap posisi
# berakhir di SL atau trailing. "R:R 1:3" hanya di atas kertas; realisasinya 0,81.
#
# Simulasi pada data yang sama, bila TP dipasang N×ATR:
#     0,50×ATR → tersentuh 48%      1,00×ATR → 27%
#     0,75×ATR → tersentuh 36%      2,00×ATR →  9%      ~4×ATR (kini) → 2%
#
# `TP_MAX_ATR_MULT` membatasi jarak TP efektif ke kelipatan ATR yang realistis.
# DEFAULT 0 = MATI (perilaku lama, TP apa adanya dari entry).
# CATATAN JUJUR: memperpendek TP saja BELUM tentu menguntungkan — SL berada di
# ~1,5× ATR sementara MFE median 0,41× ATR, jadi struktur payoff-nya memang
# timpang. Angka ini disediakan agar bisa diuji, bukan diklaim sebagai solusi.
TP_MAX_ATR_MULT = 0.0

_KEYS: dict[str, str] = {
    # nama variabel modul -> kunci config (grup "futures")
    "MAX_AGE_DAYS":              "monitor_max_age_days",
    "MAX_AGE_EXTENSIONS":        "monitor_max_age_extensions",
    "ROTATION_MIN_DAYS":         "monitor_rotation_min_days",
    "ROTATION_DRIFT_PCT":        "monitor_rotation_drift_pct",
    "ROTATION_SCORE_GAP":        "monitor_rotation_score_gap",
    "TIME_STOP_PROGRESS_FRAC":   "monitor_time_stop_progress_frac",
    "TIME_STOP_LOSS_GUARD_FRAC": "monitor_time_stop_loss_guard_frac",
    "RUGPULL_BASE_PCT":          "monitor_rugpull_base_pct",
    "RUGPULL_MIN_HOLD_MIN":      "monitor_rugpull_min_hold_min",
    "RUGPULL_CONFIRM_MULT":      "monitor_rugpull_confirm_mult",
    "FAILFAST_MIN_HOLD_MIN":     "monitor_failfast_min_hold_min",
    "FAILFAST_MAX_HOLD_MIN":     "monitor_failfast_max_hold_min",
    "FAILFAST_ATR_MULT":         "failfast_atr_mult",          # kunci lama, dipertahankan
    "FAILFAST_PROGRESS_FRAC":    "monitor_failfast_progress_frac",
    "FAILFAST_CONFIRM_FRAC":     "monitor_failfast_confirm_frac",
    "MIN_BANK_COST_MULT":        "monitor_min_bank_cost_mult",
    "COST_TO_PROFIT_GATE":       "monitor_cost_to_profit_gate",
    "COST_ABS_LOSS_GATE_PCT":    "monitor_cost_abs_loss_gate_pct",
    "BM_BE_ARM_ABS_PCT":         "monitor_bm_be_arm_abs_pct",
    "BM_HALF_PARTIAL_FRAC":      "monitor_bm_half_partial_frac",
    "TP_MAX_ATR_MULT":           "monitor_tp_max_atr_mult",
}

_INT_KEYS = {"MAX_AGE_EXTENSIONS"}


async def refresh() -> None:
    """Tarik override dari agent_config. Gagal = diam & pakai nilai terakhir —
    monitor TIDAK boleh berhenti hanya karena config tak terbaca."""
    try:
        from agents.shared.config_reader import cfg
        globs = globals()
        for var, key in _KEYS.items():
            value = await cfg.get("futures", key, globs[var])
            globs[var] = int(value) if var in _INT_KEYS else float(value)
    except Exception as exc:
        logger.warning("monitor_config_refresh_failed", error=str(exc)[:120])


def effective_take_profit(entry: float, take_profit: float, atr_pct: float,
                          direction: str) -> tuple[float, bool]:
    """TP efektif setelah dibatasi kelipatan ATR (PRIORITAS 1).

    Return `(tp, dikompresi)`. Saat `TP_MAX_ATR_MULT` = 0 (default) TP dikembalikan
    apa adanya sehingga perilaku identik dengan sebelumnya. Kompresi HANYA
    mendekatkan target — tak pernah menjauhkannya, supaya tak memperburuk R:R.
    """
    if TP_MAX_ATR_MULT <= 0 or atr_pct <= 0 or entry <= 0 or not take_profit:
        return take_profit, False
    max_dist = entry * (atr_pct / 100.0) * TP_MAX_ATR_MULT
    cur_dist = abs(take_profit - entry)
    if cur_dist <= max_dist:
        return take_profit, False
    tp = entry + max_dist if direction == "LONG" else entry - max_dist
    return round(tp, 8), True


def snapshot() -> dict:
    """Nilai ambang yang sedang berlaku — untuk endpoint/diagnostik."""
    globs = globals()
    return {key: globs[var] for var, key in _KEYS.items()}
