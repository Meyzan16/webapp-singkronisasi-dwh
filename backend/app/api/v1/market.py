"""Market data endpoints — spot positions, futures positions, futures 24h ranking."""

import hashlib
import hmac
import time
from urllib.parse import urlencode

import httpx
import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import get_settings

router = APIRouter(tags=["market"])
logger = structlog.get_logger(__name__)

SPOT_BASE = "https://api.binance.com"
FAPI_BASE = "https://fapi.binance.com"


def _sign(secret: str, query_string: str) -> str:
    return hmac.new(secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()


def _signed_url(path: str, secret: str, extra: dict | None = None) -> tuple[str, str]:
    """Return (base_query, signed_query) for a Binance signed endpoint."""
    params: dict = {"timestamp": int(time.time() * 1000), "recvWindow": 10000}
    if extra:
        params.update(extra)
    qs = urlencode(params)
    sig = _sign(secret, qs)
    return f"{qs}&signature={sig}"


# ── Pydantic schemas ────────────────────────────────────────────────────────

class SpotAsset(BaseModel):
    asset: str
    free: float
    locked: float
    total: float
    usdt_value: float

class SpotPositionsResponse(BaseModel):
    assets: list[SpotAsset]
    total_usdt_value: float

class FuturesPosition(BaseModel):
    symbol: str
    side: str            # LONG / SHORT
    size: float
    entry_price: float
    mark_price: float
    unrealized_pnl: float
    roe_percent: float   # Return on equity %
    margin: float
    leverage: int

class FuturesPositionsResponse(BaseModel):
    positions: list[FuturesPosition]
    total_unrealized_pnl: float

class FuturesTicker(BaseModel):
    symbol: str
    price: float
    change_24h: float    # %
    volume_24h: float    # in USDT
    high_24h: float
    low_24h: float

class FuturesMarketResponse(BaseModel):
    tickers: list[FuturesTicker]   # sorted by change_24h desc


# ── Helpers ─────────────────────────────────────────────────────────────────

async def _get(client: httpx.AsyncClient, url: str, headers: dict | None = None) -> dict | list:
    r = await client.get(url, headers=headers or {})
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text[:200])
    return r.json()


def _auth_headers(api_key: str) -> dict:
    return {"X-MBX-APIKEY": api_key}


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/market/spot-positions", response_model=SpotPositionsResponse)
async def get_spot_positions() -> SpotPositionsResponse:
    """Fetch all non-zero spot holdings with USDT value."""
    s = get_settings()
    if not s.binance_api_key:
        raise HTTPException(status_code=400, detail="API key not configured")

    qs = _signed_url("/api/v3/account", s.binance_api_secret)

    async with httpx.AsyncClient(timeout=15) as client:
        # Get account balances
        account = await _get(client, f"{SPOT_BASE}/api/v3/account?{qs}", _auth_headers(s.binance_api_key))

        # Get all spot prices in one call
        prices_raw: list = await _get(client, f"{SPOT_BASE}/api/v3/ticker/price")
        prices = {p["symbol"]: float(p["price"]) for p in prices_raw}

    assets: list[SpotAsset] = []
    for b in account["balances"]:
        free = float(b["free"])
        locked = float(b["locked"])
        total = free + locked
        if total < 0.00001:
            continue

        asset = b["asset"]
        if asset == "USDT":
            usdt_val = total
        else:
            price = prices.get(f"{asset}USDT", 0.0)
            usdt_val = total * price

        if usdt_val < 0.01:
            continue

        assets.append(SpotAsset(
            asset=asset,
            free=round(free, 8),
            locked=round(locked, 8),
            total=round(total, 8),
            usdt_value=round(usdt_val, 2),
        ))

    assets.sort(key=lambda a: a.usdt_value, reverse=True)
    total_usdt = sum(a.usdt_value for a in assets)

    logger.info("spot_positions_fetched", count=len(assets), total_usdt=total_usdt)
    return SpotPositionsResponse(assets=assets, total_usdt_value=round(total_usdt, 2))


@router.get("/market/futures-positions", response_model=FuturesPositionsResponse)
async def get_futures_positions() -> FuturesPositionsResponse:
    """Fetch all active (non-zero) futures positions."""
    s = get_settings()
    if not s.binance_api_key:
        raise HTTPException(status_code=400, detail="API key not configured")

    qs = _signed_url("/fapi/v2/positionRisk", s.binance_api_secret)

    async with httpx.AsyncClient(timeout=15) as client:
        raw: list = await _get(
            client,
            f"{FAPI_BASE}/fapi/v2/positionRisk?{qs}",
            _auth_headers(s.binance_api_key),
        )

    positions: list[FuturesPosition] = []
    for p in raw:
        size = float(p.get("positionAmt", 0))
        if abs(size) < 0.000001:
            continue

        entry = float(p.get("entryPrice", 0))
        mark = float(p.get("markPrice", 0))
        upnl = float(p.get("unRealizedProfit", 0))
        notional = abs(float(p.get("notional", 0)))
        leverage = int(p.get("leverage", 1))
        margin = notional / leverage if leverage > 0 else 0
        roe = (upnl / margin * 100) if margin > 0 else 0

        positions.append(FuturesPosition(
            symbol=p["symbol"],
            side="LONG" if size > 0 else "SHORT",
            size=abs(size),
            entry_price=entry,
            mark_price=mark,
            unrealized_pnl=round(upnl, 4),
            roe_percent=round(roe, 2),
            margin=round(margin, 2),
            leverage=leverage,
        ))

    positions.sort(key=lambda p: abs(p.unrealized_pnl), reverse=True)
    total_upnl = sum(p.unrealized_pnl for p in positions)

    logger.info("futures_positions_fetched", count=len(positions))
    return FuturesPositionsResponse(positions=positions, total_unrealized_pnl=round(total_upnl, 4))


@router.get("/market/futures-market", response_model=FuturesMarketResponse)
async def get_futures_market() -> FuturesMarketResponse:
    """Fetch all USDT futures pairs sorted by 24h change (highest first)."""
    async with httpx.AsyncClient(timeout=15) as client:
        raw: list = await _get(client, f"{FAPI_BASE}/fapi/v1/ticker/24hr")

    tickers: list[FuturesTicker] = []
    for t in raw:
        sym: str = t.get("symbol", "")
        if not sym.endswith("USDT"):
            continue
        tickers.append(FuturesTicker(
            symbol=sym,
            price=float(t.get("lastPrice", 0)),
            change_24h=round(float(t.get("priceChangePercent", 0)), 2),
            volume_24h=round(float(t.get("quoteVolume", 0)), 0),
            high_24h=float(t.get("highPrice", 0)),
            low_24h=float(t.get("lowPrice", 0)),
        ))

    tickers.sort(key=lambda t: t.change_24h, reverse=True)

    logger.info("futures_market_fetched", count=len(tickers))
    return FuturesMarketResponse(tickers=tickers)
