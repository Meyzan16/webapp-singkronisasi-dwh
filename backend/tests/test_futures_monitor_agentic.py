"""Fase 7 — jalur monitor untuk posisi agen tunggal.

`exit_rules` sudah diuji sebagai aturan murni. Yang diuji DI SINI adalah
penerjemahannya jadi perubahan baris DB — bagian yang tak terlihat oleh tes
aturan, dan justru di situlah keputusan benar bisa berubah jadi angka salah.
"""

import json

import pytest

from agents.futures import monitor as M


class FakeTrade:
    def __init__(self, **kw):
        self.id = kw.get("id", 1)
        self.symbol = kw.get("symbol", "XUSDT")
        self.style = kw.get("style", "futures_agentic")
        self.direction = kw.get("direction", "LONG")
        self.entry_price = kw.get("entry_price", 100.0)
        self.stop_loss = kw.get("stop_loss", 95.0)
        self.take_profit = kw.get("take_profit", 110.0)
        self.trail_sl = kw.get("trail_sl")
        self.trail_active = kw.get("trail_active", False)
        self.position_size = kw.get("position_size", 300.0)
        self.leverage = kw.get("leverage", 4)
        self.risk_dollar = kw.get("risk_dollar", 15.0)
        self.status = "open"
        self.entry_at = kw.get("entry_at", 0.0)
        self.closed_at = None
        self.close_price = None
        self.pnl_pct = None
        self.pnl_dollar = kw.get("pnl_dollar")
        self.sl_breach_pct = None
        self.signals_json = json.dumps(kw.get("meta", {
            "atr_pct": 4.0, "risk_pct": 5.0, "cost_floor_pct": 0.20,
            "setup_type": "agentic",
        }))


class FakeSession:
    """Cukup untuk `_log_exit_event` — mencatat apa yang ditambahkan."""

    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)


@pytest.fixture(autouse=True)
def tanpa_db(monkeypatch):
    """Jangan sentuh DB: ledger dicatat ke daftar, config pakai nilai beku."""
    async def _noop_refresh():
        return None

    async def _fake_log(session, trade, meta, **kw):
        session.add({"trade_id": trade.id, **kw})

    from agents.futures import exit_config as ecfg
    monkeypatch.setattr(ecfg, "refresh", _noop_refresh)
    monkeypatch.setattr(M, "_log_exit_event", _fake_log)
    yield


@pytest.mark.asyncio
async def test_daftar_kosong_tak_melakukan_apa_pun():
    assert await M._monitor_agentic(FakeSession(), [], {}) == (0, 0)


@pytest.mark.asyncio
async def test_harga_hilang_dilewati_bukan_menebak():
    """Simbol tanpa harga tak boleh diputuskan dari harga terakhir yang basi."""
    t = FakeTrade()
    closed, updated = await M._monitor_agentic(FakeSession(), [t], {})
    assert (closed, updated) == (0, 0)
    assert t.status == "open"


@pytest.mark.asyncio
async def test_sl_tertembus_menutup_dan_mencatat_penyimpangan():
    t = FakeTrade(stop_loss=95.0)
    sesi = FakeSession()
    closed, _ = await M._monitor_agentic(sesi, [t], {"XUSDT": 94.0})

    assert closed == 1
    assert t.status == "sl"
    assert t.close_price == pytest.approx(95.0)      # ditutup di SL, bukan harga pasar
    assert t.pnl_pct is not None and t.pnl_pct < 0
    # Fase 4: penyimpangan fill terhadap SL WAJIB tercatat.
    assert t.sl_breach_pct == pytest.approx(1.0)     # (95-94)/100 x 100
    assert len(sesi.added) == 1                      # ledger ditulis, B3
    assert sesi.added[0]["close_reason"] == "sl_hit"


@pytest.mark.asyncio
async def test_ledger_ditulis_bersama_penutupan():
    """B3: jalur tutup yang tak menulis ledger membuat exit-learning belajar
    dari data yang diam-diam tidak lengkap."""
    sesi = FakeSession()
    await M._monitor_agentic(sesi, [FakeTrade()], {"XUSDT": 90.0})
    assert len(sesi.added) == 1


@pytest.mark.asyncio
async def test_tp1_parsial_membank_dan_mengecilkan_posisi():
    # TP1 = 1,2 x ATR 4% = 4,8% -> 104.8
    t = FakeTrade(position_size=300.0)
    closed, updated = await M._monitor_agentic(FakeSession(), [t], {"XUSDT": 105.0})

    assert (closed, updated) == (0, 1)
    assert t.status == "open"                        # parsial, bukan tutup penuh
    meta = json.loads(t.signals_json)
    assert meta["tp1_partial_done"] is True
    assert t.position_size == pytest.approx(150.0)   # separuh dijual
    assert (t.pnl_dollar or 0) > 0                   # untung dibank
    assert t.trail_active is True                    # sisanya langsung dilindungi


@pytest.mark.asyncio
async def test_fee_parsial_dipotong_penuh_bukan_separuh():
    """Perbaikan B6. Jalur lama memotong `ROUND_TRIP x 0,5` untuk fraksi yang
    dijual, sehingga fee MASUK untuk fraksi itu tak pernah terbayar."""
    t = FakeTrade(position_size=300.0)
    await M._monitor_agentic(FakeSession(), [t], {"XUSDT": 105.0})

    kotor = (104.8 - 100.0) / 100.0 * 100            # ~4,8%
    bersih = kotor - M.ROUND_TRIP * 100              # fee PENUH
    assert t.pnl_dollar == pytest.approx(bersih / 100 * 300.0 * 0.5, rel=0.02)


@pytest.mark.asyncio
async def test_rem_memindahkan_sl_bukan_menutup():
    # +3% : lolos 3x biaya (0,6%) dan 0,6 x ATR (2,4%), tapi belum TP1 (4,8%)
    t = FakeTrade()
    closed, updated = await M._monitor_agentic(FakeSession(), [t], {"XUSDT": 103.0})

    assert (closed, updated) == (0, 1)
    assert t.status == "open"
    assert t.trail_sl is not None and t.trail_sl > 100.0   # mengunci untung
    assert t.trail_active is True


@pytest.mark.asyncio
async def test_tahan_saat_belum_ada_yang_perlu_dilakukan():
    t = FakeTrade()
    closed, updated = await M._monitor_agentic(FakeSession(), [t], {"XUSDT": 100.5})
    assert (closed, updated) == (0, 0)
    assert t.status == "open" and t.trail_sl is None


@pytest.mark.asyncio
async def test_puncak_untung_terus_dicatat():
    """`peak_pnl_pct` adalah bahan trailing DAN kolom mfe_atr di ledger."""
    t = FakeTrade()
    await M._monitor_agentic(FakeSession(), [t], {"XUSDT": 102.0})
    assert json.loads(t.signals_json)["peak_pnl_pct"] == pytest.approx(2.0, rel=0.01)


@pytest.mark.asyncio
async def test_sl_menang_atas_time_stop():
    """Regresi B2: posisi yang menembus SL sekaligus kadaluwarsa harus ditutup
    sebagai SL — bukan dilabeli mekanisme lain."""
    t = FakeTrade(entry_at=0.0)                      # sangat lama
    sesi = FakeSession()
    await M._monitor_agentic(sesi, [t], {"XUSDT": 94.0})
    assert sesi.added[0]["close_reason"] == "sl_hit"


@pytest.mark.asyncio
async def test_short_cermin_long():
    t = FakeTrade(direction="SHORT", stop_loss=105.0)
    sesi = FakeSession()
    closed, _ = await M._monitor_agentic(sesi, [t], {"XUSDT": 106.0})
    assert closed == 1 and t.status == "sl"
    assert t.sl_breach_pct == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_meta_rusak_tak_meledak():
    t = FakeTrade()
    t.signals_json = "{bukan json"
    closed, updated = await M._monitor_agentic(FakeSession(), [t], {"XUSDT": 94.0})
    assert closed + updated >= 0                     # tidak melempar


# ── Pemisahan jalur ──────────────────────────────────────────────────────────

def test_hanya_agen_aktif_yang_masuk_jalur_baru():
    """Kalau lane pensiun ikut masuk, posisinya dikelola aturan yang tak pernah
    dirancang untuknya; kalau agen aktif TIDAK masuk, ia dikelola `fail_fast`
    yang terbukti -$79 dengan nol kemenangan."""
    from app.services.agent_registry import ACTIVE_FUTURES_AGENTS, LEGACY_FUTURES_AGENTS

    assert set(M._AGENTIC_STYLES) == set(ACTIVE_FUTURES_AGENTS)
    for lama in LEGACY_FUTURES_AGENTS:
        assert lama not in M._AGENTIC_STYLES
