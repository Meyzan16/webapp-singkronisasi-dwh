"""Binance HMAC-SHA256 signed request helper.

All private Binance endpoints (account, orders, wallet) require:
  - X-MBX-APIKEY header
  - timestamp + signature query params (HMAC-SHA256 of the full query string)

Credentials priority: PostgreSQL AppSettings → .env / config.py fallback.
"""

import hashlib
import hmac
import time
import urllib.parse

import httpx

from app.services.binance_urls import spot


async def get_binance_credentials() -> tuple[str, str]:
    """
    Return (api_key, api_secret).
    Checks DB first so container UI-saved keys override env vars.
    """
    api_key = api_secret = ""
    try:
        from app.database import AsyncSessionLocal
        from app.models.app_settings import AppSettings
        async with AsyncSessionLocal() as session:
            key_row    = await session.get(AppSettings, "binance_api_key")
            secret_row = await session.get(AppSettings, "binance_api_secret")
            api_key    = (key_row.value    or "") if key_row    else ""
            api_secret = (secret_row.value or "") if secret_row else ""
    except Exception:
        pass

    if not api_key:
        from app.config import get_settings
        cfg        = get_settings()
        api_key    = cfg.binance_api_key
        api_secret = cfg.binance_api_secret

    return api_key, api_secret


async def binance_signed_get(
    endpoint: str,
    params:   dict,
    api_key:  str,
    api_secret: str,
) -> tuple[dict, int]:
    """
    GET request to Binance spot API with HMAC signature.
    Returns (response_json, status_code).
    """
    params = dict(params)
    params["timestamp"] = int(time.time() * 1000)
    query_string = urllib.parse.urlencode(params)
    signature = hmac.new(
        api_secret.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    params["signature"] = signature

    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            spot(endpoint),
            headers={"X-MBX-APIKEY": api_key},
            params=params,
        )
    try:
        return r.json(), r.status_code
    except Exception:
        return {"msg": r.text}, r.status_code
