"""
API endpoints for signal generation (T0-T4 pipeline).
"""

from typing import Annotated
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.schemas.trend import SignalResponseSchema, BatchSignalResponseSchema, SignalCardSchema
from app.services.data_pipeline.kline_repository import KlineRepository
from app.services.signal_generator.pipeline import SignalPipeline
from app.services.signal_generator.signal_card import format_signal_to_json

router = APIRouter(prefix="/signals", tags=["signals"])

# 5 pairs and 5 timeframes as per architecture
PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "SUIUSDT"]
TIMEFRAMES = ["1w", "1d", "4h", "1h", "15m"]


def _signal_card_to_schema(signal) -> SignalCardSchema:
    """Convert SignalCard dataclass to Pydantic schema."""
    return SignalCardSchema(
        pair=signal.pair,
        timeframe=signal.timeframe,
        direction=signal.direction,
        entry=round(signal.entry, 2),
        stop_loss=round(signal.stop_loss, 2),
        take_profit=round(signal.take_profit, 2),
        risk_reward=signal.risk_reward,
        confidence=round(signal.confidence, 0),
        position_size_pct=round(signal.position_size_pct, 2),
        reasoning={
            "phase": signal.phase,
            "T0_wyckoff": signal.t0_reasoning,
            "T1_trend": signal.t1_reasoning,
            "T2_support_resistance": signal.t2_reasoning,
            "T3_pattern": signal.t3_reasoning,
            "T4_trigger": signal.t4_reasoning,
        },
        timestamp=signal.timestamp,
    )


@router.get("/{pair}/{timeframe}", response_model=SignalResponseSchema)
async def generate_signal(
    pair: str,
    timeframe: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=50, le=1000)] = 100,
) -> SignalResponseSchema:
    """Generate complete trading signal for a pair/timeframe."""

    if pair not in PAIRS:
        raise ValueError(f"Pair {pair} not supported. Supported: {PAIRS}")
    if timeframe not in TIMEFRAMES:
        raise ValueError(f"Timeframe {timeframe} not supported. Supported: {TIMEFRAMES}")

    repository = KlineRepository(session)
    klines = await repository.list_by_pair_timeframe(pair=pair, timeframe=timeframe, limit=limit)

    if len(klines) < 30:
        return SignalResponseSchema(
            signal=None,
            skip_reason=f"Insufficient data for {pair} {timeframe}. Need at least 30 candles, got {len(klines)}",
            timestamp=datetime.utcnow().isoformat(),
        )

    # Extract OHLCV data
    opens = [float(k.open) for k in klines]
    highs = [float(k.high) for k in klines]
    lows = [float(k.low) for k in klines]
    closes = [float(k.close) for k in klines]
    volumes = [float(k.volume) for k in klines]
    taker_buy_volumes = [float(k.taker_buy_volume) if k.taker_buy_volume else 0 for k in klines]

    # Run signal pipeline
    pipeline = SignalPipeline(pair=pair, timeframe=timeframe)
    signal = pipeline.run(opens, highs, lows, closes, volumes, taker_buy_volumes)

    if signal is None:
        return SignalResponseSchema(
            signal=None,
            skip_reason=pipeline.skip_reason,
            timestamp=datetime.utcnow().isoformat(),
        )

    return SignalResponseSchema(
        signal=_signal_card_to_schema(signal),
        skip_reason=None,
        timestamp=datetime.utcnow().isoformat(),
    )


@router.get("/all", response_model=BatchSignalResponseSchema)
async def generate_all_signals(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BatchSignalResponseSchema:
    """Generate signals for all 5 pairs across all 5 timeframes."""

    signals = []
    repository = KlineRepository(session)

    for pair in PAIRS:
        for timeframe in TIMEFRAMES:
            try:
                klines = await repository.list_by_pair_timeframe(pair=pair, timeframe=timeframe, limit=100)

                if len(klines) < 30:
                    continue  # Skip if insufficient data

                # Extract OHLCV data
                opens = [float(k.open) for k in klines]
                highs = [float(k.high) for k in klines]
                lows = [float(k.low) for k in klines]
                closes = [float(k.close) for k in klines]
                volumes = [float(k.volume) for k in klines]
                taker_buy_volumes = [float(k.taker_buy_volume) if k.taker_buy_volume else 0 for k in klines]

                # Run signal pipeline
                pipeline = SignalPipeline(pair=pair, timeframe=timeframe)
                signal = pipeline.run(opens, highs, lows, closes, volumes, taker_buy_volumes)

                if signal:
                    signals.append(_signal_card_to_schema(signal))

            except Exception:
                # Log but continue with other pairs
                continue

    return BatchSignalResponseSchema(
        signals=signals,
        timestamp=datetime.utcnow().isoformat(),
    )
