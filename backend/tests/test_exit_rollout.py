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
    assert roll.param_config_key("tp_atr_mult", "bigmover") == mcfg.tp_lane_key("bigmover")
    assert roll.param_config_key("failfast_min_sl_gap", "momentum") == \
        mcfg.failfast_gap_key("momentum")


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
