"""
API endpoints for T3 (Pattern) detection.
"""

from typing import Annotated
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.schemas.trend import (
    PatternAnalysisResponseSchema,
    BatchPatternAnalysisResponseSchema,
    PatternAnalysisSchema,
    PatternDetectionSchema,
    MarketStructureSchema,
)
from app.services.data_pipeline.kline_repository import KlineRepository
from app.services.ta_engine.pattern_detector import detect_patterns, analyze_market_structure, validate_pattern_with_trend
from app.services.ta_engine.trend_analyzer import analyze_trend

router = APIRouter(prefix="/pattern", tags=["pattern"])

# 5 pairs and 5 timeframes as per architecture
PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "SUIUSDT"]
TIMEFRAMES = ["1w", "1d", "4h", "1h", "15m"]


def _pattern_to_schema(pattern) -> PatternDetectionSchema:
    """Convert PatternDetection dataclass to Pydantic schema."""
    return PatternDetectionSchema(
        pattern_type=pattern.pattern_type.value,
        formation_strength=pattern.formation_strength,
        potential_breakout=pattern.potential_breakout,
        confirmation_needed=pattern.confirmation_needed,
    )


def _structure_to_schema(structure) -> MarketStructureSchema:
    """Convert MarketStructureAnalysis dataclass to Pydantic schema."""
    return MarketStructureSchema(
        structure=structure.structure.value,
        recent_high=structure.recent_high,
        recent_low=structure.recent_low,
        hh_count=structure.hh_count,
        ll_count=structure.ll_count,
        has_choch=structure.has_choch,
        has_bos=structure.has_bos,
        breakout_level=structure.breakout_level,
        bias_strength=structure.bias_strength,
    )


def _analysis_to_schema(pattern, structure, is_valid, reason) -> PatternAnalysisSchema:
    """Convert pattern analysis to Pydantic schema."""
    pattern_schema = _pattern_to_schema(pattern) if pattern else None
    structure_schema = _structure_to_schema(structure)

    return PatternAnalysisSchema(
        pattern=pattern_schema,
        structure=structure_schema,
        is_valid=is_valid,
        validation_reason=reason,
    )


@router.get("/{pair}/{timeframe}", response_model=PatternAnalysisResponseSchema)
async def analyze_pair_timeframe(
    pair: str,
    timeframe: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=50, le=1000)] = 100,
) -> PatternAnalysisResponseSchema:
    """Analyze chart patterns and market structure for a specific pair and timeframe."""

    if pair not in PAIRS:
        raise ValueError(f"Pair {pair} not supported. Supported: {PAIRS}")
    if timeframe not in TIMEFRAMES:
        raise ValueError(f"Timeframe {timeframe} not supported. Supported: {TIMEFRAMES}")

    repository = KlineRepository(session)
    klines = await repository.list_by_pair_timeframe(pair=pair, timeframe=timeframe, limit=limit)

    if len(klines) < 40:
        raise ValueError(f"Insufficient data for {pair} {timeframe}. Need at least 40 candles, got {len(klines)}")

    # Extract OHLCV data
    opens = [float(k.open) for k in klines]
    highs = [float(k.high) for k in klines]
    lows = [float(k.low) for k in klines]
    closes = [float(k.close) for k in klines]

    # Get trend direction from T1 analyzer
    trend_state = analyze_trend(opens, highs, lows, closes)
    trend_direction = trend_state.direction if trend_state else "sideways"

    # Detect patterns and market structure
    pattern = detect_patterns(highs, lows)
    structure = analyze_market_structure(highs, lows)

    # Validate pattern against trend
    is_valid, reason = validate_pattern_with_trend(pattern, structure, trend_direction)

    return PatternAnalysisResponseSchema(
        pair=pair,
        timeframe=timeframe,
        analysis=_analysis_to_schema(pattern, structure, is_valid, reason),
        timestamp=datetime.utcnow().isoformat(),
    )


@router.get("/all", response_model=BatchPatternAnalysisResponseSchema)
async def analyze_all_pairs(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BatchPatternAnalysisResponseSchema:
    """Analyze patterns for all 5 pairs across all 5 timeframes."""

    analysis_results = []
    repository = KlineRepository(session)

    for pair in PAIRS:
        for timeframe in TIMEFRAMES:
            try:
                klines = await repository.list_by_pair_timeframe(pair=pair, timeframe=timeframe, limit=100)

                if len(klines) < 40:
                    continue  # Skip if insufficient data

                # Extract OHLCV data
                opens = [float(k.open) for k in klines]
                highs = [float(k.high) for k in klines]
                lows = [float(k.low) for k in klines]
                closes = [float(k.close) for k in klines]

                # Get trend direction from T1 analyzer
                trend_state = analyze_trend(opens, highs, lows, closes)
                trend_direction = trend_state.direction if trend_state else "sideways"

                # Detect patterns and market structure
                pattern = detect_patterns(highs, lows)
                structure = analyze_market_structure(highs, lows)

                # Validate pattern against trend
                is_valid, reason = validate_pattern_with_trend(pattern, structure, trend_direction)

                analysis_results.append(
                    PatternAnalysisResponseSchema(
                        pair=pair,
                        timeframe=timeframe,
                        analysis=_analysis_to_schema(pattern, structure, is_valid, reason),
                        timestamp=datetime.utcnow().isoformat(),
                    )
                )
            except Exception:
                # Log but continue with other pairs
                continue

    return BatchPatternAnalysisResponseSchema(
        analysis=analysis_results,
        timestamp=datetime.utcnow().isoformat(),
    )
