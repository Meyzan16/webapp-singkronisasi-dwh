"""
Pydantic schemas for T1 (Trend) analysis output.
"""

from pydantic import BaseModel
from typing import Optional


class TrendlineSchema(BaseModel):
    """Schema for trendline validation output."""

    is_valid: bool
    is_uptrend: bool
    num_touches: int
    slope: float
    is_broken: bool
    breakout_price: float


class TrendStateSchema(BaseModel):
    """Schema for trend state analysis."""

    direction: str  # 'uptrend', 'downtrend', or 'sideways'
    ema_13: float
    ema_21: float
    ema_cross: bool
    ema_distance_pct: float
    trendline: Optional[TrendlineSchema]
    confidence: float
    reasoning: str


class TrendAnalysisResponseSchema(BaseModel):
    """API response for trend analysis."""

    pair: str
    timeframe: str
    trend: TrendStateSchema
    timestamp: str


class BatchTrendAnalysisResponseSchema(BaseModel):
    """API response for batch trend analysis across multiple pairs/timeframes."""

    analysis: list[TrendAnalysisResponseSchema]
    timestamp: str
