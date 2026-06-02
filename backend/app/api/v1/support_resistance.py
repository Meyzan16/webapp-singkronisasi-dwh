"""
API endpoints for T2 (Support/Resistance) area analysis.
"""

from typing import Annotated
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.schemas.trend import SRAnalysisResponseSchema, BatchSRAnalysisResponseSchema, SRAnalysisSchema, SRZoneSchema
from app.services.data_pipeline.kline_repository import KlineRepository
from app.services.ta_engine.support_resistance import detect_support_resistance, ZoneType

router = APIRouter(prefix="/support-resistance", tags=["support_resistance"])

# 5 pairs and 5 timeframes as per architecture
PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "SUIUSDT"]
TIMEFRAMES = ["1w", "1d", "4h", "1h", "15m"]


def _sr_analysis_to_schema(sr_analysis) -> SRAnalysisSchema:
    """Convert SRAnalysis dataclass to Pydantic schema."""

    support_zones = [
        SRZoneSchema(
            zone_type=zone.zone_type.value,
            price_low=zone.price_low,
            price_high=zone.price_high,
            midpoint=zone.midpoint,
            num_bounces=zone.num_bounces,
            strength=zone.strength,
            is_fibonacci=zone.is_fibonacci,
        )
        for zone in sr_analysis.support_zones
    ]

    resistance_zones = [
        SRZoneSchema(
            zone_type=zone.zone_type.value,
            price_low=zone.price_low,
            price_high=zone.price_high,
            midpoint=zone.midpoint,
            num_bounces=zone.num_bounces,
            strength=zone.strength,
            is_fibonacci=zone.is_fibonacci,
        )
        for zone in sr_analysis.resistance_zones
    ]

    strongest_support = None
    if sr_analysis.strongest_support:
        strongest_support = SRZoneSchema(
            zone_type=sr_analysis.strongest_support.zone_type.value,
            price_low=sr_analysis.strongest_support.price_low,
            price_high=sr_analysis.strongest_support.price_high,
            midpoint=sr_analysis.strongest_support.midpoint,
            num_bounces=sr_analysis.strongest_support.num_bounces,
            strength=sr_analysis.strongest_support.strength,
            is_fibonacci=sr_analysis.strongest_support.is_fibonacci,
        )

    strongest_resistance = None
    if sr_analysis.strongest_resistance:
        strongest_resistance = SRZoneSchema(
            zone_type=sr_analysis.strongest_resistance.zone_type.value,
            price_low=sr_analysis.strongest_resistance.price_low,
            price_high=sr_analysis.strongest_resistance.price_high,
            midpoint=sr_analysis.strongest_resistance.midpoint,
            num_bounces=sr_analysis.strongest_resistance.num_bounces,
            strength=sr_analysis.strongest_resistance.strength,
            is_fibonacci=sr_analysis.strongest_resistance.is_fibonacci,
        )

    return SRAnalysisSchema(
        support_zones=support_zones,
        resistance_zones=resistance_zones,
        strongest_support=strongest_support,
        strongest_resistance=strongest_resistance,
        current_price=sr_analysis.current_price,
    )


@router.get("/{pair}/{timeframe}", response_model=SRAnalysisResponseSchema)
async def analyze_pair_timeframe(
    pair: str,
    timeframe: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    lookback_days: Annotated[int, Query(ge=20, le=100)] = 30,
) -> SRAnalysisResponseSchema:
    """Analyze support/resistance zones for a specific pair and timeframe."""

    if pair not in PAIRS:
        raise ValueError(f"Pair {pair} not supported. Supported: {PAIRS}")
    if timeframe not in TIMEFRAMES:
        raise ValueError(f"Timeframe {timeframe} not supported. Supported: {TIMEFRAMES}")

    repository = KlineRepository(session)
    klines = await repository.list_by_pair_timeframe(pair=pair, timeframe=timeframe, limit=lookback_days + 20)

    if len(klines) < lookback_days:
        raise ValueError(f"Insufficient data for {pair} {timeframe}. Need at least {lookback_days} candles, got {len(klines)}")

    # Extract OHLCV data
    highs = [float(k.high) for k in klines]
    lows = [float(k.low) for k in klines]
    closes = [float(k.close) for k in klines]

    # Detect S/R zones
    sr_analysis = detect_support_resistance(highs, lows, closes, lookback_days=lookback_days)

    if sr_analysis is None:
        raise ValueError(f"Could not analyze S/R zones for {pair} {timeframe}")

    return SRAnalysisResponseSchema(
        pair=pair,
        timeframe=timeframe,
        analysis=_sr_analysis_to_schema(sr_analysis),
        timestamp=datetime.utcnow().isoformat(),
    )


@router.get("/all", response_model=BatchSRAnalysisResponseSchema)
async def analyze_all_pairs(
    session: Annotated[AsyncSession, Depends(get_session)],
    lookback_days: Annotated[int, Query(ge=20, le=100)] = 30,
) -> BatchSRAnalysisResponseSchema:
    """Analyze S/R zones for all 5 pairs across all 5 timeframes."""

    analysis_results = []
    repository = KlineRepository(session)

    for pair in PAIRS:
        for timeframe in TIMEFRAMES:
            try:
                klines = await repository.list_by_pair_timeframe(pair=pair, timeframe=timeframe, limit=lookback_days + 20)

                if len(klines) < lookback_days:
                    continue  # Skip if insufficient data

                # Extract OHLCV data
                highs = [float(k.high) for k in klines]
                lows = [float(k.low) for k in klines]
                closes = [float(k.close) for k in klines]

                # Detect S/R zones
                sr_analysis = detect_support_resistance(highs, lows, closes, lookback_days=lookback_days)

                if sr_analysis:
                    analysis_results.append(
                        SRAnalysisResponseSchema(
                            pair=pair,
                            timeframe=timeframe,
                            analysis=_sr_analysis_to_schema(sr_analysis),
                            timestamp=datetime.utcnow().isoformat(),
                        )
                    )
            except Exception:
                # Log but continue with other pairs
                continue

    return BatchSRAnalysisResponseSchema(
        analysis=analysis_results,
        timestamp=datetime.utcnow().isoformat(),
    )
