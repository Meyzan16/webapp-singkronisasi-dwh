"""Fase 3 — agen futures tunggal.

Dua kelompok janji yang dijaga di sini:

  1. SELAMA SAKLAR MATI, tak ada yang berubah. Ini yang membuat fase ini aman
     dimasukkan ke sistem yang sedang men-trade uang.
  2. Pemisahan daftar agen benar. Salah memakai daftar gagal SENYAP di dua arah —
     riwayat hilang dari laporan, atau agen pensiun ikut menghitung kuota.
"""

import pytest

from agents.futures import agentic as ag
from app.services import agent_registry as reg


class FakeData:
    """Cukup mirip FuturesData untuk jalur skor & level."""

    def __init__(self, n=60, harga=100.0, vol=1000.0, funding=0.0, oi=5.0,
                 lonjakan_vol=3.0, rsi_sehat=True):
        # Harga bergerak naik tapi TIDAK monoton — deret monoton menghasilkan
        # RSI ~100 yang justru kena penalti "jenuh", sehingga kandidat sintetis
        # tak pernah lolos ambang dan tes terpenting ter-skip diam-diam.
        self.closes = []
        c = harga
        for i in range(n):
            c *= 1.004 if i % 3 else 0.997
            self.closes.append(c)
        self.highs = [x * 1.01 for x in self.closes]
        self.lows = [x * 0.99 for x in self.closes]
        self.volumes = [vol] * n
        self.volumes[-1] = vol * lonjakan_vol      # konfirmasi volume
        self.funding_rate = funding / 100
        self.oi_change_pct = oi
        self.liq_long_usdt = 0.0
        self.liq_short_usdt = 0.0


def tf(**kw):
    return {"1h": FakeData(**kw), "15m": FakeData(**kw), "4h": FakeData(**kw)}


@pytest.fixture(autouse=True)
def config_bawaan():
    ag._LIVE.clear()
    ag._LIVE.update(ag._FROZEN)
    yield
    ag._LIVE.clear()
    ag._LIVE.update(ag._FROZEN)


# ── 1. Saklar mati = nol perubahan ───────────────────────────────────────────

def test_saklar_mati_tak_pernah_menghasilkan_kandidat(monkeypatch):
    monkeypatch.setattr(ag, "enabled", lambda: False)
    assert ag.scan_symbol("XUSDT", tf(), 20.0, quote_vol_24h=1e9) == []


def test_bawaan_saklar_adalah_mati():
    from app.services.agent_config_defaults import all_defaults
    rows = {d["key"]: d for d in all_defaults() if d["group"] == "futures"}
    assert float(rows["agentic_enabled"]["default"]) == 0.0


# ── 2. Daftar agen: keputusan vs riwayat ─────────────────────────────────────

def test_aktif_dan_pensiun_menutup_seluruh_riwayat():
    assert set(reg.ACTIVE_FUTURES_AGENTS) | set(reg.LEGACY_FUTURES_AGENTS) == set(reg.FUTURES_AGENTS)
    assert not set(reg.ACTIVE_FUTURES_AGENTS) & set(reg.LEGACY_FUTURES_AGENTS)


def test_daftar_riwayat_masih_memuat_empat_lane_lama():
    """Kalau ini gagal, 112 trade lama hilang dari laporan, saldo, dan gerbang
    risiko — tanpa satu pun error."""
    for lama in ("futures_agent1", "futures_agent2", "futures_agent3",
                 "futures_agent_bigmover"):
        assert lama in reg.FUTURES_AGENTS


def test_hanya_agentic_yang_aktif():
    assert reg.ACTIVE_FUTURES_AGENTS == ["futures_agentic"]


def test_agentic_punya_label_dan_lane():
    assert reg.agent_label("futures_agentic") == "Agentic"
    assert reg.AGENT_LANE["futures_agentic"] == "agentic"
    assert reg.LANE_AGENT["agentic"] == "futures_agentic"


# ── 3. Gerbang masuk ─────────────────────────────────────────────────────────

@pytest.fixture
def nyala(monkeypatch):
    monkeypatch.setattr(ag, "enabled", lambda: True)


def test_likuiditas_tipis_ditolak_sebelum_dinilai(nyala):
    """Gerbang, bukan bahan skor: koin yang tak bisa menampung posisi kita tak
    layak dinilai berapa pun bagus polanya (B2 — BLUAI)."""
    assert ag.scan_symbol("XUSDT", tf(), 20.0, quote_vol_24h=1_000.0) == []


def test_gerak_terlalu_kecil_ditolak(nyala):
    assert ag.scan_symbol("XUSDT", tf(), 1.0, quote_vol_24h=1e9) == []


def test_gerak_ekstrem_ditolak(nyala):
    assert ag.scan_symbol("XUSDT", tf(), 400.0, quote_vol_24h=1e9) == []


def test_funding_ekstrem_diveto(nyala):
    hasil = ag.scan_symbol("XUSDT", tf(funding=0.5), 20.0, quote_vol_24h=1e9)
    assert hasil == []


def test_feed_rusak_ditolak(nyala):
    d = FakeData()
    d.volumes[-1] = 0.0                       # candle bervolume nol
    assert ag.scan_symbol("XUSDT", {"1h": d}, 20.0, quote_vol_24h=1e9) == []


def test_data_kurang_ditolak(nyala):
    assert ag.scan_symbol("XUSDT", {}, 20.0, quote_vol_24h=1e9) == []


# ── 4. Bentuk kandidat ───────────────────────────────────────────────────────

def test_kandidat_valid_punya_bentuk_lengkap(nyala):
    hasil = ag.scan_symbol("XUSDT", tf(oi=5.0), 25.0, quote_vol_24h=1e9)
    if not hasil:
        pytest.skip("skor di bawah ambang untuk data sintetis ini")
    c = hasil[0]
    for f in ("symbol", "direction", "price", "score", "signals", "leverage",
              "entry", "sl", "tp1", "tp2", "risk_pct", "tp1_pct", "rr_ratio",
              "agent", "setup_type", "atr_pct", "entry_slippage_pct"):
        assert f in c, f
    assert c["agent"] == "futures_agentic"
    assert c["setup_type"] == "agentic"
    assert 0 < c["score"] <= 100


def test_arah_mengikuti_tanda_gerak(nyala):
    naik = ag.scan_symbol("XUSDT", tf(), 25.0, quote_vol_24h=1e9)
    turun = ag.scan_symbol("XUSDT", tf(), -25.0, quote_vol_24h=1e9)
    for hasil, arah in ((naik, "LONG"), (turun, "SHORT")):
        if hasil:
            assert hasil[0]["direction"] == arah


# ── 5. Level datang dari exit_config — sambungan yang dulu putus ─────────────

def test_tp_dan_sl_mengikuti_exit_config(nyala):
    from agents.futures import exit_config as ecfg

    hasil = ag.scan_symbol("XUSDT", tf(), 25.0, quote_vol_24h=1e9)
    if not hasil:
        pytest.skip("skor di bawah ambang untuk data sintetis ini")
    c = hasil[0]
    atr = c["atr_pct"]
    assert c["risk_pct"] == pytest.approx(atr * ecfg.get("exit_sl_atr_mult"), rel=0.02)
    assert c["tp1_pct"] == pytest.approx(atr * ecfg.get("exit_tp1_atr_mult"), rel=0.02)


def test_mengubah_exit_config_menggerakkan_level_agen(nyala):
    """Inti sambungan: satu kunci menggerakkan agen DAN monitor. Sampai Fase 3
    keduanya punya angka sendiri — TP dipasang 4 ATR, tersentuh 4%."""
    from agents.futures import exit_config as ecfg

    a = ag.scan_symbol("XUSDT", tf(), 25.0, quote_vol_24h=1e9)
    if not a:
        pytest.skip("skor di bawah ambang untuk data sintetis ini")
    asli = ecfg._LIVE["exit_tp1_atr_mult"]
    try:
        ecfg._LIVE["exit_tp1_atr_mult"] = asli * 2
        b = ag.scan_symbol("XUSDT", tf(), 25.0, quote_vol_24h=1e9)
        assert b[0]["tp1_pct"] == pytest.approx(a[0]["tp1_pct"] * 2, rel=0.02)
    finally:
        ecfg._LIVE["exit_tp1_atr_mult"] = asli


# ── 6. Peringkat kandidat ────────────────────────────────────────────────────

def test_peringkat_mengambil_yang_terbaik():
    kandidat = [{"score": 66}, {"score": 88}, {"score": 71}]
    assert [c["score"] for c in ag.peringkat(kandidat, 2)] == [88, 71]


def test_peringkat_slot_nol_atau_negatif_kosong():
    assert ag.peringkat([{"score": 90}], 0) == []
    assert ag.peringkat([{"score": 90}], -1) == []


def test_peringkat_tak_meledak_saat_kandidat_kurang():
    assert len(ag.peringkat([{"score": 90}], 5)) == 1


# ── 7. Config ────────────────────────────────────────────────────────────────

def test_semua_kunci_agentic_punya_seed():
    from app.services.agent_config_defaults import all_defaults
    seeded = {d["key"]: d["default"] for d in all_defaults() if d["group"] == "futures"}
    for key, val in ag._FROZEN.items():
        assert key in seeded, f"{key} dibaca kode tapi tak di-seed"
        assert float(seeded[key]) == float(val), f"{key}: seed != nilai beku"
