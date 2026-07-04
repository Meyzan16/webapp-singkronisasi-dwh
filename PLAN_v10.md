# PLAN_v10 — Dynamic Profit Ladder + Ratcheting Trail (SPOT)
### "Ride winner sampai TP-n (1000%), tapi jangan pernah kehilangan profit"

Tanggal: 2026-07-03
Fokus: `agents/opportunity/monitor.py` (exit engine SPOT) + tampilan posisi.
Tujuan owner (2 kalimat): **(1)** kalau coin lari besar, ikut naik terus — TP1, TP2, …
TP-n dinamis dari sinyal monitor (flow/on-chain) + TA, bukan berhenti di TP2. **(2)**
profit yang sudah didapat **tidak boleh hilang** — setiap kenaikan dikunci bertahap.

---

## 0. Analisis — kenapa sekarang "cuma TP 20%"

Alur exit L1 di [monitor.py:607-665](agents/opportunity/monitor.py):

| Rung | Perilaku sekarang | Masalah |
|---|---|---|
| **TP1** | jual **50%**, SL naik ke entry + 50%×(TP1−entry) | ✅ oke (kunci sebagian) |
| **TP2** | **`elif eff_high >= tp2:` → tutup 100%** (`tp2_hit`) | 🔴 **INI CAP-NYA.** Runner mati di TP2 (+20%). Coin 1000% tetap ditutup di +20%. |
| **TP3** | tutup 100%, ATAU G5-extend → trailing (kalau score≥75 & vol≥1.5) | 🟡 hanya coin dengan TP3 yang bisa lanjut; jendela G5 sempit & baru di TP3 |
| Trailing | `momentum_chase`: ride sampai EMA9<EMA21 (4h) patah struktur | ✅ mekanisme "ride" sudah ada tapi **jarang terpakai** |

**Diagnosa:** mesin "ride winner" **sudah ada** (mode `momentum_chase` + `_compute_trailing_sl`
+ profit-lock tiers), tapi mayoritas trade **tak pernah sampai ke sana** karena TP2 menutup
100% lebih dulu. Yang perlu diubah: **ladder bertingkat scale-out** (bukan all-or-nothing di
TP2) + **runner yang selalu di-trail** + **rung dinamis TP4…TP-n** yang lahir saat harga
naik. THE/USDT di screenshot (TP2 +20%, R:R 1:4) adalah contoh persis: begitu +20%, habis.

**Catatan "on-chain":** yang tersedia di monitor saat ini = **flow dari kline**
(`_taker_ratio`, volume ratio, CVD-like) + TA (score live, EMA, RSI). On-chain sejati
(exchange netflow, whale, holder) **belum ter-wire** — butuh sumber data eksternal.
Rencana ini **tidak diblokir** oleh itu: "still-strong gate" pakai flow+TA yang ada
sekarang, dengan **hook** siap-pasang untuk on-chain sejati di P5 (opsional).

---

## 1. Prinsip Desain (2 janji owner → 2 mekanisme)

**Janji A — "profit tidak boleh hilang"** → **Ratchet Floor** yang hanya bergerak NAIK:
- Begitu profit ter-realisasi di sebuah rung (scale-out), itu **uang di tangan** — permanen.
- SL sisa posisi (runner) = trailing yang **monoton naik** (`max(current_sl, candidate)`),
  tak pernah turun. Setelah TP1: floor ≥ entry (mustahil rugi nominal pada runner).
- Profit-lock tiers tetap sebagai jaring: kalau harga jatuh dari puncak, kunci.

**Janji B — "ride sampai TP-n / 1000%"** → **Dynamic Ladder + Runner**:
- Scale-out **sedikit-sedikit** di tiap rung (bukan 100%): sisakan "runner" yang ikut lari.
- Rung TP4, TP5, … **TP-n dibuat on-the-fly** tiap kali harga menembus (+1×ATR / +step%),
  selama **still-strong gate** (flow+TA) masih hijau. Tidak ada batas jumlah rung.
- Kalau gate melemah → trail dirapatkan (ambil lebih banyak), tidak menebak-nebak puncak.

---

## 2. Rancangan Ladder (keputusan diambil)

**Scale-out fraction per rung** (sisakan runner untuk pump besar):

| Rung | Jual | Sisa runner | Aksi floor |
|---|---|---|---|
| TP1 (1×risk) | 30% | 70% | SL → entry + 50% gain TP1 |
| TP2 (2×risk) | 20% | 50% | SL → entry (breakeven murni, runner bebas rugi) |
| TP3 (3×risk) | 15% | 35% | **Konversi ke trailing runner** (bukan tutup 100%) |
| TP4…TP-n (+1×ATR tiap rung) | 5% tiap rung | turun perlahan | trail ratchet naik tiap rung |
| Runner floor | — | min ~15% ditahan | ride sampai struktur patah / gate merah |

> Ganti perilaku lama `elif eff_high >= tp2: tutup 100%` → **partial 20% + naikkan floor +
> lanjut**. Ini inti perbaikan. TP3 lama (tutup 100%) → **selalu** konversi trailing (buang
> syarat G5 sempit; ganti dengan still-strong gate yang lebih inklusif).

**Still-strong gate (hijau = lanjutkan ride & lahirkan rung baru):**
- Skor live ≥ ambang lane − buffer (mis. ≥55 untuk bigmover), DAN
- `taker_ratio` ≥ 0.5 (beli masih dominan), DAN
- volume ratio ≥ 1.2 (belum sepi), DAN
- struktur 4h utuh (EMA9 ≥ EMA21×0.995).
- **Merah** (salah satu gagal) → rapatkan trail ke `max(EMA21*0.995, swing_low)` & stop
  buat rung baru; runner keluar saat trail kena.

---

## 3. Fase Eksekusi

```
P1 Ladder scale-out inti  →  P2 Rung dinamis TP4..n  →  P3 Ratchet floor & lock
   ↓
P4 Tampilan posisi (ladder + banked + runner + trail)  →  P5 (opsional) hook on-chain
```

### PHASE 1 — Ladder scale-out inti (ganti cap TP2) 🔴
- **A1** Refactor blok L1 TP: TP2 dari "tutup 100%" → **partial 20% + floor→breakeven +
  set runner**. Pertahankan `remaining_fraction` sebagai sumber kebenaran ukuran runner.
- **A2** TP3 → **selalu** konversi ke mode trailing (`entry_mode=momentum_chase`,
  `tp_extended=True`), buang syarat G5 ketat; catat `close_reason` hanya saat runner benar2
  keluar (biar clean-WR PLAN_v8 tetap benar — scale-out ≠ close).
- **A3** Dukung **multi-partial** di `paper_trader`/monitor: akumulasi realized dari tiap
  rung (`banked_dollar += slice`), simpan `ladder: [{rung, price, frac, pnl$}]` di meta.

### PHASE 2 — Rung dinamis TP4…TP-n 🔴
- **B1** Generator rung: `next_rung = last_rung_price + max(1×ATR14(1h), step_pct×entry)`.
  Saat `eff_high ≥ next_rung` DAN gate hijau → jual 5%, catat rung, naikkan trail, ulangi.
  Tak ada batas jumlah (TP4, TP5, … TP-n).
- **B2** Anti-overtrade: minimal jarak antar-rung (≥0.75×ATR) & minimal notional slice
  (hormati min-notional exchange, PLAN_v6 P6) supaya tak jual debu.
- **B3** Kalau gate merah saat rung baru would-fire → **jangan** buat rung; biarkan trail
  yang urus exit (ambil sisa runner sekaligus saat trail kena).

### PHASE 3 — Ratchet floor & lock (janji "tak hilang") 🟡
- **C1** Satukan tiga pengunci jadi satu **floor monoton**: `sl = max(sl, breakeven_after_TP,
  trailing_sl, profit_lock_tier)` — **hanya boleh naik**. Uji invariant: `new_sl ≥ old_sl`.
- **C2** Perketat profit-lock untuk pump besar: tambah tier tinggi (mis. peak≥100% → lock 85%,
  peak≥300% → lock 90%) supaya coin 1000% tak balik banyak sebelum keluar.
- **C3** Guard: floor tak pernah > harga sekarang (hindari instant-stop saat spike-wick).

### PHASE 4 — Transparansi tampilan posisi 🟢
- **D1** `OpenPositionCard`: ganti "TP1/TP2 statis" → **ladder hidup**: rung tercapai (✓
  banked $) vs rung berikut (target), **Runner: X% tersisa**, **Trail SL** sekarang +
  **Locked profit $** (tak bisa hilang).
- **D2** Badge "🏃 Riding" saat runner aktif di trailing; tooltip alasan gate (hijau/merah).
- **D3** History: `close_reason` runner keluar = `trail_exit`/`structure_broken` (sudah ada)
  — tambah ringkasan "banked dari N rung + runner" di detail baris.

### PHASE 5 — Hook on-chain sejati (OPSIONAL, kalau ada sumber data) 🟢
- **E1** Interface `onchain_signal(symbol) -> {netflow, whale_bias, holder_delta}`; kalau
  tak tersedia → gate jatuh ke flow+TA (tanpa error). Tanpa vendor data, tetap fungsional.

---

## 4. Keputusan yang Sudah Diambil (tak perlu konfirmasi)
| Isu | Keputusan | Alasan |
|---|---|---|
| All-or-nothing di TP2? | **Ganti jadi scale-out ladder** | Ini akar "cuma TP 20%" |
| Batas jumlah TP? | **Tak ada** — rung dinamis TP4…TP-n via ATR + gate | Owner minta "sampai TP10 kalau ada" |
| Cara "tak hilang profit"? | **Floor monoton naik + realized per-rung permanen** | Realized = uang di tangan; runner tak bisa turun di bawah trail |
| Nebak puncak? | **Tidak** — ride selama gate hijau, exit saat trail/struktur | Hindari menebak top 1000% |
| On-chain sejati wajib? | **Tidak (P5 opsional)** | Belum ada sumber data; flow+TA sudah cukup untuk gate |
| Runner minimal? | **~15% ditahan sampai struktur patah** | Selalu ada "tiket" ke pump ekstrem |

## 5. Risiko & Mitigasi
- **Fee/slippage dari banyak partial** → B2 batasi jarak & notional per slice; hormati
  min-notional. Fee sudah dihitung (`EXECUTION_COST_PCT`).
- **Whipsaw (trail kena lalu lanjut naik)** → trail pakai ATR/swing-low, bukan persen ketat;
  runner kecil jadi kerugian opportunity terbatas.
- **Clean-WR PLAN_v8 tercemar** → scale-out **bukan** close; hanya exit runner terakhir yang
  di-bucket. Reason baru (`trail_exit`) dipetakan (lanjut kerja PLAN_v9 close-reason map).
- **Backtest dulu** → idealnya replay data historis sebelum aktif live (learning/backtester).

## 6. Prasyarat
- Monitor sudah punya: `remaining_fraction`, `peak_pnl_pct`, `_compute_trailing_sl`,
  `_taker_ratio`, score live (`_get_current_spot_score`). ATR14(1h) perlu ditambah (kecil).
- Paper trader perlu dukungan **multi-partial** (saat ini partial TP1 tunggal) — bagian A3.
