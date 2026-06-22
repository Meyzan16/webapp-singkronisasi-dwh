"""
force_open_log — Phase 1 B1.2: DB-persistent rate limit untuk force-open button.

Tanpa ini, rate limit client-side reset tiap reload tab → user bisa spam open.
Backend cek table ini sebelum trade endpoint accept body.
"""

from sqlalchemy import Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ForceOpenLog(Base):
    """One row per force-open attempt (accepted or rejected)."""

    __tablename__ = "force_open_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts:        Mapped[float] = mapped_column(Float,      nullable=False, index=True)
    session:   Mapped[str]   = mapped_column(String(64), nullable=False, index=True, default="default")
    market:    Mapped[str]   = mapped_column(String(10), nullable=False, default="futures")
    symbol:    Mapped[str]   = mapped_column(String(20), nullable=False)
    direction: Mapped[str]   = mapped_column(String(5),  nullable=False, default="LONG")
    accepted:  Mapped[bool]  = mapped_column(nullable=False, default=True)
