"""AgentConfig — DB-backed override for critical agent runtime constants (PLAN_v5 Group C).

Only the "critical" subset is stored here — score thresholds, volume gates, quotas,
and risk caps that agents check as top-level gates. Fine-grained per-signal scoring
points stay hardcoded (see PLAN_v5.md "Keputusan Terkunci"). Agents read via
agents/shared/config_reader.py (TTL-cached, falls back to the hardcoded default
when a row is missing or the DB is unavailable) — so an operator can retune the bot
from the Settings UI without a redeploy.
"""

import time

from sqlalchemy import Float, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AgentConfig(Base):
    __tablename__ = "agent_config"
    __table_args__ = (
        UniqueConstraint("agent_group", "key", name="uq_agent_config_group_key"),
    )

    id:           Mapped[int]   = mapped_column(primary_key=True, autoincrement=True)
    agent_group:  Mapped[str]   = mapped_column(String(20), nullable=False)   # 'spot' | 'futures' | 'learning'
    key:          Mapped[str]   = mapped_column(String(60), nullable=False)
    value_num:    Mapped[float] = mapped_column(Float, nullable=False)
    default_num:  Mapped[float] = mapped_column(Float, nullable=False)
    description:  Mapped[str]   = mapped_column(Text, nullable=False)
    category:     Mapped[str]   = mapped_column(String(20), nullable=False)   # 'threshold' | 'volume' | 'quota' | 'risk' | 'timing'
    updated_at:   Mapped[float] = mapped_column(Float, default=lambda: time.time(), nullable=False)
    updated_by:   Mapped[str]   = mapped_column(String(40), default="system", nullable=False)
