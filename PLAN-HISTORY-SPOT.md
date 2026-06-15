# AUDIT SPOT — Temuan BUG & Status Eksekusi

> Hasil 9 pass audit (2026-06-11) atas seluruh ekosistem spot: scanner, scheduler,
> monitor, weight updater, balance, opportunity API, history API, WS stream, store,
> UI History + UI Scanner. Total **82 temuan**, dieksekusi 2026-06-12.
>
> Status: ✅ selesai · ⏳ backlog (butuh data/infrastruktur, bukan bug)

---

## §1 — Agent Monitoring Spot (`agents/opportunity/monitor.py`) — 14 BUG, semua ✅

| # | Temuan | Status |
|---|--------|--------|
| 1.1 | Breakeven pasca-TP1 dicatat `sl` → merusak win-rate & training learning | ✅ label `tp1_breakeven`, exclude dari training |
| 1.2 | Close SL mengabaikan gap harga (selalu tepat di SL) | ✅ `min(sl, wick_low)` + slippage |
| 1.3 | `tp2=None` → TypeError → seluruh siklus gagal | ✅ guard `or` + validasi level |
| 1.4 | Balance recalc abaikan `withdrawn_total`, hardcode initial 1000 | ✅ rumus lengkap + DEFAULT_BALANCE |
| 1.5 | Cooldown in-memory dead code (scheduler pakai DB sendiri) | ✅ dihapus |
| 1.6 | `_price_history` bocor memori (simbol closed tak dibuang) | ✅ prune per siklus |
| 1.7 | Commit sekali per siklus — 1 error membatalkan semua close | ✅ per-trade try/except |
| 1.8 | **TERBUKTI LIVE**: batch ticker selalu 400 (spasi di JSON) → 30 req/menit fallback → rate limit 83% | ✅ `separators=(",",":")` |
| 1.9 | `entry_at` kosong → hold dihitung dari 1970 → close paksa salah label | ✅ guard entry_at valid |
| 1.10 | Koneksi DB disandera selama network I/O 15–30 dtk | ✅ pola 2 sesi (baca → network → tulis) |
| 1.11 | SL breakeven tak disinkron ke kolom `stop_loss` | ✅ kolom ikut diupdate |
| 1.12 | Error beruntun membekukan jadwal weight updater (cycle-based) | ✅ jadwal time-based + counter di finally |
| 1.13 | Guard `if close_price:` falsy — SL=0 jadi posisi zombie | ✅ `is not None` + validasi >0 |
| 1.14 | Race manual close vs monitor — status `manual` tertimpa `tp/sl` | ✅ re-cek `status='open'` sebelum apply |

## §10 — Scanner Engine (`scanner.py`) — 8 temuan, semua ✅

| # | Temuan | Status |
|---|--------|--------|
| 10.1 | Semua indikator dihitung dari CANDLE BELUM SELESAI → skor flicker antar scan | ✅ indikator pakai `klines[:-1]`, entry tetap live |
| 10.2 | Skor mentok cap 99 → ranking buntu, conviction gepeng | ✅ `raw_score` tanpa cap untuk ranking+sizing |
| 10.3 | `position_usdt` hasil scan dari $1000 hardcode | ✅ dihapus — sizing hanya dari `compute_spot_sizing` |
| 10.4 | Tanpa rem overbought TF besar (RSI 4h 85 tidak dikurangi) | ✅ RSI 4h >82 skip total, >75 −15 |
| 10.5 | Docstring menipu (95/2.0 vs kode 90/3.5) | ✅ sinkron + endpoint config |
| 10.6 | Gagal ticker = diam tanpa log | ✅ warning + flag `error` di hasil |
| 10.7 | Blacklist duplikat | ✅ |
| 10.8 | Beban API per scan (catatan) | ✅ liquidity filter + batch fixes menurunkan total |

## §12 — PROFITABILITAS — 7 temuan, semua ✅

| # | Temuan | Status |
|---|--------|--------|
| 12.1 | 🔴 Auto-open bisa TANPA konfirmasi arah (squeeze 35pt arah-netral) | ✅ gerbang arah WAJIB: taker ≥0.55 atau EMA bull 1h |
| 12.2 | 🔴 Exit memotong pemenang, membiarkan pecundang (asimetri 1:3.5 hancur) | ✅ profit-exit hanya bila pnl ≥ 50% jarak TP2 |
| 12.3 | 🔴 Wick terlewat — limit sell real PASTI terisi, sim tidak mencatat | ✅ wick-fill kline 1m (SL prioritas bila keduanya) |
| 12.4 | 🔴 Sizing terbalik: posisi terbesar di stop paling rapuh | ✅ cap notional 40% balance |
| 12.5 | Tanpa gerbang regime BTC | ✅ BTC 24h<−3% / EMA 4h bearish → auto-open OFF |
| 12.6 | Breakeven pasca-TP1 terlalu ketat | ✅ SL = entry + 50% jarak TP1 |
| 12.7 | Cooldown asimetris (hanya SL) | ✅ TP juga 45 menit |

## §13 — Sapu Bersih API/scheduler/WS/store — 8 temuan, semua ✅

| # | Temuan | Status |
|---|--------|--------|
| 13.1 | 🔴 Manual close saat Binance down → P&L 0 fiktif diam-diam | ✅ 503 tanpa harga live |
| 13.2 | 🔴 P&L manual close tanpa fee (beda dengan monitor) | ✅ net EXECUTION_COST seragam |
| 13.3 | 🔴 Urutan commit terbalik (balance sebelum trade) | ✅ trade dulu → recalc SUM |
| 13.4 | 🔴 Auto-open pakai harga basi scan (~25 dtk) tanpa validasi | ✅ live price: drift >1% skip, ≤1% re-anchor |
| 13.5 | Race duplikat simbol manual vs auto | ✅ partial unique index + IntegrityError handling |
| 13.6 | 🔴 Positions fetch harga per-simbol tiap panggilan → 150+ req/menit | ✅ batch + cache TTL 8 dtk |
| 13.7 | WS drop snapshot saat queue penuh → "LIVE" tapi basi | ✅ keep-latest |
| 13.8 | Countdown "--:--" pasca clear cache | ✅ |

## §14 — Manajemen Risiko Portofolio — 8 temuan, semua ✅

| # | Temuan | Status |
|---|--------|--------|
| 14.1 | 🔴 API manual open NOL validasi (sl>entry, risk 0.01% lolos) | ✅ Pydantic: 0<sl<entry<tp1≤tp2≤tp3, risk 1–6%, TP2 net>0 |
| 14.2 | 🔴 Reset balance saat posisi open = state korup | ✅ 409 bila ada posisi open |
| 14.3 | Tanpa portfolio heat cap | ✅ total risk terbuka ≤4% balance |
| 14.4 | Tanpa circuit breaker harian | ✅ rugi hari WIB ≤−3% → auto-open jeda |
| 14.5 | Risiko korelasi (BTC+ETH+SOL = 1 taruhan) | ✅ grup beta-BTC maks 1 posisi |
| 14.6 | SL fill tanpa slippage | ✅ 0.1% pada semua SL fill |
| 14.7 | Weight rendah cuma menurunkan skor — tipe busuk tetap lolos | ✅ weight<0.8 n≥10 → DILARANG auto-open |
| 14.8 | Tanpa metrik max drawdown / profit factor | ✅ di summary /history/trades |

## §15 — Biaya Eksekusi & Disiplin — status campur

| # | Temuan | Status |
|---|--------|--------|
| 15.1 | Spread+slippage tidak dimodelkan (biaya real 1.5–2.5× fee) | ✅ `EXECUTION_COST_PCT=0.31%` satu sumber (trading_costs.py) |
| 15.2 | Fee hardcode, tak per-style | ✅ struktur per-style di trading_costs.py |
| 15.3 | TP1 tanpa partial sell — profit nol terkunci saat retrace | ✅ jual 50% di TP1, sisa ride |
| 15.4 | Sizing dari skor (hipotesis), bukan expectancy (bukti) | ⏳ quarter-Kelly aktif setelah n≥30/tipe |
| 15.5 | Tanpa proteksi drawdown dari puncak | ✅ DD>10% dari HWM → risk dipotong setengah |
| 15.6 | Jam sepi tak dikenali | ✅ `entry_hour_wib` disimpan; aturan menunggu data |
| 15.7 | CoinModal fallback | ✅ (lihat 16.4) |

## §16 — Gap-Closure (file terlewat) — 6 temuan, semua ✅

| # | Temuan | Status |
|---|--------|--------|
| 16.1 | 🔴 `analyzer.py` TERLEWAT audit — jalur manual bypass semua disiplin (risk 0.4–8%, R:R tak ditegakkan) | ✅ risk clamp 1.5–5%, R:R≥3.5 ditegakkan + flag `below_standard` + warning UI |
| 16.2 | 🔴 Scan stampede (N request = N scan paralel) + force-scan spam | ✅ single-flight lock + cooldown 60 dtk |
| 16.3 | Analyzer pakai candle berjalan | ✅ |
| 16.4 | 🔴 CoinModal kirim data karangan (confidence 70 palsu) ke trade/training | ✅ fallback netral 50 + label sumber + disable saat gagal |
| 16.5 | Filter "win" menyertakan TP ber-net-negatif | ✅ konsisten `_is_real_win` |
| 16.6 | days hardcode DBHistoryTable | ✅ prop |

## §2/§3/§4/§8 — UI History Spot — semua bug ✅, 2 ⏳

| Temuan | Status |
|--------|--------|
| §2 Posisi terbuka tanpa pagination | ✅ 5/halaman + sort uPnL |
| §3 "PnL $" dari rumus hardcode $1000, margin tak tampil | ✅ `pnl_dollar` tersimpan + kolom Margin (juga diperbaiki di Dashboard) |
| §4 Kalender rolling → ala Binance | ✅ navigasi bulan, nominal per sel, klik hari → detail |
| 8.1 🔴 TIMEZONE: kalender pakai hari UTC, user WIB | ✅ `localDayKey` lokal |
| 8.2 Label "$1,000 start" hardcode | ✅ |
| 8.3 Equity curve buta deposit | ⏳ butuh balance_ledger |
| 8.4 Threshold warna ±$5 hardcode | ✅ relatif 2% balance |
| 8.5 "Maks ~66 posisi" menyesatkan | ✅ teks kebijakan eksplisit |
| 8.6 Normalisasi sinyal UI ≠ updater | ⏳ paket weight_lib |
| 8.7 Housekeeping (ref bocor, O(n²)) | ✅ |

## §11 — UI Scanner — semua ✅

| Temuan | Status |
|--------|--------|
| 11.1 Header UI berbohong (R:R 2.0 vs 3.5, dst) | ✅ render dari `GET /opportunity/config` |
| 11.2 Legend/filter pilihan mati (30pt tak pernah ada) | ✅ dari threshold engine |
| 11.3 Metrik risk-adjusted tak ditampilkan | ✅ R:R · Risk% · TP2-net di kartu |
| 11.4 Ranking by score, bukan EV | ✅ `ev_per_risk` — satu sumber scheduler+UI |
| 11.5 Tanpa badge AUTO / transparansi learning | ✅ 🤖 AUTO + chip ↑/↓x learning |
| 11.6 WS hardcode localhost | ✅ dinamis (spot; futures page menyusul) |
| 11.7 Param mati + liquidity guard | ✅ min quoteVolume $5M |

## §5/§6/§9 — Learning & Pertumbuhan

| Temuan | Status |
|--------|--------|
| 5.1 Data training kotor + konteks tak disimpan | ✅ exclude label kotor; meta: raw_score, weight, EV, regime-gate, jam WIB |
| 5.2 Tangga kasar tanpa smoothing/decay | ✅ Laplace + half-life 7 hari + step cap ±0.1 + confidence scaling |
| 5.3 Combo keys + bobot per-regime | ⏳ menunggu data baru terkumpul |
| 5.4 Exit-regret audit, P(TP1/TP2) dari data, hold-time per tipe | ⏳ menunggu puluhan close |
| 5.5 Learning stats endpoint + pembuktian boost | ⏳ |
| 6.1 🔴 Bobot basi dari 37 trade terhapus masih mem-boost scanner | ✅ reset + prune zombie permanen |
| 6.2 Summary riwayat ≠ balance (manual tak dihitung) | ✅ manual masuk closed + realized $ |
| 6.3 /positions tanpa batas waktu | ✅ default 30 hari |
| 6.4 Generalisasi futures (sizing per-style, weight_lib, prop style UI) | ⏳ fase futures |
| 9.1 Balance recalc baca semua baris per close | ✅ SQL SUM |
| 9.2 Updater load semua trade | ✅ window 90 hari |
| 9.3 Log uvicorn 6MB di git | ✅ untracked + gitignore |
| 9.4 Kunci signal tumbuh tanpa batas | ✅ prune >30 hari |
| 9.5 Model HealthEvent mati | ⏳ keputusan: wire ke DB / hapus |
| 9.6 Equity chart 1 div per trade | ✅ cap 100 |
| 9.7 ⭐ Tabel `balance_ledger` (transaction history ala Binance) | ⏳ backlog prioritas #1 |

## §7 — Anti-debu & seleksi optimal

| Temuan | Status |
|--------|--------|
| Maks 3 posisi, min notional $150/15%, maks 2 open/siklus | ✅ |
| Auto-open & sizing dari skor PRE-weight (putus loop inflasi) | ✅ |
| 29 posisi debu legacy | ✅ selesai via fresh start |
| 7C.6 Rotasi modal (tutup terburuk demi kandidat lebih baik) | ⏳ menunggu data exit-regret agar tak salah rotasi |

---

## REVIEW PASCA-IMPLEMENTASI (2026-06-12/13) — 3 pass, 9 temuan, semua ✅

Setelah eksekusi, kode hasil perubahan di-review ulang tiga kali. Kurva temuan
menurun tajam (4 → 2 → 3, makin kecil bobotnya) = konvergen.

### Pass 1 — review menyeluruh diff
| # | Temuan | Status |
|---|--------|--------|
| R1 | 🔴 Bug §3 menular ke `dashboard/page.tsx` — balance spot & P&L $ masih rumus hardcode $1000, dashboard bisa beda angka dengan History | ✅ dashboard fetch `/balance/spot` + pakai `pnl_dollar` tersimpan |
| R2 | 🟡 `/opportunity/status` countdown basis 900 dtk (15 mnt) padahal interval 3 mnt | ✅ pakai `INTERVAL_SEC` scheduler |
| R3 | 🟡 Mojibake UTF-8 di `OpenPositionsList.tsx` (akibat regex PowerShell) | ✅ ditulis ulang bersih |
| R4 | 🟢 Import `math` tak terpakai di weight_updater | ✅ |

### Pass 2 — rekonsiliasi plan (item terlewat)
| # | Temuan | Status |
|---|--------|--------|
| R5 | §12.7 cooldown pasca-TP belum terpasang | ✅ TP 45 mnt, SL tetap 2 jam (satu query) |
| R6 | §15.5 proteksi drawdown HWM belum terpasang | ✅ DD>10% dari puncak → risk ×0.5; `drawdown_pct` di hasil sizing |

### Pass 3 — fokus scanner + monitor (kalibrasi kejujuran simulasi)
| # | Temuan | Status |
|---|--------|--------|
| R7 | 🔴 SL fill via wick TERLALU PESIMIS — diisi di dasar wick 3 menit, padahal market stop real trigger DI SL + slippage. Bias kebalikan dari bug 12.3, mendistorsi learning | ✅ `fill = max(wick_low, SL×(1−slippage))`, gap tetap dihormati |
| R8 | 🟡 `_filter()` REST membuang `btc_regime` & `error` — WS dapat, REST tidak | ✅ passthrough (verifikasi: `regime=bull` di REST) |
| R9 | 🟢 Baca utuh scanner.py rakitan: urutan gerbang→rem→final benar, semua field baru sampai UI | ✅ bersih |

### Pass 4 — korelasi spot di Dashboard (`dashboard/page.tsx`)
| # | Temuan | Status |
|---|--------|--------|
| R10 | 🔴 "Recent trades" menampilkan trade TERLAMA — API urut DESC, `.slice(-20)` mengambil ekor list = 20 trade terlama; menjalar ke win rate & fallback balance | ✅ sort eksplisit by closed_at desc + slice terbaru |
| R11 | 🔴 Win rate spot beda definisi dengan History: manual ikut dihitung, TP net-negatif dihitung win, dan hanya dari 20 trade (yang salah ambil pula) | ✅ seragam: TP+SL saja, win = TP & pnl>0, dari semua closed di window |
| R12 | 🔴 KPI "Paper Balance" = spot + fut − $1000 — bukan total, bukan PnL; header kontradiksi dengan sub-nya sendiri | ✅ tampil total balance; verifikasi live: $1974 = $1000+$974 ✓ |
| R13 | 🟡 ROI tanpa konteks modal | ✅ label "dari modal $2000" |
| — | Catatan futures (di luar scope spot): `pnl$` recent-trades futures masih rumus estimasi (FutPos belum kirim pnl_dollar) — masuk fase futures | ⏳ |

### Verifikasi runtime terakhir
```
scan   : HBARUSDT score=98 raw=98 EV=3.81 auto=True dir=True rr=4.0 tp2net=+13.87%
monitor: 23 siklus berturut-turut, last_error=null
balance: $1000 | locked $703 | 2 posisi (LINK $303 + XAUT $400) | regime=bull
```

---

## AUDIT DASHBOARD × SPOT (2026-06-13) — 5 temuan baru, belum dikerjakan

> Audit integrasi `dashboard/page.tsx` dengan fitur Spot Scanner dan Spot History.
> Ditemukan saat analisis statik — belum ada fix.
>
> Status: 🔴 bug nyata · 🟡 inkonsistensi · 🟢 minor/dead code

### Pass 5 — Dashboard × Spot Scanner / Spot History

| # | Severity | File & Baris | Temuan | Status |
|---|----------|-------------|--------|--------|
| D1 | 🔴 HIGH | `dashboard/page.tsx:559-562` | **MiniEquity chart Spot Opp garis flat** — semua bar pakai `oppBalance` (nilai akhir statis), bukan running balance per trade. Chart juga hanya muncul kalau `learning` (data futures) tersedia → dependency salah | ✅ selesai (= S5) — gate `oppEquityPoints.length > 1`, running balance kumulatif |
| D2 | 🟡 MEDIUM | `dashboard/page.tsx:565-568` | **Win/Loss counter inkonsisten dengan Win Rate** — counter Win/Loss pakai `oppClosed` (20 trade terakhir), sedangkan Win Rate pakai `oppClosedAll` (semua 30 hari). User melihat angka yang tidak bisa direkonsiliasi | ✅ selesai (= S6) — semua counter pakai `oppClosedAll` |
| D3 | 🟡 MEDIUM | `dashboard/page.tsx:528-533` | **"Next scan" countdown Spot OPP tidak pernah muncul** — `health.scheduler.next_scan_in_min` selalu `undefined` karena `get_state()` scheduler tidak mengembalikan field ini. Field hanya ada di `/opportunity/status` yang tidak di-fetch dashboard. Futures bisa tampil karena fetch `/futures/status` terpisah | ✅ selesai (= S8) — `get_state()` tambah `next_scan_in_min`; dashboard tampil via `health.scheduler.next_scan_in_min` |
| D4 | 🟢 LOW | `dashboard/page.tsx:762-768` | **Futures Agent 2 status hardcoded = Agent 1** — `ok: !!(health?.futures_scanner?.running)` identik untuk kedua row. Backend tidak punya health key terpisah untuk Agent 2 | ✅ selesai — `ok` pakai `futures_scanner.running && agent2_results > 0`; `cycle` dari `futStatus.agent2_results` |
| D5 | 🟢 LOW | `components/SpotPositions.tsx` | **Dead code** — komponen diekspor dari `components/index.ts` tapi tidak diimport di mana pun. Dashboard punya implementasi inline sendiri. Kalau dipakai ulang tidak sengaja → double fetch dengan interval berbeda (60s vs 15s) | ✅ selesai — dihapus dari `components/index.ts` |

---

### Balance Sheet — Spot vs Futures (Binance-style) — 8 temuan baru

> User meminta tampilan balance spot dan futures dipisah seperti Binance:
> **Wallet Balance / Unrealized PnL / Margin Balance / Available / In Order / Realized PnL**.
> Audit ini memetakan gap antara data yang ada dan yang dibutuhkan.

#### FRONTEND — State Management & UI

| # | Severity | File & Baris | Temuan | Status |
|---|----------|-------------|--------|--------|
| B1 | 🔴 HIGH | `dashboard/page.tsx:230` | **Dashboard buang 7 field dari `/balance/spot`** — hanya `balance` yang disimpan ke state (`setSpotBalance`). Field `available`, `locked_margin`, `realized_pnl`, `deposited_total`, `total_pnl`, `open_positions` dibuang. Untuk breakdown Binance-style semua field ini dibutuhkan | ✅ selesai (S1) |
| B2 | 🔴 HIGH | `dashboard/page.tsx:184-196` | **Dashboard tidak fetch `/api/v1/balance/futures` sama sekali** — futures balance hanya dari `learning.balance.current` (simulasi per-request), tidak dari PaperBalance DB. Tidak ada state untuk futures Available / Locked / Realized PnL | ✅ selesai |
| B3 | 🟡 MEDIUM | `dashboard/page.tsx:543-575` | **Spot balance card tidak Binance-style** — hanya tampil total balance + satu angka delta. Tidak ada baris terpisah: `Available`, `In Order (locked)`, `Realized PnL`, `Unrealized PnL` | ✅ selesai |
| B4 | 🟡 MEDIUM | `dashboard/page.tsx:577-618` | **Futures balance card tidak Binance-style** — `learning.balance.current` satu angka saja. Tidak ada: `Available`, `Margin Used`, `Unrealized PnL`, `Realized PnL` terpisah | ✅ selesai |
| B5 | 🟢 LOW | `dashboard/page.tsx:557` | **"Risk $10/trade" hardcoded** — teks muncul statis meski balance sudah berubah. Risk per trade seharusnya dinamis: `balance × 1% = riskDollar` aktual | ✅ selesai (S7) |

#### BACKEND — Data & Endpoint

| # | Severity | File & Baris | Temuan | Status |
|---|----------|-------------|--------|--------|
| B6 | 🔴 HIGH | `agents/futures/monitor.py` (tidak ada) | **Futures tidak punya `_update_paper_balance()`** — Spot monitor memanggil `_update_paper_balance()` setiap posisi tutup → PaperBalance terus diupdate. Futures monitor tidak punya equivalent → baris `PaperBalance` untuk "futures_agent1" di-create sekali ($1000) dan tidak pernah diupdate. Endpoint `/balance/futures` akan selalu return $1000 | ✅ selesai — `_rebuild_futures_paper_balance()` dipanggil tiap siklus + startup rebuild |
| B7 | 🟡 MEDIUM | `backend/app/api/v1/balance.py:173-211` | **`/balance/spot` tidak return unrealized PnL** — Untuk Binance-style "Margin Balance = Wallet + Unrealized", endpoint harus fetch harga live posisi terbuka dan hitung unrealized. Saat ini endpoint hanya return realized balance | ✅ efektif selesai — dihitung di frontend dari `oppOpen[].unrealized_pnl_pct × position_size` |
| B8 | 🟢 LOW | `futures_learning.py:19` vs `balance.py:28` | **Dua konstanta `STARTING_BALANCE = 1000.0` dan `DEFAULT_BALANCE = 1_000.0` di file berbeda** — jika satu diubah (misalnya fresh start $500) yang lain tidak ikut. Satu sumber kebenaran diperlukan | ❌ belum |

---

### Audit SPOT-Only Dashboard (2026-06-13) — 12 temuan, belum dikerjakan

> Fokus eksklusif SPOT. Futures dilewati. Diaudit lapis per lapis:
> state management → UI rendering → backend endpoint.

#### Lapis 1 — Frontend State Management (`dashboard/page.tsx`)

| # | Severity | Baris | Temuan | Status |
|---|----------|-------|--------|--------|
| S1 | 🔴 HIGH | 230 | **`spotBalance` buang 7 field** — `setSpotBalance(...balance)` hanya simpan satu angka. Field `available`, `locked_margin`, `realized_pnl`, `deposited_total`, `total_pnl`, `open_positions` dibuang. Tanpa ini, Binance-style breakdown mustahil dirender | ✅ selesai |
| S2 | 🔴 HIGH | 100–104 | **`pnlDollar()` fallback hardcode `BALANCE_START = $1000`** — rumus notional = `($1000 × 1%) / risk_pct`. Kalau user deposit atau balance berubah, fallback salah. Field `pnl_dollar` dari DB sudah benar, tapi ini backup path yang menyesatkan | ✅ selesai — tambah param `balance=BALANCE_START`, semua call site spot pakai `initialOpp` |
| S3 | 🟡 MEDIUM | 291–296 | **Fallback `oppBalance` mulai dari `BALANCE_START` bukan `initial_balance` API** — kalau `/balance/spot` fail, balance dihitung ulang dari $1000 hardcode bukan dari `initial_balance` + `deposited_total` yang sesungguhnya | ✅ efektif selesai by S1 — `initialOpp = spotBal?.initial_balance ?? BALANCE_START` |
| S4 | 🟢 LOW | 106–109 | **`fmtTime()` didefinisikan tapi tidak pernah dipanggil** — dead code di dalam file 1181 baris | ✅ selesai |

#### Lapis 2 — UI Rendering SPOT (Posisi Terbuka, Balance Card, Scanner)

| # | Severity | Baris | Temuan | Status |
|---|----------|-------|--------|--------|
| S5 | 🔴 HIGH | 559–562 | **MiniEquity chart Spot Opp garis flat** — semua bar memakai `oppBalance` (nilai akhir statis). Chart juga hanya muncul bila `learning` (futures data) tersedia → dependency salah (= D1) | ✅ selesai |
| S6 | 🟡 MEDIUM | 565–568 | **Win/Loss counter pakai `oppClosed` (20 trade terakhir)** — Win Rate di baris 305 pakai `oppClosedAll` (30 hari penuh). Angka Win dan % tidak bisa direkonsiliasi user (= D2) | ✅ selesai |
| S7 | 🟡 MEDIUM | 557 | **"Modal $1,000 · Risk $10/trade" hardcoded** — saat balance $1,200 setelah profit, risk per trade seharusnya $12 (1% aktual). Teks ini tidak pernah update mengikuti `oppBalance` | ✅ selesai |
| S8 | 🟡 MEDIUM | 528–533 | **"Next scan" countdown Spot OPP tidak pernah muncul** — `health.scheduler.next_scan_in_min` tidak ada di response `/health`. Field ini hanya dihitung di `/opportunity/status` yang tidak di-fetch dashboard (= D3) | ✅ selesai |
| S9 | 🟡 MEDIUM | 401–428 | **Posisi SPOT open tidak tampilkan `position_size` (notional) dan `risk_dollar`** — hanya tampil entry, current price, dan unrealized %. Tidak ada info berapa modal yang dipakai di tiap posisi | ✅ selesai — sub-text posisi: `~$400 · Risk $17.1` |
| S10 | 🟡 MEDIUM | 348–374 | **KPI Row masih campur Spot + Futures dalam satu angka** — "Paper Balance" = spot+fut digabung, "Posisi Terbuka" = spot+fut digabung. User meminta dipisah seperti Binance | ✅ efektif selesai by B3/B4 — KPI total + sub breakdown, kartu Binance-style terpisah di bawah |

#### Lapis 3 — Backend SPOT Endpoint

| # | Severity | File & Endpoint | Temuan | Status |
|---|----------|-----------------|--------|--------|
| S11 | 🔴 HIGH | `market.py` · `/market/spot-positions` | **Tidak ada caching — N+2 Binance API calls setiap 15 detik** — setiap poll: 1× account info, 1× all ticker prices, N× `myTrades` per aset (N = jumlah aset). Dengan 5 aset = 7 calls/15 dtk = 28 calls/menit. `myTrades` = weight 10 per call → 200 weight/menit hanya untuk avg buy price yang nyaris tidak pernah berubah | ✅ selesai — `_avg_price_cache` TTL 10 menit per simbol |
| S12 | 🟡 MEDIUM | `market.py` · `_fetch_avg_buy_price()` baris 115 | **FIFO avg buy hanya ambil 500 trade terakhir** — untuk user trading aktif dengan >500 trade per simbol, lot beli yang lebih lama terpotong → avg buy price salah, PnL unrealized meleset | ✅ selesai — limit ditingkatkan ke 1000 (Binance max) |

#### Lapis 4 — Unrealized PnL Spot (Backend → Frontend mismatch)

| # | Severity | File & Baris | Temuan | Status |
|---|----------|-------------|--------|--------|
| S13 | 🟡 MEDIUM | `opportunity.py:422–425` | **Unrealized PnL posisi open tidak kurangi biaya eksekusi** — backend hitung: `(current - entry) / entry × 100`. Monitor saat close pakai `- EXECUTION_COST_PCT (0.31%)`. Akibatnya: posisi open terlihat +0.31% lebih untung dari yang akan didapat saat close. Inkonsistensi antara live display dan hasil aktual | ✅ selesai — `- EXECUTION_COST_PCT` ditambahkan ke rumus unrealized |

#### Mapping dampak per section dashboard

| Section | Bug | Dampak |
|---------|-----|--------|
| §2 KPI Row | S10 | Balance & posisi spot+fut tidak dipisah |
| §3 Posisi Terbuka | S9, S13 | Notional hilang; unrealized terlalu optimis 0.31% |
| §3 Scanner Status | S8 ✅ | Countdown Spot OPP tidak pernah muncul |
| §4 Spot Balance Card | S1 ✅, S5 ✅, S6 ✅, S7 ✅ | Chart flat; counter inkonsisten; risk teks statis; tidak bisa Binance-style |
| §4 Fallback logic | S2, S3 | Balance salah bila API gagal |
| §6 Real Holdings | S11, S12 | Rate limit risk; avg buy price bisa salah |

---

#### Mapping Binance-style vs Ketersediaan Data Saat Ini

| Field Binance | Spot Paper | Tersedia? | Futures Paper | Tersedia? |
|--------------|------------|-----------|---------------|-----------|
| Wallet Balance | `balance` dari PaperBalance DB | ✅ ada, tapi tidak di-fetch penuh di dashboard | `learning.balance.current` (simulasi) | ⚠️ simulasi saja, tidak di-persist |
| Unrealized PnL | Hitung dari posisi open × harga live | ❌ endpoint tidak return ini | Hitung dari posisi open futures | ❌ tidak ada |
| Margin Balance | Wallet + Unrealized | ❌ | Wallet + Unrealized | ❌ |
| Available Balance | `available` dari PaperBalance | ✅ ada di API, ❌ dibuang di frontend | Tidak ada | ❌ |
| In Order (Locked) | `locked_margin` dari PaperBalance | ✅ ada di API, ❌ dibuang di frontend | Tidak ada | ❌ |
| Realized PnL | `realized_pnl` dari PaperBalance | ✅ ada di API, ❌ dibuang di frontend | Tidak ada di DB | ❌ |
| Deposited | `deposited_total` | ✅ ada di API, ❌ dibuang di frontend | Tidak ada | ❌ |

---

### Re-audit Dashboard — 2026-06-13 (sesi lanjutan)

Audit ulang penuh `dashboard/page.tsx` setelah sesi sebelumnya. Dua temuan baru yang belum tercatat:

| # | Severity | File & Baris | Temuan | Status |
|---|----------|-------------|--------|--------|
| N1 | 🟡 MEDIUM | `page.tsx:357` | **ROI modal hardcoded `BALANCE_START * 2 = $2000`** — sub-text KPI "Combined PnL" hitung ROI dengan `(BALANCE_START * 2)` sebagai denominator. Jika `initial_balance` berubah (deposit, reset), ROI tetap dihitung dari $2000 bukan modal sebenarnya. Konsekuensi dari S1 (field `initial_balance` dibuang) | ✅ selesai |
| N2 | 🟡 LOW | `page.tsx:718` | **Hardcoded "Scans 100 pairs tiap 15m" — interval nyata 3 menit** — di panel System Health, `sub: "Scans 100 pairs tiap 15m"` tapi `INTERVAL_SEC = 3 * 60` di backend (bukan 15 menit). Scanner Status card di bawahnya menampilkan `{health.scheduler.interval_minutes}m` = `3` dengan benar. UI inkonsisten: satu bilang 15m, satu bilang 3m | ✅ selesai — pakai `health?.spot_scanner?.interval_minutes ?? 3` |
| N3 | ⚪ MINOR | `page.tsx:106–109` | **`fmtTime()` didefinisikan tapi tidak pernah dipanggil** — fungsi helper `fmtTime(ts: number \| null)` ada di baris 106, tapi tidak ada satu pun tempat dalam file yang memanggilnya. `fmtRelTime` (baris 111) digunakan. Dead code ke-2 selain `SpotPositions.tsx` (D5) | ✅ selesai |

Konfirmasi bug lama yang masih aktif (re-verified dalam audit ini):
- **S5/D1 (line 559)**: `{learning && <MiniEquity />}` — chart spot gated pada data futures, bukan pada `oppClosed.length`
- **S6/D2 (line 566-567)**: Win/Loss counter dari `oppClosed` (20 last), Win Rate dari `oppClosedAll` (semua 30d)
- **S7 (line 557)**: "Modal $1,000 · Risk $10/trade" hardcoded tidak mengacu balance API
- **S8/D3 (line 528)**: `health?.scheduler?.next_scan_in_min` selalu `null` — field tidak ada di `get_state()`
- **S1 (line 230)**: `setSpotBalance(({ balance })` buang 7 field dari balance API

---

## Ringkasan akhir

- **BUG: 67/67 dari audit + 13/13 dari review pasca-implementasi (4 pass) = 80 selesai (100%)** —
  termasuk 2 terbukti live (1.8 batch ticker, 6.1 bobot hantu), kalibrasi SL wick-fill (R7),
  dan korelasi spot di Dashboard (R10–R13, terverifikasi di browser)
- **AUDIT DASHBOARD (2026-06-13): 5 temuan baru (D1–D5) — belum dikerjakan** —
  D1 kritis (chart flat), D2–D3 medium (counter inkonsisten + countdown hilang), D4–D5 minor
- **BALANCE SHEET Binance-style (2026-06-13): 8 temuan baru (B1–B8) — belum dikerjakan** —
  B1–B2 kritis (state dibuang + futures tidak di-fetch), B3–B4 medium (UI tidak Binance-style),
  B6 kritis backend (futures tidak punya balance updater → selalu return $1000)
- **AUDIT SPOT-ONLY DASHBOARD (2026-06-13): 13 temuan baru (S1–S13) — belum dikerjakan** —
  S1 kritis (state buang 7 field), S5 kritis (chart flat), S11 kritis (no cache = rate limit risk),
  S2/S7/S8/S9/S10/S13 medium (hardcode, countdown hilang, notional hilang, unrealized bias)
- **RE-AUDIT DASHBOARD (2026-06-13 sesi lanjutan): 3 temuan baru (N1–N3) — N1 ✅ N3 ✅ selesai, N2 belum** —
  N1 ✅ (ROI denominator pakai `initial_balance` aktual), N2 belum (label "15m" salah), N3 ✅ (`fmtTime` dead code dihapus)
- **Improvement: 7 selesai saat eksekusi (termasuk 12.7 + 15.5), 8 backlog** —
  semuanya butuh data history baru atau infrastruktur (ledger/weight_lib), bukan kerusakan
- **Fresh start 2026-06-12**: semua trade & bobot spot dihapus, balance $1000; siklus pertama
  membuka LINK $303 + XAUT $400 (cap 40% bekerja), maks 2/siklus, regime bull terdeteksi
- **Bonus di luar plan**: futures scheduler `a1_results` NameError (auto-open futures mati
  diam-diam) + dashboard rumus hardcode $1000 — keduanya diperbaiki

**Backlog berikutnya (urutan rekomendasi):** balance_ledger (9.7) → learning stats endpoint (5.5) → combo keys/regime (5.3, setelah ~50 trade) → exit-regret + rotasi modal (5.4+7C.6) → quarter-Kelly (15.4, setelah n≥30) → generalisasi futures (6.4).
