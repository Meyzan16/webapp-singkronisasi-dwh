"""Jaring pengaman batas TP hasil belajar (MONITOR futures, PRIORITAS 2).

Yang dijaga di sini bukan kebenaran angkanya, melainkan sifat yang membuat fitur
ini aman dinyalakan: default harus NOL efek, angka hasil belajar hanya berlaku
untuk lane pemiliknya, dan kompresi tak pernah menjauhkan target.
"""

import pytest

from agents.futures import monitor_config as mcfg


@pytest.fixture(autouse=True)
def _restore():
    """Kembalikan state modul — nilainya global, bocor antar test bila dibiarkan."""
    saved = (mcfg.TP_MAX_ATR_MULT, mcfg.EXIT_LEARNING_ENABLED, dict(mcfg.TP_ATR_BY_LANE))
    yield
    mcfg.TP_MAX_ATR_MULT, mcfg.EXIT_LEARNING_ENABLED, mcfg.TP_ATR_BY_LANE = (
        saved[0], saved[1], saved[2])


def test_default_tanpa_efek():
    """Tanpa override apa pun, TP dikembalikan apa adanya."""
    assert mcfg.TP_MAX_ATR_MULT == 0.0
    assert mcfg.EXIT_LEARNING_ENABLED == 0.0
    assert mcfg.effective_take_profit(100, 130, 3.0, "LONG", lane="bigmover") == (130, False)


def test_angka_belajar_diabaikan_saat_saklar_mati():
    """Menulis rekomendasi ke DB tak boleh mengubah perilaku sebelum disetujui."""
    mcfg.TP_ATR_BY_LANE = {"bigmover": 0.6}
    mcfg.EXIT_LEARNING_ENABLED = 0.0
    assert mcfg.tp_atr_limit("bigmover") == mcfg.TP_MAX_ATR_MULT


def test_angka_belajar_hanya_untuk_lane_pemiliknya():
    """Lane tanpa angka sendiri jatuh ke batas global, bukan meminjam lane lain."""
    mcfg.TP_MAX_ATR_MULT = 4.0
    mcfg.EXIT_LEARNING_ENABLED = 1.0
    mcfg.TP_ATR_BY_LANE = {"bigmover": 0.6}
    assert mcfg.tp_atr_limit("bigmover") == 0.6
    assert mcfg.tp_atr_limit("momentum") == 4.0
    assert mcfg.tp_atr_limit("") == 4.0


@pytest.mark.parametrize("direction,tp,expected", [("LONG", 130, 101.8), ("SHORT", 70, 98.2)])
def test_kompresi_hanya_mendekatkan(direction, tp, expected):
    mcfg.EXIT_LEARNING_ENABLED = 1.0
    mcfg.TP_ATR_BY_LANE = {"bigmover": 0.6}
    got, compressed = mcfg.effective_take_profit(100, tp, 3.0, direction, lane="bigmover")
    assert compressed
    assert got == pytest.approx(expected)
    assert abs(got - 100) < abs(tp - 100)      # tak pernah menjauh


def test_tp_sudah_dekat_tak_disentuh():
    mcfg.EXIT_LEARNING_ENABLED = 1.0
    mcfg.TP_ATR_BY_LANE = {"bigmover": 2.0}
    assert mcfg.effective_take_profit(100, 101, 3.0, "LONG", lane="bigmover") == (101, False)


def test_kunci_config_per_lane_ikut_registry():
    """Lane baru harus otomatis punya kunci config — tanpa mengedit monitor_config."""
    from app.services.agent_registry import LANE_AGENT
    lanes = mcfg._known_lanes()
    assert set(lanes) == set(LANE_AGENT)
    assert mcfg.tp_lane_key("bigmover") == "monitor_tp_atr_mult_lane_bigmover"


def test_saklar_terdaftar_di_config_defaults():
    """Saklar wajib punya baris default, kalau tidak ia tak muncul di UI Settings."""
    from app.services.agent_config_defaults import DEFAULTS
    keys = {d["key"] for d in DEFAULTS if d["group"] == "futures"}
    assert "monitor_exit_learning_enabled" in keys
