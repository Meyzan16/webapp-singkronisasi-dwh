"""Jaring pengaman lebar SL per lane (M4).

Yang dijaga: nilai bawaan harus sama persis dengan perilaku sebelum sentralisasi,
tiap lane punya barisnya sendiri, dan lane tak boleh diam-diam memakai tala lane
lain — kegagalan senyap seperti itulah yang membuat 61% posisi bigmover SL-nya
mentok plafon tanpa terlihat siapa pun.
"""

import random

import pytest

from agents.futures import sl_config
from agents.futures.data import FuturesData


@pytest.fixture(autouse=True)
def _restore():
    saved = {k: dict(v) for k, v in sl_config.SL_PARAMS.items()}
    yield
    sl_config.SL_PARAMS.clear()
    sl_config.SL_PARAMS.update(saved)


def _series(seed: int, vol: float = 0.02, base: float = 100.0) -> FuturesData:
    r = random.Random(seed)
    closes = [base]
    for _ in range(60):
        closes.append(max(0.01, closes[-1] * (1 + r.uniform(-vol, vol))))
    highs = [c * (1 + abs(r.uniform(0, vol))) for c in closes]
    lows = [c * (1 - abs(r.uniform(0, vol))) for c in closes]
    return FuturesData(symbol="T", tf="1h", opens=closes[:], highs=highs,
                       lows=lows, closes=closes, volumes=[1000.0] * len(closes))


def test_default_sama_dengan_perilaku_lama():
    """Angka bawaan WAJIB sama dengan konstanta yang dulu tersebar di tiga agen.
    Kalau ini bergeser, seluruh keputusan masuk ikut bergeser tanpa ada yang minta."""
    assert sl_config._FROZEN["bigmover"] == {
        "swing_buffer_atr": 0.0, "max_pct": 8.0, "fallback_atr_mult": 1.5,
        "floor_pct": 2.5, "floor_atr_mult": 0.0,
        "quiet_fallback_pct": 4.0, "quiet_atr_pct": 0.5,
    }
    assert sl_config._FROZEN["momentum"]["swing_buffer_atr"] == 0.5
    assert sl_config._FROZEN["momentum"]["max_pct"] == 7.0
    assert sl_config._FROZEN["momentum"]["fallback_atr_mult"] == 1.2
    assert sl_config._FROZEN["pre_gainer"]["swing_buffer_atr"] == 0.3
    assert sl_config._FROZEN["pre_gainer"]["max_pct"] == 8.0
    assert sl_config._FROZEN["pre_gainer"]["fallback_atr_mult"] == 1.5
    # agent2 dulu memakai ulang level agent1 — nilainya harus identik, tapi kini
    # lewat entri lane-nya sendiri sehingga bisa ditala terpisah.
    assert sl_config._FROZEN["accumulation"] == sl_config._FROZEN["pre_gainer"]


def test_lane_tak_dikenal_tak_meminjam_lane_lain():
    p = sl_config.params("lane_yang_belum_ada")
    assert p == sl_config.SL_DEFAULTS
    assert p is not sl_config.SL_DEFAULTS          # salinan, bukan rujukan


def test_mengubah_satu_lane_tak_menyentuh_lane_lain():
    sl_config.SL_PARAMS["bigmover"]["max_pct"] = 20.0
    assert sl_config.params("momentum")["max_pct"] == 7.0
    assert sl_config.params("pre_gainer")["max_pct"] == 8.0


def test_setiap_lane_punya_baris_config_sl_lengkap():
    from app.services.agent_config_defaults import all_defaults
    keys = {d["key"] for d in all_defaults() if d["group"] == "futures"}
    for lane in sl_config.tunable_lanes():
        for param in sl_config.PARAM_NAMES:
            assert sl_config.sl_key(param, lane) in keys, f"{lane}/{param} hilang"


def test_default_baris_config_sama_dengan_nilai_beku():
    from app.services.agent_config_defaults import all_defaults
    by_key = {d["key"]: d["default"] for d in all_defaults() if d["group"] == "futures"}
    for lane in sl_config.tunable_lanes():
        base = sl_config._FROZEN.get(lane, sl_config.SL_DEFAULTS)
        for param in sl_config.PARAM_NAMES:
            assert by_key[sl_config.sl_key(param, lane)] == base[param]


def test_refresh_tanpa_override_tak_mengubah_apa_pun(monkeypatch):
    import asyncio
    from agents.shared.config_reader import cfg

    async def _no_override(group, key, default):
        return default

    monkeypatch.setattr(cfg, "get", _no_override)
    before = sl_config.snapshot()
    asyncio.run(sl_config.refresh())
    assert sl_config.snapshot() == before


def test_default_tak_hanyut_setelah_override(monkeypatch):
    """Default dibaca dari salinan beku — satu override tak boleh menjadi
    'default' permanen."""
    import asyncio
    from agents.shared.config_reader import cfg

    async def _override(group, key, default):
        return 99.0 if key == sl_config.sl_key("max_pct", "bigmover") else default

    monkeypatch.setattr(cfg, "get", _override)
    asyncio.run(sl_config.refresh())
    assert sl_config.params("bigmover")["max_pct"] == 99.0

    async def _no_override(group, key, default):
        return default

    monkeypatch.setattr(cfg, "get", _no_override)
    asyncio.run(sl_config.refresh())
    assert sl_config.params("bigmover")["max_pct"] == 8.0


# ── Fase 8 ───────────────────────────────────────────────────────────────────
# Tes untuk lane lama (pre_gainer / accumulation / momentum / bigmover) dibuang
# bersama modul agennya: `agent1.py`, `agent2.py`, `agent3.py`,
# `agent_bigmover.py` dihapus setelah trade era mereka tutup semuanya.
#
# Yang TIDAK dibuang: tes yang menjaga perilaku modul yang masih hidup. Riwayat
# 112 trade lane lama juga tetap utuh di DB — `FUTURES_AGENTS` masih memuat nama
# mereka supaya endpoint riwayat bisa membacanya.
