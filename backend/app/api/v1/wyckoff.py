"""
API endpoints for T0 (Wyckoff) phase analysis.
"""

from typing import Annotated
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.schemas.trend import WyckoffAnalysisResponseSchema, BatchWyckoffAnalysisResponseSchema, WyckoffStateSchema
from app.services.data_pipeline.kline_repository import KlineRepository
from app.services.ta_engine import detect_wyckoff_phase
from app.services.ta_engine.trend_analyzer import analyze_trend

router = APIRouter(prefix="/wyckoff", tags=["wyckoff"])

# 5 pairs and 5 timeframes as per architecture
PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "SUIUSDT"]
TIMEFRAMES = ["1w", "1d", "4h", "1h", "15m"]


def _wyckoff_state_to_schema(wyckoff_state) -> WyckoffStateSchema:
    """Convert WyckoffState dataclass to Pydantic schema."""
    return WyckoffStateSchema(
        phase=wyckoff_state.phase.value,
        strength=wyckoff_state.strength,
        description=wyckoff_state.description,
        support_level=wyckoff_state.support_level,
        resistance_level=wyckoff_state.resistance_level,
        volume_trend=wyckoff_state.volume_trend,
    )


@router.get("/{pair}/{timeframe}", response_model=WyckoffAnalysisResponseSchema)
async def analyze_pair_timeframe(
    pair: str,
    timeframe: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=50, le=1000)] = 500,
) -> WyckoffAnalysisResponseSchema:
    """Analyze Wyckoff phase for a specific pair and timeframe."""

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

    # Get trend direction from T1 analyzer first
    trend_state = analyze_trend(opens, highs, lows, closes)
    trend_direction = trend_state.direction if trend_state else "sideways"

    # Analyze Wyckoff phase
    wyckoff_state = detect_wyckoff_phase(highs, lows, closes, volumes, trend_direction)

    if wyckoff_state is None:
        raise ValueError(f"Could not analyze Wyckoff phase for {pair} {timeframe}")

    return WyckoffAnalysisResponseSchema(
        pair=pair,
        timeframe=timeframe,
        wyckoff=_wyckoff_state_to_schema(wyckoff_state),
        timestamp=datetime.utcnow().isoformat(),
    )


@router.get("/all", response_model=BatchWyckoffAnalysisResponseSchema)
async def analyze_all_pairs(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BatchWyckoffAnalysisResponseSchema:
    """Analyze Wyckoff phases for all 5 pairs across all 5 timeframes."""

    analysis_results = []
    repository = KlineRepository(session)

    for pair in PAIRS:
        for timeframe in TIMEFRAMES:
            try:
                klines = await repository.list_by_pair_timeframe(pair=pair, timeframe=timeframe, limit=500)

                if len(klines) < 20:
                    continue  # Skip if insufficient data

                # Extract OHLCV data
                opens = [float(k.open) for k in klines]
                highs = [float(k.high) for k in klines]
                lows = [float(k.low) for k in klines]
                closes = [float(k.close) for k in klines]
                volumes = [float(k.volume) for k in klines]

                # Get trend direction from T1 analyzer
                trend_state = analyze_trend(opens, highs, lows, closes)
                trend_direction = trend_state.direction if trend_state else "sideways"

                # Analyze Wyckoff phase
                wyckoff_state = detect_wyckoff_phase(highs, lows, closes, volumes, trend_direction)

                if wyckoff_state:
                    analysis_results.append(
                        WyckoffAnalysisResponseSchema(
                            pair=pair,
                            timeframe=timeframe,
                            wyckoff=_wyckoff_state_to_schema(wyckoff_state),
                            timestamp=datetime.utcnow().isoformat(),
                        )
                    )
            except Exception:
                # Log but continue with other pairs
                continue

    return BatchWyckoffAnalysisResponseSchema(
        analysis=analysis_results,
        timestamp=datetime.utcnow().isoformat(),
    )
