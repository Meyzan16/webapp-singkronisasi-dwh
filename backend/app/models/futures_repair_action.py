"""Repair ledger FUTURES — audit trail setiap perbaikan sinyal (PLAN_SIGNAL_REPAIR_LIVE R1).

Aturan terkunci plan §3: aksi perbaikan MATERIAL tanpa baris di tabel ini = bug.
Baris ini yang membuat tab Progress bermakna: deteksi → aksi → terverifikasi
membaik / tidak berubah / di-revert.
"""

from sqlalchemy import Boolean, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FuturesRepairAction(Base):
    __tablename__ = "futures_repair_actions"
    __table_args__ = (
        Index("ix_repair_target", "target_key", "applied_at"),
        Index("ix_repair_status", "status", "detected_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    detected_at: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    # predictive_agent | weekly_review | learning_ban | lane_pause | suggestion | verifier
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    # signal key / lane / simbol yang diperbaiki
    target_key: Mapped[str] = mapped_column(String(120), nullable=False)
    agent: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    # hit_rate_low | hit_rate_high | weight_ban | weight_unban | lane_consec_sl |
    # lane_wr_low | suggestion_applied | reverted_by_verifier | ...
    issue: Mapped[str] = mapped_column(String(40), nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    # weight_down | weight_up | ban | unban | pause | config_change | suggest_only
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    applied_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    # metrik pembanding (hit-rate 0..1) — verifier mengisi after + status akhir
    before_metric: Mapped[float | None] = mapped_column(Float, nullable=True)
    after_metric: Mapped[float | None] = mapped_column(Float, nullable=True)
    # applied | suggested | verified_improved | verified_no_change | reverted | dismissed
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="applied", index=True)
    verified_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    revert_of: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
