"""Sisi MASUK: jatah harian & tangga TP dapat ditala, dan nilainya dari data.

Sisi keluar sudah nol hardcode. Sisi masuk baru dimulai — berkas ini menjaga
lapis pertamanya, dan yang paling penting: menjaga bahwa "bisa ditala" TIDAK
disalahartikan sebagai "sudah dipelajari". Dua hal berbeda; hanya yang kedua
memenuhi permintaan bahwa nilai datang dari hasil training.
"""

import inspect
import pathlib

import pytest


# ── Lapis 1: bisa ditala, bawaan = perilaku lama ─────────────────────────────

def test_jatah_harian_bisa_ditala_dua_market():
    fut = pathlib.Path("../agents/futures/auto_trader.py").read_text(encoding="utf-8")
    spot = pathlib.Path("../agents/opportunity/scheduler.py").read_text(encoding="utf-8")
    assert '"bigmover_daily_budget"' in fut
    assert '"max_auto_opens_per_day"' in spot


def test_tangga_tp_bisa_ditala_dua_market():
    fsch = pathlib.Path("../agents/futures/scheduler.py").read_text(encoding="utf-8")
    for k in ("bigmover_tp1_atr_mult", "bigmover_tp2_atr_mult", "bigmover_tp3_atr_mult"):
        assert k in fsch, f"{k} tak pernah ditarik"
    from agents.opportunity import scanner as sc
    src = inspect.getsource(sc.refresh_tp_ladder)
    for k in ("bigmover_tp1_pct", "bigmover_tp2_pct", "bigmover_tp3_pct"):
        assert k in src, f"{k} tak pernah ditarik"


def test_tangga_tp_spot_benar_benar_di_refresh_loop():
    """Fungsi refresh tanpa pemanggil = kode mati. Itu persis yang terjadi pada
    `fallback_spot()` selama berbulan-bulan."""
    src = pathlib.Path("../agents/opportunity/scheduler.py").read_text(encoding="utf-8")
    assert "refresh_tp_ladder()" in src


def test_bawaan_dibekukan_bukan_nilai_berjalan():
    """`cfg.get(..., NILAI_BERJALAN)` membuat bawaan hanyut mengikuti override
    sampai titik pulang hilang. Sudah tiga kali jadi bug di proyek ini."""
    from agents.futures import auto_trader as at, agent_bigmover as bm
    from agents.opportunity import scheduler as ssch
    assert at._FROZEN["BIGMOVER_DAILY_BUDGET"] == 6
    assert ssch._FROZEN["MAX_AUTO_OPENS_PER_DAY"] == 6
    assert bm._FROZEN_TP == {"TP1_ATR_MULT": 2.0, "TP2_ATR_MULT": 4.0, "TP3_ATR_MULT": 6.0}
    from agents.opportunity import scanner as sc
    assert sc._FROZEN_TP == {"BIGMOVER_TP1_PCT": 5.0, "BIGMOVER_TP2_PCT": 12.0,
                             "BIGMOVER_TP3_PCT": 25.0}


@pytest.mark.parametrize("modul,var", [
    ("../agents/futures/scheduler.py", "a_bm._FROZEN_TP"),
    ("../agents/opportunity/scanner.py", "_FROZEN_TP"),
])
def test_cadangan_memakai_nilai_beku(modul, var):
    src = pathlib.Path(modul).read_text(encoding="utf-8")
    assert var in src, f"{modul} memakai nilai berjalan sebagai cadangan"


# ── Lapis 2: nilainya diturunkan dari DATA ───────────────────────────────────

def test_tangga_tp_diturunkan_dari_mfe_bukan_dikarang():
    """MFE = sejauh mana harga BENAR-BENAR bergerak. Itu satu-satunya bukti
    tentang target yang realistis; angka lain apa pun adalah tebakan."""
    from agents.learning.exit_learning import recommend_entry_tp_ladder as r
    src = inspect.getsource(r)
    assert "mfe_atr" in src
    assert "LADDER_PERCENTILES" in src


def test_usulan_tangga_ditahan_sampai_sampel_cukup():
    from agents.learning import exit_learning as el
    assert el.LADDER_MIN_SAMPLES >= 25
    src = inspect.getsource(el.recommend_entry_tp_ladder)
    assert "recommendation_ready" in src


def test_konversi_spot_menolak_mengarang_tanpa_atr():
    """SPOT menyusun tangganya dalam PERSEN; mengubah kelipatan ATR ke persen
    butuh ATR. Tanpa itu, angka apa pun yang keluar adalah karangan."""
    from agents.learning import exit_learning as el
    src = inspect.getsource(el.recommend_entry_tp_ladder)
    assert "if (t and atr_med) else None" in src


def test_persentil_naik_monoton():
    """TP1 < TP2 < TP3. Persentil yang tak urut menghasilkan tangga terbalik."""
    from agents.learning import exit_learning as el
    p = el.LADDER_PERCENTILES
    assert list(p) == sorted(p) and len(set(p)) == 3


# ── Jeda lane progresif (nomor 3 daftar pertumbuhan) ─────────────────────────

def test_jeda_lane_berlipat_tiap_pengulangan():
    """Jeda TETAP membuat lane rugi jadi pintu putar dengan irama tetap:
    jeda -> kedaluwarsa -> buka -> rugi -> jeda lagi. Terukur 12 Agu pada
    `momentum` (WR 10%): dua putaran dalam sehari, sambil menyumbang 82%
    kerugian futures."""
    from agents.futures import risk_gate as rg
    src = inspect.getsource(rg.update_lane_wr)
    assert "_lane_pause_streak" in src
    assert "LANE_PAUSE_ESCALATION ** (streak - 1)" in src
    assert "LANE_PAUSE_MAX_HOURS" in src, "tanpa batas atas lane bisa terkunci selamanya"


def test_lane_yang_pulih_direset_hitungannya():
    """Lane yang benar-benar membaik tak boleh dihukum riwayat lamanya."""
    from agents.futures import risk_gate as rg
    assert "_lane_pause_streak.pop(lane, None)" in inspect.getsource(rg.update_lane_wr)


def test_bawaan_jeda_sama_dgn_perilaku_lama_pada_jeda_pertama():
    """Pengulangan PERTAMA harus tetap 24 jam — perubahan hanya berlaku pada
    pengulangan berikutnya, jadi tak ada kejutan di jeda pertama."""
    from agents.futures import risk_gate as rg
    f = rg._FROZEN_PAUSE
    assert f["LANE_PAUSE_HOURS"] == 24
    assert f["LANE_PAUSE_ESCALATION"] ** 0 == 1.0
    assert f["LANE_PAUSE_MAX_HOURS"] == 168.0


def test_jeda_lane_bisa_ditala():
    import pathlib
    src = pathlib.Path("../agents/futures/risk_gate.py").read_text(encoding="utf-8")
    for k in ("lane_pause_hours", "lane_pause_escalation", "lane_pause_max_hours"):
        assert k in src, f"{k} tak pernah ditarik"
    assert "_FROZEN_PAUSE[" in src, "cadangan memakai nilai berjalan"
