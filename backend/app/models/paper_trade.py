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
    # PLAN_v6 Bug#1 fix: style holds "futures_agent_bigmover" (22 chars) — was
    # String(20) → StringDataRightTruncation on EVERY bigmover open, which aborted
    # the whole auto-open batch (zero futures positions opened). Widened to 30.
    # symbol widened too (some futures symbols exceed 20 chars).
    symbol:     Mapped[str]   = mapped_column(String(30),  nullable=False, index=True)
    direction:  Mapped[str]   = mapped_column(String(5),   nullable=False)          # LONG / SHORT
    style:      Mapped[str]   = mapped_column(String(30),  nullable=False, index=True)  # e.g. futures_agent_bigmover

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
    signals_json: Mapped[str]  = mapped_column(Text,        nullable=False, default="{}")  # JSON object
    entry_type:   Mapped[str]  = mapped_column(String(20),  nullable=False, default="market")

    # Lifecycle timestamps (unix seconds as float)
    entry_at:  Mapped[float]        = mapped_column(Float, nullable=False, index=True)
    closed_at: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Futures-specific (nullable so spot trades aren't affected)
    leverage:      Mapped[int | None]   = mapped_column(Integer,     nullable=True)
    margin_type:   Mapped[str | None]   = mapped_column(String(10),  nullable=True)
    regime:        Mapped[str | None]   = mapped_column(String(20),  nullable=True)   # market regime at entry
    trail_sl:      Mapped[float | None] = mapped_column(Float,       nullable=True)   # current trailed SL
    trail_active:  Mapped[bool | None]  = mapped_column(nullable=True, default=False) # trailing started

    # Position sizing (real-balance linked — stored at open time)
    position_size:    Mapped[float | None] = mapped_column(Float, nullable=True)   # notional $ value
    risk_dollar:      Mapped[float | None] = mapped_column(Float, nullable=True)   # actual $ at risk
    balance_snapshot: Mapped[float | None] = mapped_column(Float, nullable=True)   # balance when opened

    # Outcome
    status:      Mapped[str]         = mapped_column(String(10), nullable=False, default="open", index=True)  # open | tp | sl
    close_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_pct:     Mapped[float | None] = mapped_column(Float, nullable=True)   # % gain/loss at close
    pnl_dollar:  Mapped[float | None] = mapped_column(Float, nullable=True)   # $ gain/loss at close

    # PLAN_v2 P0.5 — per-trade monitor heartbeat & denormalized setup_type
    setup_type:        Mapped[str | None]   = mapped_column(String(20),  nullable=True, index=True)
    last_tick_at:      Mapped[float | None] = mapped_column(Float,       nullable=True)
    last_tick_price:   Mapped[float | None] = mapped_column(Float,       nullable=True)
    last_tick_pnl_pct: Mapped[float | None] = mapped_column(Float,       nullable=True)
    last_tick_event:   Mapped[str | None]   = mapped_column(String(40),  nullable=True)
