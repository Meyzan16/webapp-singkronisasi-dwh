"""Jaring pengaman jeda lane (F4) — jeda harus bertahan melewati restart.

Penyakit yang dijaga terukur di log 24-25 Agu: lane `momentum` dijeda TIGA kali
dalam ~15 jam dengan `streak` selalu **1**, dan jeda kedua datang kurang dari dua
jam setelah yang pertama. Jeda 24 jam itu sama sekali tak menahan — setiap restart
mengosongkan `_lane_paused_until`, lane hidup kembali, lalu dijeda lagi dari nol.

Akibatnya jeda berlipat yang dirancang (24 j → 48 j → … → 168 j) tak pernah sekali
pun tercapai: eskalasinya diukur dari hitungan yang selalu direset.

Test di sini memakai dict in-memory saja — tak menyentuh DB — supaya yang diuji
adalah ATURANNYA, bukan ketersediaan database.
"""

import time

import pytest

from agents.futures import risk_gate as rg


@pytest.fixture(autouse=True)
def _bersihkan_state():
    """Tiap test mulai dari keadaan bersih, dan tak meninggalkan jejak."""
    rg._lane_paused_until.clear()
    rg._lane_pause_streak.clear()
    yield
    rg._lane_paused_until.clear()
    rg._lane_pause_streak.clear()


def test_streak_naik_saat_lane_dijeda_berulang():
    """Inti eskalasi: jeda kedua harus LEBIH LAMA daripada yang pertama."""
    rg.update_lane_wr("uji", wins=1, total=rg.LANE_WR_MIN_SAMPLE)   # WR jauh di bawah ambang
    jeda_1 = rg._lane_paused_until["uji"] - time.time()
    assert rg._lane_pause_streak["uji"] == 1

    # Jeda pertama dibuat kedaluwarsa, lalu lane dinilai lagi dan tetap buruk.
    rg._lane_paused_until["uji"] = time.time() - 1
    rg.update_lane_wr("uji", wins=1, total=rg.LANE_WR_MIN_SAMPLE)

    assert rg._lane_pause_streak["uji"] == 2, "hitungan pengulangan tidak naik"
    jeda_2 = rg._lane_paused_until["uji"] - time.time()
    assert jeda_2 > jeda_1 * 1.5, (
        f"jeda kedua ({jeda_2/3600:.1f} j) tidak lebih lama dari yang pertama "
        f"({jeda_1/3600:.1f} j) — eskalasi tak bekerja")


def test_jeda_tak_diulang_selagi_masih_berjalan():
    """Selagi jeda berjalan, penilaian ulang tak boleh menaikkan streak.

    Tanpa penjaga ini, tiap siklus evaluasi (60 detik) akan melipatgandakan jeda
    sampai mentok plafon dalam hitungan menit.
    """
    rg.update_lane_wr("uji", wins=1, total=rg.LANE_WR_MIN_SAMPLE)
    until_awal = rg._lane_paused_until["uji"]

    for _ in range(5):
        rg.update_lane_wr("uji", wins=1, total=rg.LANE_WR_MIN_SAMPLE)

    assert rg._lane_pause_streak["uji"] == 1
    assert rg._lane_paused_until["uji"] == until_awal


def test_lane_membaik_mereset_hitungan():
    """Lane yang benar-benar pulih tak boleh dihukum riwayat lamanya."""
    rg.update_lane_wr("uji", wins=1, total=rg.LANE_WR_MIN_SAMPLE)
    assert rg._lane_pause_streak["uji"] == 1

    rg._lane_paused_until["uji"] = time.time() - 1          # jeda habis
    rg.update_lane_wr("uji", wins=rg.LANE_WR_MIN_SAMPLE,     # WR 100%
                      total=rg.LANE_WR_MIN_SAMPLE)

    assert "uji" not in rg._lane_pause_streak
    assert "uji" not in rg._lane_paused_until


def test_jeda_mentok_plafon():
    """Eskalasi berhenti di plafon, tidak tumbuh tanpa batas."""
    for _ in range(12):
        rg._lane_paused_until["uji"] = time.time() - 1
        rg.update_lane_wr("uji", wins=1, total=rg.LANE_WR_MIN_SAMPLE)

    jeda_jam = (rg._lane_paused_until["uji"] - time.time()) / 3600
    assert jeda_jam <= rg.LANE_PAUSE_MAX_HOURS + 1


def test_fungsi_simpan_muat_ada_dan_async():
    """Kalau salah satu hilang/berubah jadi sync, evaluate_risk_gate ikut pecah."""
    import inspect
    assert inspect.iscoroutinefunction(rg.load_lane_pause_state)
    assert inspect.iscoroutinefunction(rg.save_lane_pause_state)


def test_evaluate_memanggil_muat_dan_simpan():
    """Menyimpan tanpa pernah memuat = jeda tetap menguap saat restart.

    Diperiksa lewat AST, bukan pencarian teks: versi pertama test ini mencocokkan
    string, dan saat sambungannya sengaja dilepas dengan cara dijadikan komentar,
    test tetap lulus — komentarnya masih mengandung nama fungsi itu. Penjaga yang
    bisa dikelabui komentar lebih buruk daripada tak ada penjaga, karena ia
    memberi rasa aman yang keliru.
    """
    import ast
    import inspect
    import textwrap

    pohon = ast.parse(textwrap.dedent(inspect.getsource(rg.evaluate_risk_gate)))
    dipanggil = {
        n.func.id for n in ast.walk(pohon)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "load_lane_pause_state" in dipanggil, "jeda tak pernah dipulihkan"
    assert "save_lane_pause_state" in dipanggil, "jeda tak pernah disimpan"
