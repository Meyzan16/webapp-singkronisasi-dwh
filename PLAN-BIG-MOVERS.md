# PLAN-BIG-MOVERS.md — Sisa Pekerjaan

**Status**: Phase 0–6, BC1–BC4 (H1), EC1–EC6 (H3), B0.1–B6.3 bug mitigations,
dan capability gaps G13–G19, G21, G23, G24 **sudah terimplementasi dan terverifikasi**.

File ini sekarang hanya berisi item yang **belum dikerjakan** + gate final untuk go-live.

Untuk konteks lengkap (audit awal, semua phase, semua bug yang sudah di-fix),
lihat git history sebelum commit pembersihan ini.

---

## Sisa Pekerjaan (Pre-Live Trading Only)

User masih pada tahap paper backtest $1000 simulasi — kedua item di bawah ini
TIDAK blocking untuk paper, hanya wajib sebelum deposit real money.

### G22 — API Rate Budget Tracking (Wajib Pre-Live)

Binance: 2400 weight/menit (signed), 6000/menit (public). Pemakaian estimasi:
- Main scan: ~941 weight/cycle
- Funding refresh (every 10 cycles): +20
- Monitor: ~50 per cycle
- BM3 second pass: +400-500
- Total ~1600 weight/menit → buffer 33%. **Tidak ada hard tracking.**

**Implementasi**:
- File: `backend/app/services/rate_limit_tracker.py` (NEW)
- Track weight per endpoint dari response header `X-MBX-USED-WEIGHT-1M`
- Threshold warning > 1800/min, emergency degrade > 2100/min (skip non-critical fetches)
- Display di Health panel

### G20 — News/Event-Driven Move Filter (Highly Recommended)

Coin pump 50% bisa karena listing news, partnership announcement, ETF approval.
Sering reverse cepat setelah euforia 1-4 jam.

**Implementasi**:
- Tag `is_news_driven` di `big_mover_log` (manual atau via CryptoPanic/CoinMarketCal API)
- Di `agent_bigmover`: kalau `is_news_driven == True` AND age < 2h → position size halved (risk_pct 0.25%)

---

## Gate Final (Go-Live Checklist)

Sebelum switch dari paper ke real money:

- [ ] Paper trading sustained WR ≥ 50% minimum 3 minggu × 100 closed trades
- [ ] Max DD weekly < 10%
- [ ] Backtest weekly konsisten 2 minggu berturut-turut
- [ ] G22 rate budget tracker live
- [ ] G20 news filter (opsional tapi disarankan)
- [ ] Lanjut ke [PLAN-LIVE-TRADING.md](PLAN-LIVE-TRADING.md) Phase 1 (Testnet)

---

## KPI Tracking (Validate Paper Performance)

Setiap minggu, hitung dan display di frontend Analytics tab:

| KPI | Target | Source |
|-----|--------|--------|
| Big Movers Captured % | ≥ 30% dari coin ≥20% mover | big_mover_log |
| False Positive Rate | < 25% | trades closed SL / total opens |
| Average Hold Time | < 12 jam (Big Mover Lane) | trade.closed_at - entry_at |
| Average Profit Per Win | ≥ 5% net | pnl_pct avg status="tp" |
| Average Loss Per Loss | ≤ 3% net | pnl_pct avg status="sl" |
| Win Rate per Lane | ≥ 50% | per style |
| Capital Utilization | 60-85% | (locked + risk) / wallet |
| Missed Opportunity $ | < 5× actual profit | sum would_be_pnl untuk status="missed" |

Alert kalau ada KPI red 2 minggu konsekutif.
