"""Agen FUTURES tunggal — satu lane, satu skor, satu ambang.

PLAN-FUTURES-AGENTIC.md Fase 3. Menggantikan empat pemindai (agent1 Pre-Gainer,
agent2 Accumulation, agent3 Momentum, agent_bigmover) yang berjumlah 2.764 baris.

── Kenapa empat jadi satu ────────────────────────────────────────────────────
Dalam praktik keempatnya SUDAH satu. Dari 112 trade tertutup (5 Sep 2026):

    bigmover      91 trade  (81%)
    momentum      15        — kuotanya sendiri sudah disetel 0
    pre_gainer     3
    accumulation   3        — enam trade dalam dua bulan

Tiga lane yang menghasilkan 21 trade dalam dua bulan tetap menyeret 4 set bobot
sinyal (85 kunci), kuota per lane, jeda per lane, config SL per lane, exit-learning
per lane, dan dua pertiga dari 141 kunci config. Biayanya nyata: tiap lane baru
harus didaftarkan di 19 tempat, dan yang terlewat gagal SENYAP — persis bug 30 Jul
(BigMover hilang dari Signal Performance) dan 29 Jul (bobot repair tak beririsan).

── Apa yang diambil dari mana ────────────────────────────────────────────────
Diambil dari lane yang PUNYA BUKTI, bukan dari yang paling banyak barisnya:

  momentum & arah      bigmover — satu-satunya lane yang TP-nya pernah tersentuh
  konfirmasi vol/OI    agent3 (T-blok) + agent2 (OI confirm)
  filter derau/jebakan bigmover G14 (gap data) & G18 (puncak literal)
  likuiditas minimum   BARU — lihat B2 di bawah

Yang DIBUANG: penalti anti-momentum agent1/agent2 (menghukum koin yang bergerak,
padahal gerakan itulah tesisnya), "quiet coil" pre-gainer, dan Wyckoff pre-markup.
Ketiganya menghasilkan 6 trade dalam dua bulan — terlalu sedikit untuk dinilai,
apalagi dipertahankan.

── Dua sambungan yang sebelumnya putus ───────────────────────────────────────
1. TP DAN SL DATANG DARI `exit_config`, sumber yang SAMA yang dibaca monitor.
   Sampai kini agen memasang TP di ATR×2/4/6 sementara monitor punya config TP
   sendiri — dua angka untuk satu hal, dan tak ada yang menjaga keduanya sama.
   Akibatnya terukur: TP dipasang median 4 ATR, tersentuh 4%.
2. LIKUIDITAS jadi gerbang, bukan sekadar bahan skor. BLUAI (koin tipis) melompat
   dari −8% ke −17,3% di antara dua tick; SL 7,99% berubah jadi rugi 2,16× risiko.
   Koin yang tak bisa menampung posisi kita tak layak dimasuki berapa pun skornya.

Seluruh modul ini mati sampai `futures.agentic_enabled` = 1.
"""

from __future__ import annotations

from typing import Optional

import structlog

from .data import FuturesData
from .utils import _atr, _round_price, _rsi, cap_leverage_by_lane

logger = structlog.get_logger(__name__)

AGENT_NAME = "futures_agentic"
LANE = "agentic"


# ── Gerbang masuk ─────────────────────────────────────────────────────────────
# Semua bisa ditala lewat agent_config (futures.agentic_*); nilai di sini cadangan.
_FROZEN: dict[str, float] = {
    "agentic_min_score":       65.0,
    "agentic_min_change_24h":   5.0,    # di bawah ini belum ada tesis momentum
    "agentic_max_change_24h": 150.0,    # di atas ini sudah bukan trade, itu lotre
    "agentic_min_liquidity_usd": 5_000_000.0,
    "agentic_max_funding_pct":   0.25,  # gerbang keras funding (dua arah)
    "agentic_min_rr":            2.0,
}
_LIVE: dict[str, float] = dict(_FROZEN)


def get(key: str) -> float:
    return _LIVE[key]


async def refresh() -> None:
    """Tarik override sekali per siklus scan."""
    try:
        from agents.shared.config_reader import cfg
        _LIVE.update({k: await cfg.get("futures", k, v) for k, v in _FROZEN.items()})
    except Exception as exc:      # noqa: BLE001 — config gagal tak menghentikan scan
        logger.warning("agentic_config_refresh_failed", error=str(exc)[:120])


def enabled() -> bool:
    """Saklar induk. Selama 0, modul ini tak pernah menghasilkan kandidat."""
    try:
        from agents.shared.config_reader import cfg
        return bool(cfg.peek("futures", "agentic_enabled", 0.0))
    except Exception:
        return False


# ── Filter derau (G14 bigmover) ───────────────────────────────────────────────

def _ada_celah_data(closes: list[float], volumes: list[float], lookback: int = 10) -> bool:
    """Feed rusak atau wash-trade: candle bervolume nol, atau lompatan harga
    ekstrem antar-candle. Masuk ke koin dengan data begini berarti SL dan TP
    dihitung dari harga yang tak pernah benar-benar diperdagangkan."""
    if len(closes) < lookback or len(volumes) < lookback:
        return True
    ekor_v = volumes[-lookback:]
    if any(v <= 0 for v in ekor_v):
        return True
    ekor_c = closes[-lookback:]
    for a, b in zip(ekor_c, ekor_c[1:]):
        if a > 0 and abs(b - a) / a > 0.30:
            return True
    return False


# ── Skor ──────────────────────────────────────────────────────────────────────

def _skor(
    change_24h: float,
    change_1h: float,
    change_30m: float,
    ref: FuturesData,
    direction: str,
) -> tuple[float, list[str], dict]:
    """Skor 0-100 + sinyal yang membentuknya.

    Sinyal dikembalikan sebagai teks karena itulah yang dipelajari
    `weight_updater` — tiap teks jadi satu kunci bobot. Teksnya karena itu harus
    STABIL: mengubah kata-katanya memutus identitas fitur dan menyetel ulang
    seluruh pembelajaran ke nol (pelajaran `learning_policy.canonical_signal_key`).
    """
    skor = 0.0
    sinyal: list[str] = []
    diag: dict = {"change_1h": round(change_1h, 2), "change_30m": round(change_30m, 2)}

    # ── 1. Besaran gerak (0-30) — tesis utamanya ada di sini ─────────────────
    besar = abs(change_24h)
    if besar < 10:
        skor += 15
        sinyal.append(f"momentum_awal Δ24h {change_24h:+.1f}%")
    elif besar < 20:
        skor += 25
        sinyal.append(f"momentum_mapan Δ24h {change_24h:+.1f}%")
    elif besar < 50:
        skor += 30
        sinyal.append(f"momentum_kuat Δ24h {change_24h:+.1f}%")
    else:
        # Sengaja TIDAK nol: gerak ekstrem masih bisa ditradingkan, tapi
        # ukurannya yang dikecilkan (size_mult), bukan skornya dinolkan.
        skor += 18
        sinyal.append(f"momentum_ekstrem Δ24h {change_24h:+.1f}%")

    # ── 2. Konfirmasi arah lewat 1h (0-18) — B2.1 bigmover ───────────────────
    searah = (change_1h > 0) == (change_24h > 0)
    if searah and abs(change_1h) >= 1.0:
        skor += 18
        sinyal.append(f"arah_1h_konfirmasi {change_1h:+.1f}%")
    elif abs(change_1h) < 1.0:
        skor += 10
        sinyal.append(f"arah_1h_datar {change_1h:+.1f}% (zona re-entry)")
    else:
        skor += 3
        sinyal.append(f"arah_1h_berlawanan {change_1h:+.1f}%")

    # ── 3. Volume konfirmasi (0-15) — dari agent3 ────────────────────────────
    vols = ref.volumes or []
    if len(vols) >= 20:
        rata = sum(vols[-20:-1]) / 19 if len(vols) >= 20 else 0
        rasio = vols[-1] / rata if rata > 0 else 0
        diag["vol_ratio"] = round(rasio, 2)
        if rasio >= 2.0:
            skor += 15
            sinyal.append(f"volume_konfirmasi {rasio:.1f}x rata-rata")
        elif rasio >= 1.3:
            skor += 8
            sinyal.append(f"volume_naik {rasio:.1f}x rata-rata")
        elif rasio < 0.7:
            skor -= 5
            sinyal.append(f"volume_memudar {rasio:.1f}x — pembeli hilang")

    # ── 4. Open Interest searah (0-15) — dari agent2/agent3 ──────────────────
    oi = ref.oi_change_pct or 0.0
    diag["oi_change"] = round(oi, 2)
    if oi > 3.0:
        skor += 15
        sinyal.append(f"oi_naik {oi:+.1f}% — uang baru masuk searah")
    elif oi > 0.5:
        skor += 8
        sinyal.append(f"oi_naik_tipis {oi:+.1f}%")
    elif oi < -3.0:
        skor -= 5
        sinyal.append(f"oi_turun {oi:+.1f}% — posisi ditutup, momentum memudar")

    # ── 5. Funding belum sesak (0-12) ────────────────────────────────────────
    fr = (ref.funding_rate or 0.0) * 100
    diag["funding_pct"] = round(fr, 4)
    sesak = (direction == "LONG" and fr > 0.10) or (direction == "SHORT" and fr < -0.10)
    if not sesak and abs(fr) < 0.05:
        skor += 12
        sinyal.append(f"funding_netral {fr:+.3f}% — bahan bakar belum terpakai")
    elif not sesak:
        skor += 6
        sinyal.append(f"funding_wajar {fr:+.3f}%")
    else:
        skor -= 8
        sinyal.append(f"funding_sesak {fr:+.3f}% — sisi ini sudah ramai")

    # ── 6. RSI belum ekstrem (0-10) ──────────────────────────────────────────
    rsi = _rsi(ref.closes, 14) if ref.closes else 50.0
    diag["rsi"] = round(rsi, 1)
    if direction == "LONG":
        if 55 <= rsi <= 72:
            skor += 10
            sinyal.append(f"rsi_sehat {rsi:.0f} — masih ada ruang")
        elif rsi > 80:
            skor -= 6
            sinyal.append(f"rsi_jenuh {rsi:.0f}")
    else:
        if 28 <= rsi <= 45:
            skor += 10
            sinyal.append(f"rsi_sehat {rsi:.0f} — masih ada ruang")
        elif rsi < 20:
            skor -= 6
            sinyal.append(f"rsi_jenuh {rsi:.0f}")

    return skor, sinyal, diag


# ── Level: SL & TP dari SUMBER YANG SAMA dengan monitor ──────────────────────

def _level(direction: str, tf_map: dict[str, FuturesData], price: float) -> Optional[dict]:
    """Susun SL/TP dari `exit_config`.

    Ini sambungan yang sebelumnya putus: agen dulu memakai ATR×2/4/6 miliknya
    sendiri sementara monitor punya config TP terpisah. Dua angka untuk satu hal,
    tak ada yang menjaganya sama — dan hasilnya TP dipasang median 4 ATR lalu
    tersentuh 4%. Sekarang keduanya membaca kunci yang sama, jadi menyetel TP1
    di satu tempat otomatis menggerakkan agen DAN monitor.
    """
    from agents.futures import exit_config as ecfg

    ref = tf_map.get("1h") or tf_map.get("15m") or tf_map.get("4h")
    if not ref or len(ref.closes) < 20 or price <= 0:
        return None

    atr = _atr(ref.highs, ref.lows, ref.closes, 14)
    atr_pct = atr / price * 100 if price > 0 else 0.0
    if atr_pct <= 0:
        return None

    sl_pct = atr_pct * ecfg.get("exit_sl_atr_mult")
    tp1_pct = atr_pct * ecfg.get("exit_tp1_atr_mult")
    tp2_pct = atr_pct * ecfg.get("exit_tp2_atr_mult")

    risiko = price * sl_pct / 100
    if risiko <= 0:
        return None

    arah = 1 if direction == "LONG" else -1
    sl = price - arah * risiko
    tp1 = price + arah * price * tp1_pct / 100
    tp2 = price + arah * price * tp2_pct / 100

    if direction == "SHORT":
        # Lantai: target SHORT tak boleh menembus nol. Koin ber-ATR ekstrem
        # menghasilkan harga target NEGATIF yang mustahil tersentuh.
        lantai = price * 0.10
        tp1, tp2 = max(tp1, lantai), max(tp2, lantai)
        tp1_pct = (price - tp1) / price * 100
        tp2_pct = (price - tp2) / price * 100

    rr = tp2_pct / sl_pct if sl_pct > 0 else 0.0
    return {
        "entry":   _round_price(price, price),
        "sl":      _round_price(sl, price),
        "tp1":     _round_price(tp1, price),
        "tp2":     _round_price(tp2, price),
        "tp3":     _round_price(tp2, price),   # tangga ke-3 = pelari, dikelola trailing
        "risk_pct": round(sl_pct, 3),
        "tp1_pct": round(tp1_pct, 3),
        "tp2_pct": round(tp2_pct, 3),
        "tp3_pct": round(tp2_pct, 3),
        "rr_ratio": round(rr, 2),
        "atr_pct": round(atr_pct, 3),
    }


# ── Titik masuk ───────────────────────────────────────────────────────────────

def scan_symbol(
    symbol: str,
    tf_map: dict[str, FuturesData],
    change_24h: float,
    quote_vol_24h: float = 0.0,
) -> list[dict]:
    """Nol atau satu kandidat. Arah disimpulkan dari tanda `change_24h` —
    momentumnya SENDIRI yang menentukan arah, bukan tebakan terpisah."""
    if not enabled() or not tf_map:
        return []

    ref = tf_map.get("1h") or tf_map.get("15m") or tf_map.get("4h")
    if not ref or not ref.closes:
        return []
    price = ref.closes[-1]
    if price <= 0:
        return []

    besar = abs(change_24h)
    if besar < get("agentic_min_change_24h") or besar > get("agentic_max_change_24h"):
        return []

    # Gerbang likuiditas (B2). Ditaruh SEBELUM skor: koin yang tak bisa menampung
    # posisi kita tak layak dinilai, berapa pun bagus polanya.
    if quote_vol_24h and quote_vol_24h < get("agentic_min_liquidity_usd"):
        logger.debug("agentic_likuiditas_kurang", symbol=symbol, vol=quote_vol_24h)
        return []

    try:
        from agents.futures.delisting_monitor import is_delisting_risk
        if is_delisting_risk(symbol):
            return []
    except Exception:
        pass

    if _ada_celah_data(ref.closes, ref.volumes):
        return []

    direction = "LONG" if change_24h > 0 else "SHORT"

    # Gerbang funding keras — biaya menahan posisi melawan funding ekstrem
    # memakan tesisnya sendiri.
    fr_pct = (ref.funding_rate or 0.0) * 100
    batas = get("agentic_max_funding_pct")
    if (direction == "LONG" and fr_pct > batas) or (direction == "SHORT" and fr_pct < -batas):
        logger.debug("agentic_funding_veto", symbol=symbol, funding=fr_pct)
        return []

    d15 = tf_map.get("15m")
    change_1h = _perubahan(tf_map.get("1h"), 1)
    change_30m = _perubahan(d15, 2)

    # G18 — jebakan puncak: lonjakan 30 menit searah yang sangat besar berarti
    # kita masuk tepat di puncak literal. Ukurannya dikecilkan, bukan ditolak:
    # menolaknya berarti menolak persis koin yang jadi alasan lane ini ada.
    size_mult = 1.0
    if abs(change_30m) > 15.0 and (change_30m > 0) == (change_24h > 0):
        size_mult = 0.5

    skor, sinyal, diag = _skor(change_24h, change_1h, change_30m, ref, direction)
    if skor < get("agentic_min_score"):
        return []

    level = _level(direction, tf_map, price)
    if not level:
        return []
    if level["rr_ratio"] < get("agentic_min_rr"):
        return []

    from app.services.slippage_sim import calculate_entry_slippage
    slip = calculate_entry_slippage(quote_vol_24h)

    leverage = cap_leverage_by_lane(6, level["risk_pct"], lane=LANE, change_24h=change_24h)

    atr_pct = level.pop("atr_pct")
    return [{
        "symbol":      symbol,
        "direction":   direction,
        "price":       round(price, 8),
        "score":       round(min(skor, 100), 1),
        "signals":     sinyal,
        "leverage":    leverage,
        "change_24h":  round(change_24h, 2),
        "change_1h":   diag.get("change_1h", 0),
        "change_30m":  diag.get("change_30m", 0),
        "rsi":         diag.get("rsi", 50),
        "funding_rate": round(fr_pct, 4),
        "oi_change":   diag.get("oi_change", 0),
        "liq_long":    round((ref.liq_long_usdt or 0) / 1e6, 3),
        "liq_short":   round((ref.liq_short_usdt or 0) / 1e6, 3),
        "agent":       AGENT_NAME,
        "setup_type":  LANE,
        "regime":      "n/a",
        "size_mult":   round(size_mult, 2),
        "atr_pct":     atr_pct,
        "quote_vol_24h": quote_vol_24h,
        "entry_slippage_pct": slip,
        **level,
    }]


def _perubahan(d: Optional[FuturesData], n: int) -> float:
    """Perubahan harga (%) selama `n` candle terakhir. Nol bila datanya kurang —
    bukan menebak, karena tebakan di sini jadi konfirmasi arah palsu."""
    if not d or not d.closes or len(d.closes) <= n:
        return 0.0
    lalu = d.closes[-1 - n]
    return (d.closes[-1] - lalu) / lalu * 100 if lalu else 0.0


def peringkat(kandidat: list[dict], slot: int) -> list[dict]:
    """Ambil `slot` kandidat TERBAIK, bukan semua yang lolos ambang.

    Ini inti "sedikit posisi, tiap posisi optimal": sistem lama membuka apa pun
    yang lolos sampai kuota habis, sehingga kandidat berskor 66 bisa memakan slot
    yang semenit kemudian dibutuhkan kandidat berskor 88. Mengurutkan lebih dulu
    membuat slot selalu diisi yang terbaik pada siklus itu.
    """
    return sorted(kandidat, key=lambda c: c.get("score", 0), reverse=True)[:max(0, slot)]
