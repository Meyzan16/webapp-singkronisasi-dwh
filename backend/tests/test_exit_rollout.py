"""Jaring pengaman penyalaan bertahap parameter keluar (M5).

Yang dijaga di sini adalah disiplin yang membuat tahapan ini bukan sekadar
tombol: baseline harus direkam sebelum angka berlaku, hanya satu lane boleh
canary pada satu waktu, hanya exit sesudah aktivasi yang dihitung, dan perubahan
yang memburuk harus kembali sendiri.
"""

import pytest

from agents.learning import exit_rollout as roll


def test_parameter_dipetakan_ke_kunci_config_yang_dibaca_monitor():
    """Kunci diturunkan dari monitor_config, bukan ditulis ulang — kalau ditulis
    ulang, ledger dan monitor bisa menunjuk kunci berbeda tanpa error."""
    from agents.futures import monitor_config as mcfg
    assert roll.param_config_key("tp_atr_mult", "bigmover") == \
        ("futures", mcfg.tp_lane_key("bigmover"))
    assert roll.param_config_key("failfast_min_sl_gap", "momentum") == \
        ("futures", mcfg.failfast_gap_key("momentum"))


def test_grup_config_ikut_dikembalikan_per_market():
    """SPOT dan FUTURES menyimpan ambang di GRUP berbeda. Menulis ke grup yang
    salah "berhasil" tanpa error tapi tak pernah dibaca monitor mana pun — jadi
    grup wajib ikut dikembalikan, bukan diasumsikan pemanggil."""
    from agents.opportunity import monitor_config as scfg
    grup, kunci = roll.param_config_key("tp_atr_mult", "bigmover", market="spot")
    assert grup == "spot"
    assert kunci == scfg.tp_lane_key("bigmover")
    # Lane `bigmover` ada di KEDUA market — grupnya yang membedakan, bukan namanya.
    assert roll.param_config_key("tp_atr_mult", "bigmover")[0] == "futures"


def test_failfast_tak_ditawarkan_ke_spot():
    """Monitor SPOT tak punya fail-fast; menawarkannya berarti menulis kunci yang
    tak pernah dibaca monitornya."""
    assert "failfast_min_sl_gap" in roll.SUPPORTED_PARAMS_BY_MARKET["futures"]
    assert "failfast_min_sl_gap" not in roll.SUPPORTED_PARAMS_BY_MARKET["spot"]
    with pytest.raises(ValueError):
        roll.param_config_key("failfast_min_sl_gap", "bigmover", market="spot")


def test_market_disimpan_eksplisit_bukan_ditebak_dari_lane():
    """Lane `accumulation` dan `bigmover` ada di kedua market, jadi market mustahil
    ditebak dari nama lane — menebak salah berarti menulis ke monitor yang salah."""
    from app.models.futures_exit_rollout import FuturesExitRollout
    from agents.futures import monitor_config as mcfg
    from agents.opportunity import monitor_config as scfg
    assert hasattr(FuturesExitRollout, "market")
    assert set(mcfg.tunable_lanes()) & set(scfg.tunable_lanes()), \
        "uji ini kehilangan maknanya bila tak ada lane yang beririsan"


def test_parameter_tak_dikenal_ditolak():
    with pytest.raises(ValueError):
        roll.param_config_key("parameter_karangan", "bigmover")


@pytest.mark.asyncio
async def test_propose_menolak_parameter_tak_didukung():
    out = await roll.propose("bigmover", "parameter_karangan", 1.0)
    assert out["status"] == "param_tak_dikenal"
    assert "tp_atr_mult" in out["supported"]


def test_gate_masuk_akal():
    """Canary butuh lebih banyak bukti daripada baseline minimum, dan toleransi
    harus kecil — toleransi longgar membuat rollback tak pernah terjadi."""
    assert roll.CANARY_MIN_OUTCOMES > roll.BASELINE_MIN_OUTCOMES
    assert 0 < roll.CANARY_TOLERANCE_PCT <= 1.0


def test_tahapan_hanya_yang_dikenal():
    """Tahapan ditulis di beberapa tempat; kalau ada yang mengarang nama tahap
    baru, alur bisa macet tanpa error."""
    import inspect
    src = inspect.getsource(roll)
    for stage in ('"shadow"', '"canary"', '"active"', '"rolled_back"'):
        assert stage in src


def test_semua_parameter_didukung_punya_kunci():
    for param in roll.SUPPORTED_PARAMS:
        for lane in ("bigmover", "momentum"):
            assert roll.param_config_key(param, lane)


def test_model_rollout_terdaftar():
    """Model yang tak terdaftar tabelnya tak pernah dibuat — gagal senyap saat
    dipakai pertama kali."""
    from app.models import FuturesExitRollout
    from app.models.futures_exit_rollout import FuturesExitRollout as Direct
    assert FuturesExitRollout is Direct
    assert Direct.__tablename__ == "futures_exit_rollouts"


def test_advance_tak_menaikkan_shadow_ke_canary():
    """Loop hanya boleh MENGEVALUASI. Menaikkan sendiri berarti memberlakukan
    perubahan ke uang sungguhan tanpa ada yang memutuskan."""
    import inspect
    src = inspect.getsource(roll.advance)
    assert "start_canary" not in src
    assert "evaluate" in src
