"""RejectionLog — P7.1 (PLAN_v2).

Records signals that were scored below threshold during a scan cycle.
Used by the Rejections tab to explain "why coin X didn't get opened".
"""

from sqlalchemy import Float, Integer, String, Text, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RejectionLog(Base):
    __tablename__ = "rejection_log"

    __table_args__ = (
        Index("ix_rl_symbol_ts", "symbol", "rejected_at"),
        Index("ix_rl_agent",     "agent",  "rejected_at"),
    )

    id:            Mapped[int]   = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol:        Mapped[str]   = mapped_column(String(20), nullable=False)
    agent:         Mapped[str]   = mapped_column(String(30), nullable=False)
    direction:     Mapped[str]   = mapped_column(String(10), nullable=False, default="LONG")
    score:         Mapped[float] = mapped_column(Float, nullable=False)
    threshold:     Mapped[float] = mapped_column(Float, nullable=False)
    regime:        Mapped[str]   = mapped_column(String(20), nullable=False, default="all")
    reject_reason: Mapped[str]   = mapped_column(String(60), nullable=False, default="score_below_threshold")
    # JSON array of up to 3 weakest signals + their weights
    weak_signals:  Mapped[str]   = mapped_column(Text, nullable=True)
    rejected_at:   Mapped[float] = mapped_column(Float, nullable=False, index=True)
