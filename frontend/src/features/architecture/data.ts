// Static data for the architecture documentation page

export const BUGS_FIXED = [
  { id: "B1", sev: "🔴", title: "Spot Monitor menutup posisi sebagai 'tp' walau net P&L negatif", fix: "Hanya tandai 'tp' jika pnl_net > 0 setelah fee 0.2%", file: "agents/opportunity/monitor.py" },
  { id: "B2", sev: "🔴", title: "Posisi ditutup dalam 53 detik — tidak ada minimum hold time", fix: "Tambah MIN_HOLD_MINUTES=30: risk-adjusted exits tidak bisa fire dalam 30 menit pertama", file: "agents/opportunity/monitor.py" },
  { id: "B3", sev: "🔴", title: "trend_reversal menembak saat EMA sudah bearish SEBELUM entry", fix: "Simpan entry_ema_bullish di meta saat buka posisi, monitor cek apakah terjadi reversal nyata", file: "agents/opportunity/monitor.py + scheduler.py" },
  { id: "B4", sev: "🔴", title: "Futures Auto-trader buka posisi di regime VOLATILE → langsung SL", fix: "Regime volatile blokir lane Pre-Move (momentum tetap jalan), threshold adaptif 70-77, dasar 72", file: "agents/futures/auto_trader.py" },
  { id: "B5", sev: "🔴", title: "WBTCUSDT re-entry 3x berturut-turut tanpa jeda setelah SL", fix: "Cooldown 2 jam setelah SL hit — tidak bisa buka posisi yang sama dalam 2 jam", file: "agents/opportunity/monitor.py + scheduler.py" },
  { id: "B6", sev: "🟡", title: "Win-rate inflasi: 'tp' dengan pnl=-0.16% dihitung sebagai menang", fix: "Fungsi _is_real_win() diterapkan di history, learning stats, futures analytics", file: "backend/app/api/v1/history.py + futures_learning.py" },
  { id: "B7", sev: "🟡", title: "flow_reversal menutup terlalu agresif (taker < 0.40)", fix: "Naikkan threshold ke 0.38, minimum profit 1.0% net sebelum bisa menutup via flow_reversal", file: "agents/opportunity/monitor.py" },
  { id: "B8", sev: "🟡", title: "Equity chart di History hanya pakai 'status==tp' bukan net pnl", fix: "Semua kalkulasi win/loss pakai _is_real_win() yang cek pnl_net > 0", file: "backend/app/api/v1/futures_learning.py" },
];

export const NEW_FEATURES = [
  { icon: "⚡", title: "Auto-Trade Futures (1 Scanner, score ≥ 72 adaptif)", desc: "Satu pipeline gabungan semua lane (Pre-Move + Momentum + New-Listing) buka paper trade jika score ≥ threshold adaptif (70-77 per win-rate). Dedup GLOBAL per-symbol (cross-margin = 1 posisi/koin), max 6 posisi global (1 wallet). Volatile blokir Pre-Move saja.", file: "agents/futures/auto_trader.py" },
  { icon: "🔍", title: "Futures Monitor — Risk Dashboard", desc: "GET /futures/monitor/risk: per posisi tampilkan liq_price, margin, liq_dist_pct, SAFE/WARNING/DANGER status. Portfolio: Sharpe proxy, max drawdown, total margin.", file: "backend/app/api/v1/futures_scanner.py" },
  { icon: "🚨", title: "Liquidation Guard", desc: "Monitor cek jarak ke liquidation price setiap 2 menit. Jika price dalam 8% dari liq price → tutup posisi di SL sekarang (sebelum diliquidasi exchange).", file: "agents/futures/monitor.py" },
  { icon: "📈", title: "TP Extension ke TP3", desc: "Jika TP1 sudah dicapai dan score masih ≥ 70, monitor otomatis extend TP2 ke TP3 untuk memaksimalkan profit. Satu kali per posisi.", file: "agents/futures/monitor.py" },
  { icon: "📅", title: "Monthly Win Rate — per Strategi", desc: "History Futures tab: bandingkan win rate per strategi (Pre-Gainer / Accumulation / Momentum) per bulan dengan selector bulan dan progress bar.", file: "backend/app/api/v1/futures_learning.py + FuturesTab.tsx" },
  { icon: "🔵🟣", title: "Open Positions per Strategi", desc: "History Monitor tab: posisi terbuka dikelompokkan per strategi (Pre-Gainer / Accumulation / Momentum). Margin/liq/upnl dari nilai backend nyata (balance-aware), bukan hitung ulang client.", file: "frontend/src/features/history/components/FuturesTab.tsx" },
  { icon: "💼", title: "Spot Portfolio Real Holdings", desc: "Dashboard section: real Binance spot holdings dengan harga masuk rata-rata (FIFO dari trade history), unrealized PnL per koin, alokasi portfolio. Debug endpoint: /market/spot-debug.", file: "backend/app/api/v1/market.py" },
  { icon: "📊", title: "Scanner — Open Positions Monitor Banner", desc: "Futures Scanner page: banner aktif menampilkan semua posisi terbuka dengan unrealized PnL, risk status (SAFE/WARNING/DANGER), dan liq distance. Auto-refresh 30s.", file: "frontend/src/features/scanner/page.tsx" },
];

export const AGENTS = {
  "Pre-Gainer": {
    icon: "🎯", file: "agents/futures/agent1.py",
    color: "from-blue-500/10 to-indigo-500/10 border-blue-300",
    status: "✅ Lane dari 1 Scanner", interval: "Setiap 2 menit", group: "⚡ Futures",
    desc: "Lane Pre-Move dari Scanner tunggal — cari koin SEBELUM bergerak via BB Squeeze, akumulasi volume, Funding/OI, S/R. SL floor sadar-leverage (min 1.5%), leverage direkonsiliasi dengan jarak SL.",
    pipeline: [
      "Ambil top-100 pair USDT Futures dari Binance (by volume)",
      "Fetch funding rate: terlalu tinggi (+) → SHORT bias, terlalu rendah (−) → LONG bias",
      "Analisis Open Interest: OI naik + harga naik → trend kuat; OI naik + harga turun → short squeeze risk",
      "Deteksi liquidation zones: area dengan banyak posisi terancam = magnet harga",
      "Analisis S/R Zones (swing pivot clustering, 20 candle 4H)",
      "Hitung Entry/SL/TP dengan R:R ≥ 1:3 berbasis ATR + S/R",
      "Filter: score ≥ threshold, R:R valid → log ke paper_trades (agent='futures_agent1')",
    ],
    code: `# agents/futures/scheduler.py → agent1.py
async def run_agent1_scan(symbols: list[str]) -> list[Signal]:
    for sym in symbols:
        funding = await fetch_funding_rate(sym)
        oi      = await fetch_open_interest(sym)
        liq     = await fetch_liquidation_zones(sym)
        sr      = await compute_sr_zones(sym)          # 4H swing pivots
        signal  = await score_and_decide(funding, oi, liq, sr)
        if signal.rr >= 1.3:
            results.append(signal)
    return results`,
  },
  "Accumulation": {
    icon: "📦", file: "agents/futures/agent2.py",
    color: "from-purple-500/10 to-violet-500/10 border-purple-300",
    status: "✅ Lane dari 1 Scanner", interval: "Setiap 2 menit", group: "⚡ Futures",
    desc: "Lane akumulasi (Wyckoff/T0-T4) dari Scanner tunggal — fase akumulasi sebelum markup. Skornya masuk pool ranking global yang sama; dedup per-symbol memilih lane skor tertinggi per koin.",
    pipeline: [
      "T0 — Wyckoff: deteksi phase Accumulation/Distribution/Markup/Markdown",
      "T1 — Trend: EMA alignment (9/21/50), ADX strength, multi-TF confluence",
      "T2 — S/R: swing pivot clustering, Fibonacci retracement zones",
      "T3 — Pattern: BB Squeeze, Volume Accumulation, RSI divergence, candle patterns",
      "T4 — Trigger: final confirmation (EMA cross, pressure shift, volume spike)",
      "Hitung Entry/SL/TP dengan R:R ≥ 1:3 berbasis S/R + ATR",
      "Log ke paper_trades (agent='futures_agent2') jika semua filter lolos",
    ],
    code: `# agents/futures/agent2.py — T0-T4 pipeline
async def run_agent2_scan(symbols: list[str]) -> list[Signal]:
    for sym in symbols:
        klines = await fetch_multi_tf(sym)   # 15m, 1H, 4H
        phase  = wyckoff_phase(klines)       # T0
        trend  = analyze_trend(klines)       # T1
        zones  = compute_sr(klines)          # T2
        patt   = detect_patterns(klines)     # T3
        trig   = check_trigger(klines)       # T4
        score  = aggregate_score(...)
        if score >= MIN_SCORE and rr >= 1.3:
            results.append(build_signal(...))`,
  },
  "Momentum": {
    icon: "🔥", file: "agents/futures/agent3.py",
    color: "from-orange-500/10 to-amber-500/10 border-orange-300",
    status: "✅ Lane dari 1 Scanner", interval: "Setiap 2 menit", group: "⚡ Futures",
    desc: "Lane Momentum dari Scanner tunggal — masuk SAAT gerakan sudah terbentuk (change 5-20%, volume + OI searah, RSI 55-72). Kebalikan Pre-Move. Leverage cap 10x, tetap pakai SL floor sadar-leverage.",
    pipeline: [
      "Reward koin yang sudah bergerak 5-20% dalam 24h (sweet spot 8-12%)",
      "Konfirmasi volume surge + OI naik searah harga (konviksi, bukan squeeze kosong)",
      "RSI 55-72 (LONG) / 28-45 (SHORT) — momentum ada, belum exhausted",
      "Breakout di atas high / break di bawah low 30-candle",
      "SL floor sadar-leverage + leverage cap 10x (already-moved = vol lebih tinggi)",
      "Skor masuk pool ranking global yang sama dengan lane lain",
    ],
    code: `# agents/futures/agent3.py — Momentum Capture
async def scan_symbol(sym, tf_map, change_24h):
    regime = detect_coin_regime(tf_map["1h"])   # per-coin, bukan BTC
    score  = score_momentum(change_24h, vol, oi, rsi)
    levels = _calc_levels(...)                   # SL floor sadar-leverage
    lev    = calc_leverage_momentum(atr, score, levels["risk_pct"])  # cap 10x
    return [{ ..., "setup_type": "momentum", "regime": regime }]`,
  },
  "Futures Monitor": {
    icon: "👁", file: "agents/futures/monitor.py",
    color: "from-indigo-500/10 to-blue-500/10 border-indigo-300",
    status: "✅ Aktif 24/7", interval: "Setiap 120 detik", group: "⚡ Futures",
    desc: "Monitor risk-adjusted semua posisi Futures (1 monitor). Wick detection 1m (TP/SL antar-poll tak terlewat), SL+ lifecycle, Liquidation Guard (tutup di harga dekat-liq), TP1 partial kecilkan size, expired masuk balance.",
    pipeline: [
      "Query semua futures paper_trades dengan status='open'",
      "Batch fetch live prices dari Binance Futures",
      "Layer 1 — Hard exits: SL hit → sl | TP2/TP3 hit → tp",
      "Layer 2 — Liquidation Guard: jika price dalam 8% liq_price → tutup di SL (protect capital)",
      "Layer 3 — Trail SL: 50% menuju TP1 → SL ke breakeven | TP1 hit → SL ke entry+50%",
      "Layer 4 — TP Extension: TP1 dicapai + score ≥ 70 → extend TP2 ke TP3",
      "Log liq_guards + tp_extended ke health endpoint",
    ],
    code: `# agents/futures/monitor.py — v2 (dengan Liq Guard + TP Extension)
async def check_futures_positions():
    for trade in open_trades:
        # Layer 1: SL/TP hit
        if sl_or_tp_hit(price, sl, tp2): close_position()
        # Layer 2: Liquidation Guard (NEW)
        liq = calc_liq_price(entry, leverage, direction)
        if dist_to_liq(price, liq) < 8%: close_at_sl()
        # Layer 3: Trail SL
        if halfway_to_tp1: move_sl_to_breakeven()
        # Layer 4: TP Extension (NEW)
        if tp1_hit and score >= 70: extend_tp_to_tp3()`,
  },
  "Weight Updater": {
    icon: "🧠", file: "agents/futures/weight_updater.py",
    color: "from-green-500/10 to-teal-500/10 border-green-300",
    status: "✅ Aktif 24/7", interval: "Setiap 6 jam", group: "⚡ Futures",
    desc: "Adaptive learning — auto-tune bobot sinyal berdasarkan win rate historis. Sinyal dengan win rate tinggi mendapat bobot lebih besar di scan berikutnya.",
    pipeline: [
      "Ambil semua paper_trades (type='futures') yang sudah closed (tp/sl)",
      "Hitung win rate per sinyal: BBSqueeze, EMA, Funding, OI, dsb",
      "Normalisasi bobot: sinyal dengan WR > 60% → weight naik; WR < 40% → turun",
      "Simpan ke signal_weights table di PostgreSQL",
      "Agent1 & Agent2 baca weight terbaru di scan berikutnya",
      "Log weight update ke structlog",
    ],
    code: `# agents/futures/weight_updater.py
while True:
    win_rates = await compute_signal_win_rates()
    weights   = normalize_weights(win_rates)
    await save_weights(weights)           # → signal_weights table
    logger.info("weights_updated", n=len(weights))
    await asyncio.sleep(6 * 3600)        # tiap 6 jam`,
  },
  "Spot Opp Scanner": {
    icon: "🚀", file: "agents/opportunity/scheduler.py",
    color: "from-teal-500/10 to-green-500/10 border-teal-300",
    status: "✅ Aktif 24/7", interval: "Setiap 15 menit", group: "🎯 Spot",
    desc: "Scan 100 pair USDT Spot berdasarkan volume. Cari koin dengan potensi naik (BB Squeeze, Akumulasi, Breakout). Broadcast hasil via WebSocket ke frontend.",
    pipeline: [
      "Ambil top-100 pair USDT Spot dari Binance (bukan Futures)",
      "Analisis 3 TF serentak: 15m + 1H + 4H",
      "9 sinyal: BB Squeeze, Vol Akumulasi, RSI Zone, Buy Pressure, EMA Align, Near Breakout, Momentum 24H, Short-term Mom, Taker Ratio",
      "Hitung Entry (harga pasar) · SL (swing low −0.5%) · TP1/TP2/TP3 (R:R 1:1.5/3/5)",
      "Filter: score ≥ 30 · SL max 8% · R:R ke TP2 ≥ 2.0",
      "Top-30 kandidat disimpan ke opportunity store (in-memory)",
      "WebSocket broadcast ke semua klien /ws/opportunity",
    ],
    code: `# agents/opportunity/scheduler.py
while True:
    result = await run_opportunity_scan()   # scan 100 spot pairs
    opp_store.set_result(result)            # update in-memory cache
    await broadcast_ws(result)             # push ke frontend via WS
    await asyncio.sleep(15 * 60)`,
  },
  "Spot Monitor": {
    icon: "📍", file: "agents/opportunity/monitor.py",
    color: "from-amber-500/10 to-orange-500/10 border-amber-300",
    status: "✅ Aktif 24/7", interval: "Setiap 60 detik", group: "🎯 Spot",
    desc: "Risk-adjusted monitor untuk posisi Opportunity SPOT. v2: Min hold 30 menit, cooldown 2 jam setelah SL, trend_reversal hanya jika EMA memang berbalik (bukan sudah bearish sebelum entry).",
    pipeline: [
      "Query semua opportunity_spot trades dengan status='open'",
      "Fetch live prices dari Binance Spot (batch concurrent)",
      "Layer 1 Hard exits: SL hit → sl | TP2/TP3 hit → tp",
      "TP1 hit → flag tp1_hit, SL pindah ke breakeven (entry × 1.002)",
      "Layer 2 Risk-adjusted (hanya setelah 30 menit buka): EMA reversal, RSI overbought+stall, flow reversal",
      "BUG FIX: status 'tp' hanya jika net pnl > 0 (setelah fee 0.2%)",
      "SL hit → set cooldown 2 jam untuk symbol ini (cegah re-entry langsung)",
    ],
    code: `# agents/opportunity/monitor.py — v2 (bug fixes)
# BUG FIX 1: min hold 30 menit sebelum risk-adjusted exits
# BUG FIX 2: 'tp' hanya jika net P&L > 0 setelah fee
# BUG FIX 3: trend_reversal hanya jika EMA berbalik setelah entry
# BUG FIX 4: cooldown 2 jam setelah SL

if hold_minutes < MIN_HOLD_MINUTES: return None  # jangan tutup terlalu cepat
pnl_net = pnl_gross - EXECUTION_COST_PCT         # fee + spread + slippage
new_status = "tp" if pnl_net > 0 else "sl"       # bukan cuma price > entry
# cooldown re-entry 2 jam: query DB di scheduler (tahan restart)`,
  },
};

export const TA_SIGNALS = {
  "BB Squeeze": {
    icon: "🔵", score: "+25 × w_squeeze",
    formula: `BB Width = (StdDev(close, n) × 4) / BB_mid
Squeeze    jika Width < threshold  (3–8% tergantung style)
Tightening jika Width < threshold × 1.5`,
    why: "Volatilitas menyempit (BB menguncup) = energi terkompresi sebelum breakout besar. Semakin sempit BB, semakin besar potensi pergerakan.",
  },
  "Vol Akumulasi": {
    icon: "📦", score: "+22 × w_accum",
    formula: `vol_slope  = (vol[-1] − vol[-5]) / vol[-5]
price_slope = (close[-1] − close[-5]) / close[-5]
Akumulasi  jika vol_slope > min_vol AND |price_slope| < 4%
Hidden Str jika vol_slope tinggi AND price_slope < 0`,
    why: "Volume naik saat harga flat = smart money masuk diam-diam (akumulasi). Volume naik saat harga turun = hidden strength.",
  },
  "Near Breakout": {
    icon: "🎯", score: "+20 × w_breakout",
    formula: `dist_high = (recent_high − price) / price
dist_low  = (price − recent_low)  / price
Near breakout  jika 0 < dist_high < 1.5–2.5%
Near reversal  jika 0 < dist_low  < 1.5–2.5%`,
    why: "Harga mendekati high/low terakhir = titik keputusan kritis. Bisa breakout (LONG) atau bounce dari support.",
  },
  "RSI": {
    icon: "📈", score: "+15 × w_rsi (oversold)",
    formula: `RSI = 100 − 100 / (1 + AvgGain / AvgLoss)
Period: 9 (scalping) · 14 (day,swing) · 21 (position)

< 30  = oversold → reversal LONG  (+15 pts)
30–50 = energy building            (+12 pts)
50–65 = momentum building           (+8 pts)
> 75  = overbought → SHORT signal  (−10 + SHORT)`,
    why: "RSI < 30 = jenuh jual, potensi reversal kuat. RSI > 75 dengan volume yang sudah pump = entry LONG terlambat.",
  },
  "EMA": {
    icon: "⚡", score: "+15 × w_ema (compress)",
    formula: `EMA(n) = price × k + EMA_prev × (1−k),  k = 2/(n+1)
Spread   = |EMA9 − EMA21| / price
Compress jika spread < 0.3% (scalp) / 0.5% (day)
Bullish  jika EMA9 > EMA21 > EMA50`,
    why: "EMA 9/21 yang hampir menyatu = kondisi pra-breakout. Alignment EMA9>21>50 konfirmasi trend bullish.",
  },
  "Pressure Shift": {
    icon: "🟢", score: "+15 × w_pressure",
    formula: `bull_ratio = Σ vol[i] (candle hijau) / Σ vol_total (5 candle)
shift = bull_ratio_now − bull_ratio_prev
Buy pressure  jika shift > +15%
Sell pressure jika shift < −15%`,
    why: "Pergeseran dominasi buyer/seller dalam 5 candle = konfirmasi momentum nyata.",
  },
  "Candle Shrink": {
    icon: "🕯", score: "+10 × w_candle",
    formula: `body[i]    = |close[i] − open[i]|
body_slope = (body[-1] − body[0]) / body[0]  (7 candle)
Kompresi   jika body_slope < −50%`,
    why: "Badan candle semakin kecil = kelelahan trend sebelumnya. Setup ideal untuk breakout berikutnya.",
  },
  "Taker Ratio": {
    icon: "🔄", score: "+12 (Spot Opp only)",
    formula: `taker_ratio = taker_buy_vol / total_vol  (avg 15 candle)
Binance kline col[9] = taker_buy_base_volume
Binance kline col[5] = total_volume

> 0.60 = institusi akumulasi diam-diam  (+12 pts)
0.55–0.60 = lebih banyak pembeli        (+6 pts)
< 0.45 = seller dominan                 (bearish)`,
    why: "Taker buy = market order dari pembeli agresif. Jika taker ratio tinggi tanpa lonjakan harga = smart money akumulasi sebelum pump.",
  },
};

export const STYLES = {
  "Scalping": {
    icon: "⚡", tf: "15m", dur: "Menit–Jam",
    color: "from-yellow-500/10 to-orange-500/10 border-yellow-300",
    params: { "RSI Period": "9", "BB Period": "14", "BB Squeeze": "< 3% width", "Vol Slope Min": "> 20%", "Min SL": "≥ 0.8%", "SL Fallback": "ATR × 1.0", "TP Fallback": "ATR × 3.5", "Min Score": "25 pts" },
    weights: "RSI×2.0 · Pressure×1.8 · Breakout×1.5 · Candle×1.5",
  },
  "Day Trade": {
    icon: "📅", tf: "1H", dur: "Harian",
    color: "from-blue-500/10 to-indigo-500/10 border-blue-300",
    params: { "RSI Period": "14", "BB Period": "20", "BB Squeeze": "< 4.5% width", "Vol Slope Min": "> 25%", "Min SL": "≥ 1.2%", "SL Fallback": "ATR × 1.2", "TP Fallback": "ATR × 4.0", "Min Score": "28 pts" },
    weights: "RSI×1.5 · Pressure×1.5 · Breakout×1.3 · EMA×1.3",
  },
  "Swing": {
    icon: "🌊", tf: "4H", dur: "Hari–Minggu",
    color: "from-teal-500/10 to-green-500/10 border-teal-300",
    params: { "RSI Period": "14", "BB Period": "20", "BB Squeeze": "< 6% width", "Vol Slope Min": "> 30%", "Min SL": "≥ 2.0%", "SL Fallback": "ATR × 1.5", "TP Fallback": "ATR × 5.0", "Min Score": "30 pts" },
    weights: "Accumulation×2.0 · Squeeze×1.8 · Breakout×1.5",
  },
  "Position": {
    icon: "🏔", tf: "1D", dur: "Minggu–Bulan",
    color: "from-purple-500/10 to-violet-500/10 border-purple-300",
    params: { "RSI Period": "21", "BB Period": "30", "BB Squeeze": "< 8% width", "Vol Slope Min": "> 40%", "Min SL": "≥ 3.0%", "SL Fallback": "ATR × 2.0", "TP Fallback": "ATR × 7.0", "Min Score": "35 pts" },
    weights: "Accumulation×2.5 · Squeeze×2.0 · EMA×1.5",
  },
};
