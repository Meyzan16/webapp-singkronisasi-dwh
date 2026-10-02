"""GET /market/spot-filters — aturan order Binance SPOT per simbol.

Dipakai kalkulator rebalancing di dashboard supaya jumlah koin yang disarankan
benar-benar bisa dipasang: dibulatkan ke `stepSize` (LOT_SIZE) dan ditandai bila
nilainya di bawah minimum order (NOTIONAL / MIN_NOTIONAL). Tanpa ini kalkulator
menyarankan "jual 0,0012345678 BTC" yang ditolak bursa.
"""

import json
import time

import httpx
import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services.binance_urls import spot

router = APIRouter(tags=["market"])
logger = structlog.get_logger(__name__)

_CACHE_TTL = 30 * 60          # exchangeInfo nyaris tak pernah berubah
_cache: dict[str, tuple["SpotFilter", float]] = {}


class SpotFilter(BaseModel):
    """Batas order satu simbol SPOT."""
    symbol: str
    step_size: float          # kelipatan jumlah koin (LOT_SIZE.stepSize)
    min_qty: float            # jumlah koin minimum (LOT_SIZE.minQty)
    min_notional: float       # nilai order minimum dalam quote (USDT)


class SpotFiltersResponse(BaseModel):
    """Peta simbol → filter; simbol yang tak dikenal bursa dilewati."""
    filters: dict[str, SpotFilter]


def _parse(sym: dict) -> SpotFilter:
    """Ambil LOT_SIZE + NOTIONAL/MIN_NOTIONAL dari satu entri exchangeInfo."""
    step, min_qty, min_notional = 0.0, 0.0, 0.0
    for f in sym.get("filters", []):
        t = f.get("filterType")
        if t == "LOT_SIZE":
            step = float(f.get("stepSize", 0) or 0)
            min_qty = float(f.get("minQty", 0) or 0)
        elif t in ("NOTIONAL", "MIN_NOTIONAL"):
            min_notional = max(min_notional, float(f.get("minNotional", 0) or 0))
    return SpotFilter(symbol=sym["symbol"], step_size=step, min_qty=min_qty, min_notional=min_notional)


@router.get("/market/spot-filters", response_model=SpotFiltersResponse)
async def spot_filters(symbols: str = Query(..., description="Daftar dipisah koma, mis. BTCUSDT,ETHUSDT")) -> SpotFiltersResponse:
    """Filter order untuk simbol yang diminta (cache 30 menit per simbol)."""
    wanted = sorted({s.strip().upper() for s in symbols.split(",") if s.strip()})[:100]
    now = time.time()
    out = {s: _cache[s][0] for s in wanted if s in _cache and now - _cache[s][1] < _CACHE_TTL}
    missing = [s for s in wanted if s not in out]
    if missing:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(spot("/api/v3/exchangeInfo"),
                                     params={"symbols": json.dumps(missing, separators=(",", ":"))})
            # 400 = ada simbol yang tak dikenal → ulangi satu per satu agar sisanya tetap dapat.
            if r.status_code == 400 and len(missing) > 1:
                rows = []
                async with httpx.AsyncClient(timeout=15) as client:
                    for s in missing:
                        rr = await client.get(spot("/api/v3/exchangeInfo"), params={"symbol": s})
                        if rr.status_code == 200:
                            rows += rr.json().get("symbols", [])
            else:
                r.raise_for_status()
                rows = r.json().get("symbols", [])
        except httpx.HTTPError as exc:
            logger.warning("spot_filters_fetch_failed", error=str(exc)[:120])
            if not out:
                raise HTTPException(status_code=502, detail="exchangeInfo Binance tidak terjangkau") from exc
            rows = []
        for sym in rows:
            f = _parse(sym)
            _cache[f.symbol] = (f, now)
            out[f.symbol] = f
    return SpotFiltersResponse(filters=out)
