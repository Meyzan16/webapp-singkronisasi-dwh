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


class WyckoffStateSchema(BaseModel):
    """Schema for Wyckoff phase state."""

    phase: str  # "Accumulation", "Mark Up", "Distribution", "Mark Down"
    strength: float  # 0-100
    description: str
    support_level: float
    resistance_level: float
    volume_trend: str  # "increasing", "decreasing", "normal", "unknown"


class WyckoffAnalysisResponseSchema(BaseModel):
    """API response for Wyckoff phase analysis."""

    pair: str
    timeframe: str
    wyckoff: WyckoffStateSchema
    timestamp: str


class BatchWyckoffAnalysisResponseSchema(BaseModel):
    """API response for batch Wyckoff analysis."""

    analysis: list[WyckoffAnalysisResponseSchema]
    timestamp: str


class SRZoneSchema(BaseModel):
    """Schema for support/resistance zone."""

    zone_type: str  # "Support" or "Resistance"
    price_low: float
    price_high: float
    midpoint: float
    num_bounces: int
    strength: float  # 0-100
    is_fibonacci: bool


class SRAnalysisSchema(BaseModel):
    """Schema for complete S/R analysis."""

    support_zones: list[SRZoneSchema]
    resistance_zones: list[SRZoneSchema]
    strongest_support: Optional[SRZoneSchema]
    strongest_resistance: Optional[SRZoneSchema]
    current_price: float


class SRAnalysisResponseSchema(BaseModel):
    """API response for S/R analysis."""

    pair: str
    timeframe: str
    analysis: SRAnalysisSchema
    timestamp: str


class BatchSRAnalysisResponseSchema(BaseModel):
    """API response for batch S/R analysis."""

    analysis: list[SRAnalysisResponseSchema]
    timestamp: str
