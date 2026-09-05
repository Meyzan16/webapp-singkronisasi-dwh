"""Fase 1b — "menang" futures menuntut untung yang BERMAKNA (bug B1).

Dua janji yang dijaga tes ini:
  1. SPOT tidak berubah sama sekali (engine spot haram disentuh).
  2. Futures: impas bukan menang DAN bukan kalah — ia dibuang dari pelatihan.

Tes ketiga menjaga regresi Bab 1 (10 Agu 2026): `sl_plus` — trailing stop yang
menutup DI ATAS entry dengan `status="sl"` — harus tetap terbaca menang selama
untungnya bermakna. Memperketat ambang tidak boleh menghidupkan kembali bug lama.
"""

import json

import pytest

from agents.shared import trade_outcome as out


class FakeTrade:
    """Cukup mirip PaperTrade untuk fungsi-fungsi di trade_outcome."""

    def __init__(self, *, style="futures_agent_bigmover", status="sl",
                 pnl_dollar=0.0, pnl_pct=0.0, position_size=100.0,
                 cost_floor_pct=None, direction="LONG", symbol="XUSDT"):
        self.style = style
        self.status = status
        self.pnl_dollar = pnl_dollar
        self.pnl_pct = pnl_pct
        self.position_size = position_size
        self.direction = direction
        self.symbol = symbol
        self.signals_json = json.dumps(
            {"cost_floor_pct": cost_floor_pct} if cost_floor_pct is not None else {})


@pytest.fixture(autouse=True)
def ambang_bawaan():
    """Tiap tes mulai dari ambang beku (K6: $3, 2x biaya)."""
    out.refresh_from_config(out._FROZEN)
    yield
    out.refresh_from_config(out._FROZEN)


# ── SPOT tidak berubah ────────────────────────────────────────────────────────

def test_spot_tetap_pakai_pnl_pct():
    menang = FakeTrade(style="opportunity_spot", pnl_pct=0.01, pnl_dollar=0.02)
    kalah = FakeTrade(style="opportunity_spot", pnl_pct=-0.01, pnl_dollar=-0.02)
    assert out.is_win(menang) is True          # +0,01% tetap menang di SPOT
    assert out.is_win(kalah) is False
    assert out.is_scratch(menang) is False     # SPOT tak punya konsep impas
    assert out.is_scratch(kalah) is False


# ── FUTURES: tiga wilayah ─────────────────────────────────────────────────────

def test_menang_harus_lewat_ambang_dolar():
    assert out.is_win(FakeTrade(pnl_dollar=3.0)) is True
    assert out.is_win(FakeTrade(pnl_dollar=2.99)) is False


def test_untung_kecil_adalah_impas_bukan_menang_bukan_kalah():
    """Ini jantung B1: 31 trade `sl_plus` rata-rata +$0,30 = persis fee."""
    t = FakeTrade(pnl_dollar=0.30, pnl_pct=0.25)
    assert out.is_win(t) is False
    assert out.is_loss(t) is False
    assert out.is_scratch(t) is True


def test_rugi_kecil_juga_impas():
    t = FakeTrade(pnl_dollar=-0.40)
    assert out.is_loss(t) is False
    assert out.is_scratch(t) is True


def test_rugi_bermakna_tetap_kalah():
    t = FakeTrade(pnl_dollar=-5.0)
    assert out.is_loss(t) is True
    assert out.is_scratch(t) is False
    assert out.is_win(t) is False


def test_ambang_ikut_biaya_posisi_besar():
    """$3 pada posisi $100 = menang; $3 pada posisi $3.000 masih derau biaya.

    Biaya = 0,20% x 3000 = $6; ambang = max($3, 2 x $6) = $12.
    """
    kecil = FakeTrade(pnl_dollar=3.0, position_size=100.0, cost_floor_pct=0.20)
    besar = FakeTrade(pnl_dollar=3.0, position_size=3000.0, cost_floor_pct=0.20)
    assert out.win_threshold_usd(kecil) == 3.0
    assert out.win_threshold_usd(besar) == pytest.approx(12.0)
    assert out.is_win(kecil) is True
    assert out.is_win(besar) is False


def test_baris_tanpa_cost_floor_pakai_fee_saja():
    """Cadangan harus LEBIH LONGGAR, bukan lebih ketat — kesalahan data tak boleh
    membuat trade lama tampak lebih buruk dari kenyataannya."""
    t = FakeTrade(pnl_dollar=3.0, position_size=1000.0)      # tanpa cost_floor_pct
    assert out.trade_cost_usd(t) == pytest.approx(1.0)        # 0,10% x 1000
    assert out.win_threshold_usd(t) == 3.0                    # $3 > 2 x $1


# ── Regresi Bab 1: sl_plus yang bermakna tetap menang ────────────────────────

def test_sl_plus_bermakna_tetap_menang():
    """Trailing stop menutup di atas entry dengan status='sl'. Memperketat
    ambang TIDAK boleh menghidupkan lagi bug 10 Agu (20 dari 21 kemenangan
    futures terbaca kalah karena syarat status == 'tp')."""
    t = FakeTrade(status="sl", pnl_dollar=14.29, pnl_pct=13.04)
    assert out.is_win(t) is True


def test_status_tp_tapi_rugi_bukan_menang():
    t = FakeTrade(status="tp", pnl_dollar=-2.0, pnl_pct=-1.5)
    assert out.is_win(t) is False


# ── Agregat ───────────────────────────────────────────────────────────────────

def test_win_loss_membuang_impas_dari_penyebut():
    trades = [
        FakeTrade(pnl_dollar=10.0),    # menang
        FakeTrade(pnl_dollar=-8.0),    # kalah
        FakeTrade(pnl_dollar=0.30),    # impas
        FakeTrade(pnl_dollar=0.10),    # impas
        FakeTrade(pnl_dollar=-0.20),   # impas
    ]
    assert out.win_loss(trades) == (1, 2)


def test_win_loss_hanya_menghitung_yang_selesai():
    trades = [FakeTrade(pnl_dollar=10.0, status="open"), FakeTrade(pnl_dollar=10.0)]
    assert out.win_loss(trades) == (1, 1)


def test_summarize_tiga_arah():
    trades = [
        FakeTrade(pnl_dollar=10.0), FakeTrade(pnl_dollar=-8.0),
        FakeTrade(pnl_dollar=0.30), FakeTrade(pnl_dollar=0.10),
    ]
    r = out.summarize(trades)
    assert (r["menang"], r["kalah"], r["impas"], r["selesai"]) == (1, 1, 2, 4)
    assert r["win_rate"] == 50.0      # 1 dari 2 yang tegas, bukan 1 dari 4


# ── Config ────────────────────────────────────────────────────────────────────

def test_ambang_bisa_ditala():
    out.refresh_from_config({"win_min_profit_usd": 10.0, "win_min_cost_mult": 2.0})
    assert out.is_win(FakeTrade(pnl_dollar=5.0)) is False
    out.refresh_from_config({"win_min_profit_usd": 1.0, "win_min_cost_mult": 2.0})
    assert out.is_win(FakeTrade(pnl_dollar=5.0)) is True


def test_kunci_win_punya_baris_seed():
    from app.services.agent_config_defaults import all_defaults

    seeded = {d["key"]: d["default"] for d in all_defaults() if d["group"] == "futures"}
    for key, val in out._FROZEN.items():
        assert key in seeded, f"{key} dibaca kode tapi tak di-seed"
        assert float(seeded[key]) == float(val), f"{key}: seed != nilai beku"
