"""Penjadwal pekerjaan berkala FUTURES — eksplisit, dan tahan restart.

PLAN-FUTURES-AGENTIC.md §8.6. Mengeluarkan 12 pekerjaan berkala yang selama ini
bersembunyi di dalam `run_futures_loop`, dipicu `_cycle_count % N` dan jendela
kalender.

── Kenapa dipindah ──────────────────────────────────────────────────────────
Bukan demi kerapian. Cara lama punya tiga kegagalan yang semuanya SENYAP:

1. HITUNGAN SIKLUS KEMBALI NOL SAAT RESTART.
   `_cycle_count` variabel di memori. Setiap backend restart, semua pemicu
   `% N` mulai lagi dari nol — pekerjaan ber-N besar (`% 180`, `% 1000`) praktis
   tak pernah sampai giliran di mesin yang sering di-restart. Ini sudah pernah
   ditemukan untuk latihan model (catatan 6 Agu 2026) dan ditambal khusus di
   sana; sebelas pekerjaan lain dibiarkan.

2. JENDELA KALENDER HANYA MENYALA BILA SCAN KEBETULAN MENDARAT DI DALAMNYA.
   `weekday()==6 and hour==0 and minute<2` menuntut ada siklus scan yang jatuh
   tepat di jendela dua menit itu. Kalau scanner sedang berhenti, dijeda, atau
   siklusnya melar karena API lambat, `weekly_backtest` terlewat SEMINGGU PENUH
   dan tak ada satu pun baris log yang menyebutkan bahwa ia dilewati. Yang
   bulanan lebih parah lagi: terlewat sebulan.

3. IRAMA SCAN MENYETIR IRAMA BELAJAR.
   Siklus scan ~2 menit hanya asumsi. Melambat jadi 4 menit membuat SEMUA
   pekerjaan `% N` melambat dua kali lipat tanpa ada yang menyadarinya.

── Gantinya ─────────────────────────────────────────────────────────────────
Setiap pekerjaan punya jadwal yang dinyatakan dalam WAKTU, bukan hitungan
siklus, dan waktu jalan terakhirnya DISIMPAN di `app_settings` — jadi restart
tak mengulang dari nol dan tak pula memicu banjir pekerjaan sekaligus.

Pekerjaan kalender memakai semantik "TERLAMBAT", bukan "sedang di jendelanya":
mingguan berarti "belum jalan sejak batas minggu terakhir", jadi scanner yang
menyala pukul 09:00 Senin tetap menjalankan pekerjaan Minggu yang terlewat —
sekali, bukan berkali-kali.

Modul ini TIDAK menjalankan apa pun sendiri. `run_due()` dipanggil sekali per
siklus scan, dan mengembalikan laporan pekerjaan mana yang jalan — supaya
"pekerjaan X sudah lama tak jalan" bisa terlihat, bukan ditebak.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

import structlog

logger = structlog.get_logger(__name__)

_SETTINGS_KEY = "futures_jobs_last_run"

MENIT = 60.0
JAM = 3600.0


# ── Jadwal ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Jadwal:
    """Kapan sebuah pekerjaan dianggap terlambat.

    `every_sec` untuk yang berulang; `weekly`/`monthly` untuk yang berpatokan
    kalender. Keduanya dijawab dengan pertanyaan yang sama: "sudah jalan sejak
    batas terakhirnya?" — bukan "apakah sekarang tepat di jendelanya".
    """

    every_sec: Optional[float] = None
    weekly_on: Optional[int] = None      # 0=Senin … 6=Minggu (UTC)
    weekly_hour: int = 0
    monthly_day: Optional[int] = None    # 1..28 (UTC)
    monthly_hour: int = 0

    def batas_terakhir(self, sekarang: float) -> float:
        """Titik waktu terakhir pekerjaan ini SEHARUSNYA sudah jalan."""
        if self.every_sec:
            return sekarang - self.every_sec
        now = datetime.fromtimestamp(sekarang, tz=timezone.utc)
        if self.weekly_on is not None:
            batas = now.replace(hour=self.weekly_hour, minute=0, second=0, microsecond=0)
            mundur = (now.weekday() - self.weekly_on) % 7
            batas = batas.fromtimestamp(batas.timestamp() - mundur * 86400, tz=timezone.utc)
            if batas.timestamp() > sekarang:
                batas = batas.fromtimestamp(batas.timestamp() - 7 * 86400, tz=timezone.utc)
            return batas.timestamp()
        if self.monthly_day is not None:
            batas = now.replace(day=min(self.monthly_day, 28), hour=self.monthly_hour,
                                minute=0, second=0, microsecond=0)
            if batas.timestamp() > sekarang:
                bulan_lalu = (batas.month - 2) % 12 + 1
                tahun = batas.year - (1 if batas.month == 1 else 0)
                batas = batas.replace(year=tahun, month=bulan_lalu)
            return batas.timestamp()
        return sekarang      # tanpa jadwal = selalu terlambat (tiap siklus)


@dataclass
class Pekerjaan:
    nama: str
    jadwal: Jadwal
    jalankan: Callable[[], Awaitable[object]]
    #: Pekerjaan penting yang kegagalannya wajib WARNING, bukan sekadar info.
    kritis: bool = False
    catatan: str = ""


# ── Ingatan waktu jalan terakhir ──────────────────────────────────────────────

_last_run: dict[str, float] = {}
_loaded = False


async def muat_state() -> None:
    """Baca waktu jalan terakhir dari DB. Dipanggil sekali saat loop mulai.

    Tanpa ini restart mengulang dari nol — dan pekerjaan mingguan/bulanan akan
    dianggap terlambat setiap kali proses naik, sehingga backend yang beberapa
    kali restart dalam sehari menjalankan backtest mingguan berkali-kali.
    """
    global _loaded
    if _loaded:
        return
    try:
        import json

        from sqlalchemy import select

        from app.database import AsyncSessionLocal, is_db_available
        from app.models.app_settings import AppSettings

        if not is_db_available():
            return
        async with AsyncSessionLocal() as session:
            row = (await session.execute(
                select(AppSettings).where(AppSettings.key == _SETTINGS_KEY)
            )).scalar_one_or_none()
            if row and row.value:
                data = json.loads(row.value)
                if isinstance(data, dict):
                    _last_run.update({k: float(v) for k, v in data.items()
                                      if isinstance(v, (int, float))})
        _loaded = True
        logger.info("futures_jobs_state_loaded", jobs=len(_last_run))
    except Exception as exc:      # noqa: BLE001 — gagal baca tak boleh menghentikan scan
        logger.warning("futures_jobs_state_load_failed", error=str(exc)[:120])


async def simpan_state() -> None:
    """Tulis waktu jalan terakhir. Satu baris untuk semua pekerjaan."""
    try:
        import json

        from sqlalchemy import select

        from app.database import AsyncSessionLocal, is_db_available
        from app.models.app_settings import AppSettings

        if not is_db_available() or not _last_run:
            return
        async with AsyncSessionLocal() as session:
            row = (await session.execute(
                select(AppSettings).where(AppSettings.key == _SETTINGS_KEY)
            )).scalar_one_or_none()
            payload = json.dumps({k: round(v, 1) for k, v in _last_run.items()})
            if row is None:
                session.add(AppSettings(key=_SETTINGS_KEY, value=payload,
                                        updated_at=time.time()))
            else:
                row.value = payload
                row.updated_at = time.time()
            await session.commit()
    except Exception as exc:      # noqa: BLE001
        logger.warning("futures_jobs_state_save_failed", error=str(exc)[:120])


def terlambat(p: Pekerjaan, sekarang: Optional[float] = None) -> bool:
    """Apakah pekerjaan ini sudah waktunya jalan?"""
    now = time.time() if sekarang is None else sekarang
    return _last_run.get(p.nama, 0.0) < p.jadwal.batas_terakhir(now)


def status() -> dict:
    """Kapan tiap pekerjaan terakhir jalan, dan apakah sekarang terlambat.

    Dibuat supaya "pekerjaan X sudah lama tak jalan" bisa DILIHAT. Cara lama
    tak menyediakan cara apa pun untuk mengetahuinya selain membaca kode.
    """
    now = time.time()
    return {
        p.nama: {
            "terakhir_jalan": _last_run.get(p.nama) or None,
            "umur_jam": round((now - _last_run[p.nama]) / 3600, 2) if p.nama in _last_run else None,
            "terlambat": terlambat(p, now),
            "catatan": p.catatan,
        }
        for p in daftar_pekerjaan()
    }


# ── Pelaksana ─────────────────────────────────────────────────────────────────

async def run_due(sekarang: Optional[float] = None) -> dict:
    """Jalankan semua pekerjaan yang sudah terlambat. Dipanggil sekali/siklus.

    Kegagalan satu pekerjaan TIDAK menghentikan yang lain, dan TIDAK menandainya
    sudah jalan — supaya ia dicoba lagi siklus berikutnya alih-alih terlewat
    sampai jadwal berikutnya.
    """
    await muat_state()
    now = time.time() if sekarang is None else sekarang
    dijalankan: list[str] = []
    gagal: list[str] = []

    for p in daftar_pekerjaan():
        if not terlambat(p, now):
            continue
        try:
            await p.jalankan()
            _last_run[p.nama] = now
            dijalankan.append(p.nama)
        except Exception as exc:      # noqa: BLE001
            gagal.append(p.nama)
            (logger.warning if p.kritis else logger.info)(
                "futures_job_failed", job=p.nama, error=str(exc)[:200])

    if dijalankan:
        await simpan_state()
    return {"dijalankan": dijalankan, "gagal": gagal}


# ── Daftar pekerjaan ──────────────────────────────────────────────────────────
# Jadwalnya dinyatakan dalam WAKTU. Angka di komentar adalah irama LAMA
# (`% N` siklus, dengan asumsi siklus ~2 menit) supaya perubahannya bisa
# ditelusuri: yang berubah adalah cara memicunya, bukan seberapa seringnya.

def daftar_pekerjaan() -> list[Pekerjaan]:
    return [
        Pekerjaan(
            nama="outcome_pass",
            jadwal=Jadwal(every_sec=20 * MENIT),          # dulu % 10 == 5
            kritis=True,
            catatan="Label hasil 30m/1h/4h/24h + sambungkan trade tertutup ke ledger",
            jalankan=_outcome_pass,
        ),
        Pekerjaan(
            nama="big_mover_backfill",
            jadwal=Jadwal(every_sec=20 * MENIT),          # dulu % 10 == 0
            catatan="Isi forward-PnL big_mover_log (150 baris/putaran)",
            jalankan=_big_mover_backfill,
        ),
        Pekerjaan(
            nama="predictive_resolve",
            jadwal=Jadwal(every_sec=24 * MENIT),          # dulu % 12 == 0
            catatan="Selesaikan prediksi yang sudah lewat horizonnya",
            jalankan=_predictive_resolve,
        ),
        Pekerjaan(
            nama="predictive_repair",
            jadwal=Jadwal(every_sec=30 * MENIT),          # dulu % 15 == 7
            catatan="Agen perbaikan bobot otomatis (aksi terbatas + cooldown)",
            jalankan=_predictive_repair,
        ),
        Pekerjaan(
            nama="repair_verifier",
            jadwal=Jadwal(every_sec=6 * JAM),             # dulu % 180 == 20
            catatan="Verifikasi aksi perbaikan; auto-revert bila memburuk",
            jalankan=_repair_verifier,
        ),
        Pekerjaan(
            nama="prune_old_events",
            jadwal=Jadwal(every_sec=24 * JAM),            # dulu % 100 == 5
            catatan="Pangkas ledger keputusan lama",
            jalankan=_prune_old_events,
        ),
        Pekerjaan(
            nama="prune_predictive_log",
            jadwal=Jadwal(every_sec=24 * JAM),            # dulu % 1000 == 0
            catatan="Pangkas predictive_log > 30 hari",
            jalankan=_prune_predictive_log,
        ),
        Pekerjaan(
            nama="prune_rejection_log",
            jadwal=Jadwal(every_sec=24 * JAM),            # dulu % 100 == 0
            catatan="Pangkas rejection_log > 7 hari",
            jalankan=_prune_rejection_log,
        ),
        Pekerjaan(
            nama="weekly_backtest",
            jadwal=Jadwal(weekly_on=6, weekly_hour=0),    # Minggu 00:00 UTC
            kritis=True,
            catatan="Replay big_mover_log mingguan",
            jalankan=_weekly_backtest,
        ),
        Pekerjaan(
            nama="weekly_signal_review",
            jadwal=Jadwal(weekly_on=0, weekly_hour=0),    # Senin 00:00 UTC
            kritis=True,
            catatan="Tinjau sinyal mingguan + sesuaikan bobot",
            jalankan=_weekly_signal_review,
        ),
        Pekerjaan(
            nama="monthly_calibration",
            jadwal=Jadwal(monthly_day=1, monthly_hour=0),
            kritis=True,
            catatan="Kalibrasi ambang adaptif bulanan",
            jalankan=_monthly_calibration,
        ),
    ]


# ── Pembungkus tiap pekerjaan ────────────────────────────────────────────────
# Sengaja tipis: isinya tetap di modulnya masing-masing. Yang pindah ke sini
# hanya KAPAN dijalankan, bukan APA yang dijalankan.

#: Ditandai saat outcome BARU muncul. Dipakai scheduler untuk memicu latihan
#: model di mode embedded — memicu HANYA dari hitungan siklus membuat latihan
#: futures hilang tiap kali backend restart (temuan 6 Agu 2026).
_ada_outcome_baru = False


def ambil_outcome_baru() -> bool:
    """Baca-lalu-hapus. Sekali dibaca, tandanya turun — supaya satu kedatangan
    outcome tak memicu latihan berkali-kali."""
    global _ada_outcome_baru
    nilai = _ada_outcome_baru
    _ada_outcome_baru = False
    return nilai


async def _outcome_pass() -> None:
    global _ada_outcome_baru
    from agents.futures.outcome_tracker import (
        backfill_closed_futures_trades, update_decision_outcomes,
    )
    n_label = await update_decision_outcomes()
    n_link = await backfill_closed_futures_trades()
    if n_label or n_link:
        _ada_outcome_baru = True
        logger.info("futures_outcome_pass", price_labels=n_label, trade_links=n_link)


async def _prune_old_events() -> None:
    from agents.futures.outcome_tracker import prune_old_events
    await prune_old_events()


async def _big_mover_backfill() -> None:
    from app.services.big_mover_logger import backfill_pending
    await backfill_pending(max_rows=150)


async def _predictive_resolve() -> None:
    from app.database import is_db_available
    if not is_db_available():
        return
    from agents.futures.scheduler import _resolve_predictive_logs
    await _resolve_predictive_logs()


async def _predictive_repair() -> None:
    from agents.learning.predictive_repair import run_predictive_repair
    hasil = await run_predictive_repair()
    if hasil.get("actions"):
        logger.info("predictive_repair_pass", actions=len(hasil["actions"]),
                    checked=hasil.get("checked"))


async def _repair_verifier() -> None:
    from agents.learning.repair_verifier import verify_repairs
    await verify_repairs()


async def _prune_predictive_log() -> None:
    """Dulu dipicu `% 1000` siklus (~33 jam nominal). Dengan hitungan yang
    kembali nol tiap restart, ia praktis TAK PERNAH sampai giliran."""
    import time as _t

    from sqlalchemy import delete

    from app.database import AsyncSessionLocal, is_db_available
    from app.models.predictive_log import PredictiveLog

    if not is_db_available():
        return
    async with AsyncSessionLocal() as session:
        await session.execute(
            delete(PredictiveLog).where(PredictiveLog.scanned_at < _t.time() - 30 * 86400))
        await session.commit()


async def _prune_rejection_log() -> None:
    import time as _t

    from sqlalchemy import delete

    from app.database import AsyncSessionLocal, is_db_available
    from app.models.rejection_log import RejectionLog

    if not is_db_available():
        return
    async with AsyncSessionLocal() as session:
        await session.execute(
            delete(RejectionLog).where(RejectionLog.rejected_at < _t.time() - 7 * 86400))
        await session.commit()


async def _weekly_backtest() -> None:
    from agents.learning.weekly_backtest import run_weekly_backtest
    await run_weekly_backtest()


async def _weekly_signal_review() -> None:
    from agents.learning.weekly_signal_review import run_weekly_signal_review
    hasil = await run_weekly_signal_review()
    if hasil.get("adjustments"):
        logger.info("weekly_signal_review_adjustments", n=len(hasil["adjustments"]))


async def _monthly_calibration() -> None:
    from agents.learning.monthly_calibration import run_monthly_calibration
    hasil = await run_monthly_calibration()
    if hasil.get("changes"):
        logger.info("monthly_calibration_done", changes=hasil["changes"])
