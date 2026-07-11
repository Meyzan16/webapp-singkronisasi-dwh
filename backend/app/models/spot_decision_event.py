"""Immutable point-in-time decisions emitted by the SPOT scanner."""

from sqlalchemy import Boolean, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SpotDecisionEvent(Base):
    """One versioned candidate decision, including recommendations and vetoes."""

    __tablename__ = "spot_decision_events"
    __table_args__ = (
        UniqueConstraint("decision_key", name="uq_spot_decision_key"),
        Index("ix_spot_decision_scan", "scan_ts", "symbol"),
        Index("ix_spot_decision_outcome_due", "outcome_status", "scan_ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    decision_key: Mapped[str] = mapped_column(String(96), nullable=False)
    scan_ts: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    alert_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entry_mode: Mapped[str] = mapped_column(String(40), nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(60), nullable=False)
    auto_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    opened: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    raw_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    adaptive_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    weight_applied: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    estimated_win_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    regime: Mapped[str | None] = mapped_column(String(40), nullable=True)
    learning_status: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    model_version: Mapped[str] = mapped_column(String(40), nullable=False, default="spot_rules_v1")
    feature_schema_version: Mapped[str] = mapped_column(String(20), nullable=False, default="spot_features_v1")
    feature_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)

    # Forward/counterfactual labels are filled by the outcome worker later.
    outcome_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    realized_pnl_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_pnl_dollar: Mapped[float | None] = mapped_column(Float, nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String(60), nullable=True)
    closed_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_1h_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_4h_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_24h_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_3d_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_7d_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    mae_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    mfe_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    outcome_updated_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    outcome_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    outcome_error: Mapped[str | None] = mapped_column(String(120), nullable=True)
    review_json: Mapped[str | None] = mapped_column(Text, nullable=True)
