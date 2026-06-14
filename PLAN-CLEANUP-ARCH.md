# PLAN-CLEANUP-ARCH.md — Rapikan Framing "3 Agent" + Refactor Halaman Arsitektur

> **Jenis dokumen:** analisis & rancangan (narasi). **TIDAK ada kode** di sesi ini.
> Disusun setelah P1-P7 selesai. Tiga fokus dari user:
> 1. Re-cek BUG P1-P7 (sisa?)
> 2. Rapikan **semua hal yang masih membingkai "3 agent"** → sekarang konsepnya **1 agent Scanner + 1 agent Monitor**
> 3. Refactor **halaman arsitektur** agar mencerminkan SPOT + FUTURES yang sudah di-refactor & di-bugfix
>
> **Status:** `❌ BELUM` semua (dokumen rencana). Konvensi: ✅ SELESAI · 🔧 PROSES · ❌ BELUM

---

## 1. Re-cek BUG P1-P7 (hasil audit ulang)

### 1.1 Verifikasi otomatis (grep) — BERSIH
| Cek | Hasil |
|-----|-------|
| Dedup per-agent (`style == agent`) | ✅ tidak ada (global) |
| SL floor lama (`risk_pct < 0.3`) | ✅ tidak ada |
| `calc_leverage` tanpa risk_pct | ✅ tidak ada |
| `event=event` (structlog crash) | ✅ tidak ada |
| `get_cached_regime` di scan agent | ✅ tidak ada (per-coin) |
| List backend 2-agent (tanpa agent3) | ✅ tidak ada |
| Pola label biner `agent1?:else` abaikan agent3 | ✅ tidak ada |

### 1.2 Validasi runtime P7 (setelah reset DB) — LULUS
- **L25 (flood new-listing):** ditemukan & diperbaiki saat P7 → `added_new_listings count=1` (sebelumnya **671**). Akar: binance.bh **mengabaikan param `symbols`** di `/ticker/24hr` → difilter client-side.
- **Dedup global (L1):** `opened=1 pool=6`, 0 duplikat symbol di DB.
- **Leverage↔SL (L6/L7):** CRDO lev **9** SL **1.5%**, PORTAL lev **4** SL **2.84%** — tak ada lagi 12-15x + SL 0.3%.
- **Sizing (L4/L9):** risk_dollar ~**$11.94 (~1.2%)**, notional **796** (tak membengkak).
- **setup_type:** pre_move / momentum ter-tag.

### 1.3 BUG SISA DITEMUKAN (belum tertangani)

| ID | Severity | Lokasi | Temuan |
|----|----------|--------|--------|
| **UI-9** | 🟡 MEDIUM | [FuturesTab.tsx:554,587,767](frontend/src/features/history/components/FuturesTab.tsx:554) | Masih ada label **"Agent 1 — AI" / "Agent 1 AI"** di Monitor sub-tab (breakdown + 2 panel open-position). Screenshot user mengonfirmasi "Agent 1 — AI" tampil. Re-audit sebelumnya melewatkan 3 spot ini. Harus → "Agent 1 — Pre-Gainer" |
| **L26** | 🟢 LOW | [data.py _COMMODITY](agents/futures/data.py) | `XAUUSDT` (emas) lolos filter komoditas (`_COMMODITY` punya "GOLD"/"XAUT" tapi base XAUUSDT = "XAU" tak ada). Screenshot: XAU ke-open 12x. Emas tak merespons TA kripto → kandidat noise. Tambah "XAU" ke `_COMMODITY` |

> Catatan: XAU 12x SL 0.5% di screenshot adalah trade TERCEMAR lama (era 671-pairs, pra-reset), bukan hasil logika baru. DB sekarang bersih.

---

## 2. Rapikan Framing "3 Agent" → "1 Scanner + 1 Monitor"

### 2.1 Masalah konsep
Refactor P2 menyatukan **orkestrasi** (1 pipeline auto-open, dedup global, ranking global) TAPI **UI masih membingkai 3 agent terpisah**: 3 tab, 3 panel, "Dipisah per agent", filter per-agent. Ini bertentangan dengan model "1 Scanner + 1 Monitor" yang user inginkan.

Internal tetap punya 3 lane (futures_agent1/2/3) untuk **atribusi win-rate** — itu OK. Yang dirapikan adalah **presentasi user-facing**: dari "3 Agent" → "1 Scanner, 3 lane setup_type" (Pre-Move / Momentum / New-Listing).

### 2.2 Catalog framing "3 agent" yang perlu dirapikan

| # | Lokasi | Framing sekarang | Jadi |
|---|--------|------------------|------|
| C1 | [scanner/page.tsx](frontend/src/features/scanner/page.tsx) tab `activeAgent` | 3 tab "Agent 1/2/3" | 1 Scanner + filter **setup_type** (Semua / Pre-Move / Momentum / New) |
| C2 | [FuturesTab.tsx:749-754](frontend/src/features/history/components/FuturesTab.tsx:749) | "Posisi Terbuka — **Dipisah per agent**" + 3 panel | 1 daftar posisi + badge setup_type per baris |
| C3 | FuturesTab Monitor breakdown (3 kotak agent) | "Agent 1 AI / Agent 2 / Agent 3" | breakdown per setup_type (Pre-Move/Momentum/New) |
| C4 | FuturesTab `agentFilter` | filter agent1/2/3 | filter setup_type |
| C5 | FuturesAnalytics head-to-head | "Agent 1 vs 2 vs 3" | per setup_type (atau tetap 3 lane tapi judul "Lane Performance") |
| C6 | Dashboard status panel + health cards | 3 kartu "Agent" | 1 "Futures Scanner" + rincian lane |
| C7 | **UI-9** label "Agent 1 — AI" | stale | "Pre-Gainer" (atau hilangkan "Agent N", pakai nama lane) |

> **Keputusan desain yang perlu user konfirmasi:** apakah hapus total kata "Agent 1/2/3" dari UI dan ganti dengan nama lane (Pre-Move/Momentum/New-Listing)? Atau pertahankan "Agent" sebagai label lane? Rekomendasi: **pakai nama lane** ("Pre-Gainer", "Accumulation"→gabung ke Pre-Move, "Momentum", "New-Listing") karena itu inti keputusan "1 scanner".

### 2.3 Catatan: Pre-Move = gabungan agent1+agent2
Sejak analisis awal, agent1 (Pre-Gainer) ≈ agent2 (Accumulation) — keduanya "sebelum gerak". Di UI 1-scanner, keduanya jadi satu lane **Pre-Move**. Internal boleh tetap 2 fungsi skoring, tapi user lihat 1 lane.

---

## 3. Refactor Halaman Arsitektur (SPOT + FUTURES)

[architecture/page.tsx](frontend/src/features/architecture/page.tsx) **sangat stale** — masih menggambarkan arsitektur PRA-refactor. Harus ditulis ulang.

### 3.1 Konten stale yang salah (harus dikoreksi)
| Baris | Stale | Realita sekarang |
|-------|-------|------------------|
| 47, 386 | `agentTab`/tabs hanya "Futures Agent 1/2" | 1 Scanner (3 lane) + 1 Monitor |
| 62 | "Auto-Trade score ≥ 80 · threshold 85 ranging · Max 5 per agent" | score ≥ **72 adaptif (70-77)** · +5 ranging · **Max 6 global** |
| 66-67 | "Agent 1 (AI) vs Agent 2 (T0-T4)" · "Open Positions Terpisah per Agent" | per setup_type, 1 wallet, dedup global |
| 73-115 | deskripsi "Futures Agent 1 (AI Knowledge)" + "Agent 2 (T0-T4)" | Pre-Move / Momentum / New-Listing lanes |
| 341, 358-359 | "AI + T0-T4", "Agent 1 — AI / Agent 2 — T0-T4" | nama lane baru |
| 460-466, 524-525 | diagram "Agent 1 / Agent 2 (T0-T4)" | diagram 1 Scanner → 3 lane → ranking global → dedup → 1 wallet |
| 776, 785, 788 | "MAX_AUTO_POSITIONS=5 per agent · score>=80" | 6 global · 72 adaptif |

### 3.2 Yang harus DITAMBAH ke halaman arsitektur
**FUTURES (pasca P1-P7):**
- 1 Scanner: lane Pre-Move / Momentum / New-Listing, ranking global + dedup global per-symbol (cross-margin)
- SL floor sadar-leverage (min 1.5% / 0.8×ATR) + rekonsiliasi leverage↔SL (margin loss ≤25%)
- Sizing: notional cap 1.5× wallet, risk 1% tak ditimpa margin-cap
- 1 Monitor: wick detection 1m, SL+ lifecycle, liq-guard realistis, TP1 partial kecilkan size, expired masuk balance
- Risk gate: RAR_MIN_TRADES 12, regime per-coin
- Learning: recency 30 hari + warm-start dari DB
- Data: new-listing lane (onboardDate), liq proxy (bukan USDT nyata)

**SPOT (pasca refactor sebelumnya — R1-R8):**
- MAX_AGE_DAYS 7, stagnant rotation, auto-open 85, momentum fast-track, max-opens 3, cooldown TP 20m, momentum priority scan + chase scoring

**Daftar BUG** di halaman: ganti list lama (B1-B7 spot) → ringkasan 32 bug futures (L1-L25 + UI) yang sudah ✅, link ke PLAN-FUTURES-LIVE.md.

### 3.3 Sumber kebenaran untuk penulisan ulang
- Futures bugs & fixes: [PLAN-FUTURES-LIVE.md](PLAN-FUTURES-LIVE.md)
- Arsitektur target: [PLAN-FUTURES-REFACTOR.md](PLAN-FUTURES-REFACTOR.md)
- Spot: commit `feat(spot-p1..p3)` + [PLAN-HISTORY-SPOT.md](PLAN-HISTORY-SPOT.md)

---

## 4. Urutan Eksekusi (saat disetujui — belum dikerjakan)

| # | Langkah | Status |
|---|---------|--------|
| CU-1 | UI-9: ganti "Agent 1 — AI" → "Pre-Gainer" (3 spot FuturesTab) | ❌ BELUM |
| CU-2 | L26: tambah "XAU" ke `_COMMODITY` filter | ❌ BELUM |
| CU-3 | Rapikan framing 3-agent → 1-scanner (C1-C7) — **butuh konfirmasi desain §2.2** | ❌ BELUM |
| CU-4 | Refactor halaman arsitektur (§3) — FUTURES + SPOT pasca-refactor | ❌ BELUM |

> CU-1 & CU-2 = bugfix cepat (bisa langsung). CU-3 = perubahan UX besar (perlu keputusan: hapus kata "Agent" atau tidak). CU-4 = penulisan ulang dokumentasi.
