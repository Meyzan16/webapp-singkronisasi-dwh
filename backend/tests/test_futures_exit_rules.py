"""Fase 4 — aturan keluar futures.

Tiga bug yang jadi alasan modul ini ada, masing-masing punya tes regresinya:

  B2  SL dinilai PALING PERTAMA. Mendahulukan mekanisme lain persis itulah cara
      BLUAI ditutup di 2,16x risiko lalu dilabeli `fail_fast`.
  B5  Rem pelindung mengunci SEBAGIAN UNTUNG, bukan pindah ke titik impas.
      Memindahkan SL tepat ke breakeven membuat tiap sentuhan bernilai nol
      menurut definisi.
  TP  TP1 di jarak yang pernah dicapai, dan sebagian posisi dibiarkan jadi
      pelari tanpa plafon.
"""

import pytest

from agents.futures import exit_rules as ex


def P(**kw) -> ex.ExitParams:
    dasar = dict(tp1_atr_mult=1.2, tp2_atr_mult=2.5, tp1_close_frac=0.5,
                 tp2_close_frac=0.25, be_arm_cost_mult=3.0, be_arm_atr=0.6,
                 be_lock_frac=0.5, trail_lock_frac=0.75, max_hold_h=8.0,
                 time_stop_progress=0.5)
    dasar.update(kw)
    return ex.ExitParams(**dasar)


def S(**kw) -> ex.ExitState:
    dasar = dict(direction="LONG", entry=100.0, price=100.0, sl=95.0, atr_pct=4.0,
                 cost_pct=0.20, risk_pct=5.0, hold_minutes=10.0, peak_pnl_pct=0.0)
    dasar.update(kw)
    return ex.ExitState(**dasar)


# ── B2: SL selalu pertama ────────────────────────────────────────────────────

def test_sl_menang_atas_time_stop():
    """Posisi yang sudah menembus SL DAN kadaluwarsa harus ditutup sebagai SL —
    bukan dilabeli mekanisme lain. Pelabelan salah inilah yang membuat 11 trade
    tercatat `fail_fast` padahal SL-nya sudah tertembus."""
    d = ex.evaluate(S(price=94.0, hold_minutes=999.0), P())
    assert d.reason == ex.SL_HIT
    assert d.close_frac == 1.0


def test_sl_menang_atas_tp1():
    """Wick yang menyentuh SL dan TP1 dalam candle yang sama: SL yang menang."""
    d = ex.evaluate(S(price=100.0, low=94.0, high=106.0), P())
    assert d.reason == ex.SL_HIT


def test_sl_dinilai_dari_wick_bukan_harga_penutupan():
    tanpa_wick = ex.evaluate(S(price=96.0), P())
    dengan_wick = ex.evaluate(S(price=96.0, low=94.0), P())
    assert tanpa_wick.reason != ex.SL_HIT
    assert dengan_wick.reason == ex.SL_HIT


@pytest.mark.parametrize("arah,harga,sl,rendah,tinggi", [
    ("LONG", 100.0, 95.0, 90.0, None),
    ("SHORT", 100.0, 105.0, None, 110.0),
])
def test_sl_breach_pct_terukur(arah, harga, sl, rendah, tinggi):
    """Penyimpangan fill terhadap SL WAJIB tercatat. Tanpa angka ini, rugi
    2,16x risiko cuma bisa ditemukan lewat forensik manual."""
    d = ex.evaluate(S(direction=arah, price=harga, sl=sl, low=rendah, high=tinggi), P())
    assert d.reason == ex.SL_HIT
    assert "sl_breach_pct=5.0" in d.note


def test_sl_di_atas_entry_adalah_sl_plus_bukan_kerugian():
    d = ex.evaluate(S(price=101.0, sl=102.0, low=101.0, tp1_done=True), P())
    assert d.reason == ex.SL_PLUS
    assert ex.SL_PLUS not in ex.REAL_LOSS_REASONS      # bukan rentetan kekalahan


def test_fail_fast_tidak_ada_di_kosakata():
    assert "fail_fast" not in ex.REAL_LOSS_REASONS
    kosakata = {ex.SL_HIT, ex.SL_PLUS, ex.TP1_HIT, ex.TP2_HIT, ex.TRAIL_HIT,
                ex.TIME_STOP, ex.LIQ_GUARD, ex.EMERGENCY}
    assert "fail_fast" not in kosakata and len(kosakata) == 8


# ── B5: rem mengunci untung, bukan pindah ke impas ───────────────────────────

def test_rem_tak_menyala_saat_untung_masih_selevel_biaya():
    """+0,5% dengan biaya 0,20% = 2,5x biaya — di bawah syarat 3x."""
    d = ex.evaluate(S(price=100.5), P())
    assert d.reason != "breakeven"


def test_rem_butuh_DUA_syarat():
    """3x biaya (0,6%) terpenuhi tapi 0,6xATR (2,4%) belum → belum menyala.
    Tanpa syarat ATR, rem menyala oleh derau harian koin volatil."""
    d = ex.evaluate(S(price=101.0, atr_pct=4.0), P())
    assert d.reason != "breakeven"


def test_rem_menyala_saat_kedua_syarat_terpenuhi():
    d = ex.evaluate(S(price=103.0, atr_pct=4.0), P())     # +3% > 0,6% dan > 2,4%
    assert d.reason == "breakeven"
    assert d.action == "move_sl"


def test_rem_mengunci_untung_bukan_impas():
    """Inti perbaikan B5: kalau SL ini tersentuh, hasilnya untung NYATA."""
    d = ex.evaluate(S(price=104.0, atr_pct=4.0), P())
    assert d.reason == "breakeven"
    # untung 4% x lock 0,5 = 2% di atas entry — jauh di atas biaya 0,2%
    assert d.new_sl == pytest.approx(102.0)
    assert d.new_sl > 100.0 * (1 + 0.20 / 100)


def test_lantai_rem_tetap_entry_plus_biaya():
    """Saat untung kecil, penguncian tak boleh jatuh di bawah biaya."""
    s = S(price=100.3, atr_pct=0.2)          # untung 0,3%; 0,5x = 0,15% < biaya 0,2%
    assert ex.protective_price(s, P()) == pytest.approx(100.2)


def test_rem_short_cermin_long():
    d = ex.evaluate(S(direction="SHORT", entry=100.0, price=96.0, sl=105.0), P())
    assert d.reason == "breakeven"
    assert d.new_sl == pytest.approx(98.0)


# ── TP: jarak yang pernah dicapai + pelari ───────────────────────────────────

def test_tp1_parsial_bukan_tutup_penuh():
    d = ex.evaluate(S(price=104.9), P())        # 1,2 x ATR 4% = 4,8%
    assert d.reason == ex.TP1_HIT
    assert d.action == "partial"
    assert d.close_frac == 0.5
    assert d.new_sl is not None                 # sisanya langsung dilindungi


def test_tp2_menyisakan_pelari():
    d = ex.evaluate(S(price=111.0, tp1_done=True), P())   # 2,5 x 4% = 10%
    assert d.reason == ex.TP2_HIT
    assert d.close_frac == 0.25
    # 0,5 + 0,25 = 0,75 → 25% dibiarkan jalan tanpa plafon
    assert P().tp1_close_frac + P().tp2_close_frac == 0.75


def test_tp1_belum_tersentuh_maka_tahan():
    d = ex.evaluate(S(price=102.0, atr_pct=4.0), P(be_arm_atr=99.0))
    assert d.action == "hold"


def test_trailing_hanya_sesudah_tp1():
    sebelum = ex.evaluate(S(price=103.0, peak_pnl_pct=8.0, atr_pct=4.0),
                          P(be_arm_atr=99.0))
    sesudah = ex.evaluate(S(price=103.0, peak_pnl_pct=8.0, tp1_done=True), P())
    assert sebelum.reason != "trail"
    assert sesudah.reason == "trail"
    assert sesudah.new_sl == pytest.approx(106.0)     # 8% x 0,75


# ── Time-stop ────────────────────────────────────────────────────────────────

def test_time_stop_menutup_yang_tak_berkembang():
    d = ex.evaluate(S(price=100.5, hold_minutes=9 * 60), P())
    assert d.reason == ex.TIME_STOP
    assert d.close_frac == 1.0


def test_time_stop_membiarkan_yang_sudah_berkembang():
    """Progres >= 0,5x risiko (5% x 0,5 = 2,5%) → tesisnya jalan, biarkan."""
    d = ex.evaluate(S(price=103.0, hold_minutes=9 * 60, tp1_done=True,
                      peak_pnl_pct=3.0, sl=102.0), P())
    assert d.reason != ex.TIME_STOP


def test_time_stop_belum_berlaku_sebelum_batas():
    d = ex.evaluate(S(price=100.1, hold_minutes=7 * 60, atr_pct=0.01), P())
    assert d.reason != ex.TIME_STOP


# ── Config ───────────────────────────────────────────────────────────────────

def test_semua_parameter_punya_baris_seed():
    from app.services.agent_config_defaults import all_defaults
    from agents.futures import exit_config as ecfg

    seeded = {d["key"]: d["default"] for d in all_defaults() if d["group"] == "futures"}
    for key, val in ecfg._FROZEN.items():
        assert key in seeded, f"{key} dibaca kode tapi tak di-seed"
        assert float(seeded[key]) == float(val), f"{key}: seed != nilai beku"


def test_kunci_tak_dikenal_melempar():
    from agents.futures import exit_config as ecfg
    with pytest.raises(KeyError):
        ecfg.get("exit_yang_tidak_ada")
