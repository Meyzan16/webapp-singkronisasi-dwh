"""
Weekly Backtest Result — stores per-week simulation outcomes from big_mover_log data.

Schema holds:
  - 3-week rolling window context (train N-2, test N-1, report N)
  - Per-horizon win rates
  - Threshold optimization result from training week
  - Forward-walk test WR for validation
"""

from sqlalchemy import Column, Float, Integer, String
from app.database import Base


class WeeklyBacktestResult(Base):
    __tablename__ = "weekly_backtest_result"

    id           = Column(Integer, primary_key=True, autoincrement=True)

    # ISO week label — "2026-W25"
    week_label   = Column(String(20), nullable=False, index=True, unique=True)
    week_start   = Column(Float, nullable=False)   # epoch Sunday 00:00 UTC
    market       = Column(String(20), default="futures")
    computed_at  = Column(Float, nullable=False)

    # Counts
    n_entries    = Column(Integer, default=0)    # rows in big_mover_log for week N
    n_with_pnl   = Column(Integer, default=0)    # rows with at least 1h PnL filled

    # Win rates per horizon (price > scan_price)
    wr_1h        = Column(Float)
    wr_4h        = Column(Float)
    wr_24h       = Column(Float)
    wr_7d        = Column(Float)

    # Average PnL at 24h (raw move, no TP/SL clamp)
    avg_pnl_24h  = Column(Float)

    # B4.2 forward-walk — best threshold found on train week (N-2)
    train_week   = Column(String(20))    # which week was used as training data
    best_thresh  = Column(Float)         # score threshold that max'd WR on train week
    train_wr     = Column(Float)         # WR achieved on train week at best_thresh

    # Test week (N-1) validation
    test_week    = Column(String(20))
    test_wr      = Column(Float)         # WR on test week applying train best_thresh
    test_n       = Column(Integer)       # sample size in test week

    # Forward prediction for week N (current)
    forward_pred = Column(Float)         # expected WR this week (test_wr as prior)
    forward_note = Column(String(200))   # human-readable summary
