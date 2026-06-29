"""PredictiveLog — PLAN_v3 P4 D4.1.

Records signal predictions at scan time so their accuracy can be measured later.
After 4h and 24h, a resolver job checks whether price moved in the predicted direction
and fills in the outcome fields. This data feeds the weight updater (D4.4).
"""

from sqlalchemy import Boolean, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PredictiveLog(Base):
    __tablename__ = "predictive_log"

    __table_args__ = (
        Index("ix_pl_symbol_ts",  "symbol", "scanned_at"),
        Index("ix_pl_agent",      "agent",  "scanned_at"),
        Index("ix_pl_unresolved", "resolved_at"),   # NULL = needs resolution
    )

    id:             Mapped[int]   = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol:         Mapped[str]   = mapped_column(String(20), nullable=False)
    agent:          Mapped[str]   = mapped_column(String(50), nullable=False)
    direction:      Mapped[str]   = mapped_column(String(10), nullable=False)
    regime:         Mapped[str]   = mapped_column(String(30), nullable=True)
    score:          Mapped[float] = mapped_column(Float, nullable=False)
    signals_json:   Mapped[str]   = mapped_column(Text, nullable=True)   # JSON list of signal labels
    price_at_scan:  Mapped[float] = mapped_column(Float, nullable=False)
    oi_change:      Mapped[float] = mapped_column(Float, nullable=True)
    funding_rate:   Mapped[float] = mapped_column(Float, nullable=True)
    change_24h:     Mapped[float] = mapped_column(Float, nullable=True)
    scanned_at:     Mapped[float] = mapped_column(Float, nullable=False, index=True)

    # Outcome fields — filled by the resolver job
    price_4h:         Mapped[float] = mapped_column(Float, nullable=True)
    price_24h:        Mapped[float] = mapped_column(Float, nullable=True)
    hit_4h:           Mapped[bool]  = mapped_column(Boolean, nullable=True)   # directed move ≥1.5% within 4h
    hit_24h:          Mapped[bool]  = mapped_column(Boolean, nullable=True)   # directed move ≥3.0% within 24h
    move_4h_pct:      Mapped[float] = mapped_column(Float, nullable=True)
    move_24h_pct:     Mapped[float] = mapped_column(Float, nullable=True)
    resolved_at:      Mapped[float] = mapped_column(Float, nullable=True)
