"""Katalog sinyal: agen tunggal harus terjelaskan, bukan sekadar terdaftar.

Lubang Fase 5 yang ditutup di sini bukan "sinyalnya hilang" — ke-18 ID `ag.*`
memang sudah masuk katalog, karena katalog dibangun dari `_SIGNAL_ID_RULES`.
Yang salah lebih halus: kategorinya diambil dari bagian PERTAMA ID (`ag`), yang
tak dikenal, sehingga ke-18-nya jatuh ke "lainnya" sekaligus, tanpa deskripsi
dan tanpa pemetaan agen.

Di layar Analysis, sinyal yang terdaftar-tanpa-penjelasan tak terbedakan dari
sinyal yang memang tak dikenal. Terdaftar bukan berarti terjelaskan.
"""

import pytest

from app.services import signal_catalog as SC


def id_agentic() -> list[str]:
    """Semua ID stabil agen tunggal, dari sumber yang sama dengan katalog."""
    from agents.futures.learning_policy import _SIGNAL_ID_RULES

    return sorted({sid for _parts, sid in _SIGNAL_ID_RULES if sid.startswith("ag.")})


def test_ada_sinyal_agentic_untuk_diuji():
    """Kalau ini kosong, tes di bawahnya lulus tanpa menguji apa pun."""
    assert len(id_agentic()) >= 18


@pytest.mark.parametrize("sid", id_agentic())
def test_tiap_sinyal_agentic_punya_kategori_nyata(sid):
    entry = SC.SIGNAL_CATALOG[f"signal_id:{sid}"]
    assert entry["category"] != "lainnya", (
        f"{sid} tak terkelompok — tambahkan keluarganya ke _CATEGORY_BY_PREFIX")


@pytest.mark.parametrize("sid", id_agentic())
def test_tiap_sinyal_agentic_punya_deskripsi(sid):
    entry = SC.SIGNAL_CATALOG[f"signal_id:{sid}"]
    assert entry["description"].strip(), (
        f"{sid} tanpa deskripsi — di layar ia tak terbedakan dari sinyal tak dikenal")


@pytest.mark.parametrize("sid", id_agentic())
def test_tiap_sinyal_agentic_menunjuk_agennya(sid):
    entry = SC.SIGNAL_CATALOG[f"signal_id:{sid}"]
    assert entry["agents"], f"{sid} tak menunjuk agen mana pun"
    assert all(a["agent"] == "futures_agentic" for a in entry["agents"])


def test_semua_sinyal_agentic_terkumpul_di_peta_agen():
    """`AGENT_SIGNAL_MAP` yang bolong membuat pertanyaan 'sinyal apa saja yang
    dipakai agen ini' terjawab SEBAGIAN — dan jawaban sebagian terlihat sama
    meyakinkannya dengan jawaban lengkap."""
    assert set(SC.AGENT_SIGNAL_MAP.get("futures_agentic", [])) == {
        f"signal_id:{sid}" for sid in id_agentic()
    }


# ── Kategori diturunkan dari keluarga, bukan didaftar satu per satu ──────────

def test_kategori_agentic_ikut_keluarganya():
    assert SC._kategori_untuk("ag.momentum_mapan") == "momentum"
    assert SC._kategori_untuk("ag.oi_naik_tipis") == "open interest"
    assert SC._kategori_untuk("ag.rsi_jenuh") == "teknikal"
    assert SC._kategori_untuk("ag.volume_memudar") == "aliran dana"


def test_sinyal_non_agentic_tak_berubah_perilakunya():
    """Perubahan ini tak boleh menyentuh sinyal market lain."""
    assert SC._kategori_untuk("tech.bb_squeeze") == "teknikal"
    assert SC._kategori_untuk("bm.apa_pun") == "big mover"
    assert SC._kategori_untuk("entah.apa") == "lainnya"


def test_keluarga_ag_tak_dikenal_jatuh_ke_lainnya_bukan_meledak():
    """Sinyal `ag.*` baru dengan keluarga asing harus turun anggun — dan tes
    kategori di atas yang akan menangkapnya, bukan pengguna."""
    assert SC._kategori_untuk("ag.keluargabaru_sesuatu") == "lainnya"


def test_poin_tidak_disalin_ke_katalog():
    """Nilai poin hidup di `agentic._skor`. Menyalinnya ke katalog melahirkan dua
    kebenaran yang menyimpang diam-diam begitu salah satunya disetel — pola yang
    sudah berulang kali jadi sumber cacat di proyek ini."""
    for sid in id_agentic():
        entry = SC.SIGNAL_CATALOG[f"signal_id:{sid}"]
        for agen in entry["agents"]:
            assert "max_pts" not in agen, f"{sid} menduplikasi angka poin"
