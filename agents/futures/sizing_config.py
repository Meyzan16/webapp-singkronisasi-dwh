"""Config rantai ukuran FUTURES — satu rumah untuk `risk → notional → leverage → margin`.

Dibuat 5 Sep 2026 (PLAN-FUTURES-AGENTIC.md Fase 1a). Sebelum ini, rantai yang
menentukan BERAPA BESAR uang masuk justru bagian paling tidak bisa ditala:

    backend/app/api/v1/balance.py   18 konstanta hardcode, 0 dibaca dari config
    agents/futures/utils.py         15 konstanta hardcode, 0 dibaca dari config

Padahal 141 kunci lain sudah dinamis. Untuk mengubah risiko per trade, plafon
margin, atau plafon leverage, satu-satunya jalan adalah deploy ulang.

Dan ada jebakan yang lebih halus, ditemukan saat menulis modul ini:
`lane_cap_*` SUDAH punya baris config dan tampil di UI, tapi `utils.py` tak
pernah membacanya sendiri — nilainya sampai ke sana hanya karena loop MONITOR
memutasi dict `MAX_SL_MARGIN_PCT_BY_LANE` yang kebetulan dipakai bersama. Jadi
plafon leverage milik SCANNER bergantung pada loop MONITOR yang sudah sempat
jalan. Kalau monitor mati atau siklus pertamanya belum selesai, scanner diam-diam
memakai angka hardcode sementara UI menampilkan angka lain. Modul ini menutup
celah itu: kedua loop memanggil `refresh()` yang sama.

Pola mengikuti `agents/futures/sl_config.py` yang sudah terbukti: nilai BEKU
sebagai cadangan, `refresh()` sekali per siklus, `snapshot()` untuk diagnostik.
Kegagalan membaca config TIDAK PERNAH menghentikan agen — ia memakai nilai
terakhir yang berhasil dibaca.

Fase 1a sengaja TIDAK mengubah satu pun angka: seluruh `default` di sini sama
persis dengan konstanta yang digantikannya, sehingga perilaku live identik.
Yang berubah hanya: angkanya kini bisa diubah tanpa deploy.
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)


# ── Nilai BEKU ────────────────────────────────────────────────────────────────
# Cadangan saat DB tak terbaca, DAN acuan `default` saat memanggil cfg.get.
# JANGAN memakai nilai berjalan sebagai default cfg.get — bawaannya akan hanyut
# mengikuti override sampai titik pulang hilang (pelajaran BIGMOVER_DAILY_BUDGET).
_FROZEN: dict[str, float] = {
    # Risiko per trade (persen wallet). Sumber: balance.FUTURES_RISK_*_FRACTION.
    # Disimpan sebagai PERSEN, bukan fraksi — supaya angka di UI terbaca manusia
    # ("1.0" = 1 %), sama seperti kunci `daily_loss_limit_pct` yang sudah ada.
    "size_risk_base_pct":          1.0,     # 0.01
    "size_risk_max_pct":           1.5,     # 0.015
    "size_conviction_floor":      72.0,
    "size_conviction_ceil":       90.0,
    # Batas portofolio & posisi tunggal.
    #
    # `max_auto_positions` SENGAJA memakai kunci yang sudah ada (dipakai
    # auto_trader), bukan kunci baru. Sampai fase ini ada DUA konstanta untuk
    # satu hal yang sama — `MAX_AUTO_POSITIONS`=6 di auto_trader dan
    # `FUTURES_MAX_CONCURRENT`=6 di balance.py — dan hanya yang pertama bisa
    # ditala. Operator yang menaikkannya lewat UI akan mendapati gerbang kedua
    # tetap menolak di angka lama, tanpa satu pun pesan yang menjelaskan.
    "max_auto_positions":          6.0,
    "size_min_notional_abs":      50.0,
    "size_portfolio_max_risk_pct": 6.0,     # 0.06
    "size_max_margin_pct":        35.0,     # 0.35
    "size_max_notional_mult":      1.5,
    # Pemotong risiko saat drawdown (dulu dua angka telanjang di tengah fungsi).
    "size_drawdown_cut_pct":      10.0,
    "size_drawdown_risk_mult":     0.5,
    # Leverage — sumber: utils.py
    "lev_liq_safety_mult":         2.0,
    "lev_max_default":             6.0,
    "lev_lane_cap_default":       25.0,
    "lev_extended_change_24h_pct": 15.0,
}

#: Plafon leverage ABSOLUT per lane (utils.MAX_LEVERAGE_BY_LANE).
_FROZEN_LEV_MAX_LANE: dict[str, float] = {
    "accumulation": 5.0,
    "pre_gainer":   5.0,
    "pre_move":     5.0,     # alias lama
    "momentum":     6.0,
    "bigmover":     3.0,
}

# Nilai yang SEDANG berlaku — dibaca sinkron oleh jalur panas (per simbol).
_LIVE: dict[str, float] = dict(_FROZEN)
_LIVE_LEV_MAX_LANE: dict[str, float] = dict(_FROZEN_LEV_MAX_LANE)


def lev_max_key(lane: str) -> str:
    """Kunci `agent_config` untuk plafon leverage sebuah lane."""
    return f"lev_max_{lane}"


def tunable_lanes() -> list[str]:
    """Lane yang wajib punya baris config sendiri — registry ∪ yang sudah punya
    nilai beku, supaya lane baru ikut tanpa mengedit berkas ini."""
    try:
        from app.services.agent_registry import LANE_AGENT
        known = set(LANE_AGENT)
    except Exception:
        known = set()
    return sorted(known | set(_FROZEN_LEV_MAX_LANE))


# ── Pembacaan sinkron (jalur panas) ───────────────────────────────────────────

def get(key: str) -> float:
    """Nilai yang sedang berlaku. Kunci tak dikenal → KeyError, bukan diam-diam 0."""
    return _LIVE[key]


def risk_fraction_base() -> float:
    """Fraksi (bukan persen) — bentuk yang dipakai rumus sizing."""
    return _LIVE["size_risk_base_pct"] / 100.0


def risk_fraction_max() -> float:
    return _LIVE["size_risk_max_pct"] / 100.0


def portfolio_max_risk_fraction() -> float:
    return _LIVE["size_portfolio_max_risk_pct"] / 100.0


def max_margin_fraction() -> float:
    return _LIVE["size_max_margin_pct"] / 100.0


def lev_max_for_lane(lane: str) -> int:
    """Plafon leverage absolut sebuah lane; lane tak dikenal → bawaan.

    Sengaja TIDAK meminjam angka lane tetangga — meminjam diam-diam persis jenis
    kegagalan senyap yang berulang di proyek ini.
    """
    return int(_LIVE_LEV_MAX_LANE.get(lane, _LIVE["lev_max_default"]))


# ── Pembaruan (sekali per siklus) ─────────────────────────────────────────────

async def refresh() -> None:
    """Tarik override dari `agent_config`.

    Dipanggil dari loop scanner DAN loop monitor. Keduanya, bukan salah satu:
    kalau hanya satu loop yang menyegarkan, loop lain memakai angka basi tanpa
    satu pun error — dan itulah celah yang modul ini dibuat untuk menutupnya.
    """
    try:
        from agents.shared.config_reader import cfg

        merged = {k: await cfg.get("futures", k, v) for k, v in _FROZEN.items()}
        merged_lane = {
            lane: await cfg.get(
                "futures", lev_max_key(lane),
                _FROZEN_LEV_MAX_LANE.get(lane, _FROZEN["lev_max_default"]))
            for lane in tunable_lanes()
        }
        _LIVE.update(merged)
        _LIVE_LEV_MAX_LANE.update(merged_lane)
    except Exception as exc:      # noqa: BLE001 — config gagal tak boleh menghentikan agen
        logger.warning("sizing_config_refresh_failed", error=str(exc)[:120])


def snapshot() -> dict:
    """Nilai yang sedang berlaku — untuk endpoint diagnostik & UI."""
    return {"scalar": dict(_LIVE), "lev_max_by_lane": dict(_LIVE_LEV_MAX_LANE)}
