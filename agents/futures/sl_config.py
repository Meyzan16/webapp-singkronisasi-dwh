"""Lebar SL per lane — satu sumber, bisa ditala tanpa deploy (M4).

**Temuan 2 Agu 2026 dari ledger keluar (44 exit, dinormalkan ke ATR):**

    lane          n   ATR%   SL harga%   SL/ATR   WR     expectancy
    bigmover     28   6,07     7,99       1,32   64,3%     +0,04%
    momentum     13   1,54     6,29       4,00    0,0%     −2,40%
    accumulation  2   1,18     4,20       3,60  100,0%     +2,42%
    pre_gainer    2   2,13     6,06       3,26    0,0%     −3,98%

Sebaran SL dalam **harga%** jauh lebih rapat (CV 0,23) daripada dalam **kelipatan
ATR** (CV 0,72). Artinya lebar SL sebenarnya disusun terhadap HARGA, bukan
terhadap volatilitas koin — perbedaan 1,3× vs 4,0× ATR antar lane itu **efek
samping** dari koin yang diperdagangkan, bukan keputusan desain.

Akibat paling nyata: **61% posisi bigmover SL-nya mentok plafon 8%**, bukan hasil
`ATR × 1,5` yang dimaksudkan. Di lane yang justru memperdagangkan koin paling
bergejolak (ATR median 6,3%, maksimum 29,6%), rancangan sadar-volatilitas itu
mati diam-diam pada mayoritas posisi.

Efek berantainya: setiap gerbang yang diskalakan ke `risk_pct` — progress
time-stop, progress fail-fast, penjaga rugi — berperilaku sangat berbeda antar
lane tanpa itu pernah diniatkan.

Modul ini mengumpulkan angka-angka penyusun SL yang tadinya tersebar sebagai
konstanta di tiga file agen berbeda (`agent1` yang juga dipakai `agent2`,
`agent3`, `agent_bigmover`). Nilai bawaannya **wajib** sama persis dengan
perilaku lama, sehingga tanpa override apa pun tak ada satu pun keputusan yang
berubah.
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)


#: Lebar SL per lane. Kunci `agent_config`: `sl_{param}_{lane}`.
#:
#: Arti tiap parameter (perhatikan: lane memakainya dengan cara berbeda, dan itu
#: memang keadaan sebenarnya — didokumentasikan, bukan disamarkan):
#:
#:   swing_buffer_atr  jarak tambahan di bawah/atas swing, dalam kelipatan ATR.
#:                     0 = lane ini tak memakai swing sama sekali (bigmover).
#:   max_pct           batas lebar SL (% harga). Pada lane berbasis swing ini
#:                     PEMICU: bila SL swing melebihi ini, SL dihitung ulang dari
#:                     `fallback_atr_mult`. Pada bigmover ini PLAFON KERAS.
#:   fallback_atr_mult kelipatan ATR yang dipakai saat SL swing terlalu lebar
#:                     (lane swing) atau sebagai rumus utama (bigmover).
#:   floor_pct         SL tak boleh lebih sempit dari ini (% harga).
#:   floor_atr_mult    lantai kedua: SL tak boleh lebih sempit dari ATR × ini.
#:                     0 = lane ini tak punya lantai berbasis ATR.
#:   quiet_fallback_pct SL tetap untuk koin terlalu sepi (ATR < quiet_atr_pct).
#:                     0 = tak berlaku.
#:   quiet_atr_pct     ambang "koin terlalu sepi". 0 = tak berlaku.
SL_PARAMS: dict[str, dict[str, float]] = {
    # agent1 — dipakai juga oleh agent2 (accumulation memakai level agent1)
    "pre_gainer": {
        "swing_buffer_atr": 0.3, "max_pct": 8.0, "fallback_atr_mult": 1.5,
        "floor_pct": 1.5, "floor_atr_mult": 1.0,
        "quiet_fallback_pct": 0.0, "quiet_atr_pct": 0.0,
    },
    "accumulation": {
        "swing_buffer_atr": 0.3, "max_pct": 8.0, "fallback_atr_mult": 1.5,
        "floor_pct": 1.5, "floor_atr_mult": 1.0,
        "quiet_fallback_pct": 0.0, "quiet_atr_pct": 0.0,
    },
    "momentum": {
        "swing_buffer_atr": 0.5, "max_pct": 7.0, "fallback_atr_mult": 1.2,
        "floor_pct": 1.5, "floor_atr_mult": 1.0,
        "quiet_fallback_pct": 0.0, "quiet_atr_pct": 0.0,
    },
    "bigmover": {
        "swing_buffer_atr": 0.0, "max_pct": 8.0, "fallback_atr_mult": 1.5,
        "floor_pct": 2.5, "floor_atr_mult": 0.0,
        "quiet_fallback_pct": 4.0, "quiet_atr_pct": 0.5,
    },
}

#: Lane yang belum punya entri sendiri memakai ini — nilai paling konservatif
#: dari lane yang ada, bukan meminjam angka lane tertentu.
SL_DEFAULTS: dict[str, float] = {
    "swing_buffer_atr": 0.3, "max_pct": 8.0, "fallback_atr_mult": 1.5,
    "floor_pct": 1.5, "floor_atr_mult": 1.0,
    "quiet_fallback_pct": 0.0, "quiet_atr_pct": 0.0,
}

#: Salinan BEKU — `refresh()` menimpa `SL_PARAMS`, jadi default WAJIB dibaca dari
#: sini. Kalau tidak, satu override akan menjadi "default" permanen dan menghapus
#: baris config tak lagi memulihkan perilaku asli.
_FROZEN: dict[str, dict[str, float]] = {k: dict(v) for k, v in SL_PARAMS.items()}

PARAM_NAMES: tuple[str, ...] = tuple(SL_DEFAULTS)


def sl_key(param: str, lane: str) -> str:
    """Kunci `agent_config` untuk satu parameter SL sebuah lane."""
    return f"sl_{param}_{lane}"


def tunable_lanes() -> list[str]:
    """Lane yang wajib punya baris config SL sendiri — registry ∪ yang sudah
    punya nilai bawaan, supaya lane baru ikut tanpa mengedit file ini."""
    try:
        # Lane PENSIUN saja. Lane `agentic` diatur `exit_config` (satu set
        # parameter, bukan per lane) — memberinya baris di sini akan
        # menghidupkan lagi tumpukan tombol yang sedang ditinggalkan.
        from app.services.agent_registry import LEGACY_LANES
        known = set(LEGACY_LANES)
    except Exception:
        known = set()
    return sorted(known | set(_FROZEN))


def params(lane: str) -> dict[str, float]:
    """Parameter SL yang berlaku untuk sebuah lane.

    Lane tak dikenal mendapat `SL_DEFAULTS`, **bukan** angka lane lain — meminjam
    diam-diam dari lane tetangga persis jenis kegagalan senyap yang ingin
    dihindari di sini.
    """
    return SL_PARAMS.get(lane) or dict(SL_DEFAULTS)


async def refresh() -> None:
    """Tarik override dari `agent_config`. Gagal = diam & pakai nilai terakhir —
    scanner TIDAK boleh berhenti hanya karena config tak terbaca."""
    try:
        from agents.shared.config_reader import cfg
        merged: dict[str, dict[str, float]] = {}
        for lane in tunable_lanes():
            base = _FROZEN.get(lane, SL_DEFAULTS)
            merged[lane] = {
                param: await cfg.get("futures", sl_key(param, lane), base[param])
                for param in PARAM_NAMES
            }
        SL_PARAMS.clear()
        SL_PARAMS.update(merged)
    except Exception as exc:
        logger.warning("sl_config_refresh_failed", error=str(exc)[:120])


def snapshot() -> dict:
    """Nilai yang sedang berlaku — untuk endpoint/diagnostik."""
    return {lane: dict(vals) for lane, vals in SL_PARAMS.items()}
