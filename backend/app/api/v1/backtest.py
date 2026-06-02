"""Backtest API endpoints."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.database import get_db
from app.services.data_pipeline.kline_repository import KlineRepository
from app.services.signal_generator.pipeline import SignalPipeline
from app.services.backtest_engine.backtest import BacktestEngine, BacktestMetrics

router = APIRouter(prefix="/backtest", tags=["backtest"])


class BacktestRequest(BaseModel):
    """Request to run a backtest."""

    pair: str
    timeframe: str
    start_date: str  # ISO format: 2024-01-01
    end_date: str  # ISO format: 2024-12-31


class BacktestResponseSchema(BaseModel):
    """Backtest results response."""

    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    profit_factor: float
    max_drawdown: float
    total_return_pct: float
    sharpe_ratio: float


@router.post("/{pair}/{timeframe}")
async def run_backtest(pair: str, timeframe: str, request: BacktestRequest) -> BacktestResponseSchema:
    """Run backtest for a pair/timeframe with date range."""
    try:
        # Parse dates
        start_date = datetime.fromisoformat(request.start_date)
        end_date = datetime.fromisoformat(request.end_date)

        # Validate dates
        if start_date >= end_date:
            raise HTTPException(status_code=400, detail="start_date must be before end_date")

        if (end_date - start_date).days < 7:
            raise HTTPException(status_code=400, detail="Date range must be at least 7 days")

        # Get DB session
        async with get_db() as session:
            # Initialize components
            kline_repo = KlineRepository(session)
            signal_pipeline = SignalPipeline(kline_repo)

            # Create and run backtest
            engine = BacktestEngine(
                pair=pair,
                timeframe=timeframe,
                start_date=start_date,
                end_date=end_date,
                kline_repo=kline_repo,
                signal_pipeline=signal_pipeline,
            )

            metrics = await engine.run()

            # Convert to response
            return BacktestResponseSchema(
                total_trades=metrics.total_trades,
                winning_trades=metrics.winning_trades,
                losing_trades=metrics.losing_trades,
                win_rate=metrics.win_rate,
                profit_factor=metrics.profit_factor,
                max_drawdown=metrics.max_drawdown,
                total_return_pct=metrics.total_return_pct,
                sharpe_ratio=metrics.sharpe_ratio,
            )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid date format: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Backtest failed: {str(e)}")


@router.get("/{pair}/{timeframe}/info")
async def get_backtest_info(pair: str, timeframe: str) -> dict:
    """Get backtest info for a pair/timeframe."""
    return {
        "pair": pair,
        "timeframe": timeframe,
        "description": "Run backtest to test strategy on historical data",
        "min_date_range": "7 days",
        "metrics": [
            "total_trades",
            "win_rate",
            "profit_factor",
            "max_drawdown",
            "total_return_pct",
            "sharpe_ratio",
        ],
    }
