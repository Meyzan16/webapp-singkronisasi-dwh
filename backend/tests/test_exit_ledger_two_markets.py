"""Jaring pengaman ledger keluar dua-market (M7).

Yang dijaga: SPOT dan FUTURES melewati SATU jalur kode. Penyakit berulang di
proyek ini adalah sisi SPOT dibangun sebagai salinan lalu menyimpang diam-diam —
katalog Formulas dan tab Predictive dua-duanya sempat futures-only tanpa satu pun
error muncul.
"""

import inspect

import pytest

from agents.learning import exit_learning as el


def test_satu_tabel_untuk_dua_market():
    """Dua tabel terpisah = dua skema yang harus dijaga sinkron manual."""
    from app.models.futures_exit_event import ExitEvent, FuturesExitEvent
    assert ExitEvent is FuturesExitEvent
    assert ExitEvent.__tablename__ == "exit_events"
    assert hasattr(ExitEvent, "market")


def test_semua_fungsi_analisa_menerima_market():
    """Fungsi yang lupa parameter `market` akan membaca SELURUH baris kedua
    market dan melaporkannya sebagai milik satu market."""
    for fn in (el.analyze_exits, el.recommend_exit_params, el.analyze_exit_triggers,
               el.recommend_failfast_params, el.analyze_sl_width,
               el.apply_exit_recommendations, el.backfill_exit_events):
        params = inspect.signature(fn).parameters
        assert "market" in params, f"{fn.__name__} tak menerima market"
        assert params["market"].default == "futures", \
            f"{fn.__name__} default market bukan 'futures' (kompatibilitas pemanggil lama)"


def test_taksonomi_keluar_dini_terpisah_per_market():
    """Monitor spot dan futures punya istilah exit yang berbeda. Memaksa istilah
    futures ke spot menghasilkan tabel kosong yang terbaca seolah 'spot tak
    pernah keluar dini' — padahal justru mayoritas exit-nya begitu."""
    fut = el.early_exit_reasons("futures")
    spot = el.early_exit_reasons("spot")
    assert "fail_fast" in fut and "fail_fast" not in spot
    assert "urgent_rotation" in spot and "urgent_rotation" not in fut
    assert el.early_exit_reasons("market_karangan") == set()


def test_pencatat_ledger_dipakai_bersama():
    """Kalau monitor futures kembali punya salinan sendiri, kolom kedua market
    bisa berbeda tanpa ada yang menyadari."""
    from agents.shared.exit_ledger import log_exit
    import agents.futures.monitor as fut_mon
    import agents.opportunity.monitor as spot_mon

    assert "log_exit" in inspect.getsource(fut_mon._log_exit_event)
    assert "log_exit" in inspect.getsource(spot_mon._process_trade)
    assert "market" in inspect.signature(log_exit).parameters


def test_lebar_sl_tak_meminjam_config_futures_untuk_spot():
    """`sl_config` hanya milik futures. Memakainya untuk spot akan melaporkan
    'mentok plafon' terhadap plafon yang tak pernah berlaku di sana."""
    src = inspect.getsource(el.analyze_sl_width)
    assert 'market == "futures"' in src
    assert "sl_params = None" in src


def test_alasan_asli_tak_diberi_awalan_hist():
    """Awalan `hist:` menandai alasan hasil TEBAKAN. Trade yang menyimpan alasan
    aslinya (SPOT 100%) tak boleh ikut ditandai — itu merendahkan data bagus."""
    src = inspect.getsource(el.backfill_exit_events)
    assert 'meta.get("close_reason")' in src
    assert el._strip_hist("hist:fail_fast") == "fail_fast"
    assert el._strip_hist("urgent_rotation") == "urgent_rotation"


def test_lane_dibaca_dari_kunci_kedua_market():
    """futures memakai `setup_type`, spot menurunkannya lewat `lane_of`. Satu
    kunci saja membuat separuh baris kehilangan lane dan menumpuk di bucket '-'.

    Logikanya kini di `_lane_for` (bukan lagi inline di backfill) supaya monitor
    dan backfill mustahil memakai aturan yang berbeda.
    """
    src = inspect.getsource(el._lane_for)
    assert "setup_type" in src, "jalur futures hilang"
    assert "lane_of" in src, "jalur spot tak memakai pemeta monitor"


@pytest.mark.parametrize("market", ["futures", "spot"])
def test_endpoint_tersedia_untuk_kedua_market(market):
    from app.api.v1.futures_learning import router
    paths = {r.path for r in router.routes}
    for suffix in ("analysis", "triggers", "sl-width", "backfill"):
        assert f"/{market}/exit-learning/{suffix}" in paths


# ── M4b: gerak merugikan terjauh (MAE) ───────────────────────────────────────

def test_kedua_monitor_merekam_gerak_merugikan_terjauh():
    """Tanpa MAE, "berapa jarak SL yang terpakai" tak terjawab — dan mempersempit
    SL jadi tebakan yang bisa mengubah pemenang jadi pecundang."""
    import agents.futures.monitor as fut_mon
    import agents.opportunity.monitor as spot_mon
    assert "trough_pnl_pct" in inspect.getsource(fut_mon.check_futures_positions)
    assert "trough_pnl_pct" in inspect.getsource(spot_mon._process_trade)


def test_mae_disimpan_positif_agar_sebanding_dengan_jarak_sl():
    from agents.shared import exit_ledger
    src = inspect.getsource(exit_ledger.log_exit)
    assert "abs(trough)" in src


def test_rekomendasi_sl_ditahan_sampai_mae_cukup():
    """Menerbitkan rekomendasi lebar SL dari MFE saja adalah kekeliruan mahal —
    penjaga ini memastikan penahannya tidak hilang tanpa sengaja."""
    src = inspect.getsource(el.analyze_sl_width)
    assert "MAE_MIN_SAMPLES" in src
    assert "sl_recommendation_ready" in src
    assert el.MAE_MIN_SAMPLES >= 30


# ── ATR SPOT: tanpa ini seluruh ledger keluar SPOT tak bisa dinormalkan ───────

def test_scanner_spot_menyertakan_atr_pct_di_semua_lane():
    """Tiap lane SPOT harus membawa `atr_pct` di hasilnya.

    Perbaikan pertama (8 Agu) menambahkannya di SCHEDULER dengan membaca
    `coin["atr"]` — field yang tak pernah ada di hasil scanner. Nilainya selalu
    None, 67 baris ledger lahir tanpa ATR, dan perbaikannya tampak selesai
    padahal nol efek. Penjaga ini memastikan sumbernya benar-benar mengisi.
    """
    import inspect
    from agents.opportunity import scanner
    src = inspect.getsource(scanner)
    # 4 lane + definisi helper
    assert src.count('"atr_pct":') >= 4, "ada lane SPOT yang tak membawa atr_pct"
    assert "def _atr_pct_from_tf" in src


def test_scheduler_spot_membaca_atr_pct_bukan_atr():
    """Membaca field yang salah gagal TANPA error — hanya menghasilkan None."""
    import inspect
    from agents.opportunity import scheduler
    src = inspect.getsource(scheduler)
    assert 'coin.get("atr_pct")' in src
    assert 'coin.get("atr")' not in src, "membaca `atr` lagi = mengulang bug lama"


def test_lane_ledger_memakai_kosakata_monitor():
    """Ledger, config, dan keputusan HARUS memakai nama lane yang sama.

    Terukur 8 Agu 2026: ledger SPOT menyimpan `squeeze`/`bigmover_chase` (nilai
    alert_type mentah) sementara monitor & config memakai `accumulation`/
    `bigmover`. Usulan TP mendarat di `monitor_tp_atr_mult_lane_squeeze` yang tak
    pernah ada — hasil belajar tersimpan rapi di kunci yang tak dibaca siapa pun.
    """
    from agents.opportunity.monitor import lane_of
    from agents.opportunity import monitor_config as scfg
    kosakata = set(scfg.tunable_lanes())
    for alert in ("squeeze", "bigmover_chase", "breakout_pump", "early_radar", None):
        assert lane_of({}, alert) in kosakata, f"{alert} keluar dari kosakata config"


def test_backfill_dan_monitor_memakai_pemeta_lane_yang_sama():
    """Dua jalur menulis ledger (backfill & monitor saat menutup). Keduanya harus
    memakai `lane_of`, kalau tidak baris lama dan baru memakai kosakata berbeda."""
    import inspect
    from agents.learning import exit_learning
    from agents.opportunity import monitor as spot_mon
    assert "lane_of" in inspect.getsource(exit_learning._lane_for)
    assert "lane_of(meta, trade.alert_type)" in inspect.getsource(spot_mon._process_trade)


def test_monitor_spot_benar_benar_memanggil_kompresi_tp():
    """Angka hasil belajar yang tak pernah DIPANGGIL berefek nol.

    Terukur 8 Agu 2026: canary `bigmover` 2,031 sudah sampai ke `tp_atr_limit()`
    dan terlihat "aktif" di config, tapi monitor SPOT tak pernah memanggil
    `effective_take_profit()` — jadi efeknya NOL. Ini penyakit yang sama dengan
    monitor futures sebelum M2: nilai di-refresh tapi tak ada yang membacanya.
    """
    import inspect
    from agents.opportunity import monitor as spot_mon
    src = inspect.getsource(spot_mon._process_trade)
    assert "scfg.effective_take_profit(" in src, \
        "monitor SPOT tak memanggil kompresi TP — hasil belajar berefek nol"
    # Lane harus ikut, kalau tidak semua lane memakai batas yang sama.
    assert "lane=_lane_tp" in src


def test_kedua_monitor_memanggil_kompresi_tp():
    """Padanan di sisi futures — supaya salah satu tak diam-diam kehilangannya."""
    import inspect
    from agents.futures import monitor as fut_mon
    assert "effective_take_profit(" in inspect.getsource(fut_mon.check_futures_positions)


def test_pemicu_trend_reversal_bisa_ditala():
    """`trend_reversal` adalah satu-satunya pemicu keluar dini SPOT yang merugikan
    (n=10, WR 10%, expectancy −1,191%) — padanan `fail_fast` di futures yang juga
    0% menang sebelum diberi syarat tambahan.

    Tiga angkanya dulu terkunci di tengah fungsi, jadi mesin belajar tak punya
    jalan untuk mengoreksinya walau datanya sudah jelas.
    """
    import inspect
    from agents.opportunity import monitor as spot_mon
    from agents.opportunity import monitor_config as scfg
    src = inspect.getsource(spot_mon)
    for var in ("TREND_REVERSAL_EMA_BUFFER", "TREND_REVERSAL_MIN_HOLD_MIN",
                "TREND_REVERSAL_PROFIT_FLOOR_FRAC"):
        assert f"scfg.{var}" in src, f"{var} tak dibaca monitor"
        assert var in scfg._KEYS, f"{var} tak punya kunci config"
    # Angka telanjang yang lama tak boleh kembali.
    assert "ema21 * 0.998" not in src
    assert "hold_minutes >= 60" not in src


def test_lantai_profit_trend_reversal_default_nol():
    """Default WAJIB 0 = perilaku lama persis. Menaikkannya mengubah keputusan
    trading, jadi itu harus jadi pilihan sadar, bukan efek samping deploy."""
    from agents.opportunity import monitor_config as scfg
    assert scfg.TREND_REVERSAL_PROFIT_FLOOR_FRAC == 0.0
    assert scfg.TREND_REVERSAL_MIN_HOLD_MIN == 60.0
    assert scfg.TREND_REVERSAL_EMA_BUFFER == 0.998
