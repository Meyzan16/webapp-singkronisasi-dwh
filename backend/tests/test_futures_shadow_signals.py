"""PLAN-OKT-2026 P1 — riset sinyal shadow: simulasi bracket & detektor."""

from agents.futures.data import FuturesData
from agents.futures.shadow_signals import detect, simulate_bracket

T0 = 1_790_000_000.0


def _k(i: int, hi: float, lo: float, cl: float) -> list:
    """Lilin 15m ke-i sesudah scan."""
    return [(T0 + i * 900) * 1000, cl, hi, lo, cl, 0]


def test_tp_tersentuh_dulu_long():
    kl = [_k(0, 101, 99.5, 100.5), _k(1, 106.5, 100, 106)]
    r = simulate_bracket("LONG", 100, 97, 106, 0.3, kl, T0, now=T0 + 3600)
    assert r["bracket_exit"] == "tp"
    assert abs(r["bracket_r"] - (2.0 - 0.1)) < 1e-9     # 2R − biaya 0,3/3


def test_sl_dan_tp_satu_lilin_dihitung_sl():
    kl = [_k(0, 107, 96, 100)]
    r = simulate_bracket("LONG", 100, 97, 106, 0.3, kl, T0, now=T0 + 3600)
    assert r["bracket_exit"] == "sl"
    assert r["bracket_r"] < -1.0


def test_short_cermin():
    kl = [_k(0, 100.5, 93.9, 94)]
    r = simulate_bracket("SHORT", 100, 103, 94, 0.3, kl, T0, now=T0 + 3600)
    assert r["bracket_exit"] == "tp"
    assert r["bracket_r"] > 1.8


def test_lilin_sebelum_scan_diabaikan():
    kl = [[(T0 - 600) * 1000, 100, 120, 80, 100, 0], _k(0, 101, 99, 100)]
    assert simulate_bracket("LONG", 100, 97, 106, 0.3, kl, T0, now=T0 + 3600) is None


def test_tanpa_sentuhan_final_setelah_24_jam():
    kl = [_k(i, 101, 99, 100.6) for i in range(96)]
    assert simulate_bracket("LONG", 100, 97, 106, 0.3, kl, T0, now=T0 + 3600) is None
    r = simulate_bracket("LONG", 100, 97, 106, 0.3, kl, T0, now=T0 + 25 * 3600)
    assert r["bracket_exit"] == "open"
    assert abs(r["bracket_r"] - (0.6 / 3 - 0.1)) < 1e-9


def _fd(tf: str, closes: list[float]) -> FuturesData:
    return FuturesData(symbol="X", tf=tf, opens=[c * 0.999 for c in closes],
                       highs=[c * 1.004 for c in closes], lows=[c * 0.996 for c in closes],
                       closes=closes, volumes=[1000.0] * len(closes))


def test_data_kurang_tak_memicu_apa_pun():
    tf = {"1h": _fd("1h", [100.0] * 50), "4h": _fd("4h", [100.0] * 60), "15m": _fd("15m", [100.0] * 60)}
    assert detect("X", tf, 0.0) == []


def test_bracket_searah_arah_sinyal():
    # tren naik panjang lalu turun tipis kembali ke sekitar EMA20 dengan lilin terakhir hijau
    up = [100 * (1.004 ** i) for i in range(190)]
    pull = up + [up[-1] * (0.997 ** i) for i in range(1, 9)]
    h1 = _fd("1h", pull)
    h1.opens[-1] = pull[-1] * 0.998               # lilin terakhir hijau
    h4 = _fd("4h", [100 * (1.01 ** i) for i in range(100)])
    m15 = _fd("15m", [pull[-1]] * 60)
    sinyal = detect("X", {"1h": h1, "4h": h4, "15m": m15}, 3.0)
    assert [x["hypothesis"] for x in sinyal] == ["pullback_ema"]
    for s in sinyal:
        assert (s["sl_price"] < s["price_at_scan"] < s["tp_price"]) == (s["direction"] == "LONG")
