"""Ringkasan riset sinyal shadow futures — satu sumber untuk API, Telegram, dan ops/.

ATURAN LULUS — ditetapkan 1 Okt 2026, SEBELUM ada satu pun hasil. Jangan diubah
setelah melihat angka; mengubahnya membuat riset ini jadi pencarian parameter.
Sebuah hipotesis LULUS bila semuanya terpenuhi:
  1. ≥ 300 sinyal berlabel (bracket final)
  2. rata-rata bracket_r > +0,10 R di PARUH AWAL dan PARUH AKHIR (kronologis)
  3. mengalahkan kontrol ≥ 0,15 R di keseluruhan periode
  4. tak lebih dari 40% dari total R datang dari satu minggu kalender
"""

from __future__ import annotations

import datetime as dt
import statistics as st

from sqlalchemy import func, select

from app.database import AsyncSessionLocal
from app.models.futures_shadow_signal import FuturesShadowSignal

MIN_N = 300
MIN_R_HALF = 0.10
MIN_EDGE_VS_CONTROL = 0.15
MAX_WEEK_SHARE = 0.40

#: Penjelasan bahasa manusia per hipotesis — dipakai FE & Telegram.
DESCRIPTIONS: dict[str, str] = {
    "control": "Pembanding: 1 koin acak per scan, LONG. Mengukur naik-turun pasar biasa.",
    "pullback_ema": "Tren naik, harga turun kembali ke EMA20 1 jam (RSI 40–55, lilin hijau).",
    "squeeze_breakout": "Bollinger 1 jam menyempit lalu harga menembus pita dengan volume besar.",
    "dip_in_uptrend": "Tren 4 jam naik, RSI 1 jam < 32, harga mulai naik lagi.",
    "bull_flag": "Sudah pump ≥10%, istirahat rapat 6 jam, lalu menembus puncak istirahat itu.",
    "rel_strength": "BTC turun ≥1,5% dalam 4 jam tapi koin ini bertahan lebih kuat.",
}


def _stats(rows: list) -> dict:
    """Statistik bracket satu kelompok baris berlabel."""
    if not rows:
        return {"n": 0, "r_per_trade": None, "tp_rate": None, "profit_factor": None, "median_hold_min": None}
    r = [x.bracket_r for x in rows]
    gain = sum(v for v in r if v > 0)
    loss = -sum(v for v in r if v < 0)
    return {
        "n": len(r),
        "r_per_trade": round(st.mean(r), 4),
        "tp_rate": round(sum(1 for x in rows if x.bracket_exit == "tp") / len(r) * 100, 1),
        "profit_factor": round(gain / loss, 2) if loss else None,
        "median_hold_min": round(st.median(x.bracket_hold_min or 0 for x in rows), 0),
    }


async def build_shadow_report() -> dict:
    """Ringkasan per (hipotesis, arah) + pemeriksaan aturan lulus."""
    async with AsyncSessionLocal() as s:
        rows = list((await s.execute(
            select(FuturesShadowSignal).where(FuturesShadowSignal.bracket_r.isnot(None))
            # id sebagai pemutus seri: sinyal dari scan yang sama punya scan_ts identik,
            # dan tanpa ini urutan (= batas paruh awal/akhir) acak antar-run.
            .order_by(FuturesShadowSignal.scan_ts, FuturesShadowSignal.id)
        )).scalars().all())
        pending_rows = (await s.execute(
            select(FuturesShadowSignal.hypothesis, FuturesShadowSignal.direction, func.count())
            .where(FuturesShadowSignal.bracket_r.is_(None))
            .group_by(FuturesShadowSignal.hypothesis, FuturesShadowSignal.direction)
        )).all()
        first_ts = await s.scalar(select(func.min(FuturesShadowSignal.scan_ts)))

    pending = {(h, d): n for h, d, n in pending_rows}
    by: dict[tuple[str, str], list] = {}
    for r in rows:
        by.setdefault((r.hypothesis, r.direction), []).append(r)
    for key in pending:
        by.setdefault(key, [])

    ctrl = [r.bracket_r for r in by.get(("control", "LONG"), [])]
    ctrl_mean = st.mean(ctrl) if ctrl else 0.0

    groups = []
    for (hyp, d), rs in sorted(by.items(), key=lambda kv: (kv[0][0] != "control", kv[0])):
        half = len(rs) // 2
        a, b = rs[:half], rs[half:]
        entry = {
            "hypothesis": hyp, "direction": d,
            "description": DESCRIPTIONS.get(hyp, ""),
            "pending": pending.get((hyp, d), 0),
            "all": _stats(rs), "first_half": _stats(a), "second_half": _stats(b),
            "is_control": hyp == "control",
        }
        if hyp != "control":
            weeks: dict[str, float] = {}
            for x in rs:
                w = dt.datetime.fromtimestamp(x.scan_ts).strftime("%G-W%V")
                weeks[w] = weeks.get(w, 0.0) + x.bracket_r
            total = sum(x.bracket_r for x in rs)
            week_share = (max(weeks.values()) / total) if (weeks and total > 0) else 1.0
            mean_all = st.mean(x.bracket_r for x in rs) if rs else 0.0
            checks = [
                {"rule": f"≥{MIN_N} sinyal berlabel", "ok": len(rs) >= MIN_N,
                 "value": f"{len(rs)}"},
                {"rule": f"paruh awal > +{MIN_R_HALF}R", "ok": bool(a) and st.mean(x.bracket_r for x in a) > MIN_R_HALF,
                 "value": f"{st.mean(x.bracket_r for x in a):+.2f}R" if a else "-"},
                {"rule": f"paruh akhir > +{MIN_R_HALF}R", "ok": bool(b) and st.mean(x.bracket_r for x in b) > MIN_R_HALF,
                 "value": f"{st.mean(x.bracket_r for x in b):+.2f}R" if b else "-"},
                {"rule": f"≥{MIN_EDGE_VS_CONTROL}R di atas pembanding", "ok": bool(rs) and mean_all - ctrl_mean >= MIN_EDGE_VS_CONTROL,
                 "value": f"{mean_all - ctrl_mean:+.2f}R" if rs else "-"},
                {"rule": f"satu minggu ≤{int(MAX_WEEK_SHARE * 100)}% total R", "ok": week_share <= MAX_WEEK_SHARE,
                 "value": f"{week_share * 100:.0f}%" if total > 0 else "-"},
            ]
            entry["checks"] = checks
            entry["passed"] = all(c["ok"] for c in checks)
            entry["edge_vs_control"] = round(mean_all - ctrl_mean, 4) if rs else None
        groups.append(entry)

    return {
        "started_at": first_ts,
        "labelled": len(rows),
        "pending": sum(pending.values()),
        "control_r_per_trade": round(ctrl_mean, 4),
        "rules": {"min_n": MIN_N, "min_r_half": MIN_R_HALF,
                  "min_edge_vs_control": MIN_EDGE_VS_CONTROL, "max_week_share": MAX_WEEK_SHARE},
        "groups": groups,
    }
