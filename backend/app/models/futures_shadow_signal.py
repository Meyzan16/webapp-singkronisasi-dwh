"""Sinyal futures SHADOW — hipotesis entry alternatif yang dicatat, tak pernah ditradingkan.

PLAN-OKT-2026 P1 (1 Okt 2026): 1.321 kandidat agen tunggal tak punya edge di
irisan fitur mana pun. Tabel ini merekam hipotesis lain secara paralel supaya
bisa dinilai pada data maju, TERPISAH dari `futures_decision_events` — tabel itu
dibaca pelatihan model, walkforward, learning loader dan UI, dan baris riset tak
boleh mencemarinya.
"""

from sqlalchemy import Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FuturesShadowSignal(Base):
    """Satu sinyal hipotesis + label maju (horizon & simulasi bracket SL/TP)."""

    __tablename__ = "futures_shadow_signals"
    __table_args__ = (
        UniqueConstraint("signal_key", name="uq_futures_shadow_key"),
        Index("ix_fut_shadow_hyp", "hypothesis", "scan_ts"),
        Index("ix_fut_shadow_due", "outcome_status", "scan_ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_key: Mapped[str] = mapped_column(String(96), nullable=False)
    hypothesis: Mapped[str] = mapped_column(String(40), nullable=False)
    scan_ts: Mapped[float] = mapped_column(Float, nullable=False)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    price_at_scan: Mapped[float] = mapped_column(Float, nullable=False)
    sl_price: Mapped[float] = mapped_column(Float, nullable=False)
    tp_price: Mapped[float] = mapped_column(Float, nullable=False)
    cost_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.3)
    features_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    pnl_1h_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_4h_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_24h_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Simulasi bracket 24 jam: tp | sl | open (tak satu pun tersentuh → tutup di 24j)
    bracket_exit: Mapped[str | None] = mapped_column(String(10), nullable=True)
    bracket_r: Mapped[float | None] = mapped_column(Float, nullable=True)       # hasil dalam R, sudah net biaya
    bracket_hold_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    outcome_status: Mapped[str] = mapped_column(String(12), nullable=False, default="pending")
    outcome_updated_at: Mapped[float | None] = mapped_column(Float, nullable=True)
