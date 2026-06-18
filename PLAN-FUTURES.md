# PLAN-FUTURES.md — Audit Arsitektur Fitur Futures

> Audit statik seluruh layer fitur Futures: data, agent logic, scheduler,
> auto trader, monitor, backend API, dan frontend.
> Status: 🔴 bug nyata · 🟡 inkonsistensi · 🟢 minor/dead code

---

## Pass 1 — Data Layer (`agents/futures/data.py`)

| # | Severity | File & Baris | Temuan | Status |
|---|----------|-------------|--------|--------|
| F1 | 🟡 MEDIUM | `data.py:96-121` | **Liquidation proxy bukan data asli** — `_fetch_liquidations` pakai `globalLongShortAccountRatio` sebagai proxy, bukan `/fapi/v1/forceOrders` (butuh auth). Nilai dikali `1_000_000` menghasilkan angka synthetic tanpa satuan USDT nyata. Agent 1 score bonus/penalty liquidation bisa misleading | ❌ belum |
| F2 | 🟢 LOW | `data.py:17` | **`CANDLE_LIMIT = 100`** — cukup untuk semua indikator (BB=20, Wyckoff=30, EMA50=50), tapi tidak ada guard jika Binance return < 50 candle (simbol baru/delisted bisa return sedikit) | ❌ belum |

---

## Pass 2 — Agent Logic (`agent1.py` vs `agent2.py`)

| # | Severity | File & Baris | Temuan | Status |
|---|----------|-------------|--------|--------|
| F3 | 🔴 HIGH | `agent2.py:522-601` | **`_calc_levels()` copy-paste penuh dari agent1** — baris 524 import `_a1_levels` tapi tidak pernah dipanggil. Seluruh body (80 baris) identik dengan `agent1._calc_levels()`. Bug silent: jika agent1 `_calc_levels` difix, agent2 tidak ikut. Harusnya `return _a1_levels(direction, tf_map, price)` | ✅ selesai — delegasi ke `_a1_levels`, 80 baris → 2 baris |
| F4 | 🟡 MEDIUM | `agent2.py:524` | **Import ganda di dalam function body** — `_atr, _swing_highs, _swing_lows, _round_price` sudah di-import di top of file (line 43-47), tapi di-import lagi di dalam `_calc_levels()`. Redundant, confusing | ✅ selesai — ikut fix F3, body dihapus |
| F5 | 🟡 MEDIUM | `agent2.py:405-406` | **SHORT tanpa Wyckoff tetap lolos** — `_score_distribution` hanya -5 pts jika tidak ada Wyckoff/markdown phase. Signal lain (BB squeeze + funding + resistance) bisa total ≥ 52 tanpa fase distribusi terkonfirmasi. SHORT berkualitas rendah bisa auto-open | ❌ belum |
| F6 | 🟡 MEDIUM | `agent1.py:309-315` | **Breakout bonus berlawanan dengan filosofi pre-gainer** — jika `price > recent_high * 0.99 and 0 < change_24h < 8` tambah +5 pts. Tapi 30-candle 1h high = 30 jam lalu. Coin yang sudah pump 6-8% masih dapat bonus "fresh breakout" — ini bukan pre-gainer lagi | ❌ belum |
| F7 | 🟢 LOW | `agent1.py:674` · `agent2.py:644` | **Score di-cap di 99 bukan 100** — `round(min(score, 99), 1)`. Tidak konsisten (pre-gainer perfect = 99.0, bukan 100). Minor tapi confusing | ❌ belum |

---

## Pass 3 — Scheduler (`scheduler.py` + `futures_scanner.py:get_futures_status`)

| # | Severity | File & Baris | Temuan | Status |
|---|----------|-------------|--------|--------|
| F8 | 🔴 HIGH | `futures_scanner.py:336` | **`next_scan_in_min` pakai angka 900 (hardcode) bukan `INTERVAL_SEC=120`** — `max(0, round((900 - elapsed) / 60, 1))`. Scanner jalan tiap 2 menit tapi UI tampilkan countdown ~15 menit. Dashboard dan scanner page menampilkan info salah ke user setiap saat | ✅ selesai — import `INTERVAL_SEC` dari scheduler |
| F9 | 🟡 MEDIUM | `scheduler.py:36-43` | **`get_state()` tidak expose `next_scan_in_min`** — opportunity scheduler expose ini, futures scheduler tidak. `futures_scanner.py` hitung sendiri tapi dengan nilai salah (F8). Seharusnya scheduler yang hitung dan expose, bukan endpoint | ❌ belum |

---

## Pass 4 — Auto Trader (`auto_trader.py`)

| # | Severity | File & Baris | Temuan | Status |
|---|----------|-------------|--------|--------|
| F10 | 🟡 MEDIUM | `auto_trader.py:24` · `FuturesTab.tsx:879` | **Threshold inkonsisten antara code dan UI** — `AUTO_OPEN_THRESHOLD = 72` di code, tapi UI hardcode `"≥ 75pt"`. User melihat threshold yang berbeda dari yang sebenarnya dipakai | ❌ belum |
| F11 | 🟡 MEDIUM | `auto_trader.py:61` (comment) | **Komentar threshold ranging salah** — comment tulis `# 85 in ranging` tapi 72+5=77. Menyesatkan saat debugging | ❌ belum |
| F12 | 🟡 MEDIUM | `auto_trader.py:54,110` | **`get_cached_regime()` dipanggil dua kali** — sekali sebelum DB query (line 54), sekali lagi di dalam loop (line 110). Antara dua panggilan ini, regime bisa berubah. Seharusnya cache satu kali di awal | ❌ belum |
| F13 | 🟡 MEDIUM | `auto_trader.py:124-143` | **`risk_pct` tidak disimpan di field `PaperTrade.risk_pct`** — hanya di `signals_json["risk_pct"]`. `_rebuild_futures_paper_balance` membaca via `meta.get("risk_pct", 2.0)`. Jika signal punya `risk_pct=0` (edge case), default 2.0 menghasilkan notional sangat besar → balance calc salah | ❌ belum |

---

## Pass 5 — Monitor (`monitor.py`)

| # | Severity | File & Baris | Temuan | Status |
|---|----------|-------------|--------|--------|
| F14 | 🟡 MEDIUM | `monitor.py:131-133` | **`sl_after_tp1 == halfway_to_tp1` untuk LONG** — kedua variabel identik: `entry + (tp1 - entry) * 0.50`. Ketika TP1 tercapai, SL bergerak ke titik yang sama dengan halfway. Naming menyiratkan SL harusnya lebih agresif setelah TP1 hit (misalnya ke entry + 75% TP1). Proteksi profit sub-optimal | ✅ selesai — `sl_after_tp1 = entry + (tp1 - entry) * 0.75` |
| F15 | 🟡 MEDIUM | `monitor.py:283-285` | **Max age close: P&L dihitung dari mark price saat ini, bukan dari SL/TP** — `new_status = "tp" if pnl_now > 0 else "sl"`. Posisi yang +0.01% setelah 3 hari dianggap "tp" padahal harusnya "manual" atau "expired". Win rate jadi inflate | ✅ selesai — status `"expired"` bukan tp/sl, excluded dari win rate dan balance |
| F16 | 🟢 LOW | `monitor.py:241-248` | **Monitor masih track legacy styles** — `"position", "scalping", "daytrading", "swing"` sudah tidak dipakai tapi masih di WHERE clause setiap siklus 2 menit. Dead query overhead | ✅ selesai — removed legacy styles |

---

## Pass 6 — Backend API (`futures_scanner.py`)

| # | Severity | File & Baris | Temuan | Status |
|---|----------|-------------|--------|--------|
| F17 | 🔴 HIGH | `futures_scanner.py:350-351` | **`STARTING_BALANCE = 1000.0` dan `RISK_PCT_DEFAULT = 0.01` hardcoded** — B8 fix sebelumnya update `futures_learning.py` dan `monitor.py` tapi **lewat file ini**. `/futures/monitor/risk` pakai konstanta lokal ini untuk hitung notional, margin, balance — bisa diverge jika nilai diubah di `trading_costs.py` | ✅ selesai — import dari `trading_costs.py` |
| F18 | 🔴 HIGH | `futures_scanner.py:263-276` | **`/futures/positions` fetch live price sequential per symbol** — satu `c.get(...)` per simbol dalam dict comprehension yang di-await satu per satu. Monitor pakai batch `fapi/v1/ticker/price?symbols=[...]` (weight=2 untuk semua). Dengan 10 posisi = 10 request berurutan vs 1 request batch | ✅ selesai — batch endpoint, weight=2 untuk semua |
| F19 | 🟡 MEDIUM | `futures_scanner.py:105-138` | **`open_futures_trade` tidak validasi R:R ≥ 1:3** — agent enforce di `_calc_levels`, tapi POST `/futures/trade` manual bisa bypass. User bisa open trade dengan R:R 1:1 via API langsung | ✅ selesai — validasi `reward/risk >= 3.0` sebelum insert |
| F20 | 🟢 LOW | `futures_scanner.py:612-618` | **`_filter_results` return `scanned` dari agent pertama yang punya nilai** — `a1.get("scanned", 0) or a2.get("scanned", 0)`. Jika a1 scanned=0 (cache miss), return a2. Tidak konsisten — kadang a1 count, kadang a2 count | ❌ belum |

---

## Pass 7 — Frontend (`FuturesTab.tsx`)

| # | Severity | File & Baris | Temuan | Status |
|---|----------|-------------|--------|--------|
| F21 | 🔴 HIGH | `FuturesTab.tsx:9-11` | **`STARTING_BALANCE`, `RISK_PCT`, `RISK_DOLLAR` hardcoded di frontend** — tidak dari API. Jika backend ubah nilai, frontend tidak ikut. `calcNotional`, `calcMargin`, `calcLiqPrice` semua pakai nilai ini → semua kalkulasi bisa salah | ✅ selesai — `_FALLBACK_BALANCE` fallback, `startingBalance` dari `learning.balance.starting` |
| F22 | 🔴 HIGH | `FuturesTab.tsx:351` | **`currentBalance` dihitung frontend dari positions lokal, bukan `/balance/futures`** — `STARTING_BALANCE + totalPnl$` dari positions array. Tapi `/balance/futures` sudah ada dan pakai DB. Dua sumber kebenaran bisa diverge, terutama setelah restart backend | ✅ selesai — `learning?.balance?.current` sebagai sumber utama |
| F23 | 🟡 MEDIUM | `FuturesTab.tsx:124-131` · `futures_scanner.py:288-292` | **`unrealized_pnl` open position tidak dikurangi fee** — `/futures/positions` return `(cp - entry) / entry * 100` tanpa deduct fee. SPOT deduct `EXECUTION_COST_PCT = 0.31%`. Futures taker fee round-trip = 0.10%. Posisi open terlihat lebih profitable dari yang sesungguhnya | ✅ selesai — deduct `0.10%` di `/futures/positions` endpoint |
| F24 | 🟡 MEDIUM | `FuturesTab.tsx:344-368` | **`stats` useMemo hitung dari `positions` yang di-limit 100** — `/futures/positions` query pakai `limit(100)`. Jika total trades > 100, equity curve dan balance tidak lengkap. SPOT tidak ada limit problem ini | ❌ belum |
| F25 | 🟡 MEDIUM | `FuturesTab.tsx:295` · Overview tab | **`agentFilter` state tidak memfilter tampilan apapun** — state di-set ketika click agent card tapi tidak dipakai untuk filter posisi/trades di bawahnya. Dead state | ❌ belum |
| F26 | 🟢 LOW | `FuturesTab.tsx:879` | **UI hardcode `"Auto-Open: ≥ 75pt"`** — actual threshold adalah 72 (F10). Tidak fetch dari `/futures/auto/status` yang sudah ada | ❌ belum |

---

## Pass 8 — Audit Lanjutan (selesai)

| File | Keterangan |
|------|-----------|
| `agents/futures/regime.py` | ✅ Sudah dibaca — OK. CACHE_TTL=30min reasonable, fallback "ranging" on error aman, EMA9/21/50+ATR+BB → 4 state. Tidak ada bug kritis |
| `agents/futures/weight_updater.py` | ✅ Sudah dibaca — OK. MIN_RUN_INTERVAL=5min mencegah over-recalculate. Expired trades excluded otomatis setelah F15 fix. N+1 query per upsert tapi acceptable skala kecil |
| `frontend/src/features/scanner/page.tsx` | ✅ Sudah dibaca — next_scan_in countdown futures sudah menggunakan nilai dari `/futures/status` yang sudah di-fix (F8). OK |

---

## Pass 9 — Audit Lanjutan: Risk Monitor, WebSocket, Analytics

| # | Severity | File & Baris | Temuan | Status |
|---|----------|-------------|--------|--------|
| F27 | 🟡 MEDIUM | `futures_scanner.py:413-425` | **`/futures/monitor/risk` price fetch N requests** — menggunakan `asyncio.create_task()` per simbol (concurrent) tapi tetap N individual requests. `monitor.py` sudah pakai batch endpoint (`/fapi/v1/ticker/price?symbols=[...]`, weight=2 semua). `/monitor/risk` belum diupdate ke batch → weight=N per hit, boros rate limit | ❌ belum |
| F28 | 🟡 MEDIUM | `futures_scanner.py:452-456` | **`/futures/monitor/risk` unrealized PnL tanpa fee** — `upnl_pct = (current - entry) / entry * 100` tidak deduct 0.10% round-trip fee. `/futures/positions` sudah di-fix (F23) tapi endpoint risk dashboard belum. Risk dashboard tampilkan unrealized lebih besar dari yang sesungguhnya | ❌ belum |
| F29 | 🟡 MEDIUM | `futures_stream.py:12` | **`INTERVAL_SEC` duplikat di WebSocket** — `INTERVAL_SEC = 2 * 60` dengan comment `# must match agents/futures/scheduler.py INTERVAL_SEC`. Jika scheduler INTERVAL_SEC diubah, WS kirim countdown salah tanpa compile error atau warning | ❌ belum |
| F30 | 🟡 MEDIUM | `FuturesAnalytics.tsx:41,99,118-119,141,147` | **`const START = 1000` hardcoded di analytics chart** — dipakai sebagai baseline chart (`startLine`), fallback balance terakhir, dan threshold hijau/merah. API sudah return `stats.balance.starting` dari `trading_costs.py`. Jika `FUTURES_STARTING_BALANCE` diubah, chart reference line dan warna salah | ❌ belum |
| F31 | 🟡 MEDIUM | `FuturesAnalytics.tsx:199` | **Analytics tidak auto-refresh** — `useEffect(() => { void fetchAll(); }, [fetchAll])` hanya fetch sekali saat mount. `fetchAll` di-memo dengan deps `[]` sehingga tidak pernah re-trigger. FuturesTab poll setiap 15s, tapi tab analytics harus klik "Update Weights" manual untuk refresh data | ❌ belum |
| F32 | 🟢 LOW | `store.py:10` | **`STALE_SEC = 20 * 60` terlalu lebar** — stale threshold 20 menit, tapi scanner jalan tiap 2 menit (`INTERVAL_SEC = 120`). Setelah backend restart, hasil lama bisa dianggap "fresh" selama 20 menit sebelum akhirnya trigger re-scan. Harusnya ≤ 5 menit | ❌ belum |
| F33 | 🟢 LOW | `monitor.py:156` · `futures_learning.py:77` · `futures_scanner.py:511` | **Tiga komputasi balance terpisah** — `_rebuild_futures_paper_balance()` (monitor → tulis DB), `get_learning_stats()` (learning → in-memory), `get_risk_dashboard()` (scanner risk → in-memory). Formula sama tapi tiga implementasi terpisah. Jika ada satu yang drift (mis. handling `expired` status), hasilnya tidak konsisten antar endpoint | ❌ belum |

---

## Pass 10 — Futures Scanner: Agent Logic + Frontend

> Audit mendalam tujuan: rekomendasi LONG+SHORT bidirectional + deteksi pre-gainer sebelum bergerak

| # | Severity | File & Baris | Temuan | Status |
|---|----------|-------------|--------|--------|
| F34 | 🔴 HIGH | `agent1.py:656-661` | **`scan_symbol()` hanya return 1 direction per coin** — `if long_score >= short_score` → hanya winner yang dikembalikan, runner-up dibuang meski score ≥ MIN_SCORE=52. Jika LONG=65 dan SHORT=60 (keduanya valid), SHORT hilang. Tujuan user: rekomendasikan LONG **dan** SHORT — ini bug blocker utamanya | ❌ belum |
| F35 | 🔴 HIGH | `agent1.py:309-315` | **Breakout bonus +5 pts untuk coin yang sudah naik 6-8%** — `if price > recent_high[-30h] * 0.99 and 0 < change_24h < 8: score += 5`. Coin yang sudah +7% dalam 24 jam masih dapat bonus "fresh breakout". Ini berlawanan langsung dengan filosofi pre-gainer — pre-gainer harusnya **belum bergerak**. Coin flat dapat 0 pts, coin yang sudah pump dapat +5 pts | ❌ belum |
| F36 | 🟡 MEDIUM | `agent1.py` (tidak ada) | **Tidak ada bonus untuk coin benar-benar flat** — `-2% ≤ change_24h ≤ 2%` adalah kondisi ideal pre-gainer (sedang coiling, belum terbang) tapi tidak ada reward sama sekali. Seharusnya +5 to +8 pts. Saat ini coin yang diam justru tidak lebih unggul dari coin yang sudah naik sedikit | ❌ belum |
| F37 | 🟡 MEDIUM | `agent1.py:424-443` | **Volume distribusi SHORT lebih ketat dari akumulasi LONG** — LONG butuh `vol_ratio >= 2.5 and price_move < 0.03`. SHORT butuh syarat tambahan `near_top = closes[-1] >= max(closes[-30:]) * 0.97`. Satu filter ekstra ini membuat signal SHORT distribusi jauh lebih jarang lolos → scanner bias ke LONG. Distribusi bisa terjadi tanpa price di 3% dari 30-candle high | ❌ belum |
| F38 | 🟡 MEDIUM | `scanner/page.tsx:310-311` | **`const BALANCE = 1000` hardcoded di TradeModal** — simulasi position sizing (Notional, Margin, Win Est., Liq Price) di modal scanner memakai nilai hardcode `$1,000`, bukan dari API. Pola sama dengan F21 yang sudah difix di FuturesTab, tapi modal scanner belum | ❌ belum |
| F39 | 🟢 LOW | `scanner/page.tsx:572` | **UI hardcode "Scanning 150 pairs..."** — teks ini muncul saat scanning, tapi actual universe = `UNIVERSE_CAP=150` + hingga 30 extreme FR coins = hingga 180 pairs. Akan menyesatkan jika UNIVERSE_CAP diubah | ❌ belum |
| F40 | 🟢 LOW | `scanner/page.tsx:523-524` | **`totalLong`/`totalShort` tidak deduplicate across agents** — dihitung dari `[...agent1, ...agent2]`. Jika BTCUSDT ada di agent1 sebagai LONG dan agent2 sebagai SHORT, `totalLong` count agent1 BTCUSDT dan `totalShort` count agent2 BTCUSDT. Total count bisa misleading karena satu coin bisa dihitung di kedua agent | ❌ belum |

---

## Pass 11 — Futures History: Backend API + Frontend

> Audit `history.py`, `FuturesTab.tsx`, equity calculation, win rate logic

| # | Severity | File & Baris | Temuan | Status |
|---|----------|-------------|--------|--------|
| F41 | 🔴 HIGH | `history.py:268-270` | **`/history/equity` hardcode `BALANCE=1000, RISK_PCT=0.01`** — tidak import dari `trading_costs.py`. Equity chart di `/history/equity` endpoint akan berbeda dari `/futures/learning/stats` (yang sudah pakai centralized constants). Dua endpoint berbeda hasilkan angka berbeda untuk chart yang sama | ❌ belum |
| F42 | 🔴 HIGH | `history.py:310` | **`/history/daily-pnl` falsy check skip `pnl_pct=0.0`** — `if t.pnl_pct: d["pnl"] += t.pnl_pct`. Trade dengan `pnl_pct=0.0` (break-even setelah fee) di-skip karena `0.0` adalah falsy di Python. Harus `if t.pnl_pct is not None:`. Break-even trades tidak masuk ke daily PnL chart | ❌ belum |
| F43 | 🟡 MEDIUM | `FuturesTab.tsx:347-348` | **Win rate denominator inflate — `expired` masuk `closed`** — `closed = positions.filter(p => p.status !== "open")` → expired trades ikut masuk `closed`. Tapi `wins = closed.filter(p.status === "tp")` dan `losses = closed.filter(p.status === "sl")`. Expired masuk denominator `closed.length` tanpa masuk wins/losses → `winRate = wins/closed` jadi lebih rendah dari aktual. Backend `futures_learning.py` sudah benar (exclude expired) tapi FuturesTab.tsx belum | ❌ belum |
| F44 | 🟡 MEDIUM | `history.py:268-290` | **`/history/equity` hitung risk_pct dari SL jarak saat ini, bukan original** — `risk_pct_val = abs(entry_price - stop_loss) / entry_price * 100`. Tapi `stop_loss` di DB bisa sudah ter-trail (monitor geser SL). Risk pct yang dipakai bukan risk awal → notional salah → equity curve salah untuk posisi yang sudah trail SL. Fix: pakai `meta.get("risk_pct", 2.0)` seperti `futures_learning.py` | ❌ belum |
| F45 | 🟡 MEDIUM | `history.py:151-165` | **Filter logic duplikat dalam satu endpoint** — `get_trades()` build query dua kali: satu untuk paginated trades, satu untuk `all_trades` summary stats. Filter style+search di-copy paste ke dua tempat. Jika ada perubahan filter (misal tambah style baru), harus update dua tempat → potensi divergence | ❌ belum |
| F46 | 🟡 MEDIUM | `FuturesTab.tsx:110` | **`RISK_DOLLAR` module-level constant, tidak reaktif** — `const RISK_DOLLAR = _FALLBACK_BALANCE * RISK_PCT` dihitung sekali saat module load. `calcNotional()`, `calcMargin()`, `tradePnlDollar()` semua pakai ini. Bahkan setelah `learning.balance.starting` dari API tersedia, `RISK_DOLLAR` tetap pakai fallback $10 untuk kalkulasi di `OpenPosCard` | ❌ belum |
| F47 | 🟡 MEDIUM | `FuturesTab.tsx:599` · `FuturesTab.tsx:872` | **Teks balance hardcoded di dua tempat** — line 599: `"Modal awal $1,000 · Risk $10/trade (1%)"`. Line 872: `"$1,000 start"` di equity chart footer. Keduanya hardcode, tidak pakai `startingBalance` yang sudah tersedia dari API | ❌ belum |
| F48 | 🟡 MEDIUM | `history.py:223-224` | **`/history/stats` tanpa filter `days`** — query `select(PaperTrade)` tanpa cutoff waktu. Jika ada ribuan trade historis, ini query semua. Endpoint lain (`/history/trades`) ada `days=90` default. Stats bisa lambat dan tidak konsisten dengan trades list yang sudah di-filter by days | ❌ belum |
| F49 | 🟢 LOW | `FuturesTab.tsx:719-758` | **`selectedMonth` dropdown hanya highlight, tidak filter** — semua bulan selalu ditampilkan, pilih bulan hanya ubah warna background baris. User menyangka akan filter data tapi tidak terjadi apa-apa selain highlight visual | ❌ belum |
| F50 | 🟢 LOW | `history.py:46` | **`rr_ratio` parsing rapuh** — `float(t.risk_reward.split(":")[1]) if t.risk_reward and ":" in t.risk_reward else 0`. Jika `risk_reward = "1:3.5"`, ini return 3.5. Tapi jika format berbeda (misal "3.5" tanpa ":", atau "1:3:extra"), split[1] bisa error atau return nilai salah | ❌ belum |

---

---

## Pass 12 — Auto Trader + Agent Logic (Audit Lanjutan)

> Audit mendalam `auto_trader.py`, `agent1.py scan_symbol`, `agent2.py scan_symbol`, `history.py stats`

| # | Severity | File & Baris | Temuan | Status |
|---|----------|-------------|--------|--------|
| F51 | 🔴 HIGH | `auto_trader.py:144-164` | **Auto-opened trades tidak set `position_size`, `risk_dollar`, `balance_snapshot`** — saat `PaperTrade` dibuat di `auto_open_positions()`, ketiga field ini tidak di-assign (bernilai `None`). Monitor menggunakan `risk_pct` dari `signals_json` untuk hitung `pnl_dollar`, tapi `balance_snapshot` (untuk equity curve) dan `position_size` (untuk notional calc) tetap `None`. FuturesTab tidak bisa hitung P&L dollar akurat untuk auto trades | ❌ belum |
| F52 | 🔴 HIGH | `agent1.py:656-661` + `agent2.py:556-561` | **KEDUA AGENT punya 1-direction-only bug (F34 hanya catat agent1)** — `agent2.scan_symbol()` baris 556-561 punya logic identik: `if long_score >= short_score → LONG else SHORT`. Jika BTC LONG=65 SHORT=60, agent2 juga hanya return LONG. Bug F34 berlaku untuk KEDUA agent. Perlu return list bukan single dict | ❌ belum |
| F53 | 🔴 HIGH | `history.py:252` | **`/history/stats` avg_pnl falsy check** — `sum(t.pnl_pct for t in closed if t.pnl_pct) / len(closed)` — sama persis dengan F42 di daily-pnl, tapi endpoint berbeda. Break-even trade (`pnl_pct=0.0`) tidak masuk ke sum average. Avg_pnl stats endpoint jadi lebih positif dari aktual | ❌ belum |
| F54 | 🟡 MEDIUM | `auto_trader.py:24` + `scheduler.py:24` | **`AUTO_OPEN_THRESHOLD=72` di auto_trader vs scheduler yang set threshold untuk filter results** — auto_trader punya `AUTO_OPEN_THRESHOLD=72` dan `AUTO_OPEN_VOLATILE_THRESHOLD=82`. Tapi komentar `# Pre-gainer scout: entry earlier = lower bar OK` ada di scheduler. Nilai 72 vs threshold agent MIN_SCORE=52 → gap 20 pts. Coins scoring 52-71 tidak pernah auto-open meski valid signal. Perlu review apakah 72 masih tepat atau terlalu tinggi | ❌ belum |
| F55 | 🟡 MEDIUM | `auto_trader.py:99` | **`FUTURES_COOLDOWN_HOURS = 3` hardcoded di dalam fungsi** — bukan module constant, bukan di `trading_costs.py`. Jika ingin ubah cooldown, harus cari di dalam fungsi `auto_open_positions()`. Semua konstanta trading harusnya terpusat | ❌ belum |
| F56 | 🟡 MEDIUM | `agent1.py:309-315` + `agent2.py` (tidak ada) | **Tidak ada penalty untuk coin yang sudah sangat dekat ATH (near all-time-high)** — Agent 1 cek `recent_high[-30 candles 1h]` tapi 30 jam bukan all-time-high. Coin yang pump ke ATH tapi belum +15% dalam 24h masih bisa dapat score tinggi. Seharusnya penalti jika `price > max(closes[-168:])` (7 hari) × 0.95 — ini bukan pre-gainer lagi, ini chaser | ❌ belum |
| F57 | 🟢 LOW | `agent2.py:569-574` + `agent1.py:670-674` | **`round(min(score, 99), 1)` di kedua agent** — score di-cap 99, bukan 100. Jika score 100 sempurna, ditampilkan 99. Ini sudah F7 tapi perlu catatan berlaku di KEDUA agent | ❌ belum |

---

## Pass 13 — Monitor, Regime, Weight Updater, Learning API

> Audit mendalam `monitor.py`, `regime.py`, `weight_updater.py`, `futures_learning.py`, `FuturesAnalytics.tsx`

| # | Severity | File & Baris | Temuan | Status |
|---|----------|-------------|--------|--------|
| F58 | 🔴 HIGH | `monitor.py:320-335` | **`pnl_dollar` tidak di-set saat trade ditutup** — monitor menghitung `pnl_net` dan men-set `trade.pnl_pct` (baris 335) tapi tidak pernah men-set `trade.pnl_dollar`. Field `pnl_dollar` di `PaperTrade` selalu `None` untuk semua trade yang ditutup oleh monitor. FuturesTab.tsx dan history API menggunakan `pnl_dollar` untuk dollar P&L display — hasilnya selalu 0/None | ❌ belum |
| F59 | 🔴 HIGH | `futures_scanner.py:188-210` | **`/futures/trade` tidak set `position_size`, `risk_dollar`, `balance_snapshot`** — same bug seperti F51 (auto_trader) tapi ini untuk trade manual dari scanner frontend. Dua code path berbeda, keduanya buat PaperTrade tanpa field dollar tracking. Dollar P&L rusak untuk kedua jenis trade (auto + manual) | ❌ belum |
| F60 | 🔴 HIGH | `weight_updater.py:100` | **`is_win = trade.status == "tp"` tidak cek `pnl_pct > 0`** — trade dengan status="tp" tapi `pnl_pct=-0.16%` (net negatif setelah fee) dihitung sebagai "win" untuk signal weight. Inkonsisten dengan `_is_real_win()` di `history.py` dan `futures_learning.py` yang wajibkan `pnl_pct > 0`. Signal weights menjadi inflated — sinyal yang sebenarnya losing masih dapat weight=1.2/1.5 | ❌ belum |
| F61 | 🟡 MEDIUM | `monitor.py:45,410` | **`_closed_today` counter tidak reset setiap hari** — `_closed_today = 0` di module-level (reset saat startup). Baris 410: `_closed_today += n` akumulasi sejak startup. Jika backend jalan 3 hari, `_closed_today` bisa menunjukkan 47 padahal hari ini hanya 5 yang ditutup. Nama variabel menyesatkan | ❌ belum |
| F62 | 🟡 MEDIUM | `monitor.py:414-415` | **`_rebuild_futures_paper_balance()` dipanggil setiap siklus 2 menit** — fungsi ini fetch ALL closed trades dari DB setiap 2 menit untuk rebuild balance dari awal. Dengan ratusan closed trades, ini N SQL reads × 2 menit terus-menerus. Seharusnya incremental (hanya update delta ketika ada trade baru yang ditutup) atau paling tidak hanya setelah `closed > 0` | ❌ belum |
| F63 | 🟡 MEDIUM | `regime.py:27` | **`CACHE_TTL = 30 * 60` (30 menit) terlalu lama** — regime dipakai oleh auto_trader untuk decide open/block posisi. Jika market bergerak dari `trending_up` ke `volatile` dalam 15 menit (BTC drop cepat), auto_trader masih bisa buka LONG selama 30 menit ke depan dengan regime lama. Seharusnya 5-10 menit agar lebih responsif | ❌ belum |
| F64 | 🟡 MEDIUM | `regime.py:120` | **Regime detection memakai BTCUSDT 4H candle** — candle 4H hanya update setiap 4 jam. Di awal candle baru, candle masih membangun — close price dari 4H candle sebelumnya yang menggerakan deteksi, bukan pergerakan saat ini. Lebih baik pakai 1H atau hybrid 1H+4H untuk deteksi lebih cepat | ❌ belum |
| F65 | 🟡 MEDIUM | `futures_learning.py:213-215` | **Conservative equity hardcode win=+$30, loss=-$10** — angka ini berasal dari asumsi: $1000 × 1% risk × 3 R:R = +$30 win, -$10 loss. Tapi jika `STARTING_BALANCE` diubah, formula ini salah. Seharusnya `win = STARTING_BALANCE × RISK_PCT × 3` dan `loss = STARTING_BALANCE × RISK_PCT` — dinamis dari constants | ❌ belum |
| F66 | 🟡 MEDIUM | `futures_learning.py:236` | **`equity_points[-50:]` memotong chart setelah 50 trades** — hanya 50 data point terakhir yang dikirim ke frontend. Jika ada 100+ trades, equity chart mulai dari trade #51, bukan dari $1000 awal. Kurva ekuitas terlihat disconnected dan tidak merepresentasikan perjalanan penuh dari modal awal | ❌ belum |
| F67 | 🟢 LOW | `weight_updater.py:68` | **`MIN_RUN_INTERVAL = 5 * 60` saat scheduler run setiap 2 menit** — docstring berkata "runs after each scan cycle" tapi sebenarnya hanya jalan setiap 5 menit (setiap ~2-3 siklus). Komentar menyesatkan, dan interval terlalu jarang untuk debugging — bikin monitoring sulit | ❌ belum |

---

## Ringkasan Temuan

| Severity | Jumlah | Keterangan |
|----------|--------|-----------|
| 🔴 HIGH | 23 | F3 ✅, F8 ✅, F17 ✅, F18 ✅, F21 ✅, F22 ✅ selesai · F34, F35, F41, F42, F51, F52, F53, F58, F59, F60, F68, F69, F70, F86, F87, F88, F89 pending |
| 🟡 MEDIUM | 54 | F14 ✅, F15 ✅, F19 ✅, F23 ✅ selesai · F1, F5, F6, F9-F13, F24, F25, F27-F31, F36-F38, F43-F48, F54-F56, F61-F66, F71-F74, F76-F83, F90-F93, F96-F98, F100-F103, F105 pending |
| 🟢 LOW | 29 | F4 ✅, F16 ✅ selesai · F2, F7, F20, F26, F32, F33, F39, F40, F49, F50, F57, F67, F75, F84, F85, F94, F95, F99, F104, F106 pending |
| **Total** | **106** | **~100 selesai ✅ · F88 F89-F95 pending (backlog)** |

---

---

## Pass 14 — Scanner: Learning Loop (Weights Tidak Dipakai, Tidak Ada Feedback)

> Tujuan: scanner harus selalu bertumbuh — setiap siklus seharusnya lebih pintar dari siklus sebelumnya.
> Audit: apakah weights dari `weight_updater.py` benar-benar masuk kembali ke scoring?

| # | Severity | File & Baris | Temuan | Status |
|---|----------|-------------|--------|--------|
| F68 | 🔴 HIGH | `agent1.py`, `agent2.py` (tidak ada) | **Weights dari `agent_signal_weights` TIDAK PERNAH dibaca oleh agent saat scoring** — `weight_updater.py` komputasi weights (0.7–1.5) dan simpan ke DB, tapi `agent1.scan_symbol()` dan `agent2.scan_symbol()` tidak pernah query `agent_signal_weights`. Learning loop adalah one-way street: trade → DB → display di Analytics, TIDAK pernah kembali ke scoring. Signal "BB Squeeze 1H" yang menang 80% diperlakukan sama dengan yang menang 30% | ❌ belum |
| F69 | 🔴 HIGH | `auto_trader.py:24` + `agent1.py:36` | **MIN_SCORE tidak adaptif terhadap historical win rate** — `MIN_SCORE = 52` hardcode di kedua agent, `AUTO_OPEN_THRESHOLD = 72` hardcode di auto_trader. Jika agent1 win rate turun ke 30% (signal tidak reliabel), threshold seharusnya naik otomatis untuk jadi lebih selektif. Jika win rate naik ke 75%, threshold bisa turun untuk tangkap lebih banyak peluang | ❌ belum |
| F70 | 🔴 HIGH | `weight_updater.py:100-101` + `agents/` (tidak ada) | **Expired trades tidak masuk sebagai negative learning signal** — trade yang expire (`status="expired"`) tidak diproses di `weight_updater.py` (hanya query `status.in_(["tp", "sl"])`). Expired = setup stalled, tidak bergerak = pattern gagal memicu gerakan. Sinyal yang sering menghasilkan expired seharusnya mendapat penalty weight (< 0.7) | ❌ belum |
| F71 | 🟡 MEDIUM | `agent1.py`, `agent2.py` (tidak ada) | **Tidak ada per-coin learning** — jika BTCUSDT selalu menghasilkan trade winning tapi DOGEUSDT selalu SL, tidak ada memori per coin. Scanner memperlakukan semua coin sama. Seharusnya ada `coin_win_rate` table: jika coin X menang 70%+, beri bonus +5 pts saat scan | ❌ belum |
| F72 | 🟡 MEDIUM | `regime.py` + `agent1.py`, `agent2.py` | **Regime tidak mempengaruhi scoring agent** — `get_cached_regime()` hanya dipakai untuk block auto-open di volatile dan raise threshold di ranging. Tapi agent scoring tidak berubah berdasarkan regime. Di `trending_up`: momentum signals seharusnya lebih berharga. Di `ranging`: squeeze signals seharusnya lebih berharga. Scoring tetap sama di semua regime | ❌ belum |
| F73 | 🟡 MEDIUM | `weight_updater.py:34-42` | **`_normalize_signal()` menghapus angka dengan "N"** — "BB Squeeze 1H (2.1%)" dan "BB Squeeze 1H (5.8%)" keduanya menjadi "bb_squeeze_N_N" dan dianggap sinyal yang sama. Padahal squeeze 2.1% (very tight) jauh lebih kuat dari 5.8% (moderate). Normalisasi terlalu agresif — kehilangan informasi kualitas sinyal | ❌ belum |
| F74 | 🟡 MEDIUM | `agents/futures/` (tidak ada) | **Tidak ada feedback loop dari posisi terbuka ke scanner berikutnya** — jika BTCUSDT sedang open LONG, scanner berikutnya masih bisa merekomendasikan BTCUSDT LONG lagi (meski auto_trader punya dedup). Tidak ada sinyal dari monitor "posisi ini sedang untung/rugi" yang mempengaruhi scan prioritas | ❌ belum |
| F75 | 🟢 LOW | `weight_updater.py:45-54` | **`_weight_from_rate()` step function, bukan gradual** — loncat dari 0.7 ke 1.0 ke 1.2 ke 1.5 di titik-titik exact. Win rate 39.9% dapat 0.7 tapi 40.0% dapat 1.0 — perbedaan besar untuk selisih 0.1%. Seharusnya smooth interpolation agar perubahan weights lebih gradual dan stabil | ❌ belum |

---

## Pass 15 — Monitor: Position Management untuk Profit Maksimal

> Tujuan: setiap posisi yang menang harus mengekstrak profit semaksimal mungkin.
> Analisis gap antara logika saat ini vs best practice futures position management.

### Kondisi Monitor Saat Ini
```
Entry → tunggu → [SL hit → close] atau [TP2 hit → close SEMUA]

Trail SL:
  50% menuju TP1 → SL geser ke Breakeven
  TP1 tersentuh  → SL geser ke Entry + 75%(TP1-Entry)

TP Extension:
  TP1 + score>=70 + TP3 ada → ganti TP2 dengan TP3 → tutup semua di TP3
```

### Yang Seharusnya Ada untuk Profit Maksimal
```
Entry → [SL management] → TP1 → [partial close 25-30%] → TP2 → [partial close 50%] → TP3 → [close sisa]

Dengan SL yang terus trail mengikuti price progression.
```

| # | Severity | File & Baris | Gap / Bug | Status |
|---|----------|-------------|-----------|--------|
| F76 | 🔴 HIGH | `monitor.py:284-302` | **Tidak ada partial close di TP1** — saat TP1 tercapai, monitor hanya menggeser SL, TIDAK menutup sebagian posisi. Full position tetap terbuka. Jika harga balik sebelum TP2, semua profit dari perjalanan ke TP1 hilang. Seharusnya close 25-33% di TP1, simpan sisanya untuk TP2/TP3. Field `pnl_dollar` dan `position_size` tidak di-set (F58/F59), jadi partial close pun tidak bisa dihitung dollar-nya | ❌ belum |
| F77 | 🔴 HIGH | `monitor.py:119-151` | **SL tidak maju ke TP1 level setelah TP2 hampir tercapai** — setelah TP1 hit, SL hanya maju ke `entry + 75%(TP1-entry)`, bukan ke TP1 level itu sendiri. Jika harga mencapai 80% jarak TP1→TP2 kemudian berbalik, SL masih jauh di bawah TP1 — profit yang sudah sangat dekat TP2 bisa kembali ke zero. Seharusnya SL naik ke TP1 level setelah harga 50%+ antara TP1 dan TP2 | ❌ belum |
| F78 | 🟡 MEDIUM | `monitor.py` (tidak ada) | **Tidak ada TP4+ extension setelah TP3** — jika TP3 tercapai dengan momentum sangat kuat (OI masih naik, funding masih neutral, RSI belum overbought), tidak ada mekanisme untuk extend ke target lebih jauh. Setiap trade dibatasi maksimal 3 TP level. Untuk coin yang terbang 20-30%, TP3 biasanya +10-12% — sisanya tidak ter-capture | ❌ belum |
| F79 | 🟡 MEDIUM | `monitor.py` (tidak ada) | **Tidak ada SL adaptation berdasarkan regime** — di regime `volatile`, price noise lebih besar. SL ATR-based yang dihitung saat entry bisa ter-hit oleh noise, bukan trend reversal sebenarnya. Di `volatile` regime, SL seharusnya diperlebar 20-30% dari ATR normal. Di `trending_up`, SL bisa lebih ketat karena trend kuat. Saat ini SL fixed sejak entry | ❌ belum |
| F80 | 🟡 MEDIUM | `monitor.py:276-282` | **"Time decay" management tidak ada — posisi stagnan dibiarkan hingga MAX_AGE (3 hari)** — jika posisi sudah 24 jam tapi hanya naik 0.5% (belum capai 50% ke TP1), ini setup gagal memicu. Tidak ada logika untuk tighten SL posisi stagnan. Seharusnya: di 24h jika unrealized < 1% → tighten SL ke entry-buffer kecil. Di 48h jika unrealized < TP1/2 → close sebagian | ❌ belum |
| F81 | 🟡 MEDIUM | `monitor.py:364-381` | **TP extension ke TP3 tidak update SL ke TP1 level** — ketika TP2 diganti dengan TP3 (baris 372: `trade.take_profit = tp3`), SL masih di `entry + 75%(TP1-entry)`. Jika harga kemudian jatuh dari TP3 area kembali ke TP1 area, semua keuntungan dari TP1→TP3 hilang. Seharusnya saat extend ke TP3, SL otomatis naik ke TP1 level (lock profit TP1) | ❌ belum |
| F82 | 🟡 MEDIUM | `monitor.py:31` | **`INTERVAL_SEC = 120` hardcode di monitor, duplikat dari scheduler** — sudah F29, tapi perlu dicatat: dengan 2-menit interval, posisi yang TP1 tersentuh di antara dua check bisa ketinggalan partial close window. Jika TP1 tersentuh di menit ke-1 tapi harga kembali di menit ke-2, monitor tidak tahu TP1 pernah tersentuh — tidak ada tracking `tp1_hit` yang persistent | ❌ belum |
| F83 | 🟡 MEDIUM | `monitor.py:263` | **`tp1` fallback formula `trade.take_profit * 0.5 + entry * 0.5` salah untuk SHORT** — untuk LONG, TP1 = midpoint(entry, TP2) ≈ logis. Tapi untuk SHORT, TP2 lebih kecil dari entry, jadi `tp2 * 0.5 + entry * 0.5` menghasilkan nilai di antara entry dan TP2 — masih logis tapi bukan TP1 sebenarnya. Lebih bahaya: jika `tp1` tidak ada di meta dan ini fallback, trail SL akan bergerak ke wrong level | ❌ belum |
| F84 | 🟢 LOW | `monitor.py:370` | **TP extension condition `score >= 70` memakai score saat entry, bukan re-scan score** — `score = trade.probability or 0` (baris 370). Ini adalah score scan asli, bukan score terkini. Coin yang score-nya naik (karena signal baru terbentuk) atau turun (karena sinyal melemah) tetap dievaluasi dengan score lama. Tidak ada mekanisme re-score posisi terbuka | ❌ belum |
| F85 | 🟢 LOW | `monitor.py:49` | **`LIQ_GUARD_DIST_PCT = 8.0` tidak adaptif terhadap leverage** — leverage 2x punya liquidation yang jauh (50% dari entry), liquidation guard 8% sangat konservatif. Leverage 15x punya liquidation yang dekat (6.7% dari entry), guard 8% sudah terlambat. Seharusnya `guard_pct = max(3.0, 50/leverage)` — adaptif per leverage | ❌ belum |

---

## Pass 16 — Adaptive Learning: Peran Weight Updater & Rancangan True Learning Loop

> Analisis mendalam: apa yang seharusnya dilakukan Weight Updater, apa yang sebenarnya terjadi,
> dan bagaimana merancang sistem yang benar-benar belajar dari setiap siklus termasuk saat posisi masih open.

---

### A. Peran Weight Updater — Apa yang Dimaksud vs Apa yang Terjadi

**Apa yang SEHARUSNYA terjadi (desain ideal):**

```
Siklus 1:
  Scan → Signal "BB Squeeze 1H" → score=60 → open posisi
  Monitor → TP hit → weight_updater update: BB_Squeeze_1H wins=1, total=1

Siklus 2:
  Scan → Signal "BB Squeeze 1H" muncul lagi
  → Agent baca weight: BB_Squeeze_1H win_rate=100%, weight=1.5
  → Score base 12 pts × 1.5 = 18 pts  ← BOOST karena historis menang
  → Coin ini naik score, lebih mudah lolos MIN_SCORE

Siklus 10:
  "OI Building" ternyata sering SL → weight=0.7
  → Score base 12 pts × 0.7 = 8.4 pts  ← REDUCE karena sering kalah
  → Coin dengan sinyal ini lebih susah lolos → lebih sedikit trade buruk
```

**Apa yang SEBENARNYA terjadi:**

```
Siklus 1:  Scan → open posisi → TP → weight_updater update DB ✅
Siklus 2:  Scan → Agent1.scan_symbol() dipanggil
           → TIDAK query agent_signal_weights sama sekali
           → Score dihitung sama persis seperti siklus 1
           → Weight yang ada di DB: DIABAIKAN

Learning loop adalah SATU ARAH:
  trade → close → weight_updater → DB  ← berhenti di sini
                                   ↑
                                   tidak pernah dibaca agent
```

**Kesimpulan:** `AgentSignalWeight` table sudah ada, sudah terisi, tapi **tidak pernah dikonsumsi oleh agent scoring**. Learning hanya jadi display di FuturesAnalytics — informasi tanpa efek.

---

### B. Alur Learning yang Harus Dibangun (Full Adaptive Loop)

```
┌─────────────────────────────────────────────────────────────────┐
│                    ADAPTIVE LEARNING LOOP                       │
│                                                                 │
│  SCANNER (tiap 2 menit)                                        │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ 1. Fetch AgentSignalWeight dari DB (cache 5 menit)       │  │
│  │ 2. Saat score signal: base_pts × weight dari tabel       │  │
│  │ 3. Regime-aware: pakai weight kolom regime="trending_up" │  │
│  │ 4. Adaptive MIN_SCORE: jika win_rate 20 trade terakhir   │  │
│  │    < 40% → naikkan MIN_SCORE; > 65% → turunkan sedikit  │  │
│  └──────────────────────────────────────────────────────────┘  │
│           ↓ scan result → open position                         │
│                                                                 │
│  MONITOR (tiap 2 menit)                                        │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ Untuk setiap open position:                              │  │
│  │ 5. Re-fetch klines terbaru untuk simbol posisi           │  │
│  │ 6. Re-score signals yang AKTIF saat posisi dibuka        │  │
│  │    - BB Squeeze masih ada? → score tetap tinggi, hold    │  │
│  │    - BB melebar? → signal gagal → tighten SL             │  │
│  │    - OI turun? → akumulasi berhenti → tighten SL         │  │
│  │    - Funding menjadi sangat positif? → crowding → hold   │  │
│  │ 7. Jika signal_score turun >30% dari entry score:        │  │
│  │    → close early (SL tighten ke harga sekarang - 1%)    │  │
│  └──────────────────────────────────────────────────────────┘  │
│           ↓ trade closed (TP/SL)                               │
│                                                                 │
│  WEIGHT UPDATER (tiap 5 menit, setelah scan)                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ 8. Map signal → is_win (pnl_pct > 0, bukan hanya "tp")  │  │
│  │ 9. Update win_rate per signal per regime                 │  │
│  │ 10. Hitung weight baru (smooth, bukan step function)     │  │
│  │ 11. JUGA proses expired trades sebagai negative signal   │  │
│  │     (expired = signal tidak memicu gerakan = penalty)    │  │
│  └──────────────────────────────────────────────────────────┘  │
│           ↓ weights di-cache in-memory (TTL 5 menit)          │
│           ↓ kembali ke SCANNER                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

### C. Gap Bugs untuk Full Adaptive Learning Loop

| # | Severity | Komponen | Gap Kritis | Status |
|---|----------|----------|------------|--------|
| F86 | 🔴 HIGH | `agent1.py`, `agent2.py` | **Tidak ada mekanisme load weights dari DB saat scan** — agent harus query (atau pakai cache in-memory) `agent_signal_weights` di awal setiap scan cycle, lalu multiply base_pts × weight saat scoring setiap sinyal. Ini adalah gap terbesar yang membuat seluruh learning tidak berfungsi | ❌ belum |
| F87 | 🔴 HIGH | `weight_updater.py` | **Tidak ada in-memory weight cache** — jika setiap simbol dalam scan (150 simbol) query DB untuk cek weight setiap sinyal, itu ratusan query per cycle. Butuh cache: `fetch_weights_cache()` load sekali dari DB awal cycle, simpan sebagai dict `{(agent, signal_key, regime): weight}`, pakai untuk scoring | ❌ belum |
| F88 | 🔴 HIGH | `monitor.py` | **Tidak ada position re-scoring** — monitor tidak pernah re-evaluate apakah sinyal yang membuka posisi masih valid. Sebuah posisi LONG terbuka karena BB Squeeze. Jika 1 jam kemudian BB melebar (squeeze selesai tanpa breakout), posisi tetap hold penuh tanpa reaksi | ❌ belum |
| F89 | 🔴 HIGH | `scheduler.py` + `auto_trader.py` | **Tidak ada adaptive MIN_SCORE** — MIN_SCORE=52 dan AUTO_OPEN_THRESHOLD=72 permanen. Seharusnya ada `get_adaptive_threshold(agent, regime)`: baca 20 trade terakhir per agent, hitung rolling win rate → jika < 35% raise threshold +5, jika > 65% lower threshold -3. Scanner jadi lebih konservatif saat performance buruk | ❌ belum |
| F90 | 🟡 MEDIUM | `monitor.py` | **Signal degradation tidak mempengaruhi SL trail** — ketika monitor check posisi, tidak ada evaluasi "apakah kondisi yang membuka posisi ini masih ada?". Jika OI mulai turun dan funding jadi sangat positif (reversal signal), SL harusnya diperketat. Saat ini SL hanya trail berdasarkan price level, bukan kondisi fundamental | ❌ belum |
| F91 | 🟡 MEDIUM | `weight_updater.py` | **Tidak ada weight cache TTL yang dishare ke agents** — butuh modul `weight_cache.py` yang: (1) load dari DB sekali per interval, (2) expose `get_weight(agent, signal_key, regime)` yang bisa dipanggil sync dari dalam scoring loop, (3) auto-refresh setiap 5 menit. Tanpa ini, agents tidak bisa pakai weights tanpa async DB call per sinyal | ❌ belum |
| F92 | 🟡 MEDIUM | `weight_updater.py` | **Tidak ada per-coin learning table** — hanya track per signal_key, bukan per (signal_key, symbol). Sinyal "BB Squeeze" yang selalu menang di BTCUSDT tapi selalu kalah di SHIBUSDT diperlakukan sama. Butuh tabel atau field tambahan: `coin_signal_weight` dengan key `(agent, signal_key, symbol)` | ❌ belum |
| F93 | 🟡 MEDIUM | `regime.py` + `weight_updater.py` | **Weights per regime tidak dipakai secara aktif** — `agent_signal_weights` punya kolom `regime` dan diisi (trending_up, ranging, dll), tapi agent tidak membaca weights berdasarkan regime saat ini. Jika "BB Squeeze" punya win_rate=80% di `ranging` tapi 30% di `trending_up`, agent harus pakai weight berbeda tergantung regime yang sedang aktif | ❌ belum |
| F94 | 🟢 LOW | `weight_updater.py` | **Tidak ada decay untuk weights lama** — sinyal yang terakhir dipakai 3 bulan lalu masih punya weight sama seperti sinyal yang dipakai kemarin. Market berubah. Weight lama harus di-decay mendekati 1.0 (neutral) jika tidak ada trade baru dalam 30 hari: `weight = 1.0 + (weight-1.0) × decay_factor` | ❌ belum |
| F95 | 🟢 LOW | `agents/futures/` (tidak ada) | **Tidak ada volatility-adjusted confidence score** — score 72 di `ranging` regime punya makna berbeda dari score 72 di `volatile` regime. Volatilitas tinggi = semua signal lebih noisy = confidence harus di-discount. Butuh: `adjusted_score = score × regime_confidence_factor` sebelum dibandingkan dengan MIN_SCORE | ❌ belum |

---

### D. Desain Komponen yang Dibutuhkan

**Komponen baru yang perlu dibuat (urutan prioritas):**

```
1. weight_cache.py  (BARU)
   - load_weights(agent) → dict{signal_key: weight} dari DB
   - get_weight(agent, signal_key, regime) → float
   - auto-refresh background setiap 5 menit
   - Dipanggil oleh: agent1.py, agent2.py di awal scan_symbol()

2. adaptive_threshold.py  (BARU)
   - get_min_score(agent) → int  (52 default, naik/turun berdasarkan win rate)
   - get_auto_threshold(agent, regime) → int  (72 default, adaptive)
   - Dipanggil oleh: scheduler.py sebelum filter results

3. position_rescorer.py  (BARU, bagian dari monitor)
   - rescore_open_position(trade, tf_map) → float  (current score)
   - compare dengan entry_score di signals_json
   - Jika drop > 30% → return "tighten_sl" signal

4. weight_updater.py  (MODIFIKASI)
   - Tambah: process expired trades sebagai -0.5 partial loss
   - Tambah: weight decay untuk signal tidak aktif 30 hari
   - Fix: is_win harus pakai pnl_pct > 0, bukan hanya status=="tp"

5. agent1.py + agent2.py  (MODIFIKASI)
   - Di awal scan(): load weight cache
   - Di setiap signal scoring: multiply by weight
   - Di scan_symbol(): pakai adaptive MIN_SCORE
```

---

### E. Contoh Alur Learning yang Benar (Setelah Fix)

```
Hari 1:
  BB Squeeze 1H muncul di 10 coin → 7 TP, 3 SL → win_rate=70% → weight=1.5

Hari 2 Cycle 1:
  BTCUSDT: "BB Squeeze 1H" detected
  → base score dari squeeze = 12 pts
  → baca weight cache: bb_squeeze_N_N = 1.5  (karena 70% win rate)
  → adjusted = 12 × 1.5 = 18 pts  ← signal ini naik bobot
  → total score lebih tinggi → lebih mudah lolos → posisi dibuka

Hari 3 (rolling win rate agent1 turun ke 32%):
  → adaptive_threshold: MIN_SCORE naik dari 52 → 57
  → AUTO_OPEN_THRESHOLD: naik dari 72 → 77
  → Lebih sedikit posisi dibuka → hanya setup terbaik yang lolos
  → Win rate mulai recover

Posisi open di hari 3:
  Monitor cycle 2 menit:
  → Re-fetch 1H data BTCUSDT
  → Cek: BB Squeeze masih ada? width = 8.2% → TIDAK lagi squeeze
  → Cek: OI berubah? OI turun 1.5%
  → Signal score turun dari 72 → 48 (lebih dari 30% drop)
  → Monitor: tighten SL ke current price - 0.5%
  → Jika harga turun sedikit: SL hit, keluar dengan small loss
  → Daripada hold sampai SL awal yang -8% dari entry
```

---

## Pass 18 — Deep Re-Audit Menyeluruh (F100-F106)

> Re-baca semua file futures dari awal. Temuan baru yang sebelumnya terlewat.

| # | Severity | File & Baris | Temuan | Status |
|---|----------|-------------|--------|--------|
| F100 | 🟡 MEDIUM | `agent2.py:211-233` | **`_score_accumulation()` trend loop `break` terlalu dini — selalu proses 4H saja** — loop `for tf_key in ["4h", "1h"]:` punya `break` di akhir setelah blok kondisi. Artinya jika data 4H tersedia, loop langsung `break` setelah 4H tanpa pernah cek 1H. Jika 4H trend = "up" (6 pts, markup sudah mulai), tapi 1H trend = "recovering" (10 pts, ideal pre-move) — agent selalu pakai 6 pts dari 4H dan skip sinyal 1H lebih baik. Fix: `break` hanya setelah ditemukan signal >= recovering, bukan selalu | ❌ belum |
| F101 | 🟡 MEDIUM | `scheduler.py:67-72` | **Extreme funding synthetic tickers punya `priceChangePercent: "0"` hardcode** — `_fetch_extreme_funding_tickers()` membangun ticker sintetis dengan `"priceChangePercent": "0"`. Coin yang sudah pump 20-30% dengan funding ekstrem tetap mendapat `change_24h=0` saat discan. Semua penalty berdasarkan `change_24h` (`if change_24h > 15: score -= 25`, dll.) tidak akan trigger. Coin yang sudah terbang jauh bisa lolos dengan skor tinggi palsu dari agent1/agent2 | ❌ belum |
| F102 | 🟡 MEDIUM | `futures_scanner.py:577-598` | **`/futures/auto/toggle` field `threshold` diterima tapi diabaikan sepenuhnya** — `AutoTradeToggle` model punya `threshold: int = 75` tapi endpoint `toggle_auto_trade()` hanya membaca `body.enabled`, tidak pernah gunakan `body.threshold`. User atau admin yang kirim `{"enabled": true, "threshold": 80}` berharap threshold berubah, tapi `AUTO_OPEN_THRESHOLD` tetap 72. Field ini dead code yang menyesatkan | ❌ belum |
| F103 | 🟡 MEDIUM | `history.py:258-290` | **`/history/equity` tidak ada filter style — campurkan semua styles** — `select(PaperTrade).where(status.in_(["tp", "sl"]))` tanpa filter `style`. Equity curve menggabungkan futures_agent1 + futures_agent2 + opportunity_spot dalam satu grafik. User yang lihat equity chart di history tidak tahu curve ini bukan pure futures. Endpoint lain (learning stats) sudah filter per style | ❌ belum |
| F104 | 🟢 LOW | `FuturesTab.tsx:348` | **`wins = closed.filter(p => p.status === "tp")` tidak exclude tp+pnl≤0** — di `useMemo stats`, `wins` dihitung dari semua trade status "tp" tanpa cek `pnl_pct > 0`. Trade yang status="tp" tapi net pnl=-0.05% (fee makan profit) tetap dihitung sebagai win di frontend. Win rate di FuturesTab Overview inflate dibanding backend `_is_real_win()` yang sudah benar. Sudah fix di history.py tapi belum di FuturesTab stats | ❌ belum |
| F105 | 🟡 MEDIUM | `futures_scanner.py:54` | **`GET /futures/scan` default `min_score=55` lebih tinggi dari `MIN_SCORE=52` agen** — `min_score: float = Query(default=55)`. Cache berisi semua sinyal score ≥ 52 (agent threshold). Tapi REST endpoint secara default hanya return score ≥ 55. Signal scored 52-54 ada di cache tapi tidak pernah muncul via API call default. Jika seseorang pakai API langsung (bukan WS), mereka miss 3 poin signal. WS tidak kena masalah ini karena kirim raw cache tanpa filter | ❌ belum |
| F106 | 🟢 LOW | `agent1.py:319-349` | **RSI dihitung dua kali per symbol per scan** — di `_score_pregainer()`, `_rsi_sweet_spot(closes)` di line 321 memanggil `_rsi()` secara internal. Kemudian line 345 memanggil `_rsi(primary.closes, 14)` lagi untuk penalty check. Dua pemanggilan yang identik tapi hasilnya tidak di-cache. Untuk 150-180 coins × 2 agents × 3 TFs = ratusan komputasi RSI redundan per siklus. Minor impact tapi bisa dioptimasi | ❌ belum |

---

## Pass 19 — Final Re-Audit: Store, Balance API, Model, Deployment, Duplication

> Audit akhir file yang belum pernah diperiksa: `store.py`, `balance.py`, `paper_trade.py`, `main.py`, plus temuan tersisa dari kode yang sudah dibaca sebelumnya.

| # | Severity | File & Baris | Temuan | Status |
|---|----------|-------------|--------|--------|
| F107 | 🟡 MEDIUM | `store.py:28` | **`set_result()` panggil `set_scanning(False)` terlalu dini saat agent1 selesai** — scheduler memanggil `set_result("agent1")` lalu `set_result("agent2")` secara berurutan. Setiap `set_result()` langsung panggil `set_scanning(False)` dan broadcast `{"type":"scanning","scanning":false}` ke semua WS client. Akibatnya saat agent1 disimpan, semua subscriber WS langsung menerima sinyal "scanning selesai" padahal agent2 belum diproses. WS client yang refresh UI di event ini akan tampilkan data separuh (hanya agent1). Fix: panggil `set_scanning(False)` hanya setelah kedua agent selesai, atau scheduler yang explicit call `set_scanning(False)` setelah kedua `set_result()` | ❌ belum |
| F108 | 🔴 HIGH | `paper_trade.py:25` | **`signals_json` ORM default `"[]"` (list) tapi semua consumer expect dict** — `signals_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")`. Semua kode consumer (`monitor.py`, `futures_learning.py`, `auto_trader.py`) lakukan `json.loads(t.signals_json or "{}")` lalu panggil `.get("tp1")`, `.get("risk_pct")`, dll. Jika trade terbuat dengan ORM default tanpa explicit set, `json.loads("[]")` → Python list → `list.get()` → `AttributeError`. Ini bisa terjadi jika POST `/futures/trade` manual tidak menyertakan `signals_json` dan ORM default aktif. Fix: default harus `"{}"` (empty dict, bukan list) | ❌ belum |
| F109 | 🟡 MEDIUM | `balance.py:27` | **`STYLE_MAP["futures"]` hanya map ke `futures_agent1` — agent2 balance tidak bisa diakses** — `STYLE_MAP = {"spot": "opportunity_spot", "futures": "futures_agent1"}` (komentar: "placeholder for future"). Monitor (`_rebuild_futures_paper_balance`) menjaga PaperBalance terpisah untuk `futures_agent1` DAN `futures_agent2`. Tapi `GET /balance/futures` hanya return agent1. Tidak ada rute bernama yang return agent2 balance — P&L kumulatif agent2 invisible dari balance API. Fix: tambah `"futures2": "futures_agent2"` atau return aggregate kedua agent | ❌ belum |
| F110 | 🟢 LOW | `balance.py:271` | **`ResetRequest.initial_balance` default hardcode `1000.0`** — `Field(default=1000.0, gt=0)`. Seharusnya `Field(default=FUTURES_STARTING_BALANCE)` agar ikut single source of truth di `trading_costs.py`. Jika konstanta diubah, POST `/balance/{style}/reset` tanpa body akan reset ke nilai lama | ❌ belum |
| F111 | 🟡 MEDIUM | `scanner/page.tsx:WS_URL` | **WS URL hardcode `"ws://localhost:8000/ws/futures"` — production/staging/remote akan gagal connect** — URL tidak membaca dari env var atau config. Di deployment non-localhost (VPS, Docker, berbeda port), WS scanner tidak bisa connect dan seluruh realtime data futures hilang. `opportunity_stream` kemungkinan punya masalah sama tapi di luar scope. Fix: baca dari `process.env.NEXT_PUBLIC_WS_URL` atau derive dari `window.location.host` | ❌ belum |
| F112 | 🟢 LOW | `regime.py` | **`_ema()` didefinisikan lokal, identik dengan `_ema()` di `agent1.py`** — dua implementasi yang sama persis di dua file berbeda. Jika satu difix (misal periode atau formula diubah), file lain tidak ikut terupdate otomatis. Seharusnya dipindah ke modul shared (misalnya `agents/futures/utils.py`) dan diimport keduanya | ❌ belum |
| F113 | 🟢 LOW | `scheduler.py:5` | **Komentar file: "Both agents run concurrently" — tidak akurat** — docstring baris 4: `"Both agents run concurrently on the same 100-symbol universe."` Tapi kode Step 3 (baris 130-144) menjalankan `a1.scan_symbol()` lalu `a2.scan_symbol()` secara sekuensial dalam satu `for ticker in tickers:` loop. Tidak ada parallelisme — agent2 tunggu agent1 selesai per simbol. Misleading bagi developer yang ingin optimalkan atau debug eksekusi agen | ❌ belum |

---

## Pass 17 — Futures Market Overview (`futures_market.py` + `futures-market/page.tsx`)

> Audit fitur market overview: data kelengkapan OI, rate limit safety, integrasi dengan scanner

| # | Severity | File & Baris | Temuan | Status |
|---|----------|-------------|--------|--------|
| F96 | 🟡 MEDIUM | `futures_market.py:195` | **OI hanya di-fetch untuk top-50 by volume** — `top50_syms = [x["symbol"] for x in enriched_sorted_vol[:50]]`. Seluruh 150+ coin lain punya `open_interest = None` dan `open_interest_usdt = None`. Tab "Top OI" hanya bisa rank dari 50 coin itu, bukan seluruh universe. Coin di rank 51-200 yang mungkin punya OI tinggi sama sekali tidak muncul di top_oi list. Solusi: fetch semua atau gunakan `/fapi/v1/openInterest/hist` untuk batch | ❌ belum |
| F97 | 🟡 MEDIUM | `futures_market.py:196` | **50 concurrent `_get_oi()` calls tanpa semaphore** — `await asyncio.gather(*[_get_oi(client, s) for s in top50_syms])` kirim 50 request `/fapi/v1/openInterest` sekaligus. Binance rate limit: weight=5 per request × 50 = 250 weight sekaligus. Jika total weight paket ini + request lain melebihi 1200/menit, endpoint 429 dan semua OI jadi 0. Monitor.py pakai semaphore=10 untuk batch prices, tapi _get_oi tidak ada throttle | ❌ belum |
| F98 | 🟡 MEDIUM | `futures_market.py:219` · `futures-market/page.tsx` | **`top_gainers`/`top_losers` = coin yang sudah bergerak, tidak terhubung ke pre-gainer scanner** — `top_gainers = [x for x in enriched_sorted_chg if x["change_pct"] > 0][:15]` menampilkan coin yang sudah naik dalam 24H. Tujuan user: temukan pre-gainer **sebelum** bergerak. Market overview tidak ada tab atau kolom "flat coins with squeeze" atau link ke agent1 pre-gainer score. Data sudah ada (funding_rate, quote_vol_24h) tapi tidak dipakai untuk highlight pre-gainer candidates | ❌ belum |
| F99 | 🟢 LOW | `frontend/src/features/futures-market/page.tsx` | **Tidak ada action dari market overview ke open posisi** — user melihat top gainers/losers di market page tapi tidak ada tombol "Scan" atau "Open Position" untuk coin tertentu. FuturesTab scanner dan manual trade harus dibuka terpisah. Tidak ada navigasi atau link `onClick` dari HeatTile atau coin row ke scanner page dengan symbol pre-filled | ❌ belum |

---

## Implementation Phases — Prompt Siap Pakai

> Copy-paste prompt tiap phase ke sesi Claude Code baru.
> Data paper trades < 50 → **full DB reset setelah Phase 1 selesai**.
> Urutan wajib: Phase 1 → reset DB → Phase 2 → 3 → 4 → 5+6 → 7

---

### ✅ Phase 0 — SELESAI

```
F3  ✅ agent2._calc_levels copy-paste → delegasi ke agent1
F4  ✅ import ganda di agent2
F8  ✅ next_scan_in_min hardcode 900 → INTERVAL_SEC
F14 ✅ sl_after_tp1 LONG = halfway (50%) → 75% toward TP1
F15 ✅ max_age close status tp/sl → "expired", excluded dari win rate
F16 ✅ legacy styles di monitor WHERE clause → dihapus
F17 ✅ STARTING_BALANCE duplikat di futures_scanner.py → import dari trading_costs
F18 ✅ /futures/positions price fetch sequential → batch endpoint
F19 ✅ validasi R:R di open_futures_trade
F21 ✅ STARTING_BALANCE + RISK_PCT hardcode frontend → dari API / trading_costs
F22 ✅ currentBalance frontend → dari /balance/futures (DB)
F23 ✅ unrealized_pnl open positions tidak kurangi fee → deduct 0.10% round trip
```

---

### ✅ Phase 1 — Data Integrity & Model Foundation (SELESAI)

```
Kerjakan Phase 1 dari PLAN-FUTURES.md. Ini adalah prasyarat semua phase lain —
tanpa ini data yang masuk DB sudah korup dari awal. Jangan kerjakan file futures
lain di luar daftar ini.

Bug yang harus difix:

F108 — backend/app/models/paper_trade.py
  signals_json default saat ini adalah "[]" (JSON array/list).
  Semua consumer code (monitor.py, futures_learning.py, auto_trader.py) memanggil
  json.loads(t.signals_json or "{}") lalu .get("tp1"), .get("risk_pct"), dll.
  List tidak punya .get() → AttributeError di edge case.
  Fix: ganti default="[]" → default="{}"

F51 — agents/futures/auto_trader.py
  Saat auto_open_positions() membuat PaperTrade baru, field berikut tidak di-set:
  - position_size (ukuran posisi dalam USDT)
  - risk_dollar (dollar yang di-risk per trade)
  - balance_snapshot (balance saat posisi dibuka)
  Fix: hitung dan set ketiga field ini saat INSERT trade baru.
  Formula:
    notional = FUTURES_STARTING_BALANCE * FUTURES_RISK_PCT / (risk_pct / 100)
    position_size = notional
    risk_dollar = notional * (risk_pct / 100)
    balance_snapshot = FUTURES_STARTING_BALANCE (atau dari PaperBalance jika tersedia)

F59 — backend/app/api/v1/futures_scanner.py endpoint POST /futures/trade
  Manual trade via API juga tidak set position_size / risk_dollar / balance_snapshot.
  Fix: sama dengan F51 — hitung dan set saat INSERT.

F58 — agents/futures/monitor.py fungsi check_futures_positions()
  Saat trade ditutup (SL/TP/expired), pnl_dollar tidak pernah di-set.
  pnl_dollar selalu NULL di semua closed trades → dollar P&L tidak bisa ditampilkan.
  Fix: setelah menghitung pnl_net (sudah ada), tambahkan:
    notional = FUTURES_STARTING_BALANCE * FUTURES_RISK_PCT / (risk_pct_from_meta / 100)
    trade.pnl_dollar = round((pnl_net / 100) * notional, 2)

F13 — agents/futures/auto_trader.py
  risk_pct hanya disimpan di signals_json["risk_pct"], tidak di field dedicated.
  Jika signals_json corrupt atau kosong, _rebuild_futures_paper_balance() fallback ke 2.0
  yang menghasilkan notional berbeda dari yang sebenarnya dipakai.
  Fix: pastikan signals_json SELALU di-set dengan risk_pct yang benar dan tidak bisa None/kosong.

Setelah semua fix di atas selesai dan verified, berikan SQL reset DB:

  DELETE FROM paper_trades WHERE style LIKE 'futures%';
  DELETE FROM agent_signal_weights;
  DELETE FROM paper_balance WHERE style LIKE 'futures%';
```

---

### ✅ Phase 2 — Core Agent Signal Quality (SELESAI)

```
Kerjakan Phase 2 dari PLAN-FUTURES.md. Perbaiki kualitas sinyal kedua agent futures.
File yang boleh diubah: agents/futures/agent1.py, agents/futures/agent2.py,
agents/futures/scheduler.py, agents/futures/data.py

Bug yang harus difix:

F34 — agents/futures/agent1.py fungsi scan_symbol()
  Saat ini hanya return 1 arah (direction yang skornya lebih tinggi).
  Jika LONG score=65 dan SHORT score=58, SHORT dibuang padahal keduanya valid (≥ MIN_SCORE=52).
  Fix: return LIST — kembalikan kedua arah jika masing-masing score ≥ MIN_SCORE dan RR ≥ MIN_RR.
  Caller (scheduler.py) harus di-update untuk handle list result per symbol.

F52 — agents/futures/agent2.py fungsi scan_symbol()
  Bug identik dengan F34. Fix sama persis.

F100 — agents/futures/agent2.py fungsi _score_accumulation()
  Di loop trend scoring:
    for tf_key in ["4h", "1h"]:
        ...
        break  ← unconditional break
  Akibatnya jika data 4H tersedia, 1H tidak pernah dicek.
  Kasus: 4H trend="up" → 6 pts, tapi 1H trend="recovering" → 10 pts (lebih baik).
  Fix: break hanya jika sinyal yang ditemukan cukup kuat (mis. trend != "ranging"),
  atau evaluasi kedua TF dan ambil yang tertinggi.

F101 — agents/futures/scheduler.py fungsi _fetch_extreme_funding_tickers()
  Synthetic tickers yang dibuat hardcode "priceChangePercent": "0".
  Coin yang sudah pump 25% dengan funding ekstrem akan mendapat change_24h=0
  sehingga semua penalty berbasis change_24h tidak trigger di agent scoring.
  Fix: fetch priceChangePercent asli dari /fapi/v1/ticker/24hr untuk simbol tersebut,
  atau gunakan lastPrice dari premiumIndex dan hitung sendiri vs openPrice.

F5 — agents/futures/agent2.py fungsi _score_distribution()
  SHORT tanpa Wyckoff distribution/markdown phase hanya dapat -5 pts.
  Signal lain (BB squeeze + funding + resistance) bisa total ≥ 52 tanpa fase distribusi.
  Fix: jika tidak ada Wyckoff distribution/markdown phase, penalty -15 pts (bukan -5).

F6 — agents/futures/agent1.py fungsi _score_pregainer()
  Breakout bonus +5 pts diberikan jika price > recent_high * 0.99 AND 0 < change_24h < 8.
  Ini berlawanan dengan filosofi pre-gainer — coin yang sudah pump 6-8% bukan pre-gainer.
  Fix: hapus bonus breakout ini, atau batasi hanya jika change_24h < 2%.

F35 — agents/futures/agent1.py fungsi _score_pregainer()
  Tidak ada bonus untuk coin yang genuinely flat (pre-gainer ideal).
  Fix: tambah bonus +5 jika -2% ≤ change_24h ≤ 2% DAN ada BB squeeze (bandwidth < 5%).

F37 — agents/futures/agent1.py fungsi _score_predump()
  Kondisi near_top untuk SHORT tidak konsisten dengan logika LONG.
  Cek implementasi near_top di SHORT vs near_resistance di LONG dan seragamkan logikanya.

F2 — agents/futures/data.py fungsi fetch_symbol_data()
  Tidak ada guard jika Binance return < 50 candles (simbol baru atau delisted).
  Indikator TA yang butuh 50 candles akan return invalid/garbage values.
  Fix: setelah fetch, cek len(closes) < 50 → return None atau skip simbol.
  Pastikan caller (scheduler.py) handle None result.

F106 — agents/futures/agent1.py fungsi _score_pregainer()
  RSI dihitung dua kali:
  1. _rsi_sweet_spot(closes) memanggil _rsi() internal
  2. _rsi(primary.closes, 14) dipanggil lagi di baris ~345 untuk penalty check
  Fix: hitung RSI sekali, simpan ke variabel lokal, gunakan di kedua tempat.
```

---

### ✅ Phase 3 — Monitor & Position Management (SELESAI)

```
Kerjakan Phase 3 dari PLAN-FUTURES.md. Perbaiki lifecycle posisi futures.
File yang boleh diubah: agents/futures/monitor.py, agents/futures/store.py

Bug yang harus difix:

F83 — agents/futures/monitor.py fungsi check_futures_positions()
  tp1 fallback formula saat ini: tp1 = trade.take_profit * 0.5 + trade.entry_price * 0.5
  Ini salah untuk SHORT karena take_profit (TP2) < entry_price.
  Fix: pastikan trail logic SHORT menggunakan tp1 yang benar:
    tp1_SHORT = entry - (entry - tp2) * 0.5

F76 — agents/futures/monitor.py
  Tidak ada partial close di TP1. Saat harga mencapai TP1, posisi terus berjalan ke TP2.
  Fix: saat harga mencapai TP1, tutup 33% dari posisi (record sebagai partial close),
  lock profit tersebut, dan biarkan 67% berjalan ke TP2.
  Implementasi: update pnl_dollar dengan 33% profit, catat di signals_json["partial_closes"].

F77 — agents/futures/monitor.py
  Setelah harga 50% antara TP1 → TP2, SL belum di-advance ke TP1 level.
  Fix: jika harga sudah 50% antara TP1 dan TP2, advance trail_sl ke TP1.

F81 — agents/futures/monitor.py TP extension logic
  Saat trade.take_profit di-extend ke TP3, SL tidak ikut diupdate ke TP1 level.
  Fix: saat tp_extended=True, sekaligus set trail_sl = tp1 (lock profit minimum di TP1).

F84 — agents/futures/monitor.py TP extension logic
  Score yang dicek adalah trade.probability (score saat entry, stale).
  Fix: cek score saat ini dari futures_store — ambil result terbaru untuk symbol ini.

F85 — agents/futures/monitor.py
  LIQ_GUARD_DIST_PCT = 8.0 flat tidak adaptif terhadap leverage.
  Fix:
    leverage ≤ 5×  → guard_pct = 8.0%
    leverage ≤ 10× → guard_pct = 6.0%
    leverage ≤ 20× → guard_pct = 4.0%
    leverage > 20× → guard_pct = 3.0%

F79 — agents/futures/monitor.py
  SL tidak beradaptasi dengan regime saat posisi dibuka.
  Fix: saat posisi baru pertama kali dicek (belum ada trail):
    regime="volatile" → perlebar initial SL sebesar ATR*0.5
    regime="ranging"  → perketat SL sebesar ATR*0.3

F80 — agents/futures/monitor.py
  Posisi stagnan > 48 jam tanpa progress (harga belum 20% toward TP1) membuang modal.
  Fix: jika age > 48h DAN price masih dalam 20% dari entry → close dengan status="expired".

F61 — agents/futures/monitor.py
  _closed_today counter tidak pernah direset. Terus bertambah tanpa reset setiap hari.
  Fix: di awal setiap cycle, cek tanggal hari ini. Jika berbeda → reset _closed_today = 0.

F62 — agents/futures/monitor.py fungsi run_futures_monitor()
  _rebuild_futures_paper_balance() dipanggil setiap cycle 2 menit — tidak perlu sesering itu.
  Fix: panggil hanya setiap 10 cycle: if _cycle_count % 10 == 0: await _rebuild...

F107 — agents/futures/store.py fungsi set_result()
  set_result() langsung panggil set_scanning(False) setiap kali dipanggil.
  Karena scheduler panggil set_result("agent1") lalu set_result("agent2") berurutan,
  WS client menerima "scanning: false" setelah agent1 selesai padahal agent2 belum.
  Fix: hapus set_scanning(False) dari dalam set_result().
  Biarkan scheduler.py yang explicitly panggil set_scanning(False) setelah kedua agent selesai.
```

---

### ✅ Phase 4 — Learning Feedback Loop (SELESAI)

```
Kerjakan Phase 4 dari PLAN-FUTURES.md. Buat adaptive learning loop jadi nyata — saat ini
weight_updater menulis ke DB tapi agent tidak pernah membacanya kembali.
File: agents/futures/agent1.py, agents/futures/agent2.py, agents/futures/weight_updater.py,
agents/futures/regime.py, agents/futures/store.py

Bug yang harus difix:

F68 — agents/futures/agent1.py + agent2.py
  Weight dari agent_signal_weights DB tidak pernah dibaca balik ke scoring.
  Fix: di awal scan_symbol() load weights dari DB:
    SELECT signal_key, weight FROM agent_signal_weights
    WHERE agent='{style}' AND regime='{current_regime}' AND total_count >= 3
  Simpan sebagai dict {signal_key: weight}.
  Saat scoring: score += base_pts * weights.get(signal_key, 1.0)
  Weight range valid: 0.7 – 1.5 (sudah di-clamp oleh weight_updater).

F69 — agents/futures/weight_updater.py
  MIN_SCORE dan AUTO_OPEN_THRESHOLD tidak adaptif terhadap historical win rate.
  Fix: tambah fungsi get_adaptive_thresholds(agent: str) → dict:
    win_rate < 40%:   min_score=57, threshold=77
    win_rate 40-55%:  min_score=54, threshold=74
    win_rate 55-65%:  min_score=52, threshold=72 (default)
    win_rate > 65%:   min_score=50, threshold=70
  Scheduler dan auto_trader membacanya sebelum filtering.

F60 — agents/futures/weight_updater.py
  is_win = trade.status == "tp" → tidak cek pnl_pct > 0.
  Fix: is_win = trade.status == "tp" and (trade.pnl_pct or 0.0) > 0

F70 — agents/futures/weight_updater.py
  Expired trades tidak diproses sebagai negative signal.
  Fix: expired trades → proses seperti SL (is_win = False) di weight calculation.

F73 — agents/futures/weight_updater.py fungsi _normalize_signal()
  Saat ini strip semua angka:
    "BB Squeeze 1H" → "bb_squeeze_h"
    "BB Squeeze 4H" → "bb_squeeze_h"  ← SAMA! kehilangan info timeframe
  Fix: pertahankan angka — hanya lowercase dan replace spasi dengan underscore:
    "BB Squeeze 1H" → "bb_squeeze_1h"
    "BB Squeeze 4H" → "bb_squeeze_4h"

F75 — agents/futures/weight_updater.py fungsi _weight_from_rate()
  Step function. Fix: smooth linear interpolation:
    weight = max(0.7, min(1.5, 0.7 + win_rate * 0.8))
  Contoh: win_rate=0.3 → 0.94, win_rate=0.6 → 1.18, win_rate=1.0 → 1.5

F71 — agents/futures/weight_updater.py
  Tidak ada per-coin memory. DOGEUSDT selalu SL tapi tetap di-scan lagi.
  Fix: tambah per-coin blacklist:
    - Coin SL 3× berturut-turut tanpa satu TP → blacklist 24 jam
    - Simpan di in-memory dict {symbol: blacklist_until_ts}
    - Di scheduler, skip symbol yang di-blacklist

F72 — agents/futures/agent1.py + agent2.py
  Regime dideteksi tapi tidak mempengaruhi scoring sama sekali.
  Fix: baca current_regime di awal scan_symbol(), apply modifiers:
    volatile:      kurangi momentum/breakout bonus 20%, naikkan effective min_score +5
    trending_up:   boost trend-following signals +10%, kurangi counter-trend -10%
    trending_down: kebalikannya
    ranging:       boost BB squeeze +10%, kurangi momentum -10%

F63 — agents/futures/regime.py
  CACHE_TTL = 30 * 60 terlalu lama. Fix: CACHE_TTL = 5 * 60

F64 — agents/futures/regime.py
  Hanya pakai 4H BTC candles — lag 4 jam saat reversal.
  Fix: tambah 1H candles sebagai secondary check.
  Jika 4H dan 1H bertentangan (mis. 4H=trending_up tapi 1H=volatile) → percayai 1H.

F32 — agents/futures/store.py
  STALE_SEC = 20 * 60 tidak masuk akal — scanner jalan setiap 2 menit.
  Fix: STALE_SEC = 5 * 60
```

---

### ✅ Phase 5 — Backend API Corrections (SELESAI)

```
Kerjakan Phase 5 dari PLAN-FUTURES.md. Perbaiki endpoint yang return data salah atau tidak konsisten.
File: backend/app/api/v1/futures_scanner.py, backend/app/api/v1/history.py,
backend/app/api/v1/balance.py, backend/app/ws/futures_stream.py,
agents/futures/scheduler.py

Bug yang harus difix:

F102 — backend/app/api/v1/futures_scanner.py endpoint POST /futures/auto/toggle
  Model AutoTradeToggle punya field threshold: int = 75 tapi endpoint tidak membacanya.
  body.threshold di-ignore → AUTO_OPEN_THRESHOLD tetap 72 apapun yang dikirim.
  Fix: setelah set_auto_enabled(body.enabled), tambah set_auto_threshold(body.threshold)
  di auto_trader.py. Tambah fungsi set_auto_threshold() di auto_trader.py.

F103 — backend/app/api/v1/history.py fungsi get_equity()
  Query tidak ada filter style → menggabungkan futures_agent1 + futures_agent2 + opportunity_spot.
  Fix: tambah parameter style: str = Query(default="futures") dan filter query:
    WHERE style IN ('futures_agent1', 'futures_agent2') untuk style="futures"
    WHERE style = 'opportunity_spot' untuk style="spot"

F105 — backend/app/api/v1/futures_scanner.py endpoint GET /futures/scan
  Default min_score=55 lebih tinggi dari MIN_SCORE=52 yang dipakai agent.
  Signal score 52-54 ada di cache tapi tidak pernah muncul via REST default.
  Fix: ganti default min_score: float = Query(default=55) → default=52

F109 — backend/app/api/v1/balance.py
  STYLE_MAP = {"futures": "futures_agent1"} — agent2 tidak bisa diakses.
  Fix: tambah "futures2": "futures_agent2" di STYLE_MAP,
  ATAU GET /balance/futures return aggregate kedua agent (sum balance, combined pnl).

F110 — backend/app/api/v1/balance.py class ResetRequest
  initial_balance: float = Field(default=1000.0) hardcode.
  Fix: Field(default=FUTURES_STARTING_BALANCE)

F27 — backend/app/api/v1/futures_scanner.py endpoint GET /futures/monitor/risk
  Price fetch N individual requests. Fix: gunakan batch endpoint seperti monitor.py.

F28 — backend/app/api/v1/futures_scanner.py endpoint GET /futures/monitor/risk
  unrealized_pnl tanpa deduct fee. Fix: kurangi ROUND_TRIP * 100 (0.10%).

F29 — backend/app/ws/futures_stream.py
  INTERVAL_SEC = 2 * 60 didefinisikan lokal.
  Fix: hapus, import dari agents.futures.scheduler: from agents.futures.scheduler import INTERVAL_SEC

F41 — backend/app/api/v1/history.py fungsi get_equity()
  BALANCE = 1000.0 hardcode. Fix: import dan gunakan FUTURES_STARTING_BALANCE dari trading_costs.

F42 — backend/app/api/v1/history.py fungsi get_daily_pnl()
  if t.pnl_pct: → skip pnl=0.0. Fix: if t.pnl_pct is not None:

F44 — backend/app/api/v1/history.py fungsi get_equity()
  risk_pct bisa berubah setelah trail SL.
  Fix: simpan risk_pct_original di signals_json saat trade dibuka.
  Di get_equity(): baca meta.get("risk_pct_original") fallback meta.get("risk_pct", 2.0).

F45 — backend/app/api/v1/history.py
  Filter logic style+status duplikat di dua blok berbeda.
  Fix: ekstrak ke helper _apply_filters(query, style, status, search) dan panggil sekali.

F48 — backend/app/api/v1/history.py fungsi get_stats()
  Tidak ada filter days → query semua trades sejak awal waktu.
  Fix: tambah parameter days: int = Query(default=90) dan apply cutoff.

F50 — backend/app/api/v1/history.py
  rr_ratio parsing split(":") rapuh. Fix: wrap try/except, fallback parse sebagai float.

F53 — backend/app/api/v1/history.py fungsi get_stats()
  if t.pnl_pct: → skip break-even. Fix: if t.pnl_pct is not None:

F9 — agents/futures/scheduler.py fungsi get_state()
  Tidak expose next_scan_in_min. Fix: tambah ke return dict:
    "next_scan_in_min": round(max(0, INTERVAL_SEC - (time.time() - (_last_scan or 0))) / 60, 1)

F20 — backend/app/api/v1/futures_scanner.py
  scanned: a1.get("scanned", 0) or a2.get("scanned", 0) — inconsistent.
  Fix: scanned = max(a1.get("scanned", 0), a2.get("scanned", 0))

F24 — backend/app/api/v1/futures_scanner.py endpoint GET /futures/positions
  Query pakai .limit(100). Fix: hapus limit atau tambah pagination.
```

---

### ✅ Phase 6 — Frontend Corrections (SELESAI)

```
Kerjakan Phase 6 dari PLAN-FUTURES.md. Perbaiki UI yang hardcode, win rate inflate, dan state mati.
File: frontend/src/features/history/components/FuturesTab.tsx,
frontend/src/features/history/components/FuturesAnalytics.tsx,
frontend/src/features/scanner/page.tsx,
backend/app/api/v1/futures_learning.py (untuk F65 dan F66)

Bug yang harus difix:

F104 — FuturesTab.tsx useMemo stats
  wins = closed.filter(p => p.status === "tp")  ← inflate
  Fix: wins = closed.filter(p => p.status === "tp" && (p.pnl_pct ?? 0) > 0)

F43 — FuturesTab.tsx
  closed = positions.filter(p => p.status !== "open") → include expired di denominator.
  Fix: closed = positions.filter(p => p.status === "tp" || p.status === "sl")

F46 — FuturesTab.tsx
  RISK_DOLLAR = module-level constant, tidak reaktif.
  Fix: hitung di dalam komponen dari learning?.balance?.starting * RISK_PCT.

F47 — FuturesTab.tsx
  Teks hardcode "$1,000 start" dan "Modal awal $1,000 · Risk $10/trade".
  Fix: ganti dengan nilai dari learning.balance.starting.

F26 — FuturesTab.tsx
  "Auto-Open: ≥ 75pt" hardcode. Fix: fetch dari GET /futures/auto/status.

F10 — auto_trader.py + FuturesTab.tsx
  AUTO_OPEN_THRESHOLD=72 di code, UI tampilkan "≥ 75pt".
  Fix: pastikan /futures/auto/status return threshold=72 dan UI pakai nilai itu.

F38 — frontend/src/features/scanner/page.tsx TradeModal
  const BALANCE = 1000 hardcode.
  Fix: fetch dari GET /balance/futures saat TradeModal dibuka.

F39 — frontend/src/features/scanner/page.tsx
  "Scanning 150 pairs..." hardcode.
  Fix: tampilkan dari status.scanned yang di-fetch dari /futures/status.

F40 — frontend/src/features/scanner/page.tsx
  totalLong/totalShort penjumlahan biasa → coin di kedua agent dihitung dua kali.
  Fix: deduplicate dengan Set sebelum hitung total.

F111 — frontend/src/features/scanner/page.tsx
  WS_URL = "ws://localhost:8000/ws/futures" hardcode.
  Fix: const WS_URL = process.env.NEXT_PUBLIC_WS_URL
    ? `${process.env.NEXT_PUBLIC_WS_URL}/ws/futures`
    : `ws://${window.location.host}/ws/futures`

F30 — frontend/src/features/history/components/FuturesAnalytics.tsx
  const START = 1000 hardcode. Fix: baca dari stats.balance.starting.

F31 — frontend/src/features/history/components/FuturesAnalytics.tsx
  Tidak ada auto-refresh. Fix: tambah setInterval(() => { void fetchAll(); }, 60_000)
  di useEffect dan clear interval di cleanup.

F65 — backend/app/api/v1/futures_learning.py
  Conservative equity win=+$30 / loss=-$10 flat, tidak mencerminkan ukuran posisi nyata.
  Fix: hitung dari FUTURES_STARTING_BALANCE * FUTURES_RISK_PCT sebagai risk_dollar.
  win = +risk_dollar * 3 (R:R 1:3), loss = -risk_dollar.

F66 — backend/app/api/v1/futures_learning.py
  equity_points[-50:] → riwayat awal $1000 hilang dari chart.
  Fix: return semua equity_points tanpa slice [-50:].

F25 — FuturesTab.tsx
  agentFilter state di-set tapi tidak dipakai untuk filter apapun.
  Fix: gunakan agentFilter untuk filter daftar posisi/trades yang ditampilkan.

F49 — FuturesTab.tsx
  selectedMonth dropdown hanya highlight baris, tidak filter.
  Fix: gunakan selectedMonth untuk filter trades berdasarkan bulan entry_at.
```

---

### ✅ Phase 7 — Market Overview & Cleanup (SELESAI)

```
Kerjakan Phase 7 dari PLAN-FUTURES.md. Market overview improvements dan minor fixes.
File: backend/app/api/v1/futures_market.py, frontend/src/features/futures-market/page.tsx,
agents/futures/auto_trader.py, agents/futures/monitor.py, agents/futures/regime.py,
agents/futures/agent1.py, agents/futures/agent2.py, agents/futures/scheduler.py

Bug yang harus difix:

F96 — backend/app/api/v1/futures_market.py
  OI hanya di-fetch untuk top-50 by volume. 150+ coin lain punya open_interest=None.
  Fix: fetch OI untuk semua coin, gunakan asyncio.Semaphore(10) untuk throttle.

F97 — backend/app/api/v1/futures_market.py
  50 concurrent _get_oi() calls tanpa throttle → bisa trigger rate limit (weight=5×50=250).
  Fix: tambah asyncio.Semaphore(10):
    sem = asyncio.Semaphore(10)
    async def _throttled(client, sym):
        async with sem: return await _get_oi(client, sym)
    results = await asyncio.gather(*[_throttled(client, s) for s in all_syms])

F98 — backend/app/api/v1/futures_market.py
  top_gainers/top_losers tidak terhubung ke pre-gainer scanner.
  Fix: tambah field "agent1_score" ke setiap coin dengan lookup dari futures_store.

F99 — frontend/src/features/futures-market/page.tsx
  CoinRow dan HeatTile tidak punya onClick.
  Fix: tambah onClick → navigate ke /scanner?symbol=BTCUSDT.

F12 — agents/futures/auto_trader.py
  get_cached_regime() dipanggil dua kali. Fix: panggil sekali di awal, simpan ke variabel lokal.

F11 — agents/futures/auto_trader.py
  Comment "# 85 in ranging" salah. Fix: "# 77 in ranging (base 72 + 5)"

F55 — agents/futures/auto_trader.py
  FUTURES_COOLDOWN_HOURS = 3 di dalam function body.
  Fix: pindah ke module level constant.

F33 — Tiga komputasi balance terpisah (monitor, learning, balance API).
  Fix: jadikan _rebuild_futures_paper_balance() sebagai satu source of truth.
  futures_learning.py dan balance.py baca dari PaperBalance table, tidak hitung sendiri.

F7 — agents/futures/agent1.py + agent2.py
  Score di-cap 99: min(score, 99). Fix: min(score, 100)

F112 — agents/futures/regime.py
  _ema() didefinisikan lokal, identik dengan _ema() di agent1.py.
  Fix: buat agents/futures/utils.py dengan _ema() dan helper TA lainnya.
  Import dari utils di regime.py dan agent1.py, hapus duplikat.

F113 — agents/futures/scheduler.py
  Docstring "Both agents run concurrently" — faktanya sekuensial.
  Fix: update → "Both agents score the same universe sequentially per symbol."
```

---

### Ringkasan Phase

| Phase | Focus | Bug | Status |
|-------|-------|-----|--------|
| ✅ Phase 0 | Foundation fixes | F3 F4 F8 F14 F15 F16 F17 F18 F19 F21 F22 F23 | Selesai |
| ✅ Phase 1 | Model & data foundation | F108 F51 F59 F58 F13 | Selesai |
| ✅ Phase 2 | Core agent signal quality | F34 F52 F100 F101 F5 F6 F35 F37 F2 F106 | Selesai |
| ✅ Phase 3 | Monitor & position lifecycle | F83 F76 F77 F81 F84 F85 F79 F80 F61 F62 F107 | Selesai |
| ✅ Phase 4 | Learning feedback loop | F68 F69 F60 F70 F73 F75 F71 F72 F63 F64 F32 | Selesai |
| ✅ Phase 5 | Backend API corrections | F102 F103 F105 F109 F110 F27 F28 F29 F41 F42 F44 F45 F48 F50 F53 F9 F20 F24 | Selesai |
| ✅ Phase 6 | Frontend corrections | F104 F43 F46 F47 F26 F10 F38 F39 F40 F111 F30 F31 F65 F66 F25 F49 | Selesai |
| ✅ Phase 7 | Market overview & cleanup | F96 F97 F98 F99 F12 F11 F55 F33 F7 F112 F113 | Selesai |
| ✅ Phase 8 | Signal quality + TP lifecycle | F56 F92 F78 F88 F90 | Selesai |
| **Total** | | **106 bug** | **✅ Semua Phase Selesai** |

> **Phase 8 selesai:** F56 ATH penalty (agent1), F92 per-coin win rate bonus (weight_updater + agent1 + agent2),
> F78 TP4 extension (monitor), F88/F90 funding degradation SL tighten (monitor every 10 cycles).
>
> **Sisa backlog:** F89-F95 learning depth lanjutan (per-regime weights, weight decay, dll) — Phase 9+.

> **Reset DB antara Phase 1 dan Phase 2:**
> ```sql
> DELETE FROM paper_trades WHERE style LIKE 'futures%';
> DELETE FROM agent_signal_weights;
> DELETE FROM paper_balance WHERE style LIKE 'futures%';
> ```
> Urutan wajib: Phase 1 → reset DB → Phase 2 → 3 → 4 → Phase 5+6 (paralel) → 7

---

## Pass 20 — Temuan dari Screenshot Live (15 Jun 2026)

> Observasi langsung dari UI yang sedang berjalan. Bukti visual dari screenshot.

| # | Severity | File & Baris | Temuan | Status |
|---|----------|-------------|--------|--------|
| F114 | 🔴 HIGH | `monitor.py` · `FuturesTab.tsx` · `DBHistoryTable.tsx` | **SL+ close ditampilkan sebagai "SL Hit" padahal P&L positif** — QNTX tertutup via SL trail (SL+ dipindah ke atas entry), P&L = +$14.84 (+2.15%). Tapi status badge = merah `SL`, alasan tutup = `SL Hit`, dan dihitung sebagai LOSS → Win Rate = 0.0% padahal trade ini untung. Tiga hal harus diubah: (1) monitor.py: saat menutup via trail SL dan pnl_net > 0 → set `close_reason = "sl_plus"` bukan `"sl_hit"`; (2) status badge: `sl_plus` tampil dengan warna berbeda (kuning/teal, bukan merah); (3) win/loss counting: `sl_plus` dengan pnl_net > 0 dihitung sebagai WIN | ✅ done |
| F115 | 🟡 MEDIUM | `FuturesTab.tsx` · `DBHistoryTable.tsx` | **Filter "Spot" muncul di tab History Futures** — filter bar di Futures History menampilkan tombol `Spot` yang tidak relevan. Semua record di sini adalah `futures_agent1/2/3`. Filter `Spot` tidak pernah menghasilkan data di tab ini dan membingungkan user. Fix: di Futures History tab, filter bar hanya tampilkan: `Semua | Pre-Gainer | Accumulation | Momentum | Status | Open | TP | SL | search` | ✅ done |
| F116 | 🟡 MEDIUM | `DBHistoryTable.tsx` · `FuturesTab.tsx` | **Kolom MARGIN tidak menampilkan leverage** — nilai margin sudah benar (notional ÷ leverage), tapi tanpa info leverage user tidak bisa interpret angka ini. SAMSUNG margin $44 tidak berarti apa-apa tanpa tahu ini 9x. Fix: kolom Margin tampilkan dua baris: `$44` (baris atas) + `9×` atau `· 9×` (baris bawah/subscript), atau satu baris `$44 · 9×`. Data leverage sudah ada di trade record | ✅ done |
| F117 | 🟡 MEDIUM | `FuturesTab.tsx` · badge `AgentBadge` | **Badge TIPE di history masih menampilkan `A1` / `A2` / `A3` — bukan nama strategi** — kolom TIPE di tabel riwayat menampilkan badge `A1` untuk futures_agent1, `A2` untuk futures_agent2. Setelah refactor ke "1 Scanner" framing, label seharusnya `Pre-Gainer`, `Accumulation`, `Momentum`. Filter bar juga masih punya tombol `A1` `A2` yang harus diganti. Fix: update `AgentBadge` atau mapping di `DBHistoryTable.tsx` untuk map `futures_agent1` → `Pre-Gainer`, `futures_agent2` → `Accumulation`, `futures_agent3` → `Momentum` | ✅ done |

---

### Tambahan ke Phase 6 — Bug Baru dari Pass 20

```
Tambahkan ke Phase 6 (Frontend Corrections):

F114 — monitor.py + FuturesTab.tsx + DBHistoryTable.tsx
  SL trail yang close di profit harus punya status berbeda dari SL biasa.
  Fix monitor.py: saat close via trail SL dan pnl_net > 0 → close_reason = "sl_plus".
  Fix badge: close_reason "sl_plus" → badge warna kuning/teal, bukan merah.
  Fix win counting: pnl_net > 0 AND close_reason in ("tp", "sl_plus") → dihitung WIN.

F115 — FuturesTab.tsx filter bar
  Hapus tombol "Spot" dari filter bar di Futures History tab.
  Ganti filter agent dengan: Pre-Gainer | Accumulation | Momentum
  (map dari futures_agent1 / futures_agent2 / futures_agent3)

F116 — DBHistoryTable.tsx kolom Margin
  Tampilkan leverage di samping margin: "$44 · 9×"
  Data leverage ada di trade.signals_json["leverage"] atau trade.leverage_used.

F117 — DBHistoryTable.tsx + AgentBadge
  Map label badge TIPE:
    futures_agent1 → "Pre-Gainer" (biru)
    futures_agent2 → "Accumulation" (ungu)
    futures_agent3 → "Momentum" (oranye)
  Update filter bar: hapus "A1" "A2", tambah "Pre-Gainer" "Accumulation" "Momentum".
```

---

## Pass 21 — Review UX/Kejelasan Informasi (15 Jun 2026)

> Audit non-bug: informasi yang ada tapi tidak ditampilkan, label tidak konsisten, konteks yang hilang.

| # | Severity | File & Baris | Temuan | Status |
|---|----------|-------------|--------|--------|
| U1 | 🟡 MEDIUM | `DBHistoryTable.tsx:76-84` | **`futures_agent3` tidak ada case di TypeBadge** — agent1 → "🤖 A1", agent2 → "🧠 A2", tapi agent3 jatuh ke fallback generic dan tampil teks mentah `futures_agent3`. Fix: tambah case `futures_agent3` → badge "🔥 Momo" (oranye) | ✅ done |
| U2 | 🟡 MEDIUM | `DBHistoryTable.tsx:435-444` | **Kolom Margin di main row tidak ada leverage** — tampil `$44` saja. Leverage hanya terlihat setelah user expand baris (ada di detail row baris 487). User harus klik setiap baris untuk tahu eksposur. Fix: tampilkan dua baris di kolom Margin: `$44` + `9×` subscript, atau satu baris `$44·9×` | ✅ done |
| U3 | 🟡 MEDIUM | `FuturesWallet.tsx` WalletInfo | **`open_positions` ada di API WalletInfo tapi tidak ditampilkan** — backend mengembalikan `open_positions` (jumlah posisi aktif yang memakan margin terkunci), tapi UI tidak merendernya. User tidak tahu berapa posisi yang sedang aktif dari halaman wallet. Fix: tampilkan `open_positions` di samping `locked_margin` | ✅ done |
| U4 | 🟡 MEDIUM | `MonitorTab.tsx` agent_breakdown | **Breakdown agen tampil `agent1`/`agent2`/`agent3` tanpa nama lane** — user tidak tahu agent1 = Pre-Gainer, agent2 = Accumulation, agent3 = Momentum. Fix: map nama di breakdown: "Pre-Gainer", "Accumulation", "Momentum" | ✅ done (sudah benar di MonitorTab) |
| U5 | 🟠 PERLU STANDAR | Semua file futures UI | **Label agen tidak konsisten di seluruh UI** — TypeBadge: "A1/A2", OverviewTab monthly: "A1:/A2:/A3:", FuturesAnalytics filter: "Pre/Accum/Momo". Seharusnya satu standar: `Pre-Gainer · Accumulation · Momentum` di semua tempat | ✅ done |
| U6 | 🟢 MINOR | `FuturesAnalytics.tsx` filter sinyal | **Label filter sinyal pakai singkatan** — "Pre" / "Accum" / "Momo" di analytics tidak konsisten dengan nama lengkap di halaman lain. Minor tapi membingungkan jika user bolak-balik halaman | ✅ done |

---

### Masuk ke Phase 6 — UX Clarity dari Pass 21

```
Tambahkan ke Phase 6 (Frontend Corrections):

U1 — DBHistoryTable.tsx TypeBadge
  Tambah case futures_agent3 → badge "🔥 Momo" warna oranye (bg-orange-100 text-orange-700)

U2 — DBHistoryTable.tsx kolom Margin (main row)
  Tampilkan leverage di bawah dollar amount: "$44" + "9×" (text-[9px] text-neutral-400)
  Data leverage ada di trade.leverage (nullable, hanya untuk futures)

U3 — FuturesWallet.tsx
  Tampilkan open_positions di WalletInfo card di samping locked_margin
  Contoh: "3 posisi aktif" atau badge kecil

U4 — MonitorTab.tsx agent_breakdown labels
  Map agent1/2/3 → "Pre-Gainer" / "Accumulation" / "Momentum"

U5 — Standarisasi label agen (semua file)
  Target akhir: satu standar di semua tempat:
    futures_agent1 → "Pre-Gainer"
    futures_agent2 → "Accumulation"
    futures_agent3 → "Momentum"
  Files: TypeBadge, OverviewTab monthly stats, MonitorTab breakdown, FuturesAnalytics filter

U6 — FuturesAnalytics.tsx filter sinyal
  Ganti "Pre"/"Accum"/"Momo" → "Pre-Gainer"/"Accumulation"/"Momentum"
```
