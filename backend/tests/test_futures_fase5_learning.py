"""Fase 5 — pembelajaran & gerbang risiko mengikuti agen tunggal.

Semua yang diuji di sini adalah kegagalan SENYAP: tak ada yang error, tapi
pelajaran diam-diam hilang. Tiga di antaranya sudah pernah terjadi di proyek ini.
"""

import pytest

from agents.futures import learning_policy as lp
from agents.futures import risk_gate as rg


# ── 1. Identitas sinyal agentic ──────────────────────────────────────────────

SINYAL_AGENTIC = [
    "momentum_awal Δ24h +8.0%",
    "momentum_mapan Δ24h +15.0%",
    "momentum_kuat Δ24h +25.0%",
    "momentum_ekstrem Δ24h +80.0%",
    "arah_1h_konfirmasi +2.5%",
    "arah_1h_datar +0.3%",
    "arah_1h_berlawanan -2.0%",
    "volume_konfirmasi 3.0x rata-rata",
    "volume_naik 1.5x rata-rata",
    "volume_memudar 0.5x rata-rata — pembeli hilang",
    "oi_naik +5.0% — uang baru masuk searah",
    "oi_naik_tipis +1.0%",
    "oi_turun -5.0% — posisi ditutup, momentum memudar",
    "funding_netral +0.010% — bahan bakar belum terpakai",
    "funding_wajar +0.070%",
    "funding_sesak +0.150% — sisi ini sudah ramai",
    "rsi_sehat 60 — masih ada ruang",
    "rsi_jenuh 85",
]


@pytest.mark.parametrize("teks", SINYAL_AGENTIC)
def test_setiap_sinyal_agentic_punya_canonical_id(teks):
    """Tanpa canonical ID, sinyal jatuh ke kunci berbasis teks yang TAK TERLIHAT
    oleh Predictive Repair — persis bug 29 Jul 2026 (49 aksi perbaikan tercatat
    "berhasil" tapi berdampak nol karena namespace-nya tak beririsan)."""
    key = lp.canonical_signal_key(teks)
    assert key is not None, teks
    assert key.startswith("signal_id:ag."), key


def test_tingkat_momentum_tidak_runtuh_jadi_satu_kunci():
    """Sebelum Fase 5 keempatnya jatuh ke `bm.magnitude` karena teksnya memuat
    'Δ24h' — resolusi tingkat hilang, padahal justru itu yang membedakan gerak
    awal dari yang sudah parabolik."""
    kunci = {lp.canonical_signal_key(t) for t in SINYAL_AGENTIC[:4]}
    assert len(kunci) == 4, kunci


def test_tanda_plus_minus_tidak_memecah_kunci():
    """`+2,5%` dan `-2,5%` dulu menghasilkan dua kunci berbeda lewat fallback
    teks, sehingga sampel LONG dan SHORT tak pernah menyatu."""
    a = lp.canonical_signal_key("arah_1h_konfirmasi +2.5%")
    b = lp.canonical_signal_key("arah_1h_konfirmasi -2.5%")
    assert a == b


def test_nilai_angka_tidak_mengubah_kunci():
    a = lp.canonical_signal_key("volume_konfirmasi 3.0x rata-rata")
    b = lp.canonical_signal_key("volume_konfirmasi 9.7x rata-rata")
    assert a == b


def test_aturan_spesifik_menang_atas_yang_umum():
    """`oi_naik_tipis` tak boleh tertangkap aturan `oi_naik`."""
    assert lp.canonical_signal_key("oi_naik_tipis +1.0%") == "signal_id:ag.oi_naik_tipis"
    assert lp.canonical_signal_key("oi_naik +5.0%") == "signal_id:ag.oi_naik"


def test_sinyal_lane_lama_tidak_tergeser():
    """Aturan agentic ditaruh paling atas — pastikan ia tak merebut sinyal lama."""
    assert lp.canonical_signal_key("Δ24h +30% — parabolic") == "signal_id:bm.magnitude"
    assert lp.canonical_signal_key("Wyckoff Accumulation") == "signal_id:wyckoff.accumulation"


# ── 2. Cross-agent learning ──────────────────────────────────────────────────

def test_cross_agent_memuat_semua_agen_futures():
    """Daftar ini sudah ketinggalan DUA kali: bigmover tak pernah masuk sejak
    lahir (81% trade!), dan agentic akan terlewat dengan cara yang sama."""
    from agents.shared.cross_agent_learning import ALL_AGENTS
    from app.services.agent_registry import FUTURES_AGENTS, SPOT_AGENT

    assert SPOT_AGENT in ALL_AGENTS
    for a in FUTURES_AGENTS:
        assert a in ALL_AGENTS, a


def test_cross_agent_memuat_bigmover_dan_agentic():
    from agents.shared.cross_agent_learning import ALL_AGENTS
    assert "futures_agent_bigmover" in ALL_AGENTS
    assert "futures_agentic" in ALL_AGENTS


# ── 3. Jejak ukuran di ledger keputusan ──────────────────────────────────────

def test_jejak_ukuran_kosong_saat_belum_disizing():
    """Kandidat yang ditolak SEBELUM tahap sizing memang tak punya ukuran.
    Menulis nol akan membuatnya tampak seperti posisi berukuran nol yang pernah
    dipertimbangkan."""
    from agents.futures.decision_ledger import _jejak_ukuran
    assert _jejak_ukuran({}) == {}
    assert _jejak_ukuran({"sizing": {}}) == {}


def test_jejak_ukuran_memetakan_seluruh_angka():
    from agents.futures.decision_ledger import _jejak_ukuran

    hasil = _jejak_ukuran({"sizing": {
        "risk_usd": 17.0, "notional": 322.0, "margin": 80.5,
        "cost_usd": 0.64, "tp1_net_usd": 15.6, "sl_net_usd": -17.6,
    }})
    assert hasil == {
        "risk_usd": 17.0, "notional_usd": 322.0, "margin_usd": 80.5,
        "tp1_net_usd": 15.6, "sl_net_usd": -17.6, "cost_usd": 0.64,
    }


def test_jejak_ukuran_abaikan_nilai_bukan_angka():
    from agents.futures.decision_ledger import _jejak_ukuran
    hasil = _jejak_ukuran({"sizing": {"risk_usd": "banyak", "notional": 100.0}})
    assert hasil["risk_usd"] is None
    assert hasil["notional_usd"] == 100.0


# ── 4. Jeda per arah ─────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def bersihkan_arah():
    rg._dir_wr.clear()
    rg._dir_paused_until.clear()
    yield
    rg._dir_wr.clear()
    rg._dir_paused_until.clear()


def test_arah_dijeda_saat_wr_jatuh():
    rg.update_direction_wr("LONG", 3, 25)          # 12% < 35%
    dijeda, alasan = rg.is_direction_paused("LONG")
    assert dijeda and "LONG" in alasan


def test_arah_sehat_tidak_dijeda():
    rg.update_direction_wr("SHORT", 15, 25)        # 60%
    assert rg.is_direction_paused("SHORT")[0] is False


def test_sampel_kurang_tidak_menjeda():
    """Menjeda dari 5 trade adalah menghukum derau."""
    rg.update_direction_wr("LONG", 0, 5)
    assert rg.is_direction_paused("LONG")[0] is False


def test_jeda_satu_arah_tak_menyeret_arah_lain():
    rg.update_direction_wr("LONG", 3, 25)
    rg.update_direction_wr("SHORT", 15, 25)
    assert rg.is_direction_paused("LONG")[0] is True
    assert rg.is_direction_paused("SHORT")[0] is False


def test_arah_tak_dikenal_diabaikan():
    rg.update_direction_wr("SAMPING", 0, 99)
    assert rg.is_direction_paused("SAMPING")[0] is False
    assert rg.get_direction_wr("SAMPING") == (0.0, 0)


def test_direction_state_bentuknya_lengkap():
    rg.update_direction_wr("LONG", 3, 25)
    st = rg.direction_state()
    assert set(st) == {"LONG", "SHORT"}
    for v in st.values():
        assert set(v) == {"wins", "total", "paused", "pause_until"}


def test_jeda_lane_tetap_ada():
    """Jeda per arah MENDAMPINGI, bukan menggantikan — empat lane lama masih
    men-trade sampai Fase 7 dan jeda lane satu-satunya rem bagi mereka."""
    assert hasattr(rg, "is_lane_paused")
    assert hasattr(rg, "update_lane_wr")


# ── 5. Skema model ───────────────────────────────────────────────────────────

def test_skema_fitur_naik_ke_v2():
    """v1 dilatih dari ledger dengan label 'menang' lama, dan 75% barisnya
    ternyata impas selevel fee. Melatih di atas campuran v1+v2 berarti mewarisi
    label yang sudah diketahui salah."""
    from agents.learning.futures_adaptive_model import FEATURE_SCHEMA_VERSION
    assert FEATURE_SCHEMA_VERSION == "futures_features_v2"
