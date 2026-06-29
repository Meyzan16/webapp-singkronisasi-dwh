"""SignalWeightHistory — snapshot of agent_signal_weights per updater run.

PLAN_v2 P0.4: enables trajectory visualization ("pertumbuhan berpikir agentic").
Each row = one signal × one agent × one regime at one point in time.
"""

from sqlalchemy import Float, Integer, String, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SignalWeightHistory(Base):
    __tablename__ = "signal_weight_history"

    __table_args__ = (
        Index("ix_swh_lookup", "agent", "signal_key", "regime", "snapshot_at"),
        Index("ix_swh_snapshot", "snapshot_at"),
    )

    id:               Mapped[int]   = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent:            Mapped[str]   = mapped_column(String(30), nullable=False)
    signal_key:       Mapped[str]   = mapped_column(String(80), nullable=False)
    regime:           Mapped[str]   = mapped_column(String(20), nullable=False, default="all")
    weight:           Mapped[float] = mapped_column(Float, nullable=False)
    win_count:        Mapped[int]   = mapped_column(Integer, nullable=False, default=0)
    total_count:      Mapped[int]   = mapped_column(Integer, nullable=False, default=0)
    win_rate:         Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    avg_pnl_pct:      Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    sample_count_raw: Mapped[int]   = mapped_column(Integer, nullable=False, default=0)
    snapshot_at:      Mapped[float] = mapped_column(Float, nullable=False, index=True)
