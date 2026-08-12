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

def test_target_short_tak_pernah_negatif():
    """SHORT untung maksimum 100% (harga ke nol). Target di bawah nol MUSTAHIL
    tersentuh — posisi hanya bisa keluar lewat SL.

    Terukur 11 Agu: TUTUSDT ber-ATR 26,67% -> tp2 = -0,0076, tp3 = -0,0685.
    """
    from agents.futures import agent_bigmover as bm
    assert 0.0 < bm.SHORT_TP_MAX_DROP_FRAC < 1.0
    harga, atr = 0.11412, 0.11412 * 0.2667      # kasus TUTUSDT yang nyata
    lantai = harga * (1 - bm.SHORT_TP_MAX_DROP_FRAC)
    for mult in (bm.TP1_ATR_MULT, bm.TP2_ATR_MULT, bm.TP3_ATR_MULT):
        assert max(harga - atr * mult, lantai) > 0, f"target masih negatif di {mult}x"


def test_lantai_tak_menyentuh_koin_normal():
    """Lantai ini HANYA boleh menggigit pada kasus yang sudah rusak. Kalau ia
    ikut memotong target koin biasa, ia diam-diam mengubah strategi."""
    from agents.futures import agent_bigmover as bm
    harga, atr = 100.0, 3.0                      # ATR 3% — koin lazim
    lantai = harga * (1 - bm.SHORT_TP_MAX_DROP_FRAC)
    for mult in (bm.TP1_ATR_MULT, bm.TP2_ATR_MULT, bm.TP3_ATR_MULT):
        mentah = harga - atr * mult
        assert mentah > lantai, "lantai menggigit koin normal — strategi berubah"


def test_lantai_benar_benar_diterapkan_di_kode():
    from agents.futures import agent_bigmover as bm
    src = inspect.getsource(bm)
    assert "_lantai_short" in src
    for tp in ("tp1", "tp2", "tp3"):
        assert f"{tp} = max({tp}, _lantai_short)" in src, f"{tp} tak diberi lantai"


def test_lantai_short_bisa_ditala_lewat_config():
    """Konstanta modul tanpa kunci config = tombol yang tak bisa diputar. Kunci
    ini ditarik scheduler tiap siklus, sama seperti MIN_SCORE."""
    src = pathlib.Path("../agents/futures/scheduler.py").read_text(encoding="utf-8")
    assert "bigmover_short_tp_max_drop_frac" in src, "override tak pernah ditarik"
    assert "a_bm.SHORT_TP_MAX_DROP_FRAC =" in src


def test_bawaan_lantai_short_dibekukan():
    """Cadangan `cfg.get()` HARUS nilai beku, bukan nilai modul yang sudah
    ditimpa siklus sebelumnya — kalau tidak bawaan hanyut mengikuti override.
    Pola ini sudah dua kali jadi bug di proyek ini."""
    from agents.futures import agent_bigmover as bm
    asli = bm.SHORT_TP_MAX_DROP_FRAC
    try:
        bm.SHORT_TP_MAX_DROP_FRAC = 0.5          # tiruan override
        assert bm._FROZEN_SHORT_TP_MAX_DROP_FRAC == 0.90
    finally:
        bm.SHORT_TP_MAX_DROP_FRAC = asli
    src = pathlib.Path("../agents/futures/scheduler.py").read_text(encoding="utf-8")
    assert "a_bm._FROZEN_SHORT_TP_MAX_DROP_FRAC" in src, \
        "scheduler memakai nilai modul sbg cadangan — bawaan akan hanyut"


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
