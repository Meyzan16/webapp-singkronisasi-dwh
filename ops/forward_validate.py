"""FASE A - Validasi Forward FUTURES (READ-ONLY).

Ukur expectancy pool auto-eligible HANYA untuk keputusan SETELAH garis batas
(saat fix #1 overextension + #2 floor lane-lemah live), lalu bandingkan dengan
baseline historis. Menjawab: apakah #1+#2 BERTAHAN pada data BARU (bukan overfit
ke 11.5 hari historis)?

Garis batas + baseline disimpan di ops/forward-baseline.json (dibuat sekali).
Output: baris vonis ringkas (dipakai validate-forward.ps1 -> Telegram) + detail.
"""
import json
import os
import sys
import asyncio
from datetime import datetime
from statistics import mean

sys.path.insert(0, r"D:\kerja\Apps\workspace\agents-trading\backend")
sys.path.insert(0, r"D:\kerja\Apps\workspace\agents-trading")

from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.futures_decision_event import FuturesDecisionEvent as E
from app.services.trading_costs import EXECUTION_COST_PCT as COST

BASELINE_FILE = r"D:\kerja\Apps\workspace\agents-trading\ops\forward-baseline.json"
# Aturan live pasca #1+#2
THR = {"pre_gainer": 70, "accumulation": 70, "momentum": 72, "bigmover": 70}
CEIL = 80


def perf(pnls):
    if not pnls:
        return {"n": 0, "wr": None, "exp": None, "pf": None}
    w = sum(1 for p in pnls if p > 0)
    gw = sum(p for p in pnls if p > 0); gl = abs(sum(p for p in pnls if p < 0))
    return {"n": len(pnls), "wr": round(w / len(pnls) * 100, 1),
            "exp": round(mean(pnls), 3), "pf": round(gw / gl, 2) if gl else None}


def eligible(x):
    thr = THR.get(x["lane"], 72)
    if x["regime"] == "ranging":
        thr += 5
    if x["score"] < thr or x["score"] >= CEIL:
        return False
    if x["regime"] == "volatile" and x["lane"] != "momentum":
        return False
    return True


async def load(after_ts=None):
    async with AsyncSessionLocal() as s:
        q = select(E.score, E.pnl_4h_pct, E.lane, E.regime, E.direction, E.scan_ts).where(
            E.pnl_4h_pct.isnot(None))
        if after_ts:
            q = q.where(E.scan_ts >= after_ts)
        rows = (await s.execute(q)).all()
    return [dict(score=float(r[0] or 0), pnl=float(r[1]) - COST, lane=r[2] or "?",
                 regime=r[3] or "?", direction=r[4] or "?", ts=float(r[5] or 0)) for r in rows]


async def main():
    now = datetime.now().timestamp()
    # Buat baseline sekali: garis batas = now, simpan metrik historis sbg acuan.
    if not os.path.exists(BASELINE_FILE):
        hist = await load()
        pool = [x["pnl"] for x in hist if eligible(x)]
        base = perf(pool)
        payload = {"boundary_ts": now, "created": datetime.now().isoformat(timespec="seconds"),
                   "baseline_eligible": base, "baseline_n_total": len(hist)}
        with open(BASELINE_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        print(f"BASELINE dibuat: garis batas {datetime.fromtimestamp(now):%Y-%m-%d %H:%M} | "
              f"eligible historis exp={base['exp']}% pf={base['pf']} n={base['n']}")
        return

    with open(BASELINE_FILE, encoding="utf-8") as f:
        b = json.load(f)
    boundary = b["boundary_ts"]
    base = b["baseline_eligible"]
    fwd = await load(after_ts=boundary)
    days = (now - boundary) / 86400
    ep = [x["pnl"] for x in fwd if eligible(x)]
    fp = perf(ep)
    lng = perf([x["pnl"] for x in fwd if eligible(x) and x["direction"] == "LONG"])
    sht = perf([x["pnl"] for x in fwd if eligible(x) and x["direction"] == "SHORT"])

    if fp["n"] < 20:
        verdict = f"FASE A ({days:.1f}h): kumpul data... eligible-matang n={fp['n']} (perlu >=20). baseline exp={base['exp']}%"
    else:
        tag = "BERTAHAN" if (fp["exp"] or -9) >= 0 else "MEMBURUK"
        verdict = (f"FASE A ({days:.1f}h) {tag}: FWD eligible exp={fp['exp']}% pf={fp['pf']} "
                   f"wr={fp['wr']}% n={fp['n']} (baseline {base['exp']}%) | "
                   f"LONG {lng['exp']}%(n{lng['n']}) SHORT {sht['exp']}%(n{sht['n']})")
    print(verdict)


if __name__ == "__main__":
    asyncio.run(main())
