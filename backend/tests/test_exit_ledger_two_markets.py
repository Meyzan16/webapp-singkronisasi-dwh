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
    """futures memakai `setup_type`, spot memakai `lane`/`alert_type`. Satu kunci
    saja membuat separuh baris kehilangan lane dan menumpuk di bucket '-'."""
    src = inspect.getsource(el.backfill_exit_events)
    for key in ("setup_type", "lane", "alert_type"):
        assert key in src


@pytest.mark.parametrize("market", ["futures", "spot"])
def test_endpoint_tersedia_untuk_kedua_market(market):
    from app.api.v1.futures_learning import router
    paths = {r.path for r in router.routes}
    for suffix in ("analysis", "triggers", "sl-width", "backfill"):
        assert f"/{market}/exit-learning/{suffix}" in paths
