"""Backtest engine - simulate strategy on historical data."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.services.signal_generator.pipeline import SignalPipeline
from app.services.data_pipeline.kline_repository import KlineRepository


@dataclass
class TradeResult:
    """Single trade result."""

    entry_time: datetime
    entry_price: float
    exit_time: Optional[datetime]
    exit_price: Optional[float]
    stop_loss: float
    take_profit: float
    signal_type: str  # 'buy' or 'sell'
    confidence: float
    profit_loss: float
    profit_loss_pct: float
    is_winner: bool


@dataclass
class BacktestMetrics:
    """Aggregated backtest metrics."""

    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    profit_factor: float
    max_drawdown: float
    total_return_pct: float
    sharpe_ratio: float
    equity_curve: list[float] = field(default_factory=list)


class BacktestEngine:
    """Run backtest on historical data."""

    def __init__(
        self,
        pair: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        kline_repo: KlineRepository,
        signal_pipeline: SignalPipeline,
    ):
        self.pair = pair
        self.timeframe = timeframe
        self.start_date = start_date
        self.end_date = end_date
        self.kline_repo = kline_repo
        self.signal_pipeline = signal_pipeline
        self.trades: list[TradeResult] = []
        self.equity_curve: list[float] = [100.0]  # Start with 100 units

    async def run(self) -> BacktestMetrics:
        """Run backtest and return metrics."""
        # Fetch historical klines for date range
        klines = await self.kline_repo.get_klines(
            self.pair,
            self.timeframe,
            start_date=self.start_date,
            end_date=self.end_date,
        )

        if not klines:
            return self._calculate_metrics()

        pending_trade: Optional[dict] = None

        for i, kline in enumerate(klines):
            kline_time = datetime.fromisoformat(kline.open_time.isoformat())

            # Skip if not in range
            if kline_time < self.start_date or kline_time > self.end_date:
                continue

            # Close pending trade if hit SL or TP
            if pending_trade:
                trade_closed = self._check_exit(pending_trade, kline)
                if trade_closed:
                    pending_trade = None

            # Generate signal on this candle
            signal = await self.signal_pipeline.run(
                pair=self.pair,
                timeframe=self.timeframe,
                klines=klines[:i+1],  # Up to current candle
            )

            # Enter trade if signal and no pending trade
            if signal and not pending_trade and signal.signal in ("buy", "sell"):
                pending_trade = {
                    "entry_time": kline_time,
                    "entry_price": float(kline.close),
                    "stop_loss": signal.stop_loss,
                    "take_profit": signal.take_profit,
                    "signal_type": signal.signal,
                    "confidence": signal.confidence,
                }

        # Close any remaining open trade at end of data
        if pending_trade and klines:
            last_kline = klines[-1]
            trade = TradeResult(
                entry_time=pending_trade["entry_time"],
                entry_price=pending_trade["entry_price"],
                exit_time=datetime.fromisoformat(last_kline.open_time.isoformat()),
                exit_price=float(last_kline.close),
                stop_loss=pending_trade["stop_loss"],
                take_profit=pending_trade["take_profit"],
                signal_type=pending_trade["signal_type"],
                confidence=pending_trade["confidence"],
                profit_loss=float(last_kline.close) - pending_trade["entry_price"],
                profit_loss_pct=(
                    (float(last_kline.close) - pending_trade["entry_price"])
                    / pending_trade["entry_price"]
                    * 100
                ),
                is_winner=(float(last_kline.close) - pending_trade["entry_price"]) > 0,
            )
            self.trades.append(trade)
            self._update_equity(trade)

        return self._calculate_metrics()

    def _check_exit(self, pending_trade: dict, kline) -> bool:
        """Check if trade hits SL or TP. Close if yes."""
        high = float(kline.high)
        low = float(kline.low)
        entry = pending_trade["entry_price"]
        sl = pending_trade["stop_loss"]
        tp = pending_trade["take_profit"]

        # Buy signal: TP on high, SL on low
        if pending_trade["signal_type"] == "buy":
            if high >= tp:
                exit_price = tp
                is_winner = True
            elif low <= sl:
                exit_price = sl
                is_winner = False
            else:
                return False
        else:  # Sell signal
            if low <= tp:
                exit_price = tp
                is_winner = True
            elif high >= sl:
                exit_price = sl
                is_winner = False
            else:
                return False

        # Record trade
        trade = TradeResult(
            entry_time=pending_trade["entry_time"],
            entry_price=entry,
            exit_time=datetime.now(),
            exit_price=exit_price,
            stop_loss=sl,
            take_profit=tp,
            signal_type=pending_trade["signal_type"],
            confidence=pending_trade["confidence"],
            profit_loss=exit_price - entry if pending_trade["signal_type"] == "buy" else entry - exit_price,
            profit_loss_pct=(
                (exit_price - entry) / entry * 100
                if pending_trade["signal_type"] == "buy"
                else (entry - exit_price) / entry * 100
            ),
            is_winner=is_winner,
        )

        self.trades.append(trade)
        self._update_equity(trade)
        return True

    def _update_equity(self, trade: TradeResult) -> None:
        """Update equity curve after trade."""
        current_equity = self.equity_curve[-1]
        pct_change = trade.profit_loss_pct / 100
        new_equity = current_equity * (1 + pct_change)
        self.equity_curve.append(new_equity)

    def _calculate_metrics(self) -> BacktestMetrics:
        """Calculate aggregate metrics."""
        if not self.trades:
            return BacktestMetrics(
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate=0,
                profit_factor=0,
                max_drawdown=0,
                total_return_pct=0,
                sharpe_ratio=0,
                equity_curve=self.equity_curve,
            )

        total = len(self.trades)
        winners = sum(1 for t in self.trades if t.is_winner)
        losers = total - winners

        # Profit factor: gross profit / gross loss
        gross_profit = sum(t.profit_loss for t in self.trades if t.is_winner)
        gross_loss = abs(sum(t.profit_loss for t in self.trades if not t.is_winner))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

        # Max drawdown
        max_dd = self._calculate_max_drawdown()

        # Total return
        total_return = (self.equity_curve[-1] - 100) / 100 * 100 if self.equity_curve else 0

        # Sharpe ratio (simplified: daily returns stddev)
        sharpe = self._calculate_sharpe_ratio()

        return BacktestMetrics(
            total_trades=total,
            winning_trades=winners,
            losing_trades=losers,
            win_rate=winners / total if total > 0 else 0,
            profit_factor=profit_factor,
            max_drawdown=max_dd,
            total_return_pct=total_return,
            sharpe_ratio=sharpe,
            equity_curve=self.equity_curve,
        )

    def _calculate_max_drawdown(self) -> float:
        """Calculate maximum drawdown from equity curve."""
        if not self.equity_curve or len(self.equity_curve) < 2:
            return 0

        max_equity = self.equity_curve[0]
        max_dd = 0

        for equity in self.equity_curve[1:]:
            if equity > max_equity:
                max_equity = equity
            dd = (max_equity - equity) / max_equity if max_equity > 0 else 0
            if dd > max_dd:
                max_dd = dd

        return max_dd

    def _calculate_sharpe_ratio(self) -> float:
        """Calculate Sharpe ratio from equity curve."""
        if not self.equity_curve or len(self.equity_curve) < 2:
            return 0

        # Calculate daily returns
        returns = []
        for i in range(1, len(self.equity_curve)):
            ret = (self.equity_curve[i] - self.equity_curve[i - 1]) / self.equity_curve[i - 1]
            returns.append(ret)

        if not returns:
            return 0

        # Calculate mean and stddev
        mean_ret = sum(returns) / len(returns)
        variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
        stddev = variance ** 0.5

        # Sharpe = (mean return - risk free rate) / stddev
        # Assuming 0% risk-free rate
        sharpe = mean_ret / stddev if stddev > 0 else 0
        return sharpe
