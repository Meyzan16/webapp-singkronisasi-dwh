"""Penjaga registry agen — mencegah daftar agen menyimpang lagi.

Latar: sampai 30 Jul 2026 daftar agen disalin ulang di belasan modul. Saat lane
`futures_agent_bigmover` lahir, sebagian salinan ikut diperbarui dan sebagian
TIDAK — `ALL_AGENTS` di `api/v1/signals.py` membuangnya sehingga 14 sinyal yang
memenuhi ambang tak pernah tampil di Signal Performance, tanpa satu pun error.

Test ini gagal bila ada modul yang kembali memakai daftar sendiri yang tak sama
dengan registry, sehingga kegagalan yang tadinya SENYAP jadi berisik.
"""

import os
import sys

# Repo root ke path — modul `agents` hidup satu level di atas backend/ dan
# pytest.ini hanya memuat `.` (pola sama dgn test_futures_learning_policy.py).
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from app.services import agent_registry as reg  # noqa: E402


def test_registry_bersumber_dari_layer_agent():
    """FUTURES_AGENTS harus persis sama dgn sumber kebenaran di layer agent."""
    from agents.futures.weight_updater import FUTURES_AGENTS as canonical

    assert reg.FUTURES_AGENTS == list(canonical)


def test_bigmover_ikut_terdaftar():
    """Regression guard bug 30 Jul: lane BigMover pernah hilang dari API."""
    assert "futures_agent_bigmover" in reg.FUTURES_AGENTS
    assert "futures_agent_bigmover" in reg.TRADING_AGENTS
    assert "futures_agent_bigmover" in reg.ALL_AGENTS


def test_semua_konsumen_backend_memakai_daftar_yang_sama():
    """Modul API tak boleh punya daftar agen yang menyimpang dari registry."""
    from app.api.v1 import admin, balance, diagnostics, futures_scanner, signals

    assert signals.ALL_AGENTS == reg.ALL_AGENTS
    assert signals.TRADING_AGENTS == reg.TRADING_AGENTS
    assert signals._FUTURES_AGENT_SET == set(reg.FUTURES_AGENTS)
    assert admin._FUTURES_STYLES == reg.FUTURES_AGENTS
    assert admin._SPOT_STYLES == [reg.SPOT_AGENT]
    assert balance._FUTURES_AGENT_STYLES == reg.FUTURES_AGENTS
    assert diagnostics._FUTURES_STYLES == reg.FUTURES_AGENTS
    assert futures_scanner._ALL_FUTURES_STYLES == reg.FUTURES_AGENTS


def test_konsumen_lain_juga_memakai_registry():
    """Sapuan 1 Agu menemukan SALINAN daftar/label agen yang masih tersisa:
    `predictive.py` (daftar futures ke-6) dan `signal_catalog.py` (label ke-3).
    Test ini menjaga keduanya tetap terikat ke registry."""
    from app.api.v1 import predictive
    from app.services import signal_catalog

    assert list(predictive._FUTURES_AGENTS) == reg.FUTURES_AGENTS
    assert signal_catalog.AGENT_LABELS is reg.AGENT_LABELS


def test_pemetaan_lane_konsisten_dua_arah():
    """AGENT_LANE dan LANE_AGENT harus saling membalik — dipakai kategori saran
    dan panel kesehatan agen; dulu ditulis DUA KALI di file yang sama."""
    for agent, lane in reg.AGENT_LANE.items():
        assert reg.LANE_AGENT[lane] == agent
    assert set(reg.AGENT_LANE) <= set(reg.FUTURES_AGENTS)


def test_setiap_agen_punya_label():
    """Agen terdaftar wajib punya nama panjang & pendek — supaya UI tak pernah
    menampilkan kunci mentah untuk lane yang sudah resmi ada."""
    for agent in reg.ALL_AGENTS:
        assert reg.AGENT_LABELS.get(agent), f"label hilang: {agent}"
        assert reg.AGENT_SHORT.get(agent), f"label pendek hilang: {agent}"


def test_lane_baru_tak_menyaru_jadi_lane_lain():
    """Lane yang belum dikatalogkan harus tampil apa adanya, BUKAN jatuh ke nama
    lane lain (akar bug 'BigMover dilabeli Accum' di dashboard)."""
    baru = "futures_agent_scalper"
    assert reg.is_futures_agent(baru)
    assert reg.agent_label(baru) == baru
    assert reg.agent_short(baru) == "scalper"
    assert reg.agent_label(baru) != reg.AGENT_LABELS["futures_agent2"]
