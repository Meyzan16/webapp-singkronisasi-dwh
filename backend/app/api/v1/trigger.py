"""
API endpoints for T4 (Trigger) signal detection.
"""

from typing import Annotated
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.schemas.trend import (
    TriggerAnalysisResponseSchema,
    BatchTriggerAnalysisResponseSchema,
    TriggerSignalSchema,
)
from app.services.data_pipeline.kline_repository import KlineRepository
from app.services.ta_engine.trigger_analyzer import detect_trigger

router = APIRouter(prefix="/trigger", tags=["trigger"])

# 5 pairs and 5 timeframes as per architecture
PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "SUIUSDT"]
TIMEFRAMES = ["1w", "1d", "4h", "1h", "15m"]


def _trigger_signal_to_schema(trigger) -> TriggerSignalSchema:
    """Convert TriggerSignal dataclass to Pydantic schema."""
    return TriggerSignalSchema(
        direction=trigger.direction,
        confidence=trigger.confidence,
        candlestick_pattern=trigger.candlestick_pattern,
        stochastic_signal=trigger.stochastic_signal,
        has_volume_spike=trigger.has_volume_spike,
        taker_buy_pressure=trigger.taker_buy_pressure,
        reasoning=trigger.reasoning,
    )


@router.get("/{pair}/{timeframe}", response_model=TriggerAnalysisResponseSchema)
async def analyze_pair_timeframe(
    pair: str,
    timeframe: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=50, le=1000)] = 100,
) -> TriggerAnalysisResponseSchema:
    """Detect entry trigger signals for a specific pair and timeframe."""

    if pair not in PAIRS:
        raise ValueError(f"Pair {pair} not supported. Supported: {PAIRS}")
    if timeframe not in TIMEFRAMES:
        raise ValueError(f"Timeframe {timeframe} not supported. Supported: {TIMEFRAMES}")

    repository = KlineRepository(session)
    klines = await repository.list_by_pair_timeframe(pair=pair, timeframe=timeframe, limit=limit)

    if len(klines) < 20:
        raise ValueError(f"Insufficient data for {pair} {timeframe}. Need at least 20 candles, got {len(klines)}")

    # Extract OHLCV data
    opens = [float(k.open) for k in klines]
    highs = [float(k.high) for k in klines]
    lows = [float(k.low) for k in klines]
    closes = [float(k.close) for k in klines]
    volumes = [float(k.volume) for k in klines]
    taker_buy_volumes = [float(k.taker_buy_volume) if k.taker_buy_volume else 0 for k in klines]

    # Detect trigger signal
    trigger = detect_trigger(opens, highs, lows, closes, volumes, taker_buy_volumes)

    trigger_schema = _trigger_signal_to_schema(trigger) if trigger else None

    return TriggerAnalysisResponseSchema(
        pair=pair,
        timeframe=timeframe,
        trigger=trigger_schema,
        timestamp=datetime.utcnow().isoformat(),
    )


@router.get("/all", response_model=BatchTriggerAnalysisResponseSchema)
async def analyze_all_pairs(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BatchTriggerAnalysisResponseSchema:
    """Detect triggers for all 5 pairs across all 5 timeframes."""

    analysis_results = []
    repository = KlineRepository(session)

    for pair in PAIRS:
        for timeframe in TIMEFRAMES:
            try:
                klines = await repository.list_by_pair_timeframe(pair=pair, timeframe=timeframe, limit=100)

                if len(klines) < 20:
                    continue  # Skip if insufficient data

                # Extract OHLCV data
                opens = [float(k.open) for k in klines]
                highs = [float(k.high) for k in klines]
                lows = [float(k.low) for k in klines]
                closes = [float(k.close) for k in klines]
                volumes = [float(k.volume) for k in klines]
                taker_buy_volumes = [float(k.taker_buy_volume) if k.taker_buy_volume else 0 for k in klines]

                # Detect trigger signal
                trigger = detect_trigger(opens, highs, lows, closes, volumes, taker_buy_volumes)

                trigger_schema = _trigger_signal_to_schema(trigger) if trigger else None

                analysis_results.append(
                    TriggerAnalysisResponseSchema(
                        pair=pair,
                        timeframe=timeframe,
                        trigger=trigger_schema,
                        timestamp=datetime.utcnow().isoformat(),
                    )
                )
            except Exception:
                # Log but continue with other pairs
                continue

    return BatchTriggerAnalysisResponseSchema(
        analysis=analysis_results,
        timestamp=datetime.utcnow().isoformat(),
    )
