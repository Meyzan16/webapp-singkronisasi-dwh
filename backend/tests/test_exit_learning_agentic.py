"""Pembelajaran keputusan KELUAR harus mengikuti agen tunggal.

Lubang Fase 5. `apply_exit_recommendations` menulis usulannya ke kunci per-lane
monitor LAMA (`monitor_tp_atr_mult_lane_<lane>`). Jalur keluar agen tunggal
membaca `exit_config` — 12 kunci, bukan per-lane. Jadi untuk agen yang benar-benar
berdagang, pembelajaran keluar menghitung, menulis, dan tak ada yang membacanya.

Itu bentuk kegagalan terburuk di proyek ini: dari luar, pembelajaran yang
hasilnya menguap tak terbedakan dari pembelajaran yang bekerja.
"""

import pytest

from agents.futures import exit_config as EC
from agents.learning import exit_learning as EL


# ── Ke mana usulan ditulis ───────────────────────────────────────────────────

def kunci_lama(lane: str) -> str:
    return f"monitor_tp_atr_mult_lane_{lane}"


def test_agen_aktif_dikenali_dari_registry():
    """Bukan dibandingkan dengan teks "agentic" — agen aktif berikutnya harus
    ikut terbawa tanpa menyunting modul ini."""
    from app.services.agent_registry import ACTIVE_FUTURES_AGENTS

    for agen in ACTIVE_FUTURES_AGENTS:
        assert EL._lane_agen_aktif(agen.removeprefix("futures_"))


def test_lane_lama_bukan_agen_aktif():
    for lama in ("bigmover", "momentum", "breakout", "pre_gainer", "accumulation"):
        assert not EL._lane_agen_aktif(lama)


def test_usulan_agen_aktif_ke_kunci_yang_dibaca():
    assert EL._kunci_tp("agentic", kunci_lama) == "exit_tp1_atr_mult_learned"


def test_usulan_lane_lama_tetap_ke_kunci_lamanya():
    """Jalur lama masih mengelola posisi era lane sampai yang terakhir tutup —
    syarat Fase 8. Memindahkannya sekarang membuat posisi itu tak tertala."""
    assert EL._kunci_tp("bigmover", kunci_lama) == "monitor_tp_atr_mult_lane_bigmover"


def test_lane_kosong_tak_dianggap_agen_aktif():
    assert not EL._lane_agen_aktif("")
    assert not EL._lane_agen_aktif(None)


# ── Saklar pemilik tetap berarti ─────────────────────────────────────────────

class CfgPalsu:
    """Pengganti `config_reader.cfg` — menjawab dari dict."""

    def __init__(self, nilai: dict):
        self.nilai = nilai

    async def get(self, group: str, key: str, default):
        return self.nilai.get(key, default)


@pytest.fixture(autouse=True)
def exit_config_bersih():
    EC._LIVE.clear()
    EC._LIVE.update(EC._FROZEN)
    yield
    EC._LIVE.clear()
    EC._LIVE.update(EC._FROZEN)


async def _refresh_dengan(monkeypatch, nilai: dict):
    import agents.shared.config_reader as CR
    monkeypatch.setattr(CR, "cfg", CfgPalsu(nilai))
    await EC.refresh()


@pytest.mark.asyncio
async def test_saklar_mati_hasil_belajar_diabaikan(monkeypatch):
    """Angka boleh tersimpan; selama saklar 0 ia tak boleh menyentuh keputusan."""
    await _refresh_dengan(monkeypatch, {
        "monitor_exit_learning_enabled": 0.0,
        "exit_tp1_atr_mult_learned": 3.3,
    })
    assert EC.get("exit_tp1_atr_mult") == EC._FROZEN["exit_tp1_atr_mult"]


@pytest.mark.asyncio
async def test_saklar_nyala_hasil_belajar_dipakai(monkeypatch):
    await _refresh_dengan(monkeypatch, {
        "monitor_exit_learning_enabled": 1.0,
        "exit_tp1_atr_mult_learned": 3.3,
    })
    assert EC.get("exit_tp1_atr_mult") == pytest.approx(3.3)


@pytest.mark.asyncio
async def test_usulan_nol_berarti_belum_ada_usulan(monkeypatch):
    """0 = konvensi 'pakai nilai global', sama dengan kunci per-lane lama.
    Tanpa ini, kunci yang baru dibuat akan menarik TP ke nol."""
    await _refresh_dengan(monkeypatch, {
        "monitor_exit_learning_enabled": 1.0,
        "exit_tp1_atr_mult_learned": 0.0,
    })
    assert EC.get("exit_tp1_atr_mult") == EC._FROZEN["exit_tp1_atr_mult"]


@pytest.mark.asyncio
async def test_nilai_manusia_tak_tertimpa_mesin(monkeypatch):
    """Kunci `_learned` TERPISAH: mematikan saklar mengembalikan angka manusia
    apa adanya, bukan angka mesin yang kebetulan tertulis terakhir."""
    await _refresh_dengan(monkeypatch, {
        "monitor_exit_learning_enabled": 0.0,
        "exit_tp1_atr_mult": 1.9,              # disetel manusia
        "exit_tp1_atr_mult_learned": 3.3,      # usulan mesin
    })
    assert EC.get("exit_tp1_atr_mult") == pytest.approx(1.9)


@pytest.mark.asyncio
async def test_hanya_kunci_dalam_daftar_yang_boleh_ditala(monkeypatch):
    """SL dan batas waktu BUKAN wilayah exit-learning. Membiarkannya ditala
    berarti mesin boleh melonggarkan pengaman kerugian sendirian."""
    assert "exit_sl_atr_mult" not in EC._LEARNABLE
    assert "exit_max_hold_h" not in EC._LEARNABLE

    await _refresh_dengan(monkeypatch, {
        "monitor_exit_learning_enabled": 1.0,
        "exit_sl_atr_mult_learned": 9.9,
    })
    assert EC.get("exit_sl_atr_mult") == EC._FROZEN["exit_sl_atr_mult"]
