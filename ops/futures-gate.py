"""Gerbang Fase 7 — apakah ukuran boleh dinaikkan ke target?

PLAN-FUTURES-AGENTIC.md Fase 7. Menjawab satu pertanyaan dengan angka, bukan
perasaan: apakah agen tunggal sudah membuktikan diri cukup untuk dipercaya
dengan risiko dua kali lipat?

Tujuh syarat, SEMUANYA harus lulus. Satu saja gagal, ukuran tetap.

Alasan ada tujuh dan bukan satu: sistem lama terlihat "WR 50%" sambil kehilangan
$145. Satu angka bisa bagus sementara yang lain busuk — dan justru kombinasinya
yang menentukan apakah memperbesar ukuran akan memperbesar untung atau
memperbesar rugi.

Skrip ini TIDAK mengubah apa pun. Ia menghitung, menulis laporan, dan berhenti.
Menaikkan ukuran tetap keputusan sadar seorang manusia.

Pakai:
    backend/.venv/Scripts/python.exe ops/futures-gate.py
    backend/.venv/Scripts/python.exe ops/futures-gate.py --tulis   # simpan laporan
"""

import argparse
import asyncio
import datetime
import json
import statistics

from sqlalchemy import select, text

from agents.shared import trade_outcome as outcome
from app.database import AsyncSessionLocal, probe_db, set_db_available
from app.models.paper_trade import PaperTrade
from app.services.agent_registry import ACTIVE_FUTURES_AGENTS

MIN_SAMPEL = 40


def _meta(t) -> dict:
    try:
        return json.loads(t.signals_json or "{}") or {}
    except (TypeError, ValueError):
        return {}


async def kumpulkan() -> dict:
    """Ambil bahan mentahnya. Hanya trade AGEN AKTIF — riwayat lane lama tak
    boleh ikut menilai agen yang aturannya sudah berbeda sama sekali."""
    async with AsyncSessionLocal() as s:
        trades = list((await s.execute(
            select(PaperTrade).where(
                PaperTrade.style.in_(ACTIVE_FUTURES_AGENTS),
                PaperTrade.status.in_(["tp", "sl"]),
            ).order_by(PaperTrade.closed_at)
        )).scalars().all())

        alasan = dict((await s.execute(text("""
            SELECT close_reason, count(*) FROM exit_events
            WHERE market='futures' AND agent = ANY(:agen) GROUP BY 1
        """), {"agen": list(ACTIVE_FUTURES_AGENTS)})).all())

        dd_cap = (await s.execute(text(
            "SELECT value_num FROM agent_config WHERE agent_group='futures' AND key='dd_hard_stop_pct'"
        ))).scalar() or 15.0

    return {"trades": trades, "alasan": alasan, "dd_cap": float(dd_cap)}


def nilai(bahan: dict) -> list[dict]:
    """Tujuh gerbang. Tiap baris: nama, nilai sekarang, syarat, lulus?"""
    trades = bahan["trades"]
    n = len(trades)
    if n == 0:
        return [{"nama": "sampel", "nilai": 0, "syarat": f">= {MIN_SAMPEL}",
                 "lulus": False,
                 "catatan": "Agen aktif belum menghasilkan satu pun trade tertutup."}]

    tegas = [t for t in trades if not outcome.is_scratch(t)]
    impas = [t for t in trades if outcome.is_scratch(t)]
    menang = [t for t in tegas if outcome.is_win(t)]

    pnl = [float(t.pnl_dollar or 0.0) for t in trades]
    ekspektasi = statistics.mean(pnl) if pnl else 0.0

    tp1 = bahan["alasan"].get("tp1_hit", 0) + bahan["alasan"].get("tp2_hit", 0)
    tp1_frac = tp1 / n if n else 0.0

    rasio_menang = []
    for t in menang:
        biaya = outcome.trade_cost_usd(t)
        if biaya > 0:
            rasio_menang.append(float(t.pnl_dollar or 0.0) / biaya)
    rata_rasio = statistics.mean(rasio_menang) if rasio_menang else 0.0

    breach = [float(t.sl_breach_pct) for t in trades
              if getattr(t, "sl_breach_pct", None) is not None]
    breach_maks = max(breach) if breach else 0.0

    lebih_dari_risk = [
        t for t in trades
        if (t.pnl_dollar or 0) < 0 and (t.risk_dollar or 0) > 0
        and -float(t.pnl_dollar) > 1.3 * float(t.risk_dollar)
    ]

    # Drawdown puncak dari kurva ekuitas trade agen aktif.
    ekuitas = puncak = 0.0
    dd_maks = 0.0
    for p in pnl:
        ekuitas += p
        puncak = max(puncak, ekuitas)
        if puncak > 0:
            dd_maks = max(dd_maks, (puncak - ekuitas) / puncak * 100)

    return [
        {"nama": "sampel cukup", "nilai": n, "syarat": f">= {MIN_SAMPEL}",
         "lulus": n >= MIN_SAMPEL,
         "catatan": "Di bawah ini, apa pun yang terlihat masih derau."},
        {"nama": "ekspektasi bersih/trade", "nilai": round(ekspektasi, 2), "syarat": "> $0",
         "lulus": ekspektasi > 0,
         "catatan": "Memperbesar ukuran sistem berekspektasi negatif hanya mempercepat rugi."},
        {"nama": "TP1/TP2 tersentuh", "nilai": f"{tp1_frac*100:.1f}%", "syarat": ">= 30%",
         "lulus": tp1_frac >= 0.30,
         "catatan": "Sistem lama: 4%. TP yang tak pernah tercapai bukan TP."},
        {"nama": "trade impas", "nilai": f"{len(impas)/n*100:.1f}%", "syarat": "<= 10%",
         "lulus": len(impas) / n <= 0.10,
         "catatan": "Sistem lama: 75%. Inilah 'ditutup 0% kemakan fee'."},
        {"nama": "win rate bermakna", "nilai": f"{len(menang)/len(tegas)*100:.1f}%" if tegas else "n/a",
         "syarat": ">= 35%", "lulus": bool(tegas) and len(menang) / len(tegas) >= 0.35,
         "catatan": "Dihitung atas trade TEGAS saja — impas bukan menang, bukan kalah."},
        {"nama": "untung:biaya pemenang", "nilai": f"{rata_rasio:.1f}x", "syarat": ">= 5x",
         "lulus": rata_rasio >= 5.0,
         "catatan": "Menang yang cuma menutup fee bukan kemenangan."},
        {"nama": "kerugian terkendali", "nilai": f"breach maks {breach_maks:.2f}%, "
                                                 f"{len(lebih_dari_risk)} rugi > 1,3x risk",
         "syarat": "breach <= 0,5% & 0 kejadian", "lulus": breach_maks <= 0.5 and not lebih_dari_risk,
         "catatan": "Sistem lama: BLUAI rugi 2,16x risiko yang direncanakan."},
        {"nama": "drawdown puncak", "nilai": f"{dd_maks:.1f}%",
         "syarat": f"<= {bahan['dd_cap']:.0f}%", "lulus": dd_maks <= bahan["dd_cap"],
         "catatan": "Batas yang sama dipakai circuit breaker."},
    ]


def laporan(hasil: list[dict]) -> str:
    lulus_semua = all(g["lulus"] for g in hasil)
    tgl = datetime.date.today().isoformat()
    baris = [
        f"# Gerbang Fase 7 — {tgl}", "",
        f"Dihasilkan `ops/futures-gate.py` pada {datetime.datetime.now():%Y-%m-%d %H:%M}.",
        "**Jangan diedit tangan** — jalankan ulang skripnya.", "",
        f"## Putusan: {'LULUS — ukuran boleh dinaikkan' if lulus_semua else 'BELUM LULUS — ukuran TETAP'}",
        "", "| gerbang | sekarang | syarat | lulus |", "|---|---|---|---|",
    ]
    for g in hasil:
        baris.append(f"| {g['nama']} | {g['nilai']} | {g['syarat']} | "
                     f"{'✅' if g['lulus'] else '❌'} |")
    baris += ["", "## Kenapa tiap gerbang ada", ""]
    for g in hasil:
        baris.append(f"- **{g['nama']}** — {g['catatan']}")
    if not lulus_semua:
        gagal = [g["nama"] for g in hasil if not g["lulus"]]
        baris += ["", "## Yang menghalangi", "",
                  "Gerbang berikut belum lulus, jadi `size_risk_base_pct` TETAP:", ""]
        baris += [f"- {n}" for n in gagal]
        baris += ["", "Menaikkan ukuran sekarang berarti memperbesar sistem yang",
                  "belum terbukti — persis yang dihindari prinsip P1 di plan."]
    else:
        baris += ["", "## Langkah berikutnya", "",
                  "Semua gerbang lulus. Ukuran boleh dinaikkan lewat UI Settings:",
                  "`futures.size_risk_base_pct` 1,0 -> 2,0 (keputusan K1).", "",
                  "Naikkan SATU langkah, lalu jalankan skrip ini lagi setelah 40",
                  "trade berikutnya."]
    return "\n".join(baris) + "\n"


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tulis", action="store_true", help="simpan ke docs/")
    args = ap.parse_args()

    set_db_available(await probe_db())
    hasil = nilai(await kumpulkan())

    lulus = sum(1 for g in hasil if g["lulus"])
    print(f"{'GERBANG':30s} {'SEKARANG':>26s}  {'SYARAT':>22s}  ?")
    for g in hasil:
        print(f"{g['nama']:30s} {str(g['nilai']):>26s}  {g['syarat']:>22s}  "
              f"{'LULUS' if g['lulus'] else 'GAGAL'}")
    print(f"\n{lulus}/{len(hasil)} lulus — "
          f"{'ukuran BOLEH dinaikkan' if lulus == len(hasil) else 'ukuran TETAP'}")

    if args.tulis:
        path = f"docs/futures-gate-{datetime.date.today().isoformat()}.md"
        with open(path, "w", encoding="utf-8") as f:
            f.write(laporan(hasil))
        print(f"\nlaporan: {path}")


if __name__ == "__main__":
    asyncio.run(main())
