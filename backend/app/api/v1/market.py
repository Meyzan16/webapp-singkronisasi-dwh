"""Market data endpoints — spot positions, futures positions, futures 24h ranking."""

import asyncio
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

from app.services.binance_urls import get_spot_url, get_fapi_url, fapi, spot


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
    current_price: float
    usdt_value: float
    avg_buy_price: float | None   # weighted avg from trade history
    pnl_usdt: float | None        # unrealized P&L in USDT
    pnl_percent: float | None     # unrealized P&L %

class SpotPositionsResponse(BaseModel):
    assets: list[SpotAsset]
    total_usdt_value: float
    total_pnl_usdt: float

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

async def _fetch_avg_buy_price(
    client: httpx.AsyncClient,
    asset: str,
    total_held: float,
    api_key: str,
    api_secret: str,
) -> float | None:
    """
    Calculate avg buy price using FIFO (First In, First Out).

    Process trades oldest→newest:
    - BUY: add lot to queue
    - SELL: consume from oldest lots first (FIFO)
    - Remaining lots in queue = current holding → weighted avg
    """
    if asset == "USDT":
        return 1.0
    symbol = f"{asset}USDT"
    try:
        qs = _signed_url("/api/v3/myTrades", api_secret, {"symbol": symbol, "limit": 500})
        resp = await client.get(spot(f"/api/v3/myTrades?{qs}"), headers=_auth_headers(api_key))
        if resp.status_code != 200:
            return None
        trade_list = resp.json()
        if not trade_list or not isinstance(trade_list, list):
            return None

        # FIFO queue of buy lots: list of [price, qty]
        buy_lots: list[list[float]] = []

        for t in trade_list:  # oldest first (Binance returns asc by default)
            qty = float(t.get("qty", 0))
            price = float(t.get("price", 0))

            if t.get("isBuyer"):
                buy_lots.append([price, qty])
            else:
                # Sell: consume FIFO from oldest buy lots
                to_sell = qty
                while to_sell > 1e-8 and buy_lots:
                    oldest_price, oldest_qty = buy_lots[0]
                    if oldest_qty <= to_sell + 1e-8:
                        to_sell -= oldest_qty
                        buy_lots.pop(0)
                    else:
                        buy_lots[0][1] -= to_sell
                        to_sell = 0

        # Remaining lots = current holding
        total_qty = sum(lot[1] for lot in buy_lots)
        if total_qty < 1e-8:
            return None

        total_val = sum(lot[0] * lot[1] for lot in buy_lots)
        return total_val / total_qty

    except Exception:
        return None


@router.get("/market/spot-positions", response_model=SpotPositionsResponse)
async def get_spot_positions() -> SpotPositionsResponse:
    """Fetch all non-zero spot holdings with current price, avg buy price, and P&L."""
    s = get_settings()
    if not s.binance_api_key:
        raise HTTPException(status_code=400, detail="API key not configured")

    qs = _signed_url("/api/v3/account", s.binance_api_secret)

    async with httpx.AsyncClient(timeout=20) as client:
        account = await _get(client, spot(f"/api/v3/account?{qs}"), _auth_headers(s.binance_api_key))
        prices_raw: list = await _get(client, spot("/api/v3/ticker/price"))
        prices = {p["symbol"]: float(p["price"]) for p in prices_raw}

        # Build initial asset list
        raw_assets = []
        for b in account["balances"]:
            free = float(b["free"])
            locked = float(b["locked"])
            total = free + locked
            if total < 0.00001:
                continue
            asset = b["asset"]
            cur_price = 1.0 if asset == "USDT" else prices.get(f"{asset}USDT", 0.0)
            usdt_val = total * cur_price
            if usdt_val < 0.01:
                continue
            raw_assets.append((asset, free, locked, total, cur_price, usdt_val))

        # Fetch avg buy price concurrently for all assets
        avg_prices = await asyncio.gather(*[
            _fetch_avg_buy_price(client, a[0], a[3], s.binance_api_key, s.binance_api_secret)
            for a in raw_assets
        ])

    assets: list[SpotAsset] = []
    for (asset, free, locked, total, cur_price, usdt_val), avg_buy in zip(raw_assets, avg_prices):
        pnl_usdt = None
        pnl_pct = None
        if avg_buy and avg_buy > 0 and asset != "USDT":
            cost_basis = avg_buy * total
            pnl_usdt = round(usdt_val - cost_basis, 2)
            pnl_pct = round((cur_price - avg_buy) / avg_buy * 100, 2)

        assets.append(SpotAsset(
            asset=asset,
            free=round(free, 8),
            locked=round(locked, 8),
            total=round(total, 8),
            current_price=round(cur_price, 8),
            usdt_value=round(usdt_val, 2),
            avg_buy_price=round(avg_buy, 8) if avg_buy else None,
            pnl_usdt=pnl_usdt,
            pnl_percent=pnl_pct,
        ))

    assets.sort(key=lambda a: a.usdt_value, reverse=True)
    total_usdt = sum(a.usdt_value for a in assets)
    total_pnl = sum(a.pnl_usdt for a in assets if a.pnl_usdt is not None)

    logger.info("spot_positions_fetched", count=len(assets), total_usdt=total_usdt)
    return SpotPositionsResponse(
        assets=assets,
        total_usdt_value=round(total_usdt, 2),
        total_pnl_usdt=round(total_pnl, 2),
    )


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
            fapi(f"/fapi/v2/positionRisk?{qs}"),
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
        raw: list = await _get(client, fapi("/fapi/v1/ticker/24hr"))

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
