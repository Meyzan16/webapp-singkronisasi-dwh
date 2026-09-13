"""Tiga perbaikan 12 Agu — semuanya kelas kegagalan SENYAP.

Ketiganya punya bentuk yang sama: mekanisme yang ADA, terlihat benar saat dibaca,
tapi tak pernah menghasilkan efek yang dimaksud. Tak satu pun memunculkan error.
"""

import inspect
import pathlib

import pytest


# ── 1. fail-fast tak boleh membukukan kerugian melewati SL ───────────────────

def test_sl_dibukukan_di_harga_sl_dan_dinilai_pertama():
    """Terukur 11 Agu: BLUAIUSDT ber-SL 7,99% dibukukan di −16,96% karena
    fail-fast dievaluasi SEBELUM blok SL dan menutup di harga pasar.

    Jalur lane lama (dengan fail-fast-nya) dibongkar 13 Sep 2026. Jaminannya
    kini struktural di `exit_rules.evaluate`: SL dinilai PALING PERTAMA dan
    menutup di `close_price=s.sl` — stop order sungguhan terisi di harga stop.
    """
    from agents.futures import exit_rules as er
    src = inspect.getsource(er.evaluate)
    assert src.index("sl_breached(s)") < src.index("TP1_HIT"), "SL bukan yang pertama"
    assert "close_price=s.sl" in src
    # Monitor tak lagi punya jalur lain yang bisa menutup di harga pasar.
    from agents.futures import monitor as fut_mon
    assert "fail_fast" not in inspect.getsource(fut_mon._monitor_agentic)


# ── 2. tangga TP SHORT tak boleh menembus nol ────────────────────────────────

def test_scheduler_tak_lagi_menarik_tala_bigmover():
    """Blok penarik `a_bm.*` bertahan sesudah modulnya dihapus di Fase 8 —
    `NameError` tiap siklus, ditelan jadi `agent_config_pull_failed`. Terlihat
    di log 13 Sep 2026 sebelum dibongkar."""
    src = pathlib.Path("../agents/futures/scheduler.py").read_text(encoding="utf-8")
    assert "a_bm." not in src


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
