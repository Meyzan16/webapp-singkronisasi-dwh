"""
API endpoints for T1 (Trend) analysis.
"""

from typing import Annotated
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.schemas.trend import (
    TrendAnalysisResponseSchema,
    BatchTrendAnalysisResponseSchema,
    TrendStateSchema,
    TrendlineSchema,
)
from app.services.data_pipeline.kline_repository import KlineRepository
from app.services.ta_engine import analyze_trend

router = APIRouter(prefix="/trend", tags=["trend"])

# 5 pairs and 5 timeframes as per architecture
PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "SUIUSDT"]
TIMEFRAMES = ["1w", "1d", "4h", "1h", "15m"]


def _trend_state_to_schema(trend_state) -> TrendStateSchema:
    """Convert TrendState dataclass to Pydantic schema."""
    trendline_schema = None
    if trend_state.trendline:
        trendline_schema = TrendlineSchema(
            is_valid=trend_state.trendline.is_valid,
            is_uptrend=trend_state.trendline.is_uptrend,
            num_touches=trend_state.trendline.num_touches,
            slope=trend_state.trendline.slope,
            is_broken=trend_state.trendline.is_broken,
            breakout_price=trend_state.trendline.breakout_price,
        )

    return TrendStateSchema(
        direction=trend_state.direction,
        ema_13=trend_state.ema_13,
        ema_21=trend_state.ema_21,
        ema_cross=trend_state.ema_cross,
        ema_distance_pct=trend_state.ema_distance_pct,
        trendline=trendline_schema,
        confidence=trend_state.confidence,
        reasoning=trend_state.reasoning,
    )


@router.get("/{pair}/{timeframe}", response_model=TrendAnalysisResponseSchema)
async def analyze_pair_timeframe(
    pair: str,
    timeframe: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=50, le=1000)] = 500,
) -> TrendAnalysisResponseSchema:
    """Analyze trend for a specific pair and timeframe."""

    if pair not in PAIRS:
        raise ValueError(f"Pair {pair} not supported. Supported: {PAIRS}")
    if timeframe not in TIMEFRAMES:
        raise ValueError(f"Timeframe {timeframe} not supported. Supported: {TIMEFRAMES}")

    repository = KlineRepository(session)
    klines = await repository.list_by_pair_timeframe(pair=pair, timeframe=timeframe, limit=limit)

    if len(klines) < 21:
        raise ValueError(f"Insufficient data for {pair} {timeframe}. Need at least 21 candles, got {len(klines)}")

    # Extract OHLC data
    opens = [float(k.open) for k in klines]
    highs = [float(k.high) for k in klines]
    lows = [float(k.low) for k in klines]
    closes = [float(k.close) for k in klines]

    # Analyze trend
    trend_state = analyze_trend(opens, highs, lows, closes)

    if trend_state is None:
        raise ValueError(f"Could not analyze trend for {pair} {timeframe}")

    return TrendAnalysisResponseSchema(
        pair=pair,
        timeframe=timeframe,
        trend=_trend_state_to_schema(trend_state),
        timestamp=datetime.utcnow().isoformat(),
    )


@router.get("/all", response_model=BatchTrendAnalysisResponseSchema)
async def analyze_all_pairs(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BatchTrendAnalysisResponseSchema:
    """Analyze trends for all 5 pairs across all 5 timeframes."""

    analysis_results = []
    repository = KlineRepository(session)

    for pair in PAIRS:
        for timeframe in TIMEFRAMES:
            try:
                klines = await repository.list_by_pair_timeframe(pair=pair, timeframe=timeframe, limit=500)

                if len(klines) < 21:
                    continue  # Skip if insufficient data

                # Extract OHLC data
                opens = [float(k.open) for k in klines]
                highs = [float(k.high) for k in klines]
                lows = [float(k.low) for k in klines]
                closes = [float(k.close) for k in klines]

                # Analyze trend
                trend_state = analyze_trend(opens, highs, lows, closes)

                if trend_state:
                    analysis_results.append(
                        TrendAnalysisResponseSchema(
                            pair=pair,
                            timeframe=timeframe,
                            trend=_trend_state_to_schema(trend_state),
                            timestamp=datetime.utcnow().isoformat(),
                        )
                    )
            except Exception:
                # Log but continue with other pairs
                continue

    return BatchTrendAnalysisResponseSchema(
        analysis=analysis_results,
        timestamp=datetime.utcnow().isoformat(),
    )
