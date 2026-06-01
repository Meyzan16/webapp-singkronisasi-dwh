from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.schemas.kline import KlineRead
from app.services.data_pipeline.kline_repository import KlineRepository

router = APIRouter(prefix="/klines", tags=["klines"])


@router.get("/{pair}/{timeframe}", response_model=list[KlineRead])
async def get_klines(
    pair: str,
    timeframe: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=5000)] = 500,
) -> list[KlineRead]:
    """Return klines for a pair and timeframe."""

    repository = KlineRepository(session)
    klines = await repository.list_by_pair_timeframe(pair=pair, timeframe=timeframe, limit=limit)
    return [KlineRead.model_validate(kline) for kline in klines]
