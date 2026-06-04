"""SQLAlchemy model for paper trades (scanner signal tracking)."""

from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PaperTrade(Base):
    """
    Tracks every scanner recommendation as a simulated trade.

    Lifecycle: open → tp (take-profit hit) | sl (stop-loss hit)
    """

    __tablename__ = "paper_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Trade identity
    symbol:     Mapped[str]   = mapped_column(String(20),  nullable=False, index=True)
    direction:  Mapped[str]   = mapped_column(String(5),   nullable=False)          # LONG / SHORT
    style:      Mapped[str]   = mapped_column(String(20),  nullable=False, index=True)  # scalping / daytrading / swing / position

    # Price levels (from scanner)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    stop_loss:   Mapped[float] = mapped_column(Float, nullable=False)
    take_profit: Mapped[float] = mapped_column(Float, nullable=False)
    risk_reward: Mapped[str]   = mapped_column(String(15), nullable=False)          # "1:2.3"
    probability: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Metadata from scanner
    alert_type:   Mapped[str]  = mapped_column(String(20),  nullable=False, default="")
    sl_method:    Mapped[str]  = mapped_column(String(120), nullable=False, default="")
    tp_method:    Mapped[str]  = mapped_column(String(120), nullable=False, default="")
    signals_json: Mapped[str]  = mapped_column(Text,        nullable=False, default="[]")  # JSON array
    entry_type:   Mapped[str]  = mapped_column(String(20),  nullable=False, default="market")

    # Lifecycle timestamps (unix seconds as float)
    entry_at:  Mapped[float]        = mapped_column(Float, nullable=False, index=True)
    closed_at: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Outcome
    status:      Mapped[str]         = mapped_column(String(10), nullable=False, default="open", index=True)  # open | tp | sl
    close_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_pct:     Mapped[float | None] = mapped_column(Float, nullable=True)   # % gain/loss at close
