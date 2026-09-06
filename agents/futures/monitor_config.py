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

#: Menit sebelum time-stop berlaku, per lane. Lane cepat (momentum/bigmover)
#: harus selesai jauh lebih cepat daripada lane yang memang butuh waktu matang.
#: Lane yang tak terdaftar memakai `TIME_STOP_DEFAULT_MIN` — lane baru tidak
#: diam-diam mewarisi angka lane lain.
TIME_STOP_DEFAULT_MIN = 360.0
TIME_STOP_MIN_BY_LANE: dict[str, float] = {
    "momentum":     90.0,
    "bigmover":     90.0,
    "pre_gainer":   360.0,
    "pre_move":     360.0,          # alias lama
    "accumulation": 360.0,
}

# ── Rug-pull / flash dump ─────────────────────────────────────────────────────
RUGPULL_BASE_PCT = 5.0             # ambang minimum gerak melawan
RUGPULL_MIN_HOLD_MIN = 10.0        # hindari panic-exit di derau pembukaan posisi
RUGPULL_CONFIRM_MULT = 1.2         # gerak harus 1.2× ambang → flash asli
RUGPULL_CANDLES = 5                # jendela deteksi: 5 × candle 1m

# ── Fail-fast ─────────────────────────────────────────────────────────────────
FAILFAST_MIN_HOLD_MIN = 10.0
FAILFAST_MAX_HOLD_MIN = 45.0       # sesudah ini time-stop yang berwenang
FAILFAST_ATR_MULT = 1.0
FAILFAST_PROGRESS_FRAC = 0.3       # tak pernah capai +0.3×risk = tesis tak jalan
FAILFAST_CONFIRM_FRAC = 0.8        # candle sebelumnya harus ikut melawan (bukan 1 wick)

#: Lane mana yang tunduk pada fail-fast. Dulu satu literal `{"momentum",
#: "bigmover"}` di monitor — lane baru mustahil ikut tanpa mengedit kode.
#: Kini per-lane, dibaca dari registry: `monitor_failfast_enabled_{lane}`.
FAILFAST_LANE_DEFAULTS: dict[str, float] = {"momentum": 1.0, "bigmover": 1.0}
FAILFAST_LANES: set[str] = {lane for lane, on in FAILFAST_LANE_DEFAULTS.items() if on > 0}

# ── M3: fail-fast wajib unggul jelas atas SL ──────────────────────────────────
# BUKTI (8 exit fail_fast, 0% menang, expectancy −3,595% — terburuk dari semua
# alasan close):
#
#   lane      SL terpasang    fail-fast memicu di   realisasi
#   bigmover  1,5× ATR        1,0× ATR              −1,17 s/d −2,27× ATR
#   momentum  5,3–6,5× ATR    ~1,7× ATR             −1,42 s/d −1,79× ATR
#
# Di bigmover pemicunya nyaris BERIMPIT dengan SL: memotong di 1,0× ATR saat SL
# ada di 1,5× ATR hampir tak menyelamatkan apa pun, tapi membuang seluruh peluang
# harga berbalik. Satu trade (ARXUSDT) bahkan realisasi −2,27× ATR — LEBIH BURUK
# daripada membiarkan SL bekerja. Di momentum sebaliknya: SL 5–6× ATR, jadi
# fail-fast benar-benar memotong lebih dini dan berguna.
#
# `FAILFAST_MIN_SL_GAP` mensyaratkan SL cukup jauh dari ambang fail-fast sebelum
# pemotongan dini diizinkan: `jarak_SL ≥ gap × ambang_failfast`. Contoh gap 2,0
# berarti "hanya potong dini bila SL setidaknya 2× lebih jauh" — di bigmover
# (1,5/1,0 = 1,5×) fail-fast padam, di momentum (≈3,5×) tetap jalan.
#
# DEFAULT 0 = MATI (perilaku lama persis). Sampelnya baru 8 — angka ini
# disediakan agar bisa DIUJI dengan data, bukan diklaim sebagai solusi.
FAILFAST_MIN_SL_GAP = 0.0

#: Gap per lane hasil belajar dari ledger keluar. Kosong = pakai gap global.
FAILFAST_SL_GAP_BY_LANE: dict[str, float] = {}
FAILFAST_GAP_KEY_PREFIX = "monitor_failfast_min_sl_gap_"


def failfast_gap_key(lane: str) -> str:
    """Kunci `agent_config` untuk gap fail-fast sebuah lane."""
    return f"{FAILFAST_GAP_KEY_PREFIX}{lane}"


def failfast_sl_gap(lane: str = "") -> float:
    """Gap yang berlaku untuk sebuah lane.

    Sama seperti batas TP: angka hasil belajar hanya dipakai bila saklar belajar
    menyala, dan lane tanpa angka sendiri jatuh ke gap global — tidak meminjam
    angka lane lain.
    """
    if EXIT_LEARNING_ENABLED > 0 and lane:
        learned = FAILFAST_SL_GAP_BY_LANE.get(lane, 0.0)
        if learned > 0:
            return learned
    return FAILFAST_MIN_SL_GAP


def failfast_allowed(lane: str, sl_dist_pct: float, threshold_pct: float) -> tuple[bool, float]:
    """Boleh memotong dini? Return `(boleh, gap_nyata)`.

    `gap_nyata` = berapa kali lipat SL lebih jauh dari ambang fail-fast; dikembalikan
    supaya monitor bisa MENCATAT alasan penolakan, bukan diam-diam tak bertindak.
    """
    if threshold_pct <= 0:
        return True, 0.0
    actual = sl_dist_pct / threshold_pct
    required = failfast_sl_gap(lane)
    return (actual >= required if required > 0 else True), round(actual, 3)

# ── Kunci profit absolut (G5b) ────────────────────────────────────────────────
# Makin tinggi puncak profit, makin sedikit yang boleh dikembalikan ke pasar.
# Diurut dari puncak tertinggi supaya tier paling ketat yang menang.
# Tiap tier bisa ditala terpisah: `monitor_profit_lock_peak_t{i}` dan
# `monitor_profit_lock_keep_t{i}` (i mulai dari 1 = tier tertinggi).
PROFIT_LOCK_TIERS: list[tuple[float, float]] = [
    (300.0, 0.90),   # puncak ≥300% margin: kembalikan maksimal 10%
    (100.0, 0.85),
    (40.0,  0.75),
    (25.0,  0.70),
    (15.0,  0.60),
]

# ── Eskalasi fast-loop (cek 30 detik) ─────────────────────────────────────────
# Posisi berisiko tinggi dipindah ke loop cepat supaya SL tak terlewat di celah
# 2 menit. Ambangnya dulu tiga angka telanjang di tengah fungsi — tak terlihat,
# tak bisa ditala, padahal ia yang menentukan posisi mana yang dijaga ketat.
FAST_LOOP_LEVERAGE_MIN = 10.0      # leverage ≥ segini = otomatis dijaga ketat
FAST_LOOP_MARGIN_LOSS_PCT = 30.0   # rugi ≥ 30% margin = dijaga ketat
FAST_LOOP_LIQ_DIST_PCT = 10.0      # jarak ke likuidasi < 10% = dijaga ketat

# ── Ambang yang LOLOS dari M2 (audit 9 Agu 2026) ──────────────────────────────
# M2 memindahkan 24 KONSTANTA MODUL ke sini, tapi melewatkan angka yang ditulis
# langsung di tengah ekspresi — bentuk hardcode yang paling sulit terlihat karena
# tak muncul saat mencari definisi konstanta.
#
# Kedelapan angka di bawah semuanya menentukan KAPAN posisi ditutup atau SL
# digeser, jadi mereka tepat sekali jenisnya dengan yang sudah dipusatkan. Selama
# masih telanjang, tak satu pun bisa ditala dari UI maupun disentuh mesin belajar.
#
# Nilai bawaan = perilaku lama persis.

#: Profit minimum (% harga) agar posisi layak diperpanjang umurnya.
AGE_EXTEND_MIN_PNL_PCT = 5.0
#: Jeda minimum (jam) antar perpanjangan umur — "satu kali per hari".
#: Dulu `20 * 3600` di tengah ekspresi, jadi tak pernah bisa ditala.
AGE_EXTEND_COOLDOWN_HOURS = 20.0
#: Lebar pita (% harga) di sekitar SL untuk menilai posisi "macet dekat SL"
#: sesudah TP1. Dulu `sl * 1.02` / `sl * 0.98` telanjang — dan angka ini
#: MENUTUP posisi, bukan sekadar menandainya.
STUCK_NEAR_SL_BAND_PCT = 2.0
#: Umur (hari) sebelum posisi mulai dinilai stagnan.
STAGNANT_CHECK_DAYS = 2.0
#: Progres minimum menuju TP1 (%) agar posisi tak dianggap stagnan.
STAGNANT_PROGRESS_PCT = 20.0
#: Jam tertahan sesudah TP1 sebelum posisi dinilai macet.
STUCK_AFTER_TP1_HOURS = 24.0
#: Jam trailing stagnan sesudah TP1 sebelum posisi layak dirotasi.
TRAIL_STAGNANT_TP1_HOURS = 48.0
#: Skor minimum agar TP boleh diperpanjang ke TP3.
TP_EXTEND_MIN_SCORE = 65.0
#: Porsi keuntungan TP1 yang dikunci saat SL digeser sesudah TP1 tersentuh.
TRAIL_LOCK_AFTER_TP1_FRAC = 0.75
#: Porsi jarak TP1→TP2 yang harus ditempuh sebelum SL dimajukan ke TP1.
TRAIL_ADVANCE_TP1_TP2_FRAC = 0.50

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

# ── PRIORITAS 2: batas TP hasil BELAJAR, per lane ─────────────────────────────
# `TP_MAX_ATR_MULT` di atas satu angka untuk semua lane. Padahal ledger keluar
# menunjukkan lane bergerak sangat berbeda (MFE/ATR median: bigmover 0,37 ·
# momentum 0,82 · accumulation 2,97) — satu angka pasti terlalu ketat untuk yang
# satu dan terlalu longgar untuk yang lain.
#
# `agents/learning/exit_learning.py` menurunkan angka per lane dari sebaran MFE
# NYATA lane itu, lalu menuliskannya ke `agent_config` sebagai
# `monitor_tp_atr_mult_lane_{lane}`. Monitor membacanya di sini.
#
# DUA saklar, dua-duanya default MATI:
#   • EXIT_LEARNING_ENABLED = 0 → angka hasil belajar DIABAIKAN sepenuhnya.
#   • angka per-lane yang belum ditulis (0.0) → lane itu jatuh ke TP_MAX_ATR_MULT.
# Jadi menulis rekomendasi ke DB TIDAK mengubah perilaku apa pun sampai saklar
# ini dinyalakan — rekomendasi bisa diamati lebih dulu sebelum dipercaya.
EXIT_LEARNING_ENABLED = 0.0
TP_ATR_BY_LANE: dict[str, float] = {}

#: Prefix kunci config per lane. Lane-nya sendiri tidak ditulis di sini —
#: diambil dari registry, supaya lane baru ikut terbaca tanpa mengubah file ini.
TP_LANE_KEY_PREFIX = "monitor_tp_atr_mult_lane_"


def tp_lane_key(lane: str) -> str:
    """Kunci `agent_config` untuk batas TP hasil belajar sebuah lane."""
    return f"{TP_LANE_KEY_PREFIX}{lane}"


def tunable_lanes() -> list[str]:
    """Lane yang wajib punya baris config sendiri.

    Gabungan lane registry dengan lane yang sudah punya nilai bawaan di modul
    ini — supaya alias lama tak hilang saat registry belum mencatatnya, dan lane
    baru cukup didaftarkan sekali di registry untuk ikut ditala.
    """
    return sorted(set(_known_lanes())
                  | set(_FROZEN["TIME_STOP_MIN_BY_LANE"])
                  | set(FAILFAST_LANE_DEFAULTS))


def _known_lanes() -> list[str]:
    """Lane futures PENSIUN dari registry — bukan salinan literal.

    Lane `agentic` sengaja TIDAK di sini: parameter keluarnya datang dari
    `exit_config` sebagai satu set, bukan per lane. Memberinya baris di sini
    akan menghidupkan lagi tumpukan tombol yang justru sedang ditinggalkan
    (38 konstanta monitor + 21 kunci per lane untuk pertanyaan yang sama).
    """
    try:
        from app.services.agent_registry import LEGACY_LANES
        return list(LEGACY_LANES)
    except Exception:
        return []


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
    "EXIT_LEARNING_ENABLED":     "monitor_exit_learning_enabled",
    "RUGPULL_CANDLES":           "monitor_rugpull_candles",
    "TIME_STOP_DEFAULT_MIN":     "monitor_time_stop_default_min",
    "FAST_LOOP_LEVERAGE_MIN":    "monitor_fast_loop_leverage_min",
    "FAST_LOOP_MARGIN_LOSS_PCT": "monitor_fast_loop_margin_loss_pct",
    "FAST_LOOP_LIQ_DIST_PCT":    "monitor_fast_loop_liq_dist_pct",
    "FAILFAST_MIN_SL_GAP":       "monitor_failfast_min_sl_gap",
    "AGE_EXTEND_MIN_PNL_PCT":    "monitor_age_extend_min_pnl_pct",
    "AGE_EXTEND_COOLDOWN_HOURS": "monitor_age_extend_cooldown_hours",
    "STUCK_NEAR_SL_BAND_PCT":    "monitor_stuck_near_sl_band_pct",
    "STAGNANT_CHECK_DAYS":       "monitor_stagnant_check_days",
    "STAGNANT_PROGRESS_PCT":     "monitor_stagnant_progress_pct",
    "STUCK_AFTER_TP1_HOURS":     "monitor_stuck_after_tp1_hours",
    "TRAIL_STAGNANT_TP1_HOURS":  "monitor_trail_stagnant_tp1_hours",
    "TP_EXTEND_MIN_SCORE":       "monitor_tp_extend_min_score",
    "TRAIL_LOCK_AFTER_TP1_FRAC": "monitor_trail_lock_after_tp1_frac",
    "TRAIL_ADVANCE_TP1_TP2_FRAC":"monitor_trail_advance_tp1_tp2_frac",
}

_INT_KEYS = {"MAX_AGE_EXTENSIONS", "RUGPULL_CANDLES"}

#: Salinan BEKU nilai bawaan, diambil saat impor. `refresh()` menimpa variabel
#: modul, jadi kalau default dibaca dari variabel itu sendiri, nilai bawaan akan
#: hanyut: override sekali → jadi "default" selamanya, dan menghapus baris config
#: tak lagi mengembalikan perilaku asli. Semua default WAJIB dibaca dari sini.
_FROZEN: dict = {
    "TIME_STOP_MIN_BY_LANE": dict(TIME_STOP_MIN_BY_LANE),
    "PROFIT_LOCK_TIERS":     list(PROFIT_LOCK_TIERS),
}

#: Ambang yang punya satu baris config PER LANE. Nilai default per lane ada di
#: dict masing-masing; lane yang belum punya entri memakai fallback yang tertera.
_PER_LANE_KEYS: dict[str, tuple[str, str, float]] = {
    # nama variabel  -> (prefix kunci, nama fallback, fallback bila tak dikenal)
    "TIME_STOP_MIN_BY_LANE": ("monitor_time_stop_min_", "TIME_STOP_DEFAULT_MIN", 360.0),
}


async def refresh() -> None:
    """Tarik override dari agent_config. Gagal = diam & pakai nilai terakhir —
    monitor TIDAK boleh berhenti hanya karena config tak terbaca."""
    try:
        from agents.shared.config_reader import cfg
        globs = globals()
        for var, key in _KEYS.items():
            value = await cfg.get("futures", key, globs[var])
            globs[var] = int(value) if var in _INT_KEYS else float(value)
        # Batas TP hasil belajar per lane — 0 berarti "belum ada", bukan "nol jarak".
        globs["TP_ATR_BY_LANE"] = {
            lane: mult
            for lane in _known_lanes()
            if (mult := await cfg.get("futures", tp_lane_key(lane), 0.0)) > 0
        }
        globs["FAILFAST_SL_GAP_BY_LANE"] = {
            lane: gap
            for lane in tunable_lanes()
            if (gap := await cfg.get("futures", failfast_gap_key(lane), 0.0)) > 0
        }

        # Lane yang dikenal = lane registry + lane yang sudah punya default.
        # Union-nya dipakai supaya alias lama (`pre_move`) tak hilang saat
        # registry belum mencatatnya, dan lane baru tetap ikut terbaca.
        for var, (prefix, fallback_var, hard_fallback) in _PER_LANE_KEYS.items():
            defaults: dict[str, float] = _FROZEN[var]
            fallback = float(globs.get(fallback_var, hard_fallback))
            globs[var] = {
                lane: await cfg.get("futures", f"{prefix}{lane}",
                                    defaults.get(lane, fallback))
                for lane in set(_known_lanes()) | set(defaults)
            }

        # Lane mana yang tunduk fail-fast — per lane, bukan literal di kode.
        globs["FAILFAST_LANES"] = {
            lane
            for lane in set(_known_lanes()) | set(FAILFAST_LANE_DEFAULTS)
            if await cfg.get("futures", f"monitor_failfast_enabled_{lane}",
                             FAILFAST_LANE_DEFAULTS.get(lane, 0.0)) > 0
        }

        # Tangga kunci profit — tiap anak tangga bisa ditala sendiri, lalu
        # diurut ulang supaya tier paling ketat tetap menang walau nilainya
        # diubah operator ke urutan yang tidak monoton.
        tiers = [
            (await cfg.get("futures", f"monitor_profit_lock_peak_t{i}", peak),
             await cfg.get("futures", f"monitor_profit_lock_keep_t{i}", keep))
            for i, (peak, keep) in enumerate(_FROZEN["PROFIT_LOCK_TIERS"], start=1)
        ]
        globs["PROFIT_LOCK_TIERS"] = sorted(tiers, key=lambda t: -t[0])
    except Exception as exc:
        logger.warning("monitor_config_refresh_failed", error=str(exc)[:120])


def tp_atr_limit(lane: str = "") -> float:
    """Batas TP (kelipatan ATR) yang berlaku untuk sebuah lane.

    Urutan: angka hasil belajar lane tsb (hanya bila saklar belajar menyala) →
    batas global → 0 (mati). Lane yang belum punya angka belajar TIDAK diam-diam
    memakai angka lane lain.
    """
    if EXIT_LEARNING_ENABLED > 0 and lane:
        learned = TP_ATR_BY_LANE.get(lane, 0.0)
        if learned > 0:
            return learned
    return TP_MAX_ATR_MULT


def effective_take_profit(entry: float, take_profit: float, atr_pct: float,
                          direction: str, lane: str = "") -> tuple[float, bool]:
    """TP efektif setelah dibatasi kelipatan ATR (PRIORITAS 1 + 2).

    Return `(tp, dikompresi)`. Saat batas = 0 (default) TP dikembalikan apa adanya
    sehingga perilaku identik dengan sebelumnya. Kompresi HANYA mendekatkan
    target — tak pernah menjauhkannya, supaya tak memperburuk R:R.

    `lane` menentukan apakah batas hasil belajar lane itu yang dipakai; tanpa
    lane, hanya batas global yang berlaku.
    """
    limit = tp_atr_limit(lane)
    if limit <= 0 or atr_pct <= 0 or entry <= 0 or not take_profit:
        return take_profit, False
    max_dist = entry * (atr_pct / 100.0) * limit
    cur_dist = abs(take_profit - entry)
    if cur_dist <= max_dist:
        return take_profit, False
    tp = entry + max_dist if direction == "LONG" else entry - max_dist
    return round(tp, 8), True


def snapshot() -> dict:
    """Nilai ambang yang sedang berlaku — untuk endpoint/diagnostik."""
    globs = globals()
    snap = {key: globs[var] for var, key in _KEYS.items()}
    snap["tp_atr_mult_by_lane"]  = dict(TP_ATR_BY_LANE)
    snap["time_stop_min_by_lane"] = dict(TIME_STOP_MIN_BY_LANE)
    snap["failfast_lanes"]        = sorted(FAILFAST_LANES)
    snap["failfast_sl_gap_by_lane"] = dict(FAILFAST_SL_GAP_BY_LANE)
    snap["profit_lock_tiers"]     = [list(t) for t in PROFIT_LOCK_TIERS]
    return snap
