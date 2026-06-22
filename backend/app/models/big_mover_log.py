"""
big_mover_log — Phase 1 T4 ground-truth data untuk validasi Big Mover Lane (Phase 2).

Tiap cycle scanner mencatat big mover yang dilihat: status (missed/opened/manual),
max_score, threshold, scan_price. Background job mengisi would_be_pnl_*h_later
dari mark price horizon multi-langkah (B1.1: 1h, 4h, 24h, 7d).

Hypothetical win rate = berapa % entries would_be_pnl positif setelah TP wajar
(assumed 1:3 R:R dengan slippage 0.3%).
"""

from sqlalchemy import Float, Integer, String, Text, BigInteger
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class BigMoverLog(Base):
    """One row per big mover seen per scan cycle."""

    __tablename__ = "big_mover_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Identity
    ts:        Mapped[float] = mapped_column(Float,      nullable=False, index=True)  # unix scan ts
    symbol:    Mapped[str]   = mapped_column(String(20), nullable=False, index=True)
    market:    Mapped[str]   = mapped_column(String(10), nullable=False, default="futures")  # futures | spot
    direction: Mapped[str]   = mapped_column(String(5),  nullable=False, default="LONG")     # LONG / SHORT

    # Scoring snapshot
    change_24h:     Mapped[float] = mapped_column(Float, nullable=False)
    scan_price:     Mapped[float] = mapped_column(Float, nullable=False)
    max_score:      Mapped[float] = mapped_column(Float, nullable=False, default=0.0)   # best across agents
    threshold:      Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    scoring_gap:    Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    funding_rate:   Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status:         Mapped[str]   = mapped_column(String(12), nullable=False, default="missed", index=True)
    # missed | opened | manual | rejected_perpetual | rejected_funding | rejected_regime

    reason:         Mapped[str]   = mapped_column(Text, nullable=False, default="")

    # Forward-looking outcome (filled by backfill)
    pnl_1h_pct:     Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_4h_pct:     Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_24h_pct:    Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_7d_pct:     Mapped[float | None] = mapped_column(Float, nullable=True)

    # Hypothetical SL/TP outcome (assumed 1:3 RR, 0.3% slippage)
    would_be_status:   Mapped[str | None]   = mapped_column(String(10), nullable=True)  # tp | sl | open
    would_be_pnl_pct:  Mapped[float | None] = mapped_column(Float, nullable=True)
    last_backfill_at:  Mapped[float | None] = mapped_column(Float, nullable=True)
