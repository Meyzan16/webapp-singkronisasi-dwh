"""Ledger penyalaan bertahap parameter KELUAR (M5).

Sampai M4, hasil belajar sisi keluar berhenti sebagai rekomendasi: angkanya bisa
ditulis ke config, tapi menyalakannya adalah satu saklar biner yang berlaku untuk
SEMUA lane sekaligus, tanpa jejak siapa menyalakan apa, kapan, dan apa hasilnya.

Keputusan MASUK sudah lama punya tahapan berdisiplin — `shadow → canary →
champion` lengkap dengan gate dan rollback (`futures_model_versions`). Sisi
KELUAR tidak punya padanannya. Tabel ini melengkapinya dengan bentuk yang sama,
tapi per **(lane × parameter)**, bukan per model:

    shadow   — angka tercatat, monitor MENGABAIKANNYA. Dipakai mengukur baseline.
    canary   — berlaku untuk SATU lane saja, hasilnya diawasi.
    active   — lolos gate; tetap diawasi dan masih bisa dibalik.
    rolled_back — gagal gate; angkanya dikembalikan ke nilai sebelumnya.

Yang membuat tahapan ini bermakna adalah `baseline_*`: metrik lane tersebut
DIREKAM SEBELUM angka baru berlaku. Tanpa itu, "membaik" hanyalah klaim yang tak
bisa diuji — pelajaran dari angka "116 terbukti membaik" yang ternyata menyesatkan.
"""

import time

from sqlalchemy import Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FuturesExitRollout(Base):
    __tablename__ = "futures_exit_rollouts"
    __table_args__ = (
        Index("ix_fer_lane_param", "lane", "param", "created_at"),
        Index("ix_fer_stage", "stage", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    #: Sasaran perubahan. `param` memakai nama yang sama dengan kunci config
    #: (mis. `tp_atr_mult`, `failfast_min_sl_gap`) supaya jejaknya bisa
    #: ditelusuri bolak-balik antara ledger dan config.
    lane:  Mapped[str] = mapped_column(String(30), nullable=False)
    param: Mapped[str] = mapped_column(String(40), nullable=False)

    stage: Mapped[str] = mapped_column(String(20), nullable=False, default="shadow")

    #: Nilai yang diusulkan mesin, dan nilai sebelumnya — keduanya disimpan
    #: supaya rollback tak perlu menebak apa pun.
    proposed_value: Mapped[float] = mapped_column(Float, nullable=False)
    previous_value: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    #: Metrik lane SEBELUM angka baru berlaku — pembanding satu-satunya yang sah.
    baseline_n:          Mapped[int]   = mapped_column(Integer, nullable=False, default=0)
    baseline_expectancy: Mapped[float | None] = mapped_column(Float, nullable=True)
    baseline_win_rate:   Mapped[float | None] = mapped_column(Float, nullable=True)

    #: Metrik yang teramati SESUDAH berlaku (diisi ulang tiap evaluasi).
    observed_n:          Mapped[int]   = mapped_column(Integer, nullable=False, default=0)
    observed_expectancy: Mapped[float | None] = mapped_column(Float, nullable=True)
    observed_win_rate:   Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at:   Mapped[float] = mapped_column(Float, nullable=False,
                                                default=lambda: time.time())
    activated_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    decided_at:   Mapped[float | None] = mapped_column(Float, nullable=True)

    #: Alasan keputusan terakhir, dalam bahasa manusia — supaya riwayatnya bisa
    #: dibaca tanpa harus membaca kode yang menghasilkannya.
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
