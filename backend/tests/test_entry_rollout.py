"""Jalur rollout untuk parameter sisi MASUK, dan parameter MAJEMUK.

Tangga TP adalah tiga angka yang harus bergerak BERSAMA. Mengajukannya sebagai
tiga baris terpisah salah dua kali: aturan satu-canary-per-market memblokir dua
sisanya, dan TP1 yang berubah sendirian mengubah BENTUK tangganya — hasilnya
tak lagi mencerminkan usulan mana pun.
"""

import inspect
import json

import pytest

from agents.learning import exit_rollout as er


def test_tangga_tp_terdaftar_sebagai_parameter_majemuk():
    assert "entry_tp_ladder" in er.COMPOSITE_PARAMS
    for market, n in (("futures", 3), ("spot", 3)):
        keys = er.composite_keys("entry_tp_ladder", market)
        assert len(keys) == n, f"{market}: tangga harus 3 anak, dapat {len(keys)}"
        assert len(set(keys)) == n, "ada kunci duplikat — satu rung tak akan tertulis"


def test_kunci_tangga_cocok_dengan_yang_DITARIK_agen():
    """Kunci yang ditulis rollout HARUS kunci yang sama dengan yang ditarik
    scheduler. Beda satu huruf = usulan mendarat di kunci mati, persis kesalahan
    lane SPOT 8 Agu."""
    import pathlib
    fsch = pathlib.Path("../agents/futures/scheduler.py").read_text(encoding="utf-8")
    from agents.opportunity import scanner as sc
    ssrc = inspect.getsource(sc.refresh_tp_ladder)
    for k in er.composite_keys("entry_tp_ladder", "futures"):
        assert k in fsch, f"{k} tak pernah ditarik scheduler futures"
    for k in er.composite_keys("entry_tp_ladder", "spot"):
        assert k in ssrc, f"{k} tak pernah ditarik scanner spot"


def test_terdaftar_di_kedua_market():
    for m in ("futures", "spot"):
        assert "entry_tp_ladder" in er.SUPPORTED_PARAMS_BY_MARKET[m]


def test_canary_menulis_SEMUA_kunci_bukan_sebagian():
    """Menulis sebagian meninggalkan tangga setengah berubah — bentuk yang tak
    pernah diusulkan siapa pun dan hasilnya tak mencerminkan apa-apa."""
    src = inspect.getsource(er.start_canary)
    assert "composite_keys(" in src
    assert "for k in _keys:" in src
    assert "baris_config_hilang" in src, "kunci hilang harus menggagalkan, bukan diam"


def test_rollback_mengembalikan_SEMUA_kunci():
    src = inspect.getsource(er.rollback)
    assert "composite_keys(" in src
    assert '"previous"' in src, "nilai lama tiap kunci harus tersimpan untuk dibalik"


def test_nilai_lama_tiap_kunci_disimpan_saat_canary():
    """Tanpa menyimpan nilai lama PER KUNCI, rollback hanya bisa memulihkan satu
    anak tangga dan menebak sisanya."""
    src = inspect.getsource(er.start_canary)
    assert '"previous": _lama' in src


def test_parameter_tunggal_tak_terpengaruh():
    """Jalur lama harus tetap utuh — parameter tunggal tidak boleh ikut memakai
    cabang majemuk."""
    for p in ("tp_atr_mult", "failfast_min_sl_gap"):
        assert er.composite_keys(p, "futures") == ()
    src = inspect.getsource(er.start_canary)
    assert "else:" in src and "cfg_row.value_num = row.proposed_value" in src


def test_usulan_tangga_masuk_selalu_shadow():
    """Sisi masuk mengubah SETIAP posisi baru. Ia wajib melewati tahapan yang
    sama dengan sisi keluar, bukan berlaku langsung."""
    src = inspect.getsource(er._usulkan_tangga_masuk)
    assert "propose(" in src
    assert "start_canary" not in src


def test_usulan_ditahan_saat_bukti_kurang():
    src = inspect.getsource(er._usulkan_tangga_masuk)
    assert "recommendation_ready" in src
    assert "mfe_kurang" in src


def test_json_usulan_berbentuk_peta_kunci_nilai():
    """Bentuknya harus {kunci: nilai}, bukan daftar — daftar bergantung pada
    urutan, dan urutan yang bergeser diam-diam menukar TP1 dengan TP3."""
    src = inspect.getsource(er.propose)
    assert 'json.dumps({"keys": values}' in src
    contoh = {"bigmover_tp1_atr_mult": 0.338, "bigmover_tp3_atr_mult": 1.895}
    assert json.loads(json.dumps({"keys": contoh}))["keys"] == contoh
