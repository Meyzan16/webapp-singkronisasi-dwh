"""Hasilkan docs/futures-baseline-<tgl>.md dari DB — garis dasar Fase 0.

Ditulis sebagai SKRIP, bukan dokumen tangan, supaya Fase 7 bisa menjalankan
ulang perintah yang sama dan membandingkan apel dengan apel.
"""
import asyncio
import datetime
from sqlalchemy import text
from app.database import AsyncSessionLocal

TGL = "2026-09-05"
OUT = f"docs/futures-baseline-{TGL}.md"

Q_UKURAN = """
SELECT round(percentile_cont(0.5) WITHIN GROUP (ORDER BY risk_dollar)::numeric,2)                       risk_p50,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY position_size)::numeric,1)                     notional_p50,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY position_size/GREATEST(leverage,1))::numeric,1) margin_p50,
       round(avg(leverage)::numeric,2)                                                                   lev_avg,
       round(percentile_cont(0.25) WITHIN GROUP (ORDER BY abs(entry_price-stop_loss)/entry_price*100)::numeric,2) sl_p25,
       round(percentile_cont(0.5)  WITHIN GROUP (ORDER BY abs(entry_price-stop_loss)/entry_price*100)::numeric,2) sl_p50,
       round(percentile_cont(0.75) WITHIN GROUP (ORDER BY abs(entry_price-stop_loss)/entry_price*100)::numeric,2) sl_p75,
       round(percentile_cont(0.5)  WITHIN GROUP (ORDER BY abs(take_profit-entry_price)/entry_price*100)::numeric,2) tp_p50,
       count(*) n
FROM paper_trades WHERE style LIKE 'futures_%' AND status<>'open' AND entry_price>0
"""

Q_WR = """
SELECT count(*) n,
       round(100.0*count(*) FILTER (WHERE pnl_pct>0)/count(*),1)      wr_resmi,
       round(100.0*count(*) FILTER (WHERE pnl_dollar>=1)/count(*),1)  wr_ge1,
       round(100.0*count(*) FILTER (WHERE pnl_dollar>=3)/count(*),1)  wr_ge3,
       count(*) FILTER (WHERE abs(pnl_dollar)<0.5)                    scratch_lt050,
       round(sum(pnl_dollar)::numeric,2)                              total_usd
FROM paper_trades WHERE style LIKE 'futures_%' AND status IN ('tp','sl')
"""

Q_LANE = """
SELECT style, count(*) n,
       count(*) FILTER (WHERE status='tp')            tp,
       count(*) FILTER (WHERE status='sl')            sl,
       round(sum(pnl_dollar)::numeric,2)              usd,
       round(avg(leverage)::numeric,1)                lev
FROM paper_trades WHERE style LIKE 'futures_%' AND status<>'open'
GROUP BY 1 ORDER BY n DESC
"""

Q_EXIT = """
SELECT close_reason, count(*) n,
       round(avg(pnl_pct)::numeric,2)   avg_pct,
       round(sum(pnl_dollar)::numeric,2) usd,
       round(avg(held_hours)::numeric,1) hold_h,
       round(avg(mfe_atr)::numeric,2)    mfe_atr,
       round(avg(tp_dist_atr)::numeric,2) tp_atr
FROM exit_events WHERE market='futures' GROUP BY 1 ORDER BY n DESC
"""

Q_BREACH = """
SELECT count(*) n_rugi_lebih_dari_risk,
       round(max(-pnl_dollar/NULLIF(risk_dollar,0))::numeric,2) rasio_maks,
       round(avg(-pnl_dollar)::numeric,2) rugi_rata,
       round(avg(risk_dollar)::numeric,2) risk_rata
FROM paper_trades WHERE style LIKE 'futures_%' AND status='sl'
  AND pnl_dollar<0 AND risk_dollar>0 AND -pnl_dollar > risk_dollar
"""

Q_WALLET = """
SELECT round(balance::numeric,2) balance, round(initial_balance::numeric,2) awal,
       round(realized_pnl::numeric,2) realized
FROM paper_balances WHERE style='futures'
"""

Q_LEDGER_GAP = """
SELECT count(*) trade_tanpa_exit_event
FROM paper_trades t LEFT JOIN exit_events e ON e.trade_id=t.id
WHERE t.style LIKE 'futures_%' AND t.status<>'open' AND e.id IS NULL
"""

Q_DECISIONS = """
SELECT count(*) total, count(*) FILTER (WHERE pnl_4h_pct IS NOT NULL) berlabel,
       count(DISTINCT agent) agen
FROM futures_decision_events
"""


def tabel(rows) -> str:
    if not rows:
        return "_(0 baris)_\n"
    head = list(rows[0]._fields)
    out = "| " + " | ".join(head) + " |\n|" + "|".join(["---"] * len(head)) + "|\n"
    for r in rows:
        out += "| " + " | ".join("—" if v is None else str(v) for v in r) + " |\n"
    return out


async def main() -> None:
    async with AsyncSessionLocal() as s:
        async def q(sql):
            return (await s.execute(text(sql))).all()
        ukuran, wr, lane, ex, breach, wallet, gap, dec = (
            await q(Q_UKURAN), await q(Q_WR), await q(Q_LANE), await q(Q_EXIT),
            await q(Q_BREACH), await q(Q_WALLET), await q(Q_LEDGER_GAP), await q(Q_DECISIONS),
        )

    md = f"""# Garis dasar FUTURES — {TGL}

Dihasilkan otomatis oleh `ops/futures-baseline.py` pada
{datetime.datetime.now().isoformat(timespec='seconds')}.
**Jangan diedit tangan** — jalankan ulang skripnya untuk memperbarui.

Ini keadaan SEBELUM rewrite agentic (PLAN-FUTURES-AGENTIC.md). Fase 7 menjalankan
skrip yang sama untuk membandingkan apel dengan apel.

## Wallet
{tabel(wallet)}
## Ukuran posisi
{tabel(ukuran)}
## Win rate: resmi vs bermakna
{tabel(wr)}
`wr_resmi` memakai definisi `pnl_pct > 0` (bug B1 — scratch selevel fee ikut terhitung menang).
`wr_ge1` / `wr_ge3` = kemenangan yang benar-benar membukukan ≥ $1 / ≥ $3.

## Per lane
{tabel(lane)}
## Alasan keluar (exit_events)
{tabel(ex)}
## Kerugian melebihi rencana (bug B2)
{tabel(breach)}
## Kelengkapan ledger (bug B3)
{tabel(gap)}
## Ledger keputusan
{tabel(dec)}
## Gerbang Fase 7 (harus dilampaui sebelum ukuran naik penuh)

| gerbang | garis dasar hari ini | target |
|---|---|---|
| ekspektasi bersih / trade | negatif | > 0 |
| `tp1_hit` | 4 % | ≥ 30 % |
| scratch (\\|pnl\\| < 2× biaya) | ~35 % | ≤ 10 % |
| WR bermakna (≥ $3) | {wr[0].wr_ge3 if wr else '—'} % | ≥ 35 % |
| rugi > 1,3× risk | {breach[0].n_rugi_lebih_dari_risk if breach else '—'} kejadian | 0 |
| trade tanpa exit_event | {gap[0].trade_tanpa_exit_event if gap else '—'} | 0 |
"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"tersimpan: {OUT}")


asyncio.run(main())
