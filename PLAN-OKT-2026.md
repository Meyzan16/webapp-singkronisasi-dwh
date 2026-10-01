# PLAN-OKT-2026 — inventaris pekerjaan tertunda + fase

Disusun 1 Okt 2026 dari: riwayat sesi, `paper_trades`, `futures_decision_events`
(3.800 kandidat matang sejak 9 Sep), `ops/logs/health.log`, dan rencana lama
(PLAN-FUTURES-AGENTIC, PLAN_ADAPTIVE_ENGINE_BOOST, SCHEDULE_FUTURES, PLAN-UI-SUSULAN).

## Kenyataan per 1 Okt 2026

| | n | P&L | PF |
|---|---|---|---|
| Futures, 14 hari sebelum 18 Sep | 81 | −$3,48 | 0,98 |
| Futures, 18 Sep – 1 Okt | 39 | **−$49,87** | **0,60** |
| Spot opportunity, sebelum 18 Sep | 28 | +$3,89 | 1,08 |
| Spot opportunity, 18 Sep – 1 Okt | 37 | **−$21,92** | **0,60** |

Sejak 21 Sep futures hanya 0–4 trade/hari: LONG dijeda otomatis
(`direction_paused`, 936×), SHORT dimatikan manual (`direction_disabled`).
Gerbang itu **melindungi**: kandidat yang ditahan rata −0,85% di 4 jam; yang
dibuka justru −1,93%.

## P0 — Runtime utuh

| # | Item | Status |
|---|---|---|
| 0.1 | Stack ganda: Docker Desktop menyalakan container `backend/agents/frontend` (kode 5 Jul, `restart: unless-stopped`) di samping stack lokal — dua scanner/auto-trader ke DB yang sama | ✅ dihentikan; `profiles: ["app"]` di compose; `start-night` menghentikan container aplikasi bila hidup |
| 0.2 | 31× "backend tidak merespon" | ✅ didiagnosis: bukan bug kode — log berhenti di tengah scan tanpa traceback; mesin hanya punya *S0 Modern Standby* yang menangguhkan proses desktop |
| 0.3 | Scan futures 132 dtk rata (maks 289) > interval 120 dtk | ✅ fetch berpagar → semaphore; `universe_sec`/`fetch_sec` di log. Terukur: fetch 48–141 dtk = latensi mirror Binance, bukan kode |
| 0.4 | **Downtime 191 jam dari ~300 jam sejak 19 Sep (≈64%)** — task `AgentsTrading-Stop` 07:00 masih aktif + mesin tidur | ⛔ **owner**: nonaktifkan task Stop, matikan sleep saat dicolok |

## P1 — Edge entry futures

Analisis kronologis (latih s/d 22 Sep 20:15, uji sesudahnya; dedup per
simbol+arah per 4 jam → 1.321 kandidat):

- Semesta kandidat: net 4 jam **−0,86% (latih) / −0,98% (uji)**, 37–39% positif.
- **Tak satu pun tersil fitur** (skor, change_24h/1h/30m, RSI, OI, funding, ATR,
  volume, breadth, probabilitas model) positif di latih DAN uji.
- **Skor lebih tinggi lebih buruk**: skor ≥72 −0,96% / −1,23%. Menaikkan
  `agentic_min_score` tidak menolong.
- Hipotesis kebalikan (memudarkan pump) tidak kokoh: +0,13% total, tanda
  berganti tiap minggu; median LONG −0,94% vs rata −0,43% → ekor kanan tebal.

**Kesimpulan:** agen memilih koin yang sudah naik 10–15% dengan RSI 67–74 —
mengejar pump. Tak ada parameter yang bisa disetel untuk membalik itu;
butuh hipotesis sinyal baru. Sampai ada edge terbukti di ledger: **jangan
menaikkan ukuran, jangan mengaktifkan kontribusi skor adaptive (P4).**

Langkah berikut (riset, tanpa efek keputusan):
1. Rekam kandidat dari hipotesis lain secara *shadow* di ledger (mis. pullback
   ke EMA setelah breakout, bukan entry di pucuk) — dinilai setelah ≥300 matang.
2. Ulangi analisis ini tiap 2 minggu dengan skrip yang sama.

## P2 — Exit futures

20 SL rugi sejak 18 Sep: **16 benar** (harga terus turun −5% s/d −16% di 4 jam),
3 berbalik (XTZ, PTB, IOTX). Banyak kena SL dalam 2–13 menit = masuk di pucuk.
Rugi per SL ≈ 1,15× risiko (fee + slippage); outlier COAI breach 5,2%.
**Exit bukan masalahnya.** Tak ada perubahan.

## P3 — Spot opportunity (engine SPOT — butuh izin owner)

Lane `accumulation` (PF 1,92 sebelum 18 Sep): 15 dari 25 penutupan kini
`urgent_rotation`, total +$1,84 (rata +$0,12, ditahan ~29 jam) — posisi dipotong
sebelum matang. Sebelum 18 Sep rotasi rata +$1,9/trade. `bigmover`: 8 SL −$22,60.

⛔ **Keputusan owner**: matikan/perketat `urgent_rotation` untuk `accumulation`?

## P4 — Adaptive engine (PLAN_ADAPTIVE_ENGINE_BOOST Fase B/D/E)

**Ditahan.** Menaikkan bobot/kontribusi skor atas strategi tanpa edge hanya
memperkuat noise. Dibuka kembali bila P1 menemukan edge.

## Rencana lama — status

- PLAN-UI-SUSULAN: U1–U5 selesai.
- SCHEDULE_FUTURES: gate Live & Hari-30 gagal (dicatat 24 Agu); belum layak live.
- PLAN_ADAPTIVE_ENGINE_BOOST: Fase A (validasi forward) gagal 24 Agu → B/C/D/E menunggu edge.
