"""SQLAlchemy model for system health events (API up/down, agent start/stop)."""

from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class HealthEvent(Base):
    """
    Persistent log of system health events.

    Populated by app.services.health_logger whenever:
      - Binance Spot/Futures API status changes (up ↔ down, ban)
      - An agent starts or stops
      - Database connection changes

    Survives backend restarts — historical data always available.
    """

    __tablename__ = "health_events"

    id:          Mapped[int]   = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts:          Mapped[float] = mapped_column(Float, nullable=False, index=True)
    category:    Mapped[str]   = mapped_column(String(30), nullable=False, index=True)
    level:       Mapped[str]   = mapped_column(String(10), nullable=False, index=True)
    message:     Mapped[str]   = mapped_column(Text, nullable=False)
    detail_json: Mapped[str]   = mapped_column(Text, nullable=False, default="{}")
