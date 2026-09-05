"""Fase 2 — mesin ukuran `agents/futures/sizing.py`.

Yang dijaga tes ini adalah SIFAT rumusnya, bukan sekadar angkanya:

  * rugi saat SL kena kira-kira sama besar untuk koin apa pun (inilah arti
    "kerugian terukur" — leverage jadi akibat dari jarak SL);
  * tak ada pengali tersembunyi: satu `tier_mult` dan itu saja;
  * jarak likuidasi selalu lebih jauh dari jarak SL;
  * gerbang menolak dengan alasan yang bisa dibaca, dan hasilnya selalu berbentuk
    sama (field lengkap) baik lolos maupun ditolak.
"""

import pytest

from agents.futures import sizing


def P(**kw) -> sizing.SizingParams:
    """Parameter uji — sengaja eksplisit, tak menyentuh config."""
    dasar = dict(
        risk_pct=2.0, margin_loss_at_sl_pct=20.0, lev_min=2.0, lev_max=8.0,
        liq_safety_mult=2.0, max_margin_frac=0.35, max_notional_mult=1.5,
        min_notional_abs=50.0, min_profit_usd=5.0, min_profit_cost_mult=4.0,
        max_positions=3, portfolio_max_risk_pct=6.0,
    )
    dasar.update(kw)
    return sizing.SizingParams(**dasar)


def hitung(**kw):
    dasar = dict(balance=1000.0, sl_pct=4.0, tp1_pct=5.0, cost_pct=0.20, p=P())
    dasar.update(kw)
    return sizing.compute(**dasar)


# ── Sifat 1: kerugian terukur ────────────────────────────────────────────────

@pytest.mark.parametrize("sl_pct", [2.0, 3.0, 4.0, 5.28, 8.0, 12.0])
def test_rugi_di_sl_selalu_sekitar_risk_usd(sl_pct):
    """Berapa pun jarak SL, rugi saat SL kena ~= risiko yang direncanakan."""
    r = hitung(sl_pct=sl_pct, tp1_pct=sl_pct * 2)
    assert r.can_open, r.reason
    assert r.risk_usd == pytest.approx(20.0, rel=0.01)          # 2% x 1000
    # + biaya; tak boleh jauh melenceng dari rencana
    assert abs(r.sl_net_usd) == pytest.approx(20.0, abs=2.5)


def test_sebaran_rugi_rapat_lintas_koin():
    """Inti keluhan owner: kerugian harus TERUKUR, bukan berayun 2x."""
    rugi = [abs(hitung(sl_pct=sl, tp1_pct=sl * 2).sl_net_usd)
            for sl in (2.0, 3.0, 5.0, 8.0, 12.0)]
    assert max(rugi) / min(rugi) < 1.5


# ── Sifat 2: leverage adalah AKIBAT dari SL ──────────────────────────────────

def test_leverage_turun_saat_sl_melebar():
    lev = [hitung(sl_pct=sl, tp1_pct=sl * 2).leverage for sl in (2.5, 4.0, 8.0)]
    assert lev == sorted(lev, reverse=True), lev


def test_leverage_dihormati_batas_operator():
    assert hitung(sl_pct=0.5, tp1_pct=5.0).leverage <= 8       # lev_max
    assert hitung(sl_pct=50.0, tp1_pct=99.0).leverage >= 1     # tak pernah 0


def test_jarak_likuidasi_selalu_lebih_jauh_dari_sl():
    """Wick yang menyentuh SL tak boleh mendarat di zona likuidasi."""
    for sl in (1.0, 2.0, 4.0, 8.0, 15.0):
        lev = sizing.leverage_for_sl(sl, P())
        liq_dist = 95.0 / lev
        assert liq_dist >= sl * 2.0 * 0.999, f"SL {sl}%: liq {liq_dist:.1f}% < 2x SL"


# ── Sifat 3: satu pengali, bukan tumpukan ────────────────────────────────────

def test_tier_mult_satu_satunya_pengali():
    penuh = hitung()
    separuh = hitung(tier_mult=0.5)
    assert separuh.risk_usd == pytest.approx(penuh.risk_usd * 0.5)
    assert separuh.notional == pytest.approx(penuh.notional * 0.5)


def test_risk_pct_menggerakkan_ukuran_linier():
    a = hitung(p=P(risk_pct=1.0))
    b = hitung(p=P(risk_pct=2.0))
    assert b.notional == pytest.approx(a.notional * 2)


# ── Gerbang ──────────────────────────────────────────────────────────────────

def test_slot_penuh_menolak():
    r = hitung(open_positions=3)
    assert not r.can_open and "slot penuh" in r.reason


def test_panas_portofolio_menolak():
    r = hitung(open_risk_usd=55.0)      # 55 + 20 > 6% x 1000
    assert not r.can_open and "panas portofolio" in r.reason


def test_tp1_yang_cuma_menutup_fee_ditolak():
    """Gerbang inti keluhan 'ditutup 0% kemakan fee'."""
    r = hitung(tp1_pct=0.5, cost_pct=0.20)      # 0,5% < 4 x 0,2%
    assert not r.can_open and "biaya" in r.reason


def test_tp1_bersih_di_bawah_minimum_ditolak():
    """Gerbang 'jangan masuk cuma 3 dolar' (K5)."""
    r = hitung(balance=100.0, sl_pct=4.0, tp1_pct=2.0, p=P(min_profit_usd=5.0))
    assert not r.can_open
    assert "TP1 bersih" in r.reason or "notional" in r.reason


def test_notional_debu_ditolak():
    r = hitung(balance=50.0, sl_pct=10.0, tp1_pct=20.0)
    assert not r.can_open and "anti-debu" in r.reason


def test_min_notional_bursa_dihormati():
    r = hitung(min_notional_exchange=10_000.0)
    assert not r.can_open and "anti-debu" in r.reason


def test_margin_melebihi_dana_bebas_ditolak():
    r = hitung(locked_margin=990.0)
    assert not r.can_open and "dana bebas" in r.reason


def test_gerbang_laba_bisa_dimatikan_untuk_jalur_lama():
    """Fase 2 tak boleh diam-diam mengubah kandidat mana yang lolos di jalur
    lama — gerbang laba dilaporkan tapi tak menolak sampai Fase 7."""
    ketat = hitung(tp1_pct=0.5)
    longgar = hitung(tp1_pct=0.5, enforce_profit_gates=False)
    assert not ketat.can_open
    assert longgar.can_open
    # Angkanya tetap jujur meski gerbangnya tak menolak: TP1 bersih masih di
    # bawah minimum dan rasio untung:biaya masih di bawah syarat. Jadi jalur lama
    # tetap BISA dinilai lewat ledger tanpa perilakunya diubah diam-diam.
    assert longgar.tp1_net_usd < longgar.as_dict()["tp1_net_usd"] + 1  # terisi
    assert longgar.tp1_net_usd < 5.0          # < min_profit_usd
    assert longgar.profit_to_cost < 4.0       # < min_profit_cost_mult


# ── Bentuk hasil ─────────────────────────────────────────────────────────────

def test_hasil_selalu_lengkap_walau_ditolak():
    r = hitung(open_positions=99)
    d = r.as_dict()
    for field in ("risk_usd", "notional", "leverage", "margin", "cost_usd",
                  "tp1_net_usd", "sl_net_usd", "profit_to_cost", "balance"):
        assert field in d, field


def test_masukan_tak_masuk_akal_ditolak_bukan_meledak():
    assert not hitung(balance=0).can_open
    assert not hitung(sl_pct=0).can_open
    assert not hitung(sl_pct=-3.0).can_open


def test_explain_terbaca_manusia():
    teks = sizing.explain(hitung())
    for potongan in ("risiko $", "notional", "TP1", "SL memakan", "untung:biaya"):
        assert potongan in teks
    assert sizing.explain(hitung(open_positions=99)).startswith("DITOLAK:")


# ── Plafon ───────────────────────────────────────────────────────────────────

def test_plafon_margin_menurunkan_notional_bukan_menaikkan_leverage():
    """Menaikkan leverage untuk mengejar ukuran akan menggeser jarak likuidasi
    yang sudah dijamin — jadi yang turun harus notional."""
    r = hitung(balance=1000.0, sl_pct=2.0, tp1_pct=6.0, p=P(max_margin_frac=0.05))
    assert r.margin <= 1000.0 * 0.05 + 0.01
    assert r.leverage == sizing.leverage_for_sl(2.0, P(max_margin_frac=0.05))


def test_plafon_notional_terhadap_wallet():
    r = hitung(balance=1000.0, sl_pct=0.5, tp1_pct=5.0, p=P(risk_pct=2.0, max_notional_mult=1.5))
    assert r.notional <= 1500.0 + 0.01


# ── Config ───────────────────────────────────────────────────────────────────

def test_params_from_config_terbaca_dan_punya_seed():
    from app.services.agent_config_defaults import all_defaults
    from agents.futures import sizing_config as szcfg

    p = sizing.params_from_config()
    assert p.lev_max >= p.lev_min
    seeded = {d["key"] for d in all_defaults() if d["group"] == "futures"}
    for key in ("size_margin_loss_at_sl_pct", "lev_min", "lev_max",
                "size_min_profit_usd", "size_min_profit_cost_mult"):
        assert key in seeded, key
        assert key in szcfg._FROZEN, key
