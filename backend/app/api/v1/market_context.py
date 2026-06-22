"""
Market Context API — real-time market sentiment summary.

GET /market/context

Returns:
  - Overall market sentiment (bullish/bearish/neutral)
  - BTC price + 24h change
  - % coins red vs green
  - Average 24h change top-50
  - Coins down >10% count
  - Live futures & spot opp signal counts
  - Contextual message for traders
  - Futures-specific: funding rate sentiment, OI direction
"""

import time
from typing import Optional

import httpx
import structlog
from fastapi import APIRouter

from app.services.binance_urls import fapi, spot

router = APIRouter(tags=["market"])
logger = structlog.get_logger(__name__)

# Cache: refresh every 5 minutes
_cache: Optional[dict] = None
_cache_ts: float = 0
CACHE_TTL = 5 * 60


async def _fetch_context() -> dict:
    async with httpx.AsyncClient(timeout=12) as client:
        spot_r    = await client.get(spot("/api/v3/ticker/24hr"))
        btc_fr_r  = await client.get(fapi("/fapi/v1/premiumIndex?symbol=BTCUSDT"))

    spot_data = spot_r.json() if spot_r.status_code == 200 else []
    btc_fr    = float((btc_fr_r.json() if btc_fr_r.status_code == 200 else {}).get("lastFundingRate", 0)) * 100

    # Filter USDT pairs, sort by volume
    usdt = [t for t in spot_data if str(t.get("symbol", "")).endswith("USDT")]
    usdt.sort(key=lambda t: float(t.get("quoteVolume", 0)), reverse=True)
    top50 = usdt[:50]

    changes         = [float(t.get("priceChangePercent", 0)) for t in top50]
    avg_change      = sum(changes) / len(changes) if changes else 0.0
    pct_green       = sum(1 for c in changes if c > 0) / len(changes) * 100 if changes else 50
    coins_down_10   = sum(1 for c in changes if c < -10)
    coins_up_10     = sum(1 for c in changes if c > 10)

    btc = next((t for t in top50 if t["symbol"] == "BTCUSDT"), {})
    btc_change = float(btc.get("priceChangePercent", 0))
    btc_price  = float(btc.get("lastPrice", 0))

    eth = next((t for t in top50 if t["symbol"] == "ETHUSDT"), {})
    eth_change = float(eth.get("priceChangePercent", 0))

    # Sentiment classification
    if avg_change < -5 and pct_green < 25:
        sentiment = "strongly_bearish"
    elif avg_change < -2 and pct_green < 35:
        sentiment = "bearish"
    elif avg_change > 5 and pct_green > 75:
        sentiment = "strongly_bullish"
    elif avg_change > 2 and pct_green > 65:
        sentiment = "bullish"
    else:
        sentiment = "neutral"

    # Funding rate sentiment
    if btc_fr < -0.03:
        fr_sentiment = "short_squeeze_risk"
        fr_msg = f"Funding BTC {btc_fr:+.3f}% — short squeeze bisa terjadi"
    elif btc_fr > 0.10:
        fr_sentiment = "long_squeeze_risk"
        fr_msg = f"Funding BTC {btc_fr:+.3f}% — longs overpaying, hati-hati"
    else:
        fr_sentiment = "neutral"
        fr_msg = f"Funding BTC {btc_fr:+.3f}% — sentiment netral"

    # Pull live signal counts from in-memory stores
    futures_count = _get_futures_count()
    opp_count     = _get_opp_count()

    # Build contextual messages
    futures_msg = _build_futures_msg(sentiment, avg_change, btc_change, pct_green, btc_fr, futures_count)
    opp_msg     = _build_opp_msg(sentiment, avg_change, btc_change, pct_green, changes, opp_count)

    return {
        "sentiment":            sentiment,
        "btc_price":            round(btc_price, 2),
        "btc_change_24h":       round(btc_change, 2),
        "eth_change_24h":       round(eth_change, 2),
        "avg_change_top50":     round(avg_change, 2),
        "pct_green":            round(pct_green, 1),
        "pct_red":              round(100 - pct_green, 1),
        "coins_down_10pct":     coins_down_10,
        "coins_up_10pct":       coins_up_10,
        "btc_funding":          round(btc_fr, 4),
        "fr_sentiment":         fr_sentiment,
        "fr_message":           fr_msg,
        "futures_signal_count": futures_count,
        "opp_signal_count":     opp_count,
        "futures_msg":          futures_msg,
        "opp_msg":              opp_msg,
        # Legacy keys kept for backward compat
        "futures_zero_msg":     futures_msg,
        "opp_context_msg":      opp_msg,
        "generated_at":         int(time.time()),
    }


def _get_futures_count() -> int:
    """Pull live futures signal count from in-memory store."""
    try:
        from agents.futures import store as fs
        cached = fs.get_all_results()
        a1 = len((cached.get("agent1") or {}).get("results", []))
        a2 = len((cached.get("agent2") or {}).get("results", []))
        a3 = len((cached.get("agent3") or {}).get("results", []))
        return a1 + a2 + a3
    except Exception:
        return -1  # -1 = not scanned yet


def _get_opp_count() -> int:
    """Pull live spot opportunity count from in-memory store."""
    try:
        from agents.opportunity import store as os_
        result = os_.get_result()
        if result is None:
            return -1  # -1 = not scanned yet
        results = result.get("results", [])
        return sum(1 for r in results if r.get("alert_type") != "breakout_pump")
    except Exception:
        return -1


def _build_futures_msg(sentiment: str, avg_change: float, btc_change: float,
                       pct_green: float, btc_fr: float, count: int) -> str:
    pct_red = 100 - pct_green

    if count > 0:
        if sentiment in ("bearish", "strongly_bearish"):
            return (
                f"{count} sinyal aktif — market bearish justru banyak short setup. "
                f"Agent 1 menemukan funding/OI divergence. Agent 2 deteksi Wyckoff Distribution. "
                f"Cek direction filter untuk konfirmasi."
            )
        elif sentiment in ("bullish", "strongly_bullish"):
            return (
                f"{count} sinyal aktif — market rally, setup LONG dominan. "
                f"Wyckoff Markup + EMA alignment terkonfirmasi. "
                f"Perhatikan R:R dan leverage."
            )
        else:
            return (
                f"{count} sinyal aktif — ada setup di market sideways. "
                f"Biasanya breakout dari konsolidasi. Cek score ≥ 65 untuk entry terbaik."
            )

    # 0 signals
    if sentiment in ("bearish", "strongly_bearish"):
        if abs(btc_fr) < 0.03:
            return (
                f"0 sinyal — market merah ({pct_red:.0f}% koin merah, avg {avg_change:+.1f}%) "
                f"tapi funding near-zero ({btc_fr:+.3f}%). "
                f"Agent 1 butuh funding < -0.03% untuk short squeeze signal. Normal jika 0 saat koreksi merata."
            )
        return (
            f"0 sinyal — koreksi besar ({avg_change:+.1f}%), agents menunggu setup yang lebih jelas. "
            f"Funding {btc_fr:+.3f}%."
        )
    elif sentiment in ("bullish", "strongly_bullish"):
        return (
            f"0 sinyal — market rally tapi belum ada divergence. "
            f"Agent 2 butuh Wyckoff Accumulation yang jelas untuk entry LONG. "
            f"Tunggu konsolidasi setelah pump."
        )
    return (
        f"0 sinyal — market sideways ({avg_change:+.1f}%). "
        f"Agent 1 butuh extreme funding/OI. Agent 2 butuh breakout dari squeeze. "
        f"Funding {btc_fr:+.3f}%."
    )


def _build_opp_msg(sentiment: str, avg_change: float, btc_change: float,
                   pct_green: float, changes: list, count: int) -> str:
    pct_red   = 100 - pct_green
    big_drops = sum(1 for c in changes if c < -10)

    if count > 0:
        if sentiment in ("bearish", "strongly_bearish"):
            if big_drops >= 5:
                return (
                    f"{count} rekomendasi — {big_drops} koin turun >10%, RSI oversold di banyak koin. "
                    f"Entry SPOT di harga diskon = R:R tinggi. SL ketat wajib."
                )
            return (
                f"{count} rekomendasi — market bearish justru banyak akumulasi tersembunyi. "
                f"Koin dengan volume naik saat harga turun = hidden strength."
            )
        elif sentiment in ("bullish", "strongly_bullish"):
            return (
                f"{count} rekomendasi — market bullish, fokus setup breakout. "
                f"Koin yang belum naik + squeeze = kandidat terbaik."
            )
        return (
            f"{count} rekomendasi — ada setup di berbagai kondisi. "
            f"Prioritaskan score tinggi dan BB Squeeze + volume naik."
        )

    # 0 results
    if sentiment in ("bearish", "strongly_bearish"):
        return (
            f"0 rekomendasi — market bearish ({avg_change:+.1f}%), scanner belum menemukan "
            f"setup dengan R:R ≥ 1:3. Tunggu oversold di zona support kuat."
        )
    return (
        f"0 rekomendasi — belum ada setup yang memenuhi kriteria. "
        f"Scanner butuh BB Squeeze + volume konfirmasi. Sabar."
    )


@router.get("/market/context")
async def get_market_context() -> dict:
    """Real-time market sentiment + live signal counts + contextual messages."""
    global _cache, _cache_ts

    if _cache and (time.time() - _cache_ts) < CACHE_TTL:
        # Always refresh signal counts (they change more often than market data)
        _cache["futures_signal_count"] = _get_futures_count()
        _cache["opp_signal_count"]     = _get_opp_count()
        return _cache

    try:
        ctx = await _fetch_context()
        _cache    = ctx
        _cache_ts = time.time()
        return ctx
    except Exception as exc:
        logger.warning("market_context_error", error=str(exc)[:80])
        return {
            "sentiment":            "unknown",
            "btc_price":            0,
            "btc_change_24h":       0,
            "avg_change_top50":     0,
            "pct_green":            50,
            "pct_red":              50,
            "coins_down_10pct":     0,
            "coins_up_10pct":       0,
            "btc_funding":          0,
            "fr_sentiment":         "neutral",
            "fr_message":           "",
            "futures_signal_count": _get_futures_count(),
            "opp_signal_count":     _get_opp_count(),
            "futures_msg":          "Tidak bisa ambil data market saat ini.",
            "opp_msg":              "Tidak bisa ambil data market saat ini.",
            "futures_zero_msg":     "Tidak bisa ambil data market saat ini.",
            "opp_context_msg":      "Tidak bisa ambil data market saat ini.",
            "generated_at":         int(time.time()),
        }
