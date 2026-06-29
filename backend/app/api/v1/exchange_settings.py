"""
Exchange Settings & Wallet API.

GET  /exchange/keys           — masked key status (has_key, has_secret, masked)
POST /exchange/keys           — save api_key + api_secret to PostgreSQL
POST /account/test-connection — test Binance connectivity with given credentials
GET  /wallet/spot             — real spot holdings using DB-stored credentials
"""

import time

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.database import AsyncSessionLocal, require_db
from app.models.app_settings import AppSettings
from app.services.binance_auth import binance_signed_get, get_binance_credentials

router = APIRouter(tags=["exchange"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class KeysPayload(BaseModel):
    api_key:    str
    api_secret: str


class TestConnectionPayload(BaseModel):
    api_key:    str
    api_secret: str
    testnet:    bool = False


# ── GET /exchange/keys ────────────────────────────────────────────────────────

@router.get("/exchange/keys", dependencies=[Depends(require_db)])
async def get_exchange_keys() -> dict:
    """Return masked API key status. Never returns the actual secret."""
    async with AsyncSessionLocal() as session:
        key_row    = await session.get(AppSettings, "binance_api_key")
        secret_row = await session.get(AppSettings, "binance_api_secret")

    api_key    = (key_row.value    or "") if key_row    else ""
    has_secret = bool(secret_row and secret_row.value)

    masked = ""
    if len(api_key) > 10:
        masked = api_key[:6] + "••••••••" + api_key[-4:]
    elif api_key:
        masked = api_key[:4] + "••••"

    return {
        "has_key":    bool(api_key),
        "has_secret": has_secret,
        "masked_key": masked,
        "updated_at": key_row.updated_at if key_row else None,
        "source":     "database" if api_key else "env",
    }


# ── POST /exchange/keys ───────────────────────────────────────────────────────

@router.post("/exchange/keys", dependencies=[Depends(require_db)])
async def save_exchange_keys(payload: KeysPayload) -> dict:
    """Save API key + secret to PostgreSQL — persists across container restarts."""
    now = time.time()
    async with AsyncSessionLocal() as session:
        for k, v in [
            ("binance_api_key",    payload.api_key.strip()),
            ("binance_api_secret", payload.api_secret.strip()),
        ]:
            row = await session.get(AppSettings, k)
            if row:
                row.value      = v
                row.updated_at = now
            else:
                session.add(AppSettings(key=k, value=v, updated_at=now))
        await session.commit()

    return {"saved": True, "message": "API credentials saved to database"}


# ── POST /account/test-connection ─────────────────────────────────────────────

@router.post("/account/test-connection")
async def test_connection(payload: TestConnectionPayload) -> dict:
    """Test Binance credentials by calling GET /api/v3/account."""
    data, status = await binance_signed_get(
        "/api/v3/account",
        params={},
        api_key=payload.api_key.strip(),
        api_secret=payload.api_secret.strip(),
    )

    if status != 200:
        msg = data.get("msg", f"Binance returned status {status}")
        return {"success": False, "message": msg}

    balances      = data.get("balances", [])
    usdt_free     = next((float(b["free"]) for b in balances if b["asset"] == "USDT"), 0.0)
    non_zero      = [b for b in balances if float(b["free"]) + float(b["locked"]) > 0]

    return {
        "success":           True,
        "message":           "Koneksi berhasil! Credentials valid.",
        "account_type":      data.get("accountType", "SPOT"),
        "can_trade":         data.get("canTrade", False),
        "spot_balance_usdt": round(usdt_free, 2),
        "total_assets":      len(non_zero),
    }


# ── GET /wallet/spot ──────────────────────────────────────────────────────────

@router.get("/wallet/spot", dependencies=[Depends(require_db)])
async def get_spot_wallet() -> dict:
    """
    Real spot holdings from Binance using credentials stored in DB.
    Returns all assets with non-zero balance, sorted by total descending.
    """
    api_key, api_secret = await get_binance_credentials()

    if not api_key or not api_secret:
        return {
            "error":    "no_credentials",
            "message":  "API key belum diset. Tambahkan di Settings → Binance API.",
            "balances": [],
        }

    data, status = await binance_signed_get(
        "/api/v3/account",
        params={},
        api_key=api_key,
        api_secret=api_secret,
    )

    if status != 200:
        return {
            "error":    "binance_error",
            "message":  data.get("msg", f"Binance error {status}"),
            "balances": [],
        }

    balances = [
        {
            "asset":  b["asset"],
            "free":   round(float(b["free"]),   8),
            "locked": round(float(b["locked"]), 8),
            "total":  round(float(b["free"]) + float(b["locked"]), 8),
        }
        for b in data.get("balances", [])
        if float(b["free"]) + float(b["locked"]) > 0
    ]

    return {
        "account_type": data.get("accountType", "SPOT"),
        "can_trade":    data.get("canTrade", False),
        "balances":     sorted(balances, key=lambda x: -x["total"]),
        "total_assets": len(balances),
        "fetched_at":   time.time(),
    }
