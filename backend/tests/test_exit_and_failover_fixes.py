"""Tiga perbaikan 12 Agu — semuanya kelas kegagalan SENYAP.

Ketiganya punya bentuk yang sama: mekanisme yang ADA, terlihat benar saat dibaca,
tapi tak pernah menghasilkan efek yang dimaksud. Tak satu pun memunculkan error.
"""

import inspect
import pathlib

import pytest


# ── 1. fail-fast tak boleh membukukan kerugian melewati SL ───────────────────

def test_failfast_mundur_bila_sl_sudah_tertembus():
    """Terukur 11 Agu: BLUAIUSDT ber-SL 7,99% dibukukan di −16,96%.

    Sebabnya urutan: fail-fast dievaluasi (~baris 985) SEBELUM blok SL (~1187),
    lalu menutup di harga pasar berjalan. Blok SL sengaja memakai
    `close_price = sl` karena stop order sungguhan terisi di harga stop.
    """
    from agents.futures import monitor as fut_mon
    src = inspect.getsource(fut_mon)
    assert "_sl_tertembus" in src, "penjaga SL pada fail-fast hilang"
    assert "and not _sl_tertembus" in src, \
        "fail-fast masih bisa menutup walau SL sudah tertembus"
    # Harus memakai harga sadar-sumbu yang sama dengan blok SL, bukan `price`
    # polos — kalau tidak, sumbu candle yang menembus SL akan terlewat.
    assert "eff_low <= sl" in src and "eff_high >= sl" in src


def test_blok_sl_tetap_membukukan_di_harga_sl():
    """Ini yang membuat perbaikan di atas berarti. Kalau blok SL ikut memakai
    harga pasar, memindahkan penanganan ke sana tak memperbaiki apa pun."""
    from agents.futures import monitor as fut_mon
    src = inspect.getsource(fut_mon)
    assert src.count("close_price  = sl") >= 2, "LONG dan SHORT harus dua-duanya"


def test_kejadian_dicatat_bukan_dibuang_diam_diam():
    """Kalau fail-fast mundur tanpa jejak, tak ada cara tahu seberapa sering
    aturan ini menggigit — dan bug serupa berikutnya kembali tak terlihat."""
    from agents.futures import monitor as fut_mon
    assert "fail_fast_after_sl" in inspect.getsource(fut_mon)


# ── 2. tangga TP SHORT tak boleh menembus nol ────────────────────────────────

def test_lantai_short_bisa_ditala_lewat_config():
    """Konstanta modul tanpa kunci config = tombol yang tak bisa diputar. Kunci
    ini ditarik scheduler tiap siklus, sama seperti MIN_SCORE."""
    src = pathlib.Path("../agents/futures/scheduler.py").read_text(encoding="utf-8")
    assert "bigmover_short_tp_max_drop_frac" in src, "override tak pernah ditarik"
    assert "a_bm.SHORT_TP_MAX_DROP_FRAC =" in src


def test_baris_config_lantai_short_tersedia():
    src = pathlib.Path("app/services/agent_config_defaults.py").read_text(encoding="utf-8")
    assert '"key": "bigmover_short_tp_max_drop_frac"' in src
    assert '"default": 0.90' in src


# ── 3. failover host SPOT benar-benar dipanggil ──────────────────────────────

def test_failover_ada_DAN_dipakai():
    """`fallback_spot()` sudah ada berbulan-bulan dan TIDAK PERNAH dipanggil —
    saat host utama diblokir 12 jam, tak ada yang beralih. Fungsi baru tanpa
    pemanggil akan mengulang kesalahan yang sama persis."""
    from app.services import binance_urls
    assert hasattr(binance_urls, "refresh_spot_host")
    src = pathlib.Path("../agents/opportunity/scheduler.py").read_text(encoding="utf-8")
    assert "refresh_spot_host()" in src, "failover tak dipanggil loop mana pun"


def test_url_spot_mengikuti_hasil_failover():
    """Kalau `get_spot_url()` tetap membaca setelan mentah, peralihan tak
    berpengaruh pada satu pun pemanggil."""
    from app.services import binance_urls as bu
    assert "_active_spot" in inspect.getsource(bu.get_spot_url)


def test_futures_sengaja_tak_punya_failover():
    """data-api.binance.vision melayani /api/v3 saja. Mengarahkan /fapi ke sana
    akan menghasilkan 404 beruntun yang terlihat seperti pemadaman."""
    from app.services import binance_urls as bu
    assert "_active_spot" not in inspect.getsource(bu.get_fapi_url)


@pytest.mark.asyncio
async def test_probe_ber_cooldown():
    """Tanpa cooldown, tiap siklus menambah dua permintaan jaringan hanya untuk
    memastikan host yang sudah diketahui sehat."""
    from app.services import binance_urls as bu
    assert bu.PROBE_INTERVAL_SEC >= 60
    bu._probe_at = __import__("time").time()
    hasil = await bu.refresh_spot_host()
    assert hasil["status"] == "dilewati"


def test_failover_punya_tugas_MANDIRI_bukan_di_loop_scanner():
    """Terukur 13 Agu: host utama mati, kedua scanner macet 42 menit, dan
    failover TIDAK menyala (`_active_spot` masih None) — karena ia dipanggil
    dari ATAS loop scanner, sementara loop itu terjebak menunggu timeout pada
    host yang sudah mati.

    Penyelamat yang menunggu di belakang pintu yang dikuncinya sendiri. Ia harus
    berjalan sebagai tugas terpisah supaya tak ikut terblokir.
    """
    from app.services import binance_urls as bu
    assert hasattr(bu, "run_host_watchdog")
    main_src = pathlib.Path("app/main.py").read_text(encoding="utf-8")
    assert "run_host_watchdog()" in main_src, "watchdog tak pernah dijalankan"
    assert "asyncio.create_task(run_host_watchdog" in main_src, \
        "watchdog dipanggil inline — ia akan ikut terblokir"


def test_watchdog_memaksa_probe_bukan_menunggu_cooldown():
    """Cooldown 300 dtk berguna saat dipanggil tiap siklus scanner. Watchdog
    punya iramanya sendiri, jadi menunggu cooldown akan melewatkan giliran."""
    from app.services import binance_urls as bu
    assert "refresh_spot_host(force=True)" in inspect.getsource(bu.run_host_watchdog)


# ── Fase 8 ───────────────────────────────────────────────────────────────────
# Tes untuk lane lama (pre_gainer / accumulation / momentum / bigmover) dibuang
# bersama modul agennya: `agent1.py`, `agent2.py`, `agent3.py`,
# `agent_bigmover.py` dihapus setelah trade era mereka tutup semuanya.
#
# Yang TIDAK dibuang: tes yang menjaga perilaku modul yang masih hidup. Riwayat
# 112 trade lane lama juga tetap utuh di DB — `FUTURES_AGENTS` masih memuat nama
# mereka supaya endpoint riwayat bisa membacanya.
