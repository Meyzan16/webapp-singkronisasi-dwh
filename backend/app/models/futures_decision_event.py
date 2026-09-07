"""Immutable point-in-time decisions dari pipeline FUTURES (scanner + auto_trader).

PLAN_ADAPTIVE_LEARNING_FUTURES_10X F1 — mirror SpotDecisionEvent (engine SPOT tidak
disentuh) dengan kolom khas futures: agent, direction, lane, leverage,
cost_floor_pct, dan horizon outcome pendek (30m/1h/4h/24h — posisi futures hidup
jam-an, bukan hari-an).
"""

from sqlalchemy import Boolean, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FuturesDecisionEvent(Base):
    """Satu keputusan kandidat futures ber-versi, termasuk skip/veto + alasannya."""

    __tablename__ = "futures_decision_events"
    __table_args__ = (
        UniqueConstraint("decision_key", name="uq_futures_decision_key"),
        Index("ix_fut_decision_scan", "scan_ts", "symbol"),
        Index("ix_fut_decision_outcome_due", "outcome_status", "scan_ts"),
        Index("ix_fut_decision_agent", "agent", "scan_ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    decision_key: Mapped[str] = mapped_column(String(96), nullable=False)
    scan_ts: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    agent: Mapped[str] = mapped_column(String(40), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    lane: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(60), nullable=False)
    opened: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    auto_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    adaptive_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    weight_applied: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    estimated_win_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_at_scan: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    leverage: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_floor_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    regime: Mapped[str | None] = mapped_column(String(40), nullable=True)
    learning_status: Mapped[str] = mapped_column(String(20), nullable=False, default="warming")
    model_version: Mapped[str] = mapped_column(String(40), nullable=False, default="futures_rules_adaptive_v1")
    feature_schema_version: Mapped[str] = mapped_column(String(30), nullable=False, default="futures_features_v1")
    feature_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)

    # Label forward (counterfactual, harga) — diisi outcome tracker.
    outcome_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    pnl_30m_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_1h_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_4h_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_24h_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Label realized (trade nyata NET true-cost) — diisi backfill dari paper_trades.
    realized_pnl_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_pnl_dollar: Mapped[float | None] = mapped_column(Float, nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String(60), nullable=True)
    closed_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    outcome_updated_at: Mapped[float | None] = mapped_column(Float, nullable=True)

    # ── Fase 5: jejak keputusan UKURAN ──────────────────────────────────────
    # Sampai kini ledger menyimpan KENAPA sebuah kandidat dipilih, tapi tidak
    # SEBERAPA BESAR ia dimasuki. Padahal itulah yang ingin diukur owner: dua
    # kandidat berskor sama tapi berukuran beda punya hasil dolar yang sama
    # sekali berbeda, dan tanpa kolom ini mesin belajar tak bisa melihatnya —
    # ia hanya melihat persen, yang justru menyamarkan perbedaannya.
    risk_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    notional_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    margin_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    tp1_net_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    sl_net_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
