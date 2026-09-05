"""Gerbang Fase 2 — hitung ulang trade historis dengan mesin ukuran baru.

Menjawab satu pertanyaan sebelum satu pun trade baru dibuka: kalau `sizing.py`
sudah berlaku sejak dulu, seberapa berbeda ukuran, untung, dan ruginya?

Ini BUKAN backtest. Harga, entry, SL, dan hasil persennya diambil apa adanya
dari trade yang benar-benar terjadi; yang dihitung ulang HANYA ukurannya. Jadi
ia tidak menjawab "apakah strateginya menang" — ia menjawab "apakah ukurannya
terukur". Perbedaan itu penting dan sengaja tidak dikaburkan.

Pakai:
    backend/.venv/Scripts/python.exe ops/futures-sizing-replay.py
    backend/.venv/Scripts/python.exe ops/futures-sizing-replay.py --risk 2.0
"""

import argparse
import asyncio
import json
import statistics

from sqlalchemy import select

from app.database import AsyncSessionLocal, probe_db, set_db_available
from app.models.paper_trade import PaperTrade
from agents.futures import sizing
from agents.futures import sizing_config as szcfg


def _meta(trade) -> dict:
    try:
        return json.loads(trade.signals_json or "{}") or {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--risk", type=float, default=None,
                    help="paksa size_risk_base_pct (default: nilai config berjalan)")
    ap.add_argument("--positions", type=int, default=None, help="paksa max_positions")
    args = ap.parse_args()

    set_db_available(await probe_db())
    await szcfg.refresh()
    p = sizing.params_from_config()
    if args.risk is not None:
        p = sizing.SizingParams(**{**p.__dict__, "risk_pct": args.risk})
    if args.positions is not None:
        p = sizing.SizingParams(**{**p.__dict__, "max_positions": args.positions})

    async with AsyncSessionLocal() as s:
        trades = list((await s.execute(select(PaperTrade).where(
            PaperTrade.style.like("futures_%"),
            PaperTrade.status.in_(["tp", "sl", "expired"]),
        ).order_by(PaperTrade.entry_at))).scalars().all())

    print(f"parameter: risk {p.risk_pct}% | rugi margin di SL {p.margin_loss_at_sl_pct}% | "
          f"lev {p.lev_min:.0f}-{p.lev_max:.0f}x | TP1 bersih min ${p.min_profit_usd} | "
          f"slot {p.max_positions}")
    print(f"trade dinilai: {len(trades)}\n")

    lama_not, baru_not, lama_lev, baru_lev = [], [], [], []
    lama_pnl, baru_pnl, sl_rugi, tp1_untung = [], [], [], []
    ditolak: dict[str, int] = {}

    for t in trades:
        m = _meta(t)
        entry, sl = float(t.entry_price or 0), float(t.stop_loss or 0)
        if entry <= 0 or sl <= 0:
            continue
        sl_pct = abs(entry - sl) / entry * 100
        tp1_pct = float(m.get("tp1_pct") or 0.0)
        cost_pct = float(m.get("cost_floor_pct") or 0.20)

        r = sizing.compute(balance=float(t.balance_snapshot or 1000.0), sl_pct=sl_pct,
                           tp1_pct=tp1_pct, cost_pct=cost_pct, p=p)

        lama_not.append(float(t.position_size or 0))
        lama_lev.append(int(t.leverage or 1))
        lama_pnl.append(float(t.pnl_dollar or 0))

        if not r.can_open:
            kunci = r.reason.split(":")[0].split(" (")[0][:44]
            ditolak[kunci] = ditolak.get(kunci, 0) + 1
            continue

        baru_not.append(r.notional)
        baru_lev.append(r.leverage)
        # P&L dihitung ulang: persen yang BENAR-BENAR terjadi, notional baru.
        baru_pnl.append(float(t.pnl_pct or 0) / 100 * r.notional)
        sl_rugi.append(abs(r.sl_net_usd))
        if r.tp1_net_usd > 0:
            tp1_untung.append(r.tp1_net_usd)

    def ringkas(nama, lama, baru, satuan="$"):
        if not baru:
            print(f"{nama:26s} (tak ada kandidat lolos)")
            return
        print(f"{nama:26s} {statistics.median(lama):9.2f}{satuan} -> "
              f"{statistics.median(baru):9.2f}{satuan}   (median)")

    print("== UKURAN ==")
    ringkas("notional", lama_not, baru_not)
    ringkas("leverage", lama_lev, baru_lev, "x")

    print("\n== KERUGIAN TERUKUR? ==")
    if sl_rugi:
        print(f"rugi bila SL kena          median ${statistics.median(sl_rugi):.2f}  "
              f"rentang ${min(sl_rugi):.2f}-${max(sl_rugi):.2f}  "
              f"(sebaran {max(sl_rugi)/max(min(sl_rugi), 0.01):.2f}x)")
        print("  ^ makin rapat rentangnya, makin terukur. Lama: $3,97 rata dgn ekor 2,16x risk.")

    print("\n== SEKALI MENANG BERARTI BERAPA? ==")
    if tp1_untung:
        print(f"TP1 bersih                 median ${statistics.median(tp1_untung):.2f}  "
              f"min ${min(tp1_untung):.2f}")
    print(f"  ^ hari ini 59% trade tak pernah bergerak lebih dari $2.")

    print("\n== KANDIDAT YANG DITOLAK MESIN BARU ==")
    total_tolak = sum(ditolak.values())
    print(f"{total_tolak} dari {len(trades)} ({total_tolak/max(len(trades),1)*100:.0f}%) tak akan dibuka:")
    for alasan, n in sorted(ditolak.items(), key=lambda x: -x[1]):
        print(f"   {n:4d}x  {alasan}")

    print("\n== P&L HIPOTETIS (persen nyata x notional baru) ==")
    print(f"total lama  ${sum(lama_pnl):9.2f}")
    print(f"total baru  ${sum(baru_pnl):9.2f}   (hanya {len(baru_pnl)} trade yang lolos gerbang)")
    print("\nCATATAN: angka baru BUKAN ramalan. Ia mengasumsikan tiap trade tetap")
    print("berjalan sama persis padahal SL/TP-nya berbeda, dan mengabaikan bahwa")
    print("gerbang slot akan mengubah trade mana yang sempat dibuka. Yang layak")
    print("dibaca dari sini hanya SEBARAN ukuran dan kerugian, bukan totalnya.")


if __name__ == "__main__":
    asyncio.run(main())
