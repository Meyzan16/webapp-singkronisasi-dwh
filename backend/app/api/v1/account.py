"""Binance account endpoints — test connection and fetch spot balance."""

import hashlib
import hmac
import time
from decimal import Decimal
from urllib.parse import urlencode

import httpx
import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import get_settings

router = APIRouter(tags=["account"])
logger = structlog.get_logger(__name__)


class TestConnectionRequest(BaseModel):
    """Credentials to test."""
    api_key: str
    api_secret: str
    testnet: bool = False


class TestConnectionResponse(BaseModel):
    """Result of connection test."""
    success: bool
    message: str
    account_type: str | None = None
    can_trade: bool | None = None
    spot_balance_usdt: float | None = None


class SpotAsset(BaseModel):
    """Single spot asset holding."""
    asset: str
    free: float
    locked: float
    total: float
    usdt_value: float | None = None


class SpotBalanceResponse(BaseModel):
    """All spot holdings."""
    assets: list[SpotAsset]
    total_usdt: float


def _sign(secret: str, params: dict) -> str:
    """HMAC-SHA256 signature for Binance API."""
    query = urlencode(params)
    return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()


async def _binance_get(
    api_key: str,
    api_secret: str,
    path: str,
    testnet: bool = False,
) -> dict:
    """Signed GET request to Binance API."""
    # Try known accessible domains in order
    base_urls = [
        "https://data-api.binance.vision",  # accessible from Indonesia (public only)
        "https://api.binance.com",           # main (blocked in Indonesia)
        "https://api1.binance.com",
        "https://api2.binance.com",
    ]
    if testnet:
        base_urls = ["https://testnet.binance.vision"]

    params = {"timestamp": int(time.time() * 1000), "recvWindow": 10000}
    params["signature"] = _sign(api_secret, params)

    headers = {"X-MBX-APIKEY": api_key}

    last_error = "All endpoints unreachable"
    async with httpx.AsyncClient(timeout=10) as client:
        for base in base_urls:
            try:
                url = f"{base}{path}"
                resp = await client.get(url, params=params, headers=headers)
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code in (401, 403):
                    # Bad credentials — no point trying other domains
                    raise HTTPException(
                        status_code=401,
                        detail=f"Invalid API credentials: {resp.json().get('msg', resp.text)}",
                    )
                last_error = f"{base}: HTTP {resp.status_code} — {resp.text[:100]}"
            except HTTPException:
                raise
            except Exception as exc:
                last_error = f"{base}: {exc}"
                continue

    raise HTTPException(status_code=503, detail=f"Binance unreachable. {last_error}")


@router.post("/account/test-connection", response_model=TestConnectionResponse)
async def test_connection(req: TestConnectionRequest) -> TestConnectionResponse:
    """Test Binance API credentials and return account info."""

    if not req.api_key or not req.api_secret:
        raise HTTPException(status_code=400, detail="API key and secret are required")

    try:
        data = await _binance_get(req.api_key, req.api_secret, "/api/v3/account", req.testnet)

        # Find USDT balance
        usdt = next(
            (float(b["free"]) + float(b["locked"])
             for b in data.get("balances", [])
             if b["asset"] == "USDT"),
            0.0,
        )

        logger.info("connection_test_success", account_type=data.get("accountType"))
        return TestConnectionResponse(
            success=True,
            message="Connection successful! Binance account verified.",
            account_type=data.get("accountType"),
            can_trade=data.get("canTrade"),
            spot_balance_usdt=round(usdt, 2),
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("connection_test_failed", error=str(exc))
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/account/spot-balance", response_model=SpotBalanceResponse)
async def get_spot_balance() -> SpotBalanceResponse:
    """Fetch all non-zero spot holdings for the configured account."""

    settings = get_settings()
    if not settings.binance_api_key or not settings.binance_api_secret:
        raise HTTPException(status_code=400, detail="API credentials not configured in .env")

    data = await _binance_get(
        settings.binance_api_key,
        settings.binance_api_secret,
        "/api/v3/account",
        settings.binance_testnet,
    )

    assets: list[SpotAsset] = []
    for b in data.get("balances", []):
        free = float(b["free"])
        locked = float(b["locked"])
        total = free + locked
        if total > 0.0001:
            assets.append(SpotAsset(
                asset=b["asset"],
                free=free,
                locked=locked,
                total=total,
            ))

    # Sort by total descending
    assets.sort(key=lambda a: a.total, reverse=True)

    usdt_total = sum(
        a.total for a in assets if a.asset == "USDT"
    )

    logger.info("spot_balance_fetched", asset_count=len(assets))
    return SpotBalanceResponse(assets=assets, total_usdt=round(usdt_total, 2))
