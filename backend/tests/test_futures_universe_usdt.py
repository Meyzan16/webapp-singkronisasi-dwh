"""Semesta scanner futures = USDT-perp SAJA, disaring di sisi klien.

13 Sep 2026: mirror binance.bh mengabaikan parameter `symbols` pada
/ticker/24hr (BUG-L25) dan `fetch_top100_futures` tak menyaring ulang —
FILUSDC dan NEARUSDC masuk semesta; FILUSDC + FILUSDT dibuka bersamaan
(aset dasar sama, eksposur ganda) dari dompet USDT.
"""

import inspect

from agents.futures import data as D


def test_ticker_disaring_ke_himpunan_usdt_perp():
    src = inspect.getsource(D.fetch_top100_futures)
    assert "_usdt_perp = set(symbols)" in src
    assert 't.get("symbol") in _usdt_perp' in src


def test_tak_lagi_memotong_200_simbol_pertama():
    src = inspect.getsource(D.fetch_top100_futures)
    assert "symbols[:200]" not in src
    assert '"symbols": syms_param' not in src
