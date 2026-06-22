"""SQLAlchemy model for futures agent signal performance weights."""

from sqlalchemy import Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AgentSignalWeight(Base):
    """
    Tracks win-rate and adaptive weight for each signal type per agent.

    Populated by agents/futures/weight_updater.py after each scan cycle.
    Used by agents to bias scoring toward historically profitable signals.
    """

    __tablename__ = "agent_signal_weights"

    __table_args__ = (
        UniqueConstraint("agent", "signal_key", "regime", name="uq_agent_signal_regime"),
    )

    id:               Mapped[int]   = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent:            Mapped[str]   = mapped_column(String(30),  nullable=False, index=True)
    signal_key:       Mapped[str]   = mapped_column(String(80),  nullable=False)
    weight:           Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    win_count:        Mapped[int]   = mapped_column(Integer, nullable=False, default=0)
    total_count:      Mapped[int]   = mapped_column(Integer, nullable=False, default=0)
    win_rate:         Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    avg_pnl_pct:      Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    sample_count_raw: Mapped[int]   = mapped_column(Integer, nullable=False, default=0)
    regime:           Mapped[str]   = mapped_column(String(20),  nullable=False, default="all")
    updated_at:       Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
