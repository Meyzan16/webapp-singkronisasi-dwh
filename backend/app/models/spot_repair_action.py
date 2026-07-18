"""Repair ledger SPOT — audit trail semua tindakan Adaptive Repair Agent SPOT.

Setiap aksi material (turunkan threshold, boost/trim bobot, backfill outcome,
cooldown simbol, retry promosi model) HARUS tercatat di sini.

Reversibility:
  - `before_json` / `after_json` menyimpan state sebelum & sesudah dalam bentuk
    JSON dinamis (kunci per action_type). Rollback = tulis kembali `before_json`.
  - `expires_at` mengontrol TTL untuk aksi bersifat sementara (loosen threshold,
    cooldown). Repair agent memeriksa expiry tiap cycle dan auto-reverse.
"""

import time

from sqlalchemy import Boolean, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SpotRepairAction(Base):
    __tablename__ = "spot_repair_actions"
    __table_args__ = (
        Index("ix_spot_repair_status_ts", "status", "detected_at"),
        Index("ix_spot_repair_type_ts", "action_type", "detected_at"),
        Index("ix_spot_repair_expires", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    detected_at: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    applied_at:  Mapped[float | None] = mapped_column(Float, nullable=True)
    expires_at:  Mapped[float | None] = mapped_column(Float, nullable=True)
    reversed_at: Mapped[float | None] = mapped_column(Float, nullable=True)

    # OUTCOME_BACKFILL | THRESHOLD_LOOSEN | THRESHOLD_TIGHTEN |
    # WEIGHT_BOOST | WEIGHT_TRIM | SYMBOL_COOLDOWN | PROMOTION_RETRY | TOGGLE
    action_type: Mapped[str] = mapped_column(String(30), nullable=False)

    # bebas per action_type: bisa signal_key, symbol, model_version, atau "*"
    target_key: Mapped[str] = mapped_column(String(120), nullable=False, default="*")

    # auto | manual | ttl_reverse
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="auto")

    # narasi Bahasa Indonesia singkat kenapa aksi ini dipicu
    reason: Mapped[str] = mapped_column(String(240), nullable=False, default="")

    # snapshot penuh state sebelum & sesudah — dipakai untuk rollback / audit
    before_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    after_json:  Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    # applied | pending | reversed | failed | dry_run | suggested |
    # verified_improved | verified_no_change | reverted
    #   NB: "reversed"  = auto-reverse via TTL / rollback manual
    #       "reverted"  = auto-revert oleh verifier setelah before/after diukur
    status: Mapped[str] = mapped_column(String(28), nullable=False, default="applied", index=True)

    # jumlah item terpengaruh (mis. OUTCOME_BACKFILL menutup 42 event)
    affected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ── Verifier fields (before/after outcome measurement) ────────────────
    # Nilai metrik ringkas SEBELUM aksi (diambil saat aksi diterapkan) — mis.
    # WR sinyal (0..1), completeness_pct (0..100), atau opened_24h.
    before_metric: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Nilai metrik SETELAH ≥24 jam (diisi verifier saat pass evaluasi).
    after_metric:  Mapped[float | None] = mapped_column(Float, nullable=True)
    # Kapan verifier menutup verifikasi (menetapkan verified_improved / no_change / reverted).
    verified_at:   Mapped[float | None] = mapped_column(Float, nullable=True)

    # true kalau aksi ini menyebabkan side-effect (mutate DB / config)
    is_material: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # id aksi lain yang di-revert oleh row ini
    revert_of: Mapped[int | None] = mapped_column(Integer, nullable=True)

    error: Mapped[str | None] = mapped_column(String(240), nullable=True)
    note:  Mapped[str | None] = mapped_column(String(240), nullable=True)

    updated_at: Mapped[float] = mapped_column(
        Float, nullable=False, default=lambda: time.time(),
    )
