"""REST endpoints for futures position management."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_session
from app.schemas.position import (
    PositionCreate,
    PositionClose,
    PositionListResponse,
    PositionResponse,
    AccountBalance,
)
from app.services.trading.futures_client import FuturesClient
from app.services.trading.position_manager import PositionManager

router = APIRouter(tags=["positions"])

_client: FuturesClient | None = None
_manager: PositionManager | None = None


def _get_manager() -> PositionManager:
    """Lazy-init futures client and position manager."""
    global _client, _manager
    if _manager is None:
        settings = get_settings()
        if not settings.binance_api_key:
            raise HTTPException(status_code=400, detail="Binance API key not configured")
        _client = FuturesClient(settings)
        _manager = PositionManager(_client)
    return _manager


@router.post("/positions", response_model=PositionResponse)
async def open_position(
    req: PositionCreate,
    session: AsyncSession = Depends(get_session),
) -> PositionResponse:
    """Open a new futures position."""

    manager = _get_manager()
    try:
        return await manager.open_position(session, req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to open position: {e}")


@router.post("/positions/{position_id}/close", response_model=PositionResponse)
async def close_position(
    position_id: int,
    req: PositionClose,
    session: AsyncSession = Depends(get_session),
) -> PositionResponse:
    """Close an open position."""

    manager = _get_manager()
    try:
        return await manager.close_position(session, position_id, reason=req.reason)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to close position: {e}")


@router.get("/positions", response_model=PositionListResponse)
async def list_positions(
    status: str = "open",
    session: AsyncSession = Depends(get_session),
) -> PositionListResponse:
    """List positions. Filter by status: open, all."""

    manager = _get_manager()
    if status == "open":
        positions = await manager.get_open_positions(session)
    else:
        positions = await manager.get_all_positions(session)
    return PositionListResponse(positions=positions, total=len(positions))


@router.post("/positions/refresh", response_model=PositionListResponse)
async def refresh_prices(
    session: AsyncSession = Depends(get_session),
) -> PositionListResponse:
    """Refresh current prices and PnL for all open positions."""

    manager = _get_manager()
    positions = await manager.update_prices(session)
    return PositionListResponse(positions=positions, total=len(positions))


@router.get("/account/balance", response_model=AccountBalance)
async def get_balance() -> AccountBalance:
    """Get futures account balance."""

    settings = get_settings()
    if not settings.binance_api_key:
        raise HTTPException(status_code=400, detail="Binance API key not configured")

    client = FuturesClient(settings)
    try:
        balance = await client.get_balance()
        usdt = balance.get("USDT", {})
        from decimal import Decimal
        return AccountBalance(
            total_balance=Decimal(str(usdt.get("total", 0))),
            available_balance=Decimal(str(usdt.get("free", 0))),
            unrealized_pnl=Decimal(str(balance.get("info", {}).get("totalUnrealizedProfit", 0))),
            margin_used=Decimal(str(usdt.get("used", 0))),
        )
    finally:
        await client.close()
