"""Fase 1a — rantai ukuran futures dapat ditala, TANPA mengubah perilaku.

Gerbang fase ini: nilai bawaan config = konstanta lama, sehingga hasil sizing
identik. Tes di sini menjaga dua janji itu sekaligus:

  1. `sizing_config._FROZEN` sama persis dengan konstanta yang digantikannya —
     kalau salah satu diedit tanpa yang lain, perilaku berubah diam-diam SAAT DB
     kebetulan tak terbaca (jalur yang paling jarang diuji, jadi paling mahal).
  2. `cap_leverage_by_lane` mengeluarkan angka yang sama dengan rumus lama.

Ditambah satu tes untuk B8: plafon leverage tidak boleh bergantung pada loop
monitor yang kebetulan sudah jalan.
"""

import pytest

from agents.futures import sizing_config as szcfg
from agents.futures.utils import (
    DEFAULT_LANE_CAP,
    DEFAULT_MAX_LEVERAGE,
    EXTENDED_CHANGE_24H_PCT,
    LIQ_SAFETY_MULT,
    MAX_LEVERAGE_BY_LANE,
    cap_leverage_by_lane,
)


# ── 1. Nilai beku harus cermin konstanta lama ────────────────────────────────

def test_frozen_leverage_cocok_dengan_konstanta_utils():
    assert szcfg._FROZEN["lev_liq_safety_mult"] == LIQ_SAFETY_MULT
    assert szcfg._FROZEN["lev_max_default"] == float(DEFAULT_MAX_LEVERAGE)
    assert szcfg._FROZEN["lev_lane_cap_default"] == DEFAULT_LANE_CAP
    assert szcfg._FROZEN["lev_extended_change_24h_pct"] == EXTENDED_CHANGE_24H_PCT


def test_frozen_lane_cocok_dengan_dict_lama():
    for lane, lev in MAX_LEVERAGE_BY_LANE.items():
        assert szcfg._FROZEN_LEV_MAX_LANE[lane] == float(lev), lane


def test_frozen_sizing_cocok_dengan_konstanta_balance():
    """balance.py menyimpan FRAKSI (0.01), config menyimpan PERSEN (1.0)."""
    from app.api.v1.balance import (
        FUTURES_CONVICTION_CEIL,
        FUTURES_CONVICTION_FLOOR,
        FUTURES_DRAWDOWN_CUT_PCT,
        FUTURES_DRAWDOWN_RISK_MULT,
        FUTURES_MAX_MARGIN_FRACTION,
        FUTURES_MAX_NOTIONAL_FRACTION,
        FUTURES_MAX_PORTFOLIO_RISK,
        FUTURES_MIN_NOTIONAL_ABS,
        FUTURES_RISK_BASE_FRACTION,
        FUTURES_RISK_MAX_FRACTION,
    )

    assert szcfg.risk_fraction_base() == pytest.approx(FUTURES_RISK_BASE_FRACTION)
    assert szcfg.risk_fraction_max() == pytest.approx(FUTURES_RISK_MAX_FRACTION)
    assert szcfg.portfolio_max_risk_fraction() == pytest.approx(FUTURES_MAX_PORTFOLIO_RISK)
    assert szcfg.max_margin_fraction() == pytest.approx(FUTURES_MAX_MARGIN_FRACTION)
    assert szcfg.get("size_conviction_floor") == FUTURES_CONVICTION_FLOOR
    assert szcfg.get("size_conviction_ceil") == FUTURES_CONVICTION_CEIL
    assert szcfg.get("size_min_notional_abs") == FUTURES_MIN_NOTIONAL_ABS
    assert szcfg.get("size_max_notional_mult") == FUTURES_MAX_NOTIONAL_FRACTION
    assert szcfg.get("size_drawdown_cut_pct") == FUTURES_DRAWDOWN_CUT_PCT
    assert szcfg.get("size_drawdown_risk_mult") == FUTURES_DRAWDOWN_RISK_MULT


# ── 2. Leverage: hasil harus sama dengan rumus lama ──────────────────────────

def _leverage_rumus_lama(base_lev, risk_pct, lane, change_24h=0.0):
    """Salinan verbatim rumus sebelum Fase 1a — pembanding independen."""
    hard_cap = MAX_LEVERAGE_BY_LANE.get(lane, DEFAULT_MAX_LEVERAGE)
    if not risk_pct or risk_pct <= 0:
        lev = min(int(base_lev), hard_cap)
    else:
        from agents.futures.utils import MAX_SL_MARGIN_PCT_BY_LANE
        lane_cap = MAX_SL_MARGIN_PCT_BY_LANE.get(lane, DEFAULT_LANE_CAP)
        sl_cap = max(1, int(lane_cap / risk_pct))
        liq_cap = max(1, int(95.0 / LIQ_SAFETY_MULT / risk_pct))
        lev = min(int(base_lev), sl_cap, liq_cap, hard_cap)
    if abs(change_24h) >= EXTENDED_CHANGE_24H_PCT:
        lev = lev // 2
    return max(1, lev)


@pytest.mark.parametrize("lane", ["accumulation", "pre_gainer", "momentum", "bigmover", "lane_asing"])
@pytest.mark.parametrize("risk_pct", [0.0, 0.5, 1.5, 2.0, 3.0, 5.0, 8.0])
@pytest.mark.parametrize("change_24h", [0.0, 20.0])
def test_leverage_identik_dengan_rumus_lama(lane, risk_pct, change_24h):
    baru = cap_leverage_by_lane(10, risk_pct, lane, change_24h)
    lama = _leverage_rumus_lama(10, risk_pct, lane, change_24h)
    assert baru == lama, f"{lane} risk={risk_pct} chg={change_24h}: {baru} != {lama}"


def test_leverage_tak_pernah_nol():
    """max(1, …) adalah janji: leverage 0 akan membagi-nol di rumus margin."""
    for risk in (0.1, 50.0, 200.0):
        assert cap_leverage_by_lane(1, risk, "bigmover", 99.0) >= 1


# ── 3. B8 — scanner tak boleh bergantung pada loop monitor ───────────────────

def test_plafon_leverage_tersedia_tanpa_loop_monitor():
    """Regresi B8 (5 Sep 2026).

    `lev_max_*` dibaca dari sizing_config, bukan dari dict yang dimutasi loop
    monitor. Tanpa ini, plafon leverage scanner hanya benar setelah monitor
    menyelesaikan siklus pertamanya — dan salah, diam-diam, sebelum itu.
    """
    assert szcfg.lev_max_for_lane("bigmover") == 3
    assert szcfg.lev_max_for_lane("momentum") == 6
    # Lane tak dikenal memakai BAWAAN, bukan angka lane tetangga.
    assert szcfg.lev_max_for_lane("lane_yang_belum_ada") == int(szcfg.get("lev_max_default"))


def test_snapshot_memuat_semua_kunci():
    snap = szcfg.snapshot()
    assert set(snap["scalar"]) == set(szcfg._FROZEN)
    assert set(snap["lev_max_by_lane"]) >= set(szcfg._FROZEN_LEV_MAX_LANE)


def test_kunci_tak_dikenal_melempar_bukan_diam():
    """Kunci salah ketik harus berisik. Mengembalikan 0.0 diam-diam akan membuat
    risiko/plafon jadi nol tanpa satu pun pesan."""
    with pytest.raises(KeyError):
        szcfg.get("kunci_yang_tidak_ada")


# ── 4. Seed config harus memuat setiap kunci yang dibaca kode ────────────────

def test_semua_kunci_sizing_punya_baris_seed():
    from app.services.agent_config_defaults import all_defaults

    seeded = {d["key"] for d in all_defaults() if d["group"] == "futures"}
    for key in szcfg._FROZEN:
        assert key in seeded, f"kunci {key} dibaca kode tapi tak pernah di-seed"
    for lane in szcfg._FROZEN_LEV_MAX_LANE:
        assert szcfg.lev_max_key(lane) in seeded, f"lev_max_{lane} tak di-seed"


def test_seed_default_sama_dengan_frozen():
    """Bawaan seed dan nilai beku harus satu angka — kalau berbeda, perilaku
    berubah tergantung apakah DB terbaca atau tidak."""
    from app.services.agent_config_defaults import all_defaults

    rows = {d["key"]: d["default"] for d in all_defaults() if d["group"] == "futures"}
    for key, val in szcfg._FROZEN.items():
        assert float(rows[key]) == float(val), key
    for lane, val in szcfg._FROZEN_LEV_MAX_LANE.items():
        assert float(rows[szcfg.lev_max_key(lane)]) == float(val), lane


def test_flag_agentic_ada_dan_mati():
    """Fase 0: saklar induk harus ada dan bawaannya OFF."""
    from app.services.agent_config_defaults import all_defaults

    rows = {d["key"]: d for d in all_defaults() if d["group"] == "futures"}
    assert "agentic_enabled" in rows
    assert float(rows["agentic_enabled"]["default"]) == 0.0
