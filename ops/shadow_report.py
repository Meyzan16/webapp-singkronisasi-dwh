"""Laporan riset sinyal shadow futures (PLAN-OKT-2026 P1).

Jalankan dari repo root:
    backend/.venv/Scripts/python.exe ops/shadow_report.py

ATURAN LULUS — ditetapkan 1 Okt 2026, SEBELUM ada satu pun hasil. Jangan diubah
setelah melihat angka; mengubahnya membuat riset ini jadi pencarian parameter.
Sebuah hipotesis LULUS bila semuanya terpenuhi:
  1. ≥ 300 sinyal berlabel (bracket final)
  2. rata-rata bracket_r > +0,10 R di PARUH AWAL dan PARUH AKHIR (kronologis)
  3. mengalahkan kontrol ≥ 0,15 R di keseluruhan periode
  4. tak lebih dari 40% dari total R datang dari satu minggu kalender
"""

from __future__ import annotations

import asyncio
import datetime as dt
import os
import statistics as st
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select  # noqa: E402

from app.database import AsyncSessionLocal  # noqa: E402
from app.models.futures_shadow_signal import FuturesShadowSignal  # noqa: E402

MIN_N = 300
MIN_R_HALF = 0.10
MIN_EDGE_VS_CONTROL = 0.15
MAX_WEEK_SHARE = 0.40


def _stats(rs: list) -> str:
    if not rs:
        return "n=0"
    r = [x.bracket_r for x in rs]
    win = sum(1 for x in rs if x.bracket_exit == "tp")
    g = sum(v for v in r if v > 0)
    l = -sum(v for v in r if v < 0)
    return (f"n={len(r):4d} R/trade={st.mean(r):+.3f} TP={100 * win / len(r):4.1f}% "
            f"PF={(g / l if l else 99):4.2f} hold={st.median(x.bracket_hold_min for x in rs):5.0f}m")


async def main() -> None:
    async with AsyncSessionLocal() as s:
        rows = list((await s.execute(
            select(FuturesShadowSignal).where(FuturesShadowSignal.bracket_r.isnot(None))
            .order_by(FuturesShadowSignal.scan_ts)
        )).scalars().all())
        pending = (await s.execute(
            select(FuturesShadowSignal.hypothesis).where(FuturesShadowSignal.bracket_r.is_(None))
        )).all()
    pend: dict[str, int] = {}
    for (h,) in pending:
        pend[h] = pend.get(h, 0) + 1

    by: dict[tuple[str, str], list] = {}
    for r in rows:
        by.setdefault((r.hypothesis, r.direction), []).append(r)
    ctrl = [r.bracket_r for r in by.get(("control", "LONG"), [])]
    ctrl_mean = st.mean(ctrl) if ctrl else 0.0
    print(f"Sinyal berlabel: {len(rows)}  pending: {sum(pend.values())}  kontrol R/trade: {ctrl_mean:+.3f}\n")

    for (hyp, d), rs in sorted(by.items()):
        half = len(rs) // 2
        a, b = rs[:half], rs[half:]
        print(f"{hyp:17s} {d:5s} {_stats(rs)}  (pending {pend.get(hyp, 0)})")
        if hyp == "control":
            continue
        print(f"{'':23s} awal  {_stats(a)}")
        print(f"{'':23s} akhir {_stats(b)}")
        weeks: dict[str, float] = {}
        for x in rs:
            w = dt.datetime.fromtimestamp(x.scan_ts).strftime("%G-W%V")
            weeks[w] = weeks.get(w, 0.0) + x.bracket_r
        total = sum(rs_.bracket_r for rs_ in rs)
        week_share = (max(weeks.values()) / total) if total > 0 else 1.0
        mean_all = st.mean(x.bracket_r for x in rs)
        checks = {
            f"n≥{MIN_N}": len(rs) >= MIN_N,
            f"awal>{MIN_R_HALF}R": bool(a) and st.mean(x.bracket_r for x in a) > MIN_R_HALF,
            f"akhir>{MIN_R_HALF}R": bool(b) and st.mean(x.bracket_r for x in b) > MIN_R_HALF,
            f"vs kontrol≥{MIN_EDGE_VS_CONTROL}R": mean_all - ctrl_mean >= MIN_EDGE_VS_CONTROL,
            f"minggu terbesar≤{int(MAX_WEEK_SHARE * 100)}%": week_share <= MAX_WEEK_SHARE,
        }
        verdict = "LULUS" if all(checks.values()) else "belum"
        print(f"{'':23s} {verdict}: " + "  ".join(f"{k}{'✓' if v else '✗'}" for k, v in checks.items()))
        print()


if __name__ == "__main__":
    asyncio.run(main())
