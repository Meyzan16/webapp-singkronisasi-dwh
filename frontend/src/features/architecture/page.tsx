"use client";
import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";

function Code({ children }: { children: string }) {
  return (
    <pre className="bg-neutral-900 text-green-400 text-[11px] font-mono p-3 rounded-lg overflow-x-auto leading-relaxed whitespace-pre-wrap">
      {children}
    </pre>
  );
}

function Badge({ label, color }: { label: string; color: string }) {
  return <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${color}`}>{label}</span>;
}

function SectionTitle({ icon, title, sub }: { icon: string; title: string; sub?: string }) {
  return (
    <div className="flex items-center gap-3 mb-4">
      <span className="text-2xl">{icon}</span>
      <div>
        <h2 className="text-lg font-bold text-neutral-900">{title}</h2>
        {sub && <p className="text-xs text-neutral-500">{sub}</p>}
      </div>
    </div>
  );
}

function Tabs({ tabs, active, onChange }: { tabs: string[]; active: string; onChange: (t: string) => void }) {
  return (
    <div className="flex bg-neutral-100 rounded-lg p-0.5 gap-0.5 mb-4 flex-wrap">
      {tabs.map(t => (
        <button key={t} onClick={() => onChange(t)}
          className={`flex-1 py-1.5 rounded-md text-xs font-semibold transition-all min-w-[80px] ${
            active === t ? "bg-white shadow text-neutral-900" : "text-neutral-500 hover:text-neutral-700"
          }`}>
          {t}
        </button>
      ))}
    </div>
  );
}

export default function ArchitecturePage() {
  const [taTab, setTaTab]       = useState("BB Squeeze");
  const [styleTab, setStyleTab] = useState("Scalping");
  const [agentTab, setAgentTab] = useState("Futures Agent 1");

  const AGENTS = {
    "Futures Agent 1": {
      icon: "🤖", file: "agents/futures/agent1.py",
      color: "from-blue-500/10 to-indigo-500/10 border-blue-300",
      status: "✅ Aktif 24/7", interval: "Setiap 15 menit",
      group: "⚡ Futures",
      desc: "AI-based futures scanner — cek kondisi pasar via Funding Rate, Open Interest, Liquidations, dan Support/Resistance. Deteksi setup LONG/SHORT Futures dengan konfirmasi multi-faktor.",
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
    "Futures Agent 2": {
      icon: "🔭", file: "agents/futures/agent2.py",
      color: "from-purple-500/10 to-violet-500/10 border-purple-300",
      status: "✅ Aktif 24/7", interval: "Setiap 15 menit",
      group: "⚡ Futures",
      desc: "TA-based futures scanner — pipeline T0–T4 penuh: Wyckoff phase detection, trend analysis, S/R zones, pattern recognition, trigger confirmation. Sama dengan TA Engine backend.",
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
    "Futures Monitor": {
      icon: "👁", file: "agents/futures/monitor.py",
      color: "from-indigo-500/10 to-blue-500/10 border-indigo-300",
      status: "✅ Aktif 24/7", interval: "Setiap 60 detik",
      group: "⚡ Futures",
      desc: "Monitor semua posisi Futures yang open. Cek harga real-time dari Binance Futures, auto-close saat TP atau SL tercapai, update unrealized PnL di database.",
      pipeline: [
        "Query semua paper_trades (type='futures') dengan status='open'",
        "Batch fetch harga terkini dari Binance Futures markPrice",
        "Per posisi LONG: harga ≤ SL → sl; harga ≥ TP2 atau TP3 → tp",
        "Per posisi SHORT: harga ≥ SL → sl; harga ≤ TP2 atau TP3 → tp",
        "Update unrealized_pnl di database untuk semua posisi terbuka",
        "Commit perubahan, increment cycle_count",
      ],
      code: `# agents/futures/monitor.py
while True:
    positions = await get_open_futures_positions()
    prices    = await batch_fetch_mark_prices(positions)
    for pos in positions:
        check_sl_tp(pos, prices[pos.symbol])
    await asyncio.sleep(60)`,
    },
    "Weight Updater": {
      icon: "🧠", file: "agents/futures/weight_updater.py",
      color: "from-green-500/10 to-teal-500/10 border-green-300",
      status: "✅ Aktif 24/7", interval: "Setiap 6 jam",
      group: "⚡ Futures",
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
      status: "✅ Aktif 24/7", interval: "Setiap 15 menit",
      group: "🎯 Spot",
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
      status: "✅ Aktif 24/7", interval: "Setiap 60 detik",
      group: "🎯 Spot",
      desc: "Monitor semua posisi Opportunity SPOT yang open. Cek harga real-time, auto-close saat TP/SL tercapai, set flag TP1 Hit tanpa menutup posisi.",
      pipeline: [
        "Query semua opportunity_spot trades dengan status='open'",
        "Fetch harga terkini dari Binance Spot (concurrent batch)",
        "Cek per posisi: harga ≤ SL → tutup status='sl'",
        "Cek: harga ≥ TP3 atau TP2 → tutup status='tp'",
        "Cek: harga ≥ TP1 (pertama kali) → set tp1_hit=True, posisi tetap open",
        "Commit ke DB, broadcast update via WebSocket",
      ],
      code: `# agents/opportunity/monitor.py
while True:
    n = await check_positions()   # cek semua open spot positions
    # TP1 hit → flag, posisi tetap open (ride ke TP2)
    # TP2/TP3 hit → close status='tp'
    # SL hit     → close status='sl'
    await asyncio.sleep(60)`,
    },
  };

  const TA_SIGNALS = {
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

  const STYLES = {
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

  const activeSig   = TA_SIGNALS[taTab as keyof typeof TA_SIGNALS];
  const activeStyle = STYLES[styleTab as keyof typeof STYLES];
  const activeAgent = AGENTS[agentTab as keyof typeof AGENTS];

  return (
    <div className="space-y-6 max-w-5xl mx-auto">

      {/* ── Hero ──────────────────────────────────────────────────────────── */}
      <Card className="bg-gradient-to-r from-neutral-900 to-neutral-800 text-white border-0">
        <CardContent className="pt-6 pb-5">
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <h1 className="text-3xl font-bold mb-1">📐 Arsitektur Sistem</h1>
              <p className="text-sm text-neutral-400 max-w-2xl leading-relaxed">
                Crypto trading agent dengan <strong className="text-white">2 sistem independen</strong>:{" "}
                <strong className="text-blue-400">Futures Scanner</strong> (AI + T0-T4, auto-log 24/7) dan{" "}
                <strong className="text-teal-400">Opportunity SPOT</strong> (user-driven, 4 layer).
                Total <strong className="text-white">6 autonomous agents</strong> berjalan di background.
              </p>
            </div>
            <div className="text-xs text-neutral-400 font-mono space-y-1 shrink-0">
              <div>Frontend  · Next.js 16 · TypeScript</div>
              <div>Backend   · FastAPI · Python 3.12</div>
              <div>Agents    · 6 aktif · asyncio · structlog</div>
              <div>Database  · PostgreSQL 16 · Redis 7</div>
              <div>Data      · Binance Spot + Futures REST</div>
            </div>
          </div>

          {/* Agent pills */}
          <div className="flex gap-2 mt-5 flex-wrap">
            {[
              { icon: "🤖", label: "Agent 1 — AI",      sub: "Futures · Funding/OI/Liq/S&R", color: "bg-blue-500/20 border-blue-400/30"   },
              { icon: "🔭", label: "Agent 2 — T0-T4",   sub: "Futures · Wyckoff/Trend/TA",    color: "bg-purple-500/20 border-purple-400/30" },
              { icon: "👁", label: "Futures Monitor",    sub: "Futures · TP/SL · 60s",         color: "bg-indigo-500/20 border-indigo-400/30" },
              { icon: "🧠", label: "Weight Updater",     sub: "Learning · 6jam",               color: "bg-green-500/20 border-green-400/30"  },
              { icon: "🚀", label: "Spot Opp Scanner",   sub: "Spot · 15m",                    color: "bg-teal-500/20 border-teal-400/30"    },
              { icon: "📍", label: "Spot Monitor",       sub: "Spot · TP/SL · 60s",            color: "bg-amber-500/20 border-amber-400/30"  },
            ].map(a => (
              <div key={a.label} className={`flex items-center gap-2 px-3 py-2 rounded-xl border ${a.color}`}>
                <span className="text-base">{a.icon}</span>
                <div>
                  <p className="text-xs font-bold text-white">{a.label}</p>
                  <p className="text-[9px] text-neutral-400">{a.sub}</p>
                </div>
                <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse ml-1" />
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* ── Agents Detail ─────────────────────────────────────────────────── */}
      <Card>
        <CardContent className="pt-5">
          <SectionTitle icon="🤖" title="6 Autonomous Agents" sub="Berjalan 24/7 di background — embedded dalam FastAPI lifespan" />

          {/* Group labels */}
          <div className="flex gap-2 mb-2 flex-wrap">
            <span className="text-[10px] font-black text-blue-500 uppercase tracking-widest">⚡ Futures:</span>
            {["Futures Agent 1", "Futures Agent 2", "Futures Monitor", "Weight Updater"].map(t => (
              <button key={t} onClick={() => setAgentTab(t)}
                className={`text-[10px] px-2 py-0.5 rounded-full font-semibold transition-all ${
                  agentTab === t ? "bg-blue-600 text-white" : "bg-blue-50 text-blue-600 hover:bg-blue-100"
                }`}>{t}</button>
            ))}
            <span className="text-[10px] font-black text-teal-600 uppercase tracking-widest ml-2">🎯 Spot:</span>
            {["Spot Opp Scanner", "Spot Monitor"].map(t => (
              <button key={t} onClick={() => setAgentTab(t)}
                className={`text-[10px] px-2 py-0.5 rounded-full font-semibold transition-all ${
                  agentTab === t ? "bg-teal-600 text-white" : "bg-teal-50 text-teal-600 hover:bg-teal-100"
                }`}>{t}</button>
            ))}
          </div>

          {activeAgent && (
            <div className={`rounded-xl border bg-gradient-to-b p-4 mt-3 ${activeAgent.color}`}>
              <div className="flex items-start justify-between gap-4 mb-4 flex-wrap">
                <div className="flex items-center gap-3">
                  <span className="text-3xl">{activeAgent.icon}</span>
                  <div>
                    <p className="font-bold text-lg">{agentTab}</p>
                    <p className="text-xs text-neutral-500 font-mono">{activeAgent.file}</p>
                  </div>
                </div>
                <div className="flex gap-2 flex-wrap">
                  <Badge label={activeAgent.status}   color="bg-green-100 text-green-700" />
                  <Badge label={activeAgent.interval} color="bg-neutral-100 text-neutral-600" />
                  <Badge label={activeAgent.group}    color="bg-neutral-900 text-neutral-200" />
                </div>
              </div>

              <p className="text-sm text-neutral-700 mb-4 leading-relaxed">{activeAgent.desc}</p>

              <div className="grid md:grid-cols-2 gap-4">
                <div>
                  <p className="text-xs font-bold text-neutral-600 uppercase tracking-wider mb-2">Pipeline per Siklus</p>
                  <div className="space-y-1.5">
                    {activeAgent.pipeline.map((step, i) => (
                      <div key={i} className="flex items-start gap-2 text-xs">
                        <span className="w-5 h-5 rounded-full bg-neutral-700 text-white text-[10px] font-bold flex items-center justify-center shrink-0 mt-0.5">
                          {i + 1}
                        </span>
                        <span className="text-neutral-600">{step}</span>
                      </div>
                    ))}
                  </div>
                </div>
                <div>
                  <p className="text-xs font-bold text-neutral-600 uppercase tracking-wider mb-2">Code Snippet</p>
                  <Code>{activeAgent.code}</Code>
                </div>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Alur Data ─────────────────────────────────────────────────────── */}
      <Card>
        <CardContent className="pt-5">
          <SectionTitle icon="🔄" title="Alur Data — 2 Sistem Independen" sub="Futures (auto-log oleh agents) vs Opportunity SPOT (user-driven)" />

          <div className="grid md:grid-cols-2 gap-4">
            {/* Futures System */}
            <div>
              <div className="flex items-center gap-2 mb-2">
                <span className="w-2 h-2 rounded-full bg-blue-500" />
                <p className="font-bold text-sm text-blue-700">Sistem 1 — Futures Scanner (2 Agents)</p>
              </div>
              <Code>{`Binance Futures API (100 pair USDT)
         │
         ▼  ⏱ setiap 15 menit
  ┌──────┴──────┐
  │  Agent 1   │  Funding · OI · Liquidation · S/R
  │  (AI)      │  → score + LONG/SHORT signal
  └──────┬──────┘
         │
  ┌──────┴──────┐
  │  Agent 2   │  T0-T4 Pipeline: Wyckoff → Trend
  │  (T0-T4)   │  → S/R → Pattern → Trigger
  └──────┬──────┘
         │
         ▼
  paper_trades (PostgreSQL)
  agent='futures_agent1' / 'futures_agent2'
         │
         ▼  ⏱ setiap 60 detik
  Futures Monitor → auto TP/SL
         │
         ▼
  Weight Updater (tiap 6 jam)
  → signal_weights (adaptive learning)
         │
         ▼
  History — Futures tab · Win rate · P&L`}
              </Code>
              <p className="text-xs text-neutral-500 mt-2">📌 Fully automatic — tidak butuh interaksi user</p>
            </div>

            {/* Spot Opportunity System */}
            <div>
              <div className="flex items-center gap-2 mb-2">
                <span className="w-2 h-2 rounded-full bg-teal-500" />
                <p className="font-bold text-sm text-teal-700">Sistem 2 — Opportunity SPOT (4 Layer)</p>
              </div>
              <Code>{`Binance Spot API (100 pair USDT)
         │
         ▼  ⏱ setiap 15 menit
Layer 1: Spot Opp Scanner
         │  9 sinyal · top-30 kandidat
         │  → WS broadcast ke frontend
         ▼
Layer 2: Coin Analyzer (on-click user)
         │  ATR · depth ratio · resistance
         │  → Entry/SL/TP1/TP2/TP3
         ▼
Layer 3: User → "Buka Posisi SPOT"
         │  validasi entry · 1 pos/koin
         │  → simpan paper_trades (status=open)
         ▼
Layer 3b: Spot Monitor (60s)
         │  → TP hit → status='tp'
         │  → SL hit → status='sl'
         │  → TP1 hit → tp1_hit=True (tetap open)
         ▼
Layer 4: History — Spot Opp tab
         win rate · avg P&L · analytics`}
              </Code>
              <p className="text-xs text-neutral-500 mt-2">📌 User memilih koin & buka posisi sendiri</p>
            </div>
          </div>

          {/* 3 kolom summary */}
          <div className="mt-4 grid md:grid-cols-3 gap-3 text-xs">
            {[
              { icon: "🤖", title: "6 Agents (background)", color: "bg-purple-50 border-purple-200",
                items: [
                  "Futures Agent 1 — AI (Funding/OI/Liq/S&R)",
                  "Futures Agent 2 — T0-T4 (Wyckoff→Trigger)",
                  "Futures Monitor — auto TP/SL setiap 60s",
                  "Weight Updater — adaptive learning tiap 6jam",
                  "Spot Opp Scanner — 9 sinyal, top-30, WS",
                  "Spot Monitor — auto TP/SL, flag TP1",
                ]},
              { icon: "⚙️", title: "Backend (API layer)", color: "bg-teal-50 border-teal-200",
                items: [
                  "REST: /futures/ · /opportunity/ · /history/",
                  "REST: /market/binance-status · /market/context",
                  "WebSocket: /ws/futures · /ws/opportunity",
                  "TA Engine (T0–T4) untuk deep analysis",
                  "Adaptive signal weights (signal_weights table)",
                  "/health endpoint — semua agent status",
                ]},
              { icon: "🖥", title: "Frontend (consumer)", color: "bg-blue-50 border-blue-200",
                items: [
                  "Dashboard: posisi terbuka + scanner status",
                  "Futures Scanner: WS live · Agent1+2 results",
                  "Spot Opportunity: WS live + CoinModal (Layer 2)",
                  "History: Spot tab + Futures tab + analytics",
                  "System Health: monitoring real-time semua agent",
                  "Architecture: docs teknis (halaman ini)",
                ]},
            ].map(s => (
              <div key={s.title} className={`rounded-xl border p-3 ${s.color}`}>
                <p className="font-bold text-neutral-800 mb-2 flex items-center gap-1.5"><span>{s.icon}</span>{s.title}</p>
                <ul className="space-y-1">
                  {s.items.map(i => <li key={i} className="text-neutral-600 flex items-start gap-1"><span className="text-neutral-400">·</span>{i}</li>)}
                </ul>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* ── Opportunity SPOT Lifecycle ────────────────────────────────────── */}
      <Card>
        <CardContent className="pt-5">
          <SectionTitle icon="🎯" title="Opportunity SPOT — Siklus Posisi" sub="Dari scanner → analisis → buka → monitor → history" />
          <div className="grid md:grid-cols-2 gap-6">
            <div>
              <Code>{`Layer 1: Scanner menemukan koin (score ≥ 30)
         │  BB Squeeze + Vol + RSI + Taker ratio
         │  Tersimpan di opportunity store (WS)
         ▼
Layer 2: User klik koin → Analyzer jalan (~2s)
         │  ATR-based SL · Resistance-based TP
         │  Order book depth ratio
         │  Confidence score 0–99
         ▼
Layer 3: User klik "Buka Posisi SPOT"
         │  Validasi: entry dalam 2% market price
         │  Validasi: tidak ada posisi koin ini
         │  Simpan ke paper_trades (status=open)
         ▼
Layer 3b: Monitor cek setiap 60 detik
         │
         ├── harga ≤ SL  → status='sl'
         ├── harga ≥ TP2 → status='tp'
         ├── harga ≥ TP3 → status='tp' (close=TP3)
         └── harga ≥ TP1 (pertama) → tp1_hit=True
                                      posisi tetap OPEN
         │
         ▼
Layer 4: History → Opportunity SPOT tab
         Win rate · Avg P&L · Per-type analytics
         Score vs Outcome · Export CSV`}
              </Code>
            </div>
            <div className="space-y-2">
              <p className="text-sm font-bold text-neutral-800 mb-3">Status Posisi</p>
              {[
                { s: "🔵 open",    c: "bg-blue-50 border-blue-200",       t: "Posisi Aktif",    d: "User sudah buka, monitor sedang track harga. Unrealized P&L live dari Binance." },
                { s: "✅ tp",      c: "bg-green-50 border-green-200",     t: "TP Hit",          d: "Harga mencapai TP2 atau TP3. Ditutup otomatis, dihitung sebagai Win." },
                { s: "🛑 sl",      c: "bg-red-50 border-red-200",         t: "SL Hit",          d: "Harga turun ke level SL. Ditutup otomatis, dihitung sebagai Loss." },
                { s: "🤚 manual",  c: "bg-neutral-50 border-neutral-200", t: "Tutup Manual",    d: "User menutup sendiri di harga pasar saat itu." },
                { s: "🟡 tp1_hit", c: "bg-yellow-50 border-yellow-200",   t: "TP1 Tersentuh",   d: "TP1 sudah kena tapi posisi tetap open — ride ke TP2." },
              ].map(s => (
                <div key={s.s} className={`rounded-xl border p-3 ${s.c}`}>
                  <div className="flex items-center gap-2 mb-1">
                    <code className="font-bold text-xs">{s.s}</code>
                    <span className="text-[10px] text-neutral-500">{s.t}</span>
                  </div>
                  <p className="text-xs text-neutral-600">{s.d}</p>
                </div>
              ))}
            </div>
          </div>

          <div className="mt-4 bg-neutral-900 text-white rounded-xl p-4 text-xs">
            <p className="font-bold text-teal-400 mb-2">✅ Aturan Posisi Opportunity SPOT</p>
            <div className="grid md:grid-cols-4 gap-3">
              {[
                { t: "Per-coin rule",     d: "1 posisi open per koin. Koin berbeda boleh bersamaan." },
                { t: "Entry validation",  d: "Entry tidak boleh > 2% dari harga pasar saat buka posisi." },
                { t: "R:R minimum",       d: "R:R ke TP2 ≥ 2.0. Koin yang tidak memenuhi dibuang." },
                { t: "SL max 8%",         d: "Stop loss tidak boleh lebih dari 8% dari entry." },
              ].map(r => (
                <div key={r.t}>
                  <p className="font-semibold text-neutral-300 mb-1">{r.t}</p>
                  <p className="text-neutral-500">{r.d}</p>
                </div>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* ── 8 Sinyal TA ──────────────────────────────────────────────────── */}
      <Card>
        <CardContent className="pt-5">
          <SectionTitle icon="🔭" title="8 Sinyal TA — Scanner Engine" sub="7 sinyal Futures Scanner + Taker Ratio (Spot Opp only)" />
          <Tabs tabs={Object.keys(TA_SIGNALS)} active={taTab} onChange={setTaTab} />
          {activeSig && (
            <div className="grid md:grid-cols-2 gap-4">
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-2xl">{activeSig.icon}</span>
                  <div>
                    <p className="font-bold text-neutral-800">{taTab}</p>
                    <Badge label={`Score: ${activeSig.score}`} color="bg-teal-100 text-teal-700" />
                  </div>
                </div>
                <Code>{activeSig.formula}</Code>
              </div>
              <div className="bg-neutral-50 rounded-xl p-4 border">
                <p className="text-xs font-bold text-neutral-700 mb-2">💡 Kenapa works?</p>
                <p className="text-sm text-neutral-600 leading-relaxed">{activeSig.why}</p>
              </div>
            </div>
          )}
          <div className="mt-4 grid grid-cols-3 gap-3">
            {[
              { range: "≥ 70", label: "Setup Sangat Kuat", desc: "Multiple signal confirm", cls: "bg-green-50 border-green-200 text-green-700" },
              { range: "50–69", label: "Setup Bagus",      desc: "Monitor lebih lanjut",    cls: "bg-yellow-50 border-yellow-200 text-yellow-700" },
              { range: "30–49", label: "Early Stage",      desc: "Belum cukup konfirmasi",  cls: "bg-neutral-50 border-neutral-200 text-neutral-500" },
            ].map(s => (
              <div key={s.range} className={`rounded-xl border p-3 text-center ${s.cls}`}>
                <p className="text-xl font-black">{s.range}</p>
                <p className="text-xs font-bold">{s.label}</p>
                <p className="text-[10px] opacity-70">{s.desc}</p>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* ── 4 Trading Styles ─────────────────────────────────────────────── */}
      <Card>
        <CardContent className="pt-5">
          <SectionTitle icon="📊" title="4 Trading Styles — Futures Scanner" sub="Semua min R:R 1:3 — parameter dan timeframe berbeda" />
          <Tabs tabs={Object.keys(STYLES)} active={styleTab} onChange={setStyleTab} />
          {activeStyle && (
            <div className={`rounded-xl border bg-gradient-to-b p-4 ${activeStyle.color}`}>
              <div className="flex items-center gap-3 mb-4">
                <span className="text-3xl">{activeStyle.icon}</span>
                <div>
                  <p className="font-bold text-lg">{styleTab}</p>
                  <p className="text-xs text-neutral-500">{activeStyle.tf} · {activeStyle.dur}</p>
                </div>
                <div className="ml-auto bg-white/70 rounded-lg px-3 py-1.5 text-[10px] font-mono text-neutral-700">
                  {activeStyle.weights}
                </div>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                {Object.entries(activeStyle.params).map(([k, v]) => (
                  <div key={k} className="bg-white/60 rounded-lg px-3 py-2">
                    <p className="text-[10px] text-neutral-500 font-semibold mb-0.5">{k}</p>
                    <p className="text-xs font-bold text-neutral-800">{v}</p>
                  </div>
                ))}
                <div className="bg-teal-100 rounded-lg px-3 py-2 border border-teal-300">
                  <p className="text-[10px] text-teal-600 font-semibold mb-0.5">Min R:R</p>
                  <p className="text-xs font-bold text-teal-800">≥ 1:3</p>
                </div>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Tech Stack ───────────────────────────────────────────────────── */}
      <Card>
        <CardContent className="pt-5">
          <SectionTitle icon="⚙️" title="Tech Stack" />
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
            {[
              { layer: "Backend", items: ["FastAPI + Python 3.12", "SQLAlchemy async", "asyncpg / PostgreSQL 16", "Redis 7 (cache & pub/sub)", "HTTPX (Binance REST)", "Structlog"] },
              { layer: "TA Engine (T0-T4)", items: ["T0: Wyckoff phase detection", "T1: EMA/ADX trend analysis", "T2: S/R swing pivot zones", "T3: BB/Vol/RSI/candle patterns", "T4: Trigger confirmation", "ATR + Fibonacci fallback"] },
              { layer: "Frontend", items: ["Next.js 16 (App Router)", "TypeScript + Tailwind v4", "Recharts (equity curve)", "WebSocket live updates", "System Health monitoring", "Browser Notification API"] },
              { layer: "Agents & Infra", items: ["6 asyncio background agents", "Binance Spot + Futures REST", "Order book depth (Spot)", "Adaptive signal weighting", "Docker Compose (local)", "PostgreSQL 16 + Redis 7"] },
            ].map(s => (
              <div key={s.layer} className="bg-neutral-50 border rounded-xl p-3">
                <p className="font-bold text-neutral-700 mb-2 pb-1 border-b">{s.layer}</p>
                <ul className="space-y-1">
                  {s.items.map(i => (
                    <li key={i} className="flex items-start gap-1 text-neutral-600">
                      <span className="text-teal-500 mt-0.5">·</span>{i}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

    </div>
  );
}
