"""Challenger-only technical and on-chain feature contracts for SPOT."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from statistics import mean, pstdev
from typing import Mapping


def _safe_return(values: list[float], periods: int) -> float | None:
    if len(values) <= periods or values[-periods - 1] <= 0:
        return None
    return round((values[-1] / values[-periods - 1] - 1.0) * 100, 4)


def _atr_pct(data: object, period: int = 14) -> float | None:
    highs = list(getattr(data, "highs", []))
    lows = list(getattr(data, "lows", []))
    closes = list(getattr(data, "closes", []))
    if len(closes) < 2 or closes[-1] <= 0:
        return None
    trs = [
        max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        for i in range(1, len(closes))
    ]
    return round(mean(trs[-period:]) / closes[-1] * 100, 4)


def extract_technical_features(tf_data: Mapping[str, object]) -> dict[str, float | None]:
    """Create continuous model features without changing production point scores."""
    out: dict[str, float | None] = {}
    for timeframe, data in tf_data.items():
        closes = list(getattr(data, "closes", []))
        volumes = list(getattr(data, "volumes", []))
        if not closes:
            continue
        returns = [
            (closes[i] / closes[i - 1] - 1.0) * 100
            for i in range(1, len(closes)) if closes[i - 1] > 0
        ]
        movement = sum(abs(closes[i] - closes[i - 1]) for i in range(1, len(closes)))
        efficiency = abs(closes[-1] - closes[0]) / movement if movement > 0 else 0.0
        vol_tail = volumes[-20:]
        vol_std = pstdev(vol_tail) if len(vol_tail) > 1 else 0.0
        volume_z = (volumes[-1] - mean(vol_tail)) / vol_std if vol_tail and vol_std > 0 else 0.0
        ema21 = float(getattr(data, "ema21", 0.0) or 0.0)
        ema9 = float(getattr(data, "ema9", 0.0) or 0.0)
        prefix = f"{timeframe}."
        out.update({
            prefix + "return_5_pct": _safe_return(closes, 5),
            prefix + "return_20_pct": _safe_return(closes, 20),
            prefix + "realized_vol_20": round(pstdev(returns[-20:]), 4) if len(returns) > 1 else None,
            prefix + "atr_pct": _atr_pct(data),
            prefix + "trend_efficiency": round(efficiency, 4),
            prefix + "ema_gap_pct": round((ema9 - ema21) / ema21 * 100, 4) if ema21 > 0 else None,
            prefix + "volume_zscore": round(volume_z, 4),
            prefix + "rsi": round(float(getattr(data, "rsi", 50.0)), 4),
            prefix + "bb_width": round(float(getattr(data, "bb_width", 0.0)), 6),
            prefix + "taker_ratio": round(float(getattr(data, "taker_ratio", 0.5)), 4),
        })
    return out


@dataclass(frozen=True)
class OnchainSnapshot:
    """Provider-neutral, freshness-aware contract; missing is never zero/bearish."""

    symbol: str
    observed_at: float
    provider: str
    metrics: Mapping[str, float | None]
    coverage: float

    def as_features(self, now: float | None = None, max_age_seconds: int = 3600) -> dict:
        now = now or time.time()
        age = max(0.0, now - self.observed_at)
        fresh = age <= max_age_seconds
        return {
            "provider": self.provider,
            "observed_at": self.observed_at,
            "age_seconds": round(age, 1),
            "coverage": round(max(0.0, min(1.0, self.coverage)), 4),
            "fresh": fresh,
            "metrics": dict(self.metrics) if fresh else {},
        }
