"""SQLAlchemy model for paper-wallet cash transactions (deposit / withdraw / reset).

Phase 9: an auditable ledger of CASH events per wallet style. Trade P&L is NOT
duplicated here — it stays on paper_trades.pnl_dollar. The balance-sheet statement
endpoint merges these cash rows with closed-trade P&L into one chronological view.
"""

from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class BalanceTransaction(Base):
    """One cash movement on a paper wallet. Append-only."""

    __tablename__ = "balance_transactions"

    id:            Mapped[int]   = mapped_column(Integer, primary_key=True, autoincrement=True)
    style:         Mapped[str]   = mapped_column(String(30), nullable=False, index=True)  # wallet key, e.g. "futures"
    kind:          Mapped[str]   = mapped_column(String(12), nullable=False)              # deposit | withdraw | reset
    amount:        Mapped[float] = mapped_column(Float, nullable=False)                   # signed: +deposit, -withdraw
    balance_after: Mapped[float] = mapped_column(Float, nullable=False)                   # wallet balance after this event
    note:          Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at:    Mapped[float] = mapped_column(Float, nullable=False, default=0.0, index=True)
