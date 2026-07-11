"""Versioned SPOT challenger/champion model registry."""

from sqlalchemy import Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SpotModelVersion(Base):
    __tablename__ = "spot_model_versions"
    __table_args__ = (UniqueConstraint("version", name="uq_spot_model_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="shadow")
    feature_schema_version: Mapped[str] = mapped_column(String(30), nullable=False)
    model_json: Mapped[str] = mapped_column(Text, nullable=False)
    metrics_json: Mapped[str] = mapped_column(Text, nullable=False)
    parent_version: Mapped[str | None] = mapped_column(String(60), nullable=True)
    trained_at: Mapped[float] = mapped_column(Float, nullable=False)
    promoted_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    retired_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    rollback_reason: Mapped[str | None] = mapped_column(String(160), nullable=True)
