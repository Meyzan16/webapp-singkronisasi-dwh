"""AppSettings — key-value store for runtime configuration (e.g. Binance API keys).

Stored in PostgreSQL so credentials persist across container restarts.
Use instead of .env for secrets that need to be editable via the UI.
"""

import time

from sqlalchemy import Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AppSettings(Base):
    __tablename__ = "app_settings"

    key:        Mapped[str]   = mapped_column(String(100), primary_key=True)
    value:      Mapped[str]   = mapped_column(Text, nullable=True)
    updated_at: Mapped[float] = mapped_column(Float, default=lambda: time.time(), nullable=False)
