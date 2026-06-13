"""SQLAlchemy model for paper trading balance per strategy style."""

from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PaperBalance(Base):
    """
    Real-time paper trading balance per style.

    Updated every time a trade closes (P&L realized).
    Supports deposit to simulate real capital injection.
    Designed for swap to real trading: replace update logic with exchange API calls.
    """

    __tablename__ = "paper_balances"

    id:               Mapped[int]   = mapped_column(Integer, primary_key=True, autoincrement=True)
    style:            Mapped[str]   = mapped_column(String(30), nullable=False, unique=True, index=True)
    balance:          Mapped[float] = mapped_column(Float, nullable=False, default=1000.0)
    initial_balance:  Mapped[float] = mapped_column(Float, nullable=False, default=1000.0)
    deposited_total:  Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    withdrawn_total:  Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    realized_pnl:     Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    updated_at:       Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at:       Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    notes:            Mapped[str | None] = mapped_column(Text, nullable=True)
