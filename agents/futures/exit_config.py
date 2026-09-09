"""Config aturan keluar FUTURES — sembilan angka, satu rumah.

PLAN-FUTURES-AGENTIC.md Fase 4. Menggantikan `monitor_config.py` (38 konstanta +
21 kunci per lane = 5 lane x 4 parameter) dan `sl_config.py` (39 rujukan lane)
untuk jalur agentic.

Kenapa sembilan dan bukan lima puluh sembilan: tiap parameter di sini menjawab
satu pertanyaan yang bisa diuji dari ledger. Parameter yang tak bisa dijawab
ledger tak layak jadi parameter — ia cuma tombol yang tak ada yang tahu cara
memutarnya, dan lima puluh sembilan tombol semacam itu adalah keadaan yang
sedang ditinggalkan.

Bawaannya berasal dari data, bukan selera:
  * `exit_tp1_atr_mult` 1,2 — trade rata-rata bergerak 0,67 ATR ke arah untung
    dan pemenangnya mencapai 3,56 ATR; TP lama dipasang 4-8 ATR dan hanya
    tersentuh 4% (5 dari 112). 1,2 ATR adalah jarak yang MEMANG pernah dicapai.
  * `exit_be_arm_cost_mult` 3,0 — breakeven lama menyala di +1,5% absolut lalu
    ditutup pullback rutin, menghasilkan 31 trade impas rata-rata +$0,25.
    Menuntut 3x biaya membuat rem itu baru menyala saat untungnya nyata.
  * `exit_max_hold_h` 8 — median hold pemenang 7,8 jam; yang lebih lama dari itu
    hampir seluruhnya berakhir di SL.

Pola sama dengan `sizing_config.py`: nilai BEKU sebagai cadangan, `refresh()`
sekali per siklus, `snapshot()` untuk diagnostik. Gagal baca config tak pernah
menghentikan monitor — posisi yang sudah terbuka WAJIB tetap dijaga.
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)


_FROZEN: dict[str, float] = {
    # Tangga TP dalam kelipatan ATR (K7 — usulan plan, belum ditetapkan owner).
    "exit_tp1_atr_mult":      1.2,
    "exit_tp2_atr_mult":      2.5,
    # Porsi posisi yang dijual di tiap tangga (K8). Sisanya (25%) jadi pelari
    # tanpa plafon — satu-satunya sumber kemenangan besar. Trade terbaik dalam
    # riwayat (+13,04%, 3,56 ATR) persis jenis yang dibunuh TP tetap.
    "exit_tp1_close_frac":    0.50,
    "exit_tp2_close_frac":    0.25,
    # Breakeven: DUA syarat sekaligus, keduanya wajib (perbaikan B5).
    "exit_be_arm_cost_mult":  3.0,
    "exit_be_arm_atr":        0.6,
    # Saat rem menyala, SL dipindahkan untuk mengunci sekian bagian untung yang
    # sudah dicapai (lantainya entry+biaya). Memindahkan tepat ke breakeven
    # membuat setiap sentuhan menghasilkan NOL menurut definisi — replay
    # membuktikan menaikkan ambang penyalaan 3x->8x biaya tak mengurangi
    # jumlah impas sama sekali, karena yang salah bukan kapannya tapi ke mana.
    "exit_be_lock_frac":      0.5,
    # Trailing sesudah TP1.
    "exit_trail_lock_frac":   0.75,
    # Time-stop.
    "exit_max_hold_h":        8.0,
    "exit_time_stop_progress": 0.5,
    # SL awal (dipakai agen saat menyusun level, bukan oleh exit_rules).
    "exit_sl_atr_mult":       1.2,
    # Loop cepat: posisi dijaga ketat saat harga sudah sedekat ini ke SL.
    # Sampai 5 Sep 2026 pemicunya adalah LEVERAGE (>=10x), bukan kedekatan ke
    # SL — sehingga BLUAI dengan leverage 2 dijaga loop lambat dan sempat
    # melompat dari −8% ke −17% di antara dua tick.
    "exit_fast_loop_atr":     1.0,
}

_LIVE: dict[str, float] = dict(_FROZEN)


def get(key: str) -> float:
    """Nilai berlaku. Kunci tak dikenal melempar — bukan diam-diam 0."""
    return _LIVE[key]


#: Kunci yang BOLEH ditala oleh exit-learning, dan hanya ini.
#:
#: Nilai hasil belajar TIDAK ditulis ke kunci aslinya, melainkan ke
#: `<kunci>_learned`. Pemisahan ini yang menjaga dua lapis pengaman
#: `exit_learning`: nilai yang disetel manusia dan nilai yang diusulkan mesin
#: tak pernah saling menimpa, dan mematikan saklar mengembalikan angka manusia
#: apa adanya — bukan angka mesin yang kebetulan tertulis terakhir.
_LEARNABLE = ("exit_tp1_atr_mult", "exit_tp2_atr_mult")

#: Saklar milik pemilik. Selama 0, angka hasil belajar boleh tersimpan tapi
#: tidak boleh menyentuh satu pun keputusan.
_LEARNING_SWITCH = "monitor_exit_learning_enabled"


async def refresh() -> None:
    """Tarik override dari `agent_config`. Gagal = pakai nilai terakhir."""
    try:
        from agents.shared.config_reader import cfg
        _LIVE.update({k: await cfg.get("futures", k, v) for k, v in _FROZEN.items()})

        # Lapis kedua: hasil belajar hanya dipakai bila pemiliknya menyalakan.
        #
        # Sampai 9 Sep 2026 modul ini tak mengenal saklar itu sama sekali,
        # sementara `exit_learning` menulis usulannya ke kunci per-lane milik
        # monitor LAMA yang tak lagi dibaca jalur agen tunggal. Hasilnya
        # kegagalan senyap dua arah: pembelajaran keluar berjalan, menghitung,
        # menulis — dan tak ada yang membacanya.
        if float(await cfg.get("futures", _LEARNING_SWITCH, 0.0)) >= 1.0:
            for k in _LEARNABLE:
                # 0 = belum ada usulan; konvensi yang sama dengan kunci per-lane.
                usulan = float(await cfg.get("futures", f"{k}_learned", 0.0))
                if usulan > 0:
                    _LIVE[k] = usulan
    except Exception as exc:      # noqa: BLE001 — monitor tak boleh berhenti
        logger.warning("exit_config_refresh_failed", error=str(exc)[:120])


def snapshot() -> dict:
    return dict(_LIVE)
