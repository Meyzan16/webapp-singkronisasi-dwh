"""Laporan riset sinyal shadow futures (PLAN-OKT-2026 P1) — versi terminal.

Jalankan dari repo root:
    backend/.venv/Scripts/python.exe ops/shadow_report.py

Logika & ATURAN LULUS ada di agents/futures/shadow_report.py — satu sumber yang
sama dipakai endpoint /api/v1/futures/shadow-report (FE) dan laporan Telegram.
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.futures.shadow_report import build_shadow_report  # noqa: E402


def _fmt(s: dict) -> str:
    if not s["n"]:
        return "n=   0"
    pf = s["profit_factor"]
    return (f"n={s['n']:4d} R/trade={s['r_per_trade']:+.3f} TP={s['tp_rate']:4.1f}% "
            f"PF={(pf if pf is not None else 99):4.2f} hold={s['median_hold_min']:5.0f}m")


async def main() -> None:
    rep = await build_shadow_report()
    print(f"Sinyal berlabel: {rep['labelled']}  pending: {rep['pending']}  "
          f"kontrol R/trade: {rep['control_r_per_trade']:+.3f}\n")
    for g in rep["groups"]:
        print(f"{g['hypothesis']:17s} {g['direction']:5s} {_fmt(g['all'])}  (pending {g['pending']})")
        if g["is_control"]:
            continue
        print(f"{'':23s} awal  {_fmt(g['first_half'])}")
        print(f"{'':23s} akhir {_fmt(g['second_half'])}")
        verdict = "LULUS" if g["passed"] else "belum"
        print(f"{'':23s} {verdict}: " + "  ".join(f"{c['rule']}{'✓' if c['ok'] else '✗'}" for c in g["checks"]))
        print()


if __name__ == "__main__":
    asyncio.run(main())
