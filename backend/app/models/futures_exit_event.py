"""Ledger keputusan KELUAR — bahan belajar Adaptive Engine untuk MONITOR.

M7 (2 Agu 2026): tabel ini semula futures-only (`futures_exit_events`) dan kini
menampung SPOT juga, dibedakan kolom `market`. Satu tabel, bukan dua: sisi SPOT
di proyek ini berulang kali dibangun sebagai salinan terpisah lalu menyimpang
diam-diam (katalog Formulas dan tab Predictive dua-duanya sempat futures-only).
Satu skema membuat penyimpangan itu mustahil terjadi tanpa terlihat.

Latar (audit 1 Agu 2026): keputusan MASUK sudah punya ledger lengkap
(`futures_decision_events`) sehingga engine bisa belajar dari entry. Keputusan
KELUAR — yang justru menentukan hasil akhir — tidak punya apa pun: monitor hanya
menempel event ke `signals_json.events[]` yang dibatasi 30 entri di dalam JSON
per-trade, tak bisa di-query, tak bisa diagregasi, tak bisa dilatih.

Akibatnya pertanyaan paling penting tak terjawab: alasan close mana yang
menguntungkan? Kapan trailing terlalu cepat? Berapa jarak TP yang realistis per
lane/regime? Tabel ini menyediakan datanya, dinormalkan terhadap ATR supaya
antar-koin sebanding (koin ber-ATR 6% dan 1% tak bisa dibandingkan dalam %).
"""

from sqlalchemy import Boolean, Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FuturesExitEvent(Base):
    """Satu baris = satu penutupan posisi, SPOT maupun FUTURES.

    Nama kelasnya dipertahankan agar impor lama tak patah; `ExitEvent` adalah
    alias yang sebaiknya dipakai kode baru.
    """

    __tablename__ = "exit_events"
    __table_args__ = (
        Index("ix_fee_closed_at", "closed_at"),
        Index("ix_fee_reason", "close_reason", "closed_at"),
        Index("ix_fee_lane", "lane", "closed_at"),
        Index("ix_fee_market", "market", "closed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    #: Tautan ke posisi yang ditutup (paper_trades.id).
    #: "futures" | "spot". Default "futures" supaya 44 baris warisan — yang
    #: seluruhnya futures — tetap benar tanpa perlu ditulis ulang.
    market:   Mapped[str] = mapped_column(String(10), nullable=False, default="futures")

    trade_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    symbol:   Mapped[str] = mapped_column(String(30), nullable=False)
    agent:    Mapped[str] = mapped_column(String(40), nullable=False)
    lane:     Mapped[str] = mapped_column(String(30), nullable=False, default="")
    direction: Mapped[str] = mapped_column(String(5), nullable=False)
    regime:   Mapped[str | None] = mapped_column(String(20), nullable=True)

    #: Alasan penutupan (taksonomi monitor: tp2_hit, sl_hit, sl_plus, fail_fast, …).
    close_reason: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    status:       Mapped[str] = mapped_column(String(10), nullable=False)   # tp | sl

    entry_at:  Mapped[float] = mapped_column(Float, nullable=False)
    closed_at: Mapped[float] = mapped_column(Float, nullable=False)
    held_hours: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    #: Hasil (NET biaya bila tersedia).
    pnl_pct:    Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_dollar: Mapped[float | None] = mapped_column(Float, nullable=True)

    # ── Normalisasi terhadap volatilitas ─────────────────────────────────────
    # Inilah yang membuat data bisa dibandingkan lintas koin & jadi fitur model.
    atr_pct:        Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Gerak menguntungkan TERJAUH selama posisi hidup, dalam kelipatan ATR.
    mfe_atr:        Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Gerak MERUGIKAN terjauh (MAE), dalam kelipatan ATR — nilai positif.
    #: M4b: pasangan wajib dari MFE. Tanpa ini tak ada cara tahu berapa banyak
    #: jarak SL yang benar-benar terpakai, sehingga mempersempit SL akan jadi
    #: tebakan yang bisa mengubah pemenang jadi pecundang.
    mae_atr:        Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Jarak TP yang DIPASANG saat entry, dalam kelipatan ATR.
    tp_dist_atr:    Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Jarak SL yang dipasang saat entry, dalam kelipatan ATR.
    sl_dist_atr:    Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Hasil akhir dalam kelipatan ATR (bisa negatif).
    realized_atr:   Mapped[float | None] = mapped_column(Float, nullable=True)

    #: Apakah TP efektif sempat dikompresi oleh aturan ATR (PRIORITAS 1).
    tp_compressed:  Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Apakah trailing stop sempat aktif sebelum ditutup.
    trail_active:   Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # ── M8: bukti untuk dua parameter trailing ────────────────────────────────
    # Dinyatakan dalam SATUAN PARAMETERNYA SENDIRI (pecahan), bukan ATR — lihat
    # `agents/shared/trail_tracker.py`. MAE global tak bisa menggantikan ini
    # karena ia mencakup periode sebelum TP1, saat pertanyaan trailing belum ada.
    #: Titik TERENDAH sesudah TP1, dalam satuan TP1. 1.0 = tak pernah balik.
    #: Pembanding langsung untuk TRAIL_LOCK_AFTER_TP1_FRAC.
    retrace_after_tp1_frac: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Kemajuan TERJAUH TP1→TP2. 0 = tak pernah lewat TP1, 1.0 = sampai TP2.
    #: Pembanding langsung untuk TRAIL_ADVANCE_TP1_TP2_FRAC.
    ext_after_tp1_frac:     Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Keuntungan di TP1 (harga%) — penyebut yang membuat kedua pecahan di atas
    #: bisa dikonversi kembali jadi hasil P&L saat menghitung counterfactual.
    tp1_gain_pct:           Mapped[float | None] = mapped_column(Float, nullable=True)

    leverage: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score:    Mapped[float | None] = mapped_column(Float, nullable=True)


#: Nama yang seharusnya dipakai kode baru — tabelnya bukan lagi milik futures saja.
ExitEvent = FuturesExitEvent
