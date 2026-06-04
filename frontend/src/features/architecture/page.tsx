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

// ── Tabs helper ───────────────────────────────────────────────────────────────
function Tabs({ tabs, active, onChange }: { tabs: string[]; active: string; onChange: (t: string) => void }) {
  return (
    <div className="flex bg-neutral-100 rounded-lg p-0.5 gap-0.5 mb-4">
      {tabs.map(t => (
        <button key={t} onClick={() => onChange(t)}
          className={`flex-1 py-1.5 rounded-md text-xs font-semibold transition-all ${
            active === t ? "bg-white shadow text-neutral-900" : "text-neutral-500 hover:text-neutral-700"
          }`}>
          {t}
        </button>
      ))}
    </div>
  );
}

export default function ArchitecturePage() {
  const [taTab, setTaTab]     = useState("BB Squeeze");
  const [styleTab, setStyleTab] = useState("Scalping");

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
      why: "Volume naik saat harga flat = smart money masuk diam-diam (akumulasi). Volume naik saat harga turun = hidden strength — distribusi sudah selesai.",
    },
    "Near Breakout": {
      icon: "🎯", score: "+20 × w_breakout",
      formula: `dist_high = (recent_high − price) / price
dist_low  = (price − recent_low)  / price
Near breakout  jika 0 < dist_high < 1.5–2.5%
Near reversal  jika 0 < dist_low  < 1.5–2.5%`,
      why: "Harga mendekati high/low terakhir = titik keputusan kritis. Bisa breakout (LONG) atau bounce dari support (SHORT reversal).",
    },
    "RSI": {
      icon: "📈", score: "+15 × w_rsi (oversold)",
      formula: `RSI = 100 − 100 / (1 + AvgGain / AvgLoss)
Period: 9 (scalping) · 14 (day,swing) · 21 (position)

< 30  = oversold → reversal LONG  (+15 pts)
30–50 = energy building            (+12 pts)
50–65 = momentum building           (+8 pts)
> 75  = overbought → SHORT signal  (−10 + SHORT)`,
      why: "RSI < 30 = jenuh jual, potensi reversal kuat. RSI > 75 dengan volume yang sudah pump = entry LONG terlambat, justru setup SHORT.",
    },
    "EMA": {
      icon: "⚡", score: "+15 × w_ema (compress)",
      formula: `EMA(n) = price × k + EMA_prev × (1−k),  k = 2/(n+1)
Spread   = |EMA9 − EMA21| / price
Compress jika spread < 0.3% (scalp) / 0.5% (day) / 0.8% (swing)
Bullish  jika EMA9 > EMA21 > EMA50
Bearish  jika EMA9 < EMA21 < EMA50`,
      why: "EMA 9/21 yang bersilangan dan hampir menyatu = kondisi pra-breakout. Alignment EMA9>21>50 konfirmasi trend bullish yang sehat.",
    },
    "Pressure Shift": {
      icon: "🟢", score: "+15 × w_pressure",
      formula: `bull_ratio = Σ vol[i] (candle hijau) / Σ vol_total (5 candle)
shift = bull_ratio_now − bull_ratio_prev
Buy pressure  jika shift > +15%
Sell pressure jika shift < −15%`,
      why: "Pergeseran dominasi buyer/seller dalam 5 candle = konfirmasi momentum nyata. Bukan sekadar noise harga.",
    },
    "Candle Shrink": {
      icon: "🕯", score: "+10 × w_candle",
      formula: `body[i]    = |close[i] − open[i]|
body_slope = (body[-1] − body[0]) / body[0]  (7 candle)
Kompresi   jika body_slope < −50%`,
      why: "Badan candle semakin kecil = kelelahan trend sebelumnya, indecision. Setup ideal untuk breakout berikutnya.",
    },
  };

  const STYLES = {
    "Scalping": {
      icon: "⚡", tf: "15m", dur: "Menit–Jam",
      color: "from-yellow-500/10 to-orange-500/10 border-yellow-300",
      params: { "RSI Period": "9 (responsif cepat)", "BB Period": "14", "BB Squeeze": "< 3% width", "Vol Slope Min": "> 20%", "Min SL": "≥ 0.8% dari entry", "SL Fallback": "ATR × 1.0", "TP Fallback": "ATR × 3.5", "Min Score": "25 pts" },
      weights: "RSI×2.0 · Pressure×1.8 · Breakout×1.5 · Candle×1.5",
    },
    "Day Trade": {
      icon: "📅", tf: "1H", dur: "Harian",
      color: "from-blue-500/10 to-indigo-500/10 border-blue-300",
      params: { "RSI Period": "14 (standar)", "BB Period": "20", "BB Squeeze": "< 4.5% width", "Vol Slope Min": "> 25%", "Min SL": "≥ 1.2% dari entry", "SL Fallback": "ATR × 1.2", "TP Fallback": "ATR × 4.0", "Min Score": "28 pts" },
      weights: "RSI×1.5 · Pressure×1.5 · Breakout×1.3 · EMA×1.3",
    },
    "Swing": {
      icon: "🌊", tf: "4H", dur: "Hari–Minggu",
      color: "from-teal-500/10 to-green-500/10 border-teal-300",
      params: { "RSI Period": "14", "BB Period": "20", "BB Squeeze": "< 6% width", "Vol Slope Min": "> 30%", "Min SL": "≥ 2.0% dari entry", "SL Fallback": "ATR × 1.5", "TP Fallback": "ATR × 5.0", "Min Score": "30 pts" },
      weights: "Accumulation×2.0 · Squeeze×1.8 · Breakout×1.5",
    },
    "Position": {
      icon: "🏔", tf: "1D", dur: "Minggu–Bulan",
      color: "from-purple-500/10 to-violet-500/10 border-purple-300",
      params: { "RSI Period": "21 (smooth)", "BB Period": "30", "BB Squeeze": "< 8% width", "Vol Slope Min": "> 40%", "Min SL": "≥ 3.0% dari entry", "SL Fallback": "ATR × 2.0", "TP Fallback": "ATR × 7.0", "Min Score": "35 pts" },
      weights: "Accumulation×2.5 · Squeeze×2.0 · EMA×1.5",
    },
  };

  const activeSig   = TA_SIGNALS[taTab as keyof typeof TA_SIGNALS];
  const activeStyle = STYLES[styleTab as keyof typeof STYLES];

  return (
    <div className="space-y-6 max-w-5xl mx-auto">

      {/* ── Hero ──────────────────────────────────────────────────────────── */}
      <Card className="bg-gradient-to-r from-neutral-900 to-neutral-800 text-white border-0">
        <CardContent className="pt-6 pb-5">
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <h1 className="text-3xl font-bold mb-1">📐 Arsitektur Aplikasi</h1>
              <p className="text-sm text-neutral-400 max-w-2xl leading-relaxed">
                Crypto trading agent — scan 100 pair USDT Futures setiap 15 menit,
                deteksi early breakout dengan 7 sinyal TA, catat hasil ke paper trading history
                untuk mengukur win rate per trading style.
              </p>
            </div>
            <div className="text-xs text-neutral-400 font-mono space-y-1">
              <div>Frontend  · Next.js 16 · TypeScript</div>
              <div>Backend   · FastAPI · Python 3.12</div>
              <div>Agents    · asyncio · structlog</div>
              <div>Database  · PostgreSQL · Redis</div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* ── 1. Monorepo Structure ─────────────────────────────────────────── */}
      <Card>
        <CardContent className="pt-5">
          <SectionTitle icon="🗂" title="Struktur Monorepo" sub="3 package terpisah — bisa dikembangkan independen" />
          <div className="grid md:grid-cols-3 gap-3">
            {[
              {
                name: "frontend/", icon: "🖥", color: "border-blue-300 bg-blue-50",
                desc: "Next.js 16 UI — read-only consumer",
                items: ["Scanner page (baca cache agents)", "History page (baca paper_trades)", "Dashboard (real-time via API)", "Architecture docs"],
                cmd: "cd frontend && npm run dev",
              },
              {
                name: "backend/", icon: "⚙️", color: "border-teal-300 bg-teal-50",
                desc: "FastAPI — API layer + TA Engine",
                items: ["scan_market_core() — TA engine", "REST API endpoints", "WebSocket positions", "PostgreSQL + Redis"],
                cmd: "uvicorn app.main:app --reload",
              },
              {
                name: "agents/", icon: "🤖", color: "border-purple-300 bg-purple-50",
                desc: "Autonomous agents — scan + log + learn",
                items: ["scanner/scheduler.py ← satu-satunya yang log", "paper_trader/trader.py ← monitor TP/SL", "learning/ ← future ML optimizer", "Jalan 24/7 independen dari browser"],
                cmd: "python -m agents",
              },
            ].map(pkg => (
              <div key={pkg.name} className={`rounded-xl border p-4 ${pkg.color}`}>
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-xl">{pkg.icon}</span>
                  <div>
                    <p className="font-bold text-sm font-mono">{pkg.name}</p>
                    <p className="text-[10px] text-neutral-500">{pkg.desc}</p>
                  </div>
                </div>
                <ul className="space-y-1 mb-3">
                  {pkg.items.map(i => (
                    <li key={i} className="text-xs text-neutral-600 flex items-start gap-1">
                      <span className="text-neutral-400 mt-0.5">·</span>{i}
                    </li>
                  ))}
                </ul>
                <code className="text-[10px] bg-neutral-900 text-green-400 px-2 py-1 rounded block">{pkg.cmd}</code>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* ── 2. Alur Data ──────────────────────────────────────────────────── */}
      <Card>
        <CardContent className="pt-5">
          <SectionTitle icon="🔄" title="Alur Data Lengkap" sub="Dari Binance → Scanner → History" />
          <Code>{`Binance Futures API (100 pair USDT, volume tertinggi)
         │
         ▼  ⏱ setiap 15 menit — agents/scanner/scheduler.py
   ┌─────────────────────────────────────────────────┐
   │  SCANNER ENGINE  (backend/app/api/v1/scanner.py) │
   │  7 sinyal TA → Probability Score 0–99            │
   │  Filter: R:R < 1:3 → DIBUANG                     │
   └────────────────────┬────────────────────────────┘
                        │
          ┌─────────────┴──────────────┐
          ▼                            ▼
   agents/scanner/store.py      paper_trades (PostgreSQL)
   [in-memory cache]            agents/paper_trader/trader.py
          │                            │
          ▼                            ▼
   Scanner API (read-only)      History API (read-only)
   GET /api/v1/scanner/scan     GET /api/v1/history/*
          │                            │
          ▼                            ▼
   Scanner Page (frontend)      History Page (frontend)
   Tampilkan sinyal live        Win rate per style`}
          </Code>

          <div className="mt-4 grid md:grid-cols-3 gap-3 text-xs">
            {[
              { icon: "🤖", title: "agents/ (Satu-satunya yang SCAN + LOG)", color: "bg-purple-50 border-purple-200",
                items: ["Scheduler loop tiap 15 menit", "scan_market_core() → ambil data Binance + hitung TA", "log_signals_batch() → tulis ke paper_trades", "check_and_close_trades() → cek TP/SL tiap 60 detik", "TIDAK ADA yang boleh log selain agents ini"] },
              { icon: "⚙️", title: "backend/ (API only — tidak log apapun)", color: "bg-teal-50 border-teal-200",
                items: ["scan_market_core() = fungsi TA engine (dipanggil agents)", "Scanner API = baca dari agents/scanner/store (cache)", "History API = baca dari paper_trades DB", "Tidak ada side-effect logging di API endpoints"] },
              { icon: "🖥", title: "frontend/ (Read-only consumer)", color: "bg-blue-50 border-blue-200",
                items: ["Auto-refresh scanner tiap 5 menit dari cache", "Auto-refresh history tiap 30 detik (LIVE badge)", "Tidak ada logika bisnis — hanya tampilkan data", "WebSocket untuk posisi live (dashboard)"] },
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

      {/* ── 3. Trade Lifecycle ────────────────────────────────────────────── */}
      <Card>
        <CardContent className="pt-5">
          <SectionTitle icon="📊" title="Siklus Trade — Dari Scanner ke History" sub="Bagaimana scanner output menjadi paper trade" />

          <div className="grid md:grid-cols-2 gap-6">
            {/* Left: lifecycle diagram */}
            <div>
              <Code>{`Scanner menemukan signal (R:R ≥ 1:3)
         │
         ├── Entry type: "at_zone" / "market"
         │   Harga SUDAH di area entry sekarang
         │        │
         │        ▼
         │   Status: 🔵 OPEN  (posisi aktif)
         │        │
         │        ▼ cek tiap 60 detik (harga Binance)
         │   ┌────┴────┐
         │   ▼         ▼
         │  ✅ TP    🛑 SL
         │
         └── Entry type: "wait_pullback" / "wait_rally"
             Harga BELUM di area entry
                  │
                  ▼
             Status: 🟡 PENDING  (limit order menunggu)
                  │
                  ▼ cek tiap 60 detik
             Harga menyentuh entry zone?
             ├── Belum → tetap PENDING
             └── Ya   → Status: 🔵 OPEN
                              │
                        ┌─────┴─────┐
                        ▼           ▼
                       ✅ TP      🛑 SL`}
              </Code>
            </div>

            {/* Right: status explanation */}
            <div className="space-y-2">
              <p className="text-sm font-bold text-neutral-800 mb-3">Penjelasan per Status</p>
              {[
                { status: "🟡 PENDING", color: "bg-amber-50 border-amber-200", title: "Menunggu Entry",
                  desc: "Signal limit order — harga belum menyentuh zona entry. Kamu harus pasang Limit Buy/Sell di Binance dan tunggu harga datang ke zona tersebut.",
                  ex: "BTCUSDT LONG wait_pullback, entry $98K, harga sekarang $100K → tunggu turun" },
                { status: "🔵 OPEN", color: "bg-blue-50 border-blue-200", title: "Posisi Aktif",
                  desc: "Entry sudah terpenuhi. Posisi sedang berjalan, TP/SL dimonitor otomatis setiap 60 detik dari harga real Binance Futures.",
                  ex: "BTCUSDT LONG at_zone, entry $100K langsung open. Atau pending yang sudah kena." },
                { status: "✅ TP", color: "bg-green-50 border-green-200", title: "Take Profit Hit",
                  desc: "Harga mencapai target TP. Trade ditutup dengan profit. Dihitung dalam win rate dan PnL kalender.",
                  ex: "Entry $100K, TP $106K kena → +4% PnL (R:R 1:4 × 1% risk = +4R)" },
                { status: "🛑 SL", color: "bg-red-50 border-red-200", title: "Stop Loss Hit",
                  desc: "Harga menyentuh SL. Trade ditutup dengan loss. Dihitung dalam win rate.",
                  ex: "Entry $100K, SL $98K kena → −1R loss" },
              ].map(s => (
                <div key={s.status} className={`rounded-xl border p-3 ${s.color}`}>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="font-bold text-sm">{s.status}</span>
                    <span className="text-[10px] font-semibold text-neutral-500">{s.title}</span>
                  </div>
                  <p className="text-xs text-neutral-600 mb-1">{s.desc}</p>
                  <p className="text-[10px] font-mono text-neutral-400">{s.ex}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Key rule */}
          <div className="mt-4 bg-neutral-900 text-white rounded-xl p-4 text-xs">
            <p className="font-bold text-teal-400 mb-2">✅ Aturan Pencatatan</p>
            <div className="grid md:grid-cols-3 gap-4">
              {[
                { title: "Semua signal R:R ≥ 1:3 dicatat", desc: "Apapun yang muncul di scanner dengan R:R cukup → masuk history. Tidak ada yang terlewat." },
                { title: "Satu slot per koin per style", desc: "Scalping BTCUSDT dan Daytrading BTCUSDT adalah dua data berbeda. Tidak bisa double entry per style." },
                { title: "Win rate dari CLOSED saja", desc: "Pending dan Open tidak masuk win rate. Hanya TP dan SL yang dihitung. Statistik akurat." },
              ].map(r => (
                <div key={r.title}>
                  <p className="font-semibold text-neutral-300 mb-1">{r.title}</p>
                  <p className="text-neutral-500">{r.desc}</p>
                </div>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* ── 4. 7 Sinyal TA (interactive) ─────────────────────────────────── */}
      <Card>
        <CardContent className="pt-5">
          <SectionTitle icon="🔭" title="7 Sinyal TA — Scanner Engine" sub="Klik sinyal untuk lihat formula dan penjelasan" />
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

          {/* Penalty */}
          <div className="mt-4 bg-red-50 border border-red-200 rounded-xl p-3 text-xs">
            <p className="font-bold text-red-700 mb-1">⚠️ Penalty — Sudah Pump/Dump</p>
            <p className="text-neutral-600">
              <code className="bg-red-100 px-1 rounded">|change_24h| &gt; pump_penalty × 2</code> → <strong>−20 pts</strong> &nbsp;|&nbsp;
              <code className="bg-red-100 px-1 rounded">|change_24h| &gt; pump_penalty</code> → <strong>−8 pts</strong>.
              Mencegah FOMO entry pada coin yang sudah bergerak terlalu jauh.
            </p>
          </div>

          {/* Score legend */}
          <div className="mt-3 grid grid-cols-3 gap-3">
            {[
              { range: "≥ 70", label: "Setup Sangat Kuat", desc: "Multiple signal confirm", cls: "bg-green-50 border-green-200 text-green-700" },
              { range: "50–69", label: "Setup Bagus", desc: "Monitor lebih lanjut",     cls: "bg-yellow-50 border-yellow-200 text-yellow-700" },
              { range: "< 50", label: "Early Stage", desc: "Belum cukup konfirmasi",   cls: "bg-neutral-50 border-neutral-200 text-neutral-500" },
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

      {/* ── 5. Entry / SL / TP ───────────────────────────────────────────── */}
      <Card>
        <CardContent className="pt-5">
          <SectionTitle icon="📐" title="Entry Zone · SL · TP" sub="Berbasis S/R Zones + Fibonacci — bukan hanya ATR" />
          <div className="grid md:grid-cols-3 gap-4">
            <div>
              <p className="font-bold text-sm text-neutral-800 mb-2">📍 Entry Zone</p>
              <div className="space-y-1.5">
                {[["at_zone (Market)","Harga ≤ 1.5% dari S/R → entry sekarang → status OPEN"],["wait_pullback","LONG: tunggu harga turun ke support → status PENDING"],["wait_rally","SHORT: tunggu harga naik ke resistance → status PENDING"]].map(([k,v]) => (
                  <div key={k} className="rounded-lg p-2 text-xs bg-blue-50 border border-blue-100">
                    <span className="font-bold text-blue-700">{k}: </span>
                    <span className="text-neutral-600">{v}</span>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <p className="font-bold text-sm text-neutral-800 mb-2">⛔ Stop Loss</p>
              <div className="space-y-1.5">
                {[["1. S/R Zone","0.3% di bawah support (LONG) / di atas resistance (SHORT)"],["2. Swing Low/High","Min/max harga dalam lookback period"],["3. Fib 0.618","Retracement 61.8% dari swing range terakhir"],["4. ATR Fallback","entry ± ATR × style_multiplier"],["5. Min Distance","0.8% (scalp) → 3.0% (position) — anti stop-hunt"]].map(([k,v]) => (
                  <div key={k} className="rounded-lg p-2 text-xs bg-red-50 border border-red-100">
                    <span className="font-bold text-red-700">{k}: </span>
                    <span className="text-neutral-600">{v}</span>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <p className="font-bold text-sm text-neutral-800 mb-2">🎯 Take Profit</p>
              <div className="space-y-1.5">
                {[["1. Resistance Zone","Next resistance dengan R:R ≥ 1:2"],["2. Fib 1.618","Extension 161.8% dari swing low ke entry"],["3. ATR Fallback","entry ± ATR × 3.5–7.0"],["Filter Final","R:R < 1:3 → signal DIBUANG"]].map(([k,v]) => (
                  <div key={k} className="rounded-lg p-2 text-xs bg-green-50 border border-green-100">
                    <span className="font-bold text-green-700">{k}: </span>
                    <span className="text-neutral-600">{v}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
          <div className="mt-4">
            <Code>{`Fibonacci levels yang digunakan:
SL  = entry − swing_range × 0.618   (Fib 61.8% retracement)
TP1 = entry + swing_range × 1.272   (Fib 127.2% extension)
TP2 = entry + swing_range × 1.618   (Golden ratio ← default TP)
TP3 = entry + swing_range × 2.618   (Fib 261.8% — target jauh)

S/R Zone detection:
  1. Swing highs (local maxima, 2-bar rule) → resistance
  2. Swing lows  (local minima, 2-bar rule) → support
  3. Cluster levels berdekatan (< 0.5% toleransi) → single zone
  4. Sort by touch count (paling banyak disentuh = paling kuat)`}
            </Code>
          </div>
        </CardContent>
      </Card>

      {/* ── 6. 4 Trading Styles ───────────────────────────────────────────── */}
      <Card>
        <CardContent className="pt-5">
          <SectionTitle icon="🎯" title="4 Trading Styles" sub="Semua min R:R 1:3 — parameter dan timeframe berbeda" />
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

      {/* ── 7. Dashboard — Run Analysis ──────────────────────────────────── */}
      <Card>
        <CardContent className="pt-5">
          <SectionTitle icon="🏠" title="Dashboard — Run Analysis" sub="Deep-dive satu koin, pipeline T0→T4 lengkap" />
          <div className="grid md:grid-cols-2 gap-6">
            <div className="space-y-2">
              <p className="text-sm text-neutral-600 mb-3">
                Klik koin di Dashboard → <strong>CoinModal</strong> dengan 3 tab:
              </p>
              {[
                { tab: "📈 Chart", desc: "Candlestick + EMA 9/21/50 + S/R zones + entry/SL/TP markers. Timeframe otomatis sesuai style." },
                { tab: "ℹ️ Info", desc: "Harga real-time, volume 24H, change %, data Binance Futures." },
                { tab: "🧠 Run Analysis", desc: "Pipeline TA lengkap T0→T4 untuk satu koin. Pilih style, klik Run, lihat hasil per layer animasi." },
              ].map(t => (
                <div key={t.tab} className="bg-neutral-50 border rounded-xl p-3">
                  <p className="font-bold text-sm mb-0.5">{t.tab}</p>
                  <p className="text-xs text-neutral-600">{t.desc}</p>
                </div>
              ))}
            </div>
            <div>
              <p className="font-bold text-sm mb-3">Pipeline T0→T4 per Layer</p>
              <div className="space-y-1.5">
                {[
                  ["T0 Wyckoff", "bg-neutral-600", "Accumulation / Markup / Distribution / Markdown"],
                  ["T1 Trend", "bg-blue-600", "EMA 13/21 — Up / Down / Sideways"],
                  ["T2 S/R Zones", "bg-teal-600", "Swing pivot clustering — support & resistance"],
                  ["T3 Pattern", "bg-purple-600", "Double bottom/top, H&S, wedge, flag, triangle"],
                  ["T4 Trigger", "bg-yellow-600", "Candlestick + Stochastic 5,3,3 + volume confirm"],
                  ["Output", "bg-green-600", "Entry, SL, TP, R:R, probability, entry_type"],
                ].map(([layer, color, desc]) => (
                  <div key={layer as string} className="flex items-start gap-2">
                    <span className={`text-[10px] text-white font-bold px-2 py-0.5 rounded shrink-0 mt-0.5 ${color}`}>{layer}</span>
                    <span className="text-xs text-neutral-600">{desc}</span>
                  </div>
                ))}
              </div>
              <div className="mt-3 bg-amber-50 border border-amber-200 rounded-xl p-3 text-xs">
                <p className="font-bold text-amber-700 mb-1">Perbedaan vs Scanner</p>
                <p className="text-neutral-600"><strong>Scanner</strong> = broad 100 pair, tiap 15 menit otomatis.<br />
                <strong>Run Analysis</strong> = deep-dive satu koin, manual on-demand, pipeline T0→T4 penuh.</p>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* ── 8. History — Win Rate Purpose ────────────────────────────────── */}
      <Card>
        <CardContent className="pt-5">
          <SectionTitle icon="📊" title="History — Tujuan & Cara Kerja" sub="Mengukur trading style mana yang paling profitable" />
          <div className="grid md:grid-cols-2 gap-6">
            <div>
              <p className="text-sm text-neutral-600 mb-3">
                History bukan sekadar log — ini adalah <strong>dataset untuk mengukur kualitas sinyal per style</strong>.
                Setelah data terkumpul 2+ minggu, kamu bisa lihat:
              </p>
              <div className="space-y-2 text-xs">
                {[
                  ["Win Rate per Style", "Scalping 68% vs Day Trade 91% → Day Trade lebih konsisten"],
                  ["Avg PnL per Trade", "Swing +16% avg → reward besar meski jarang masuk"],
                  ["PnL Kalender", "Hari mana yang konsisten profit, hari mana yang loss"],
                  ["Equity Curve", "Apakah modal tumbuh stabil atau volatile?"],
                ].map(([k, v]) => (
                  <div key={k} className="bg-neutral-50 border rounded-lg p-2">
                    <p className="font-bold text-neutral-700">{k}</p>
                    <p className="text-neutral-500">{v}</p>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <Code>{`Equity Curve (1% risk per trade):
  TP hit → gain = 1% × RR_ratio
           (R:R 1:4 = +4%, R:R 1:7 = +7%)
  SL hit → loss = −1%

  Contoh 10 trade:
  7 TP × 1:4 = +28%
  3 SL × 1   = − 3%
  Net         = +25% dari modal

Win Rate formula:
  WR = TP_count / (TP_count + SL_count) × 100
  Pending & Open → TIDAK dihitung
  Hanya closed trades yang masuk statistik

Live refresh:
  Price check  → tiap 60 detik (pending→open, open→tp/sl)
  History page → auto-poll tiap 30 detik
  Scanner cache → diperbarui tiap 15 menit oleh scheduler`}
              </Code>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* ── 9. Tech Stack ─────────────────────────────────────────────────── */}
      <Card>
        <CardContent className="pt-5">
          <SectionTitle icon="⚙️" title="Tech Stack" />
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
            {[
              { layer: "Backend", items: ["FastAPI + Python 3.12", "SQLAlchemy async", "asyncpg / PostgreSQL", "Redis (cache & pub/sub)", "HTTPX (Binance REST)", "Structlog"] },
              { layer: "TA Engine", items: ["RSI (Wilder, 9/14/21)", "Bollinger Bands (SMA+2σ)", "EMA (9/21/50)", "ATR (True Range avg)", "Fibonacci (0.618/1.618/2.618)", "S/R Swing Pivot Clustering"] },
              { layer: "Frontend", items: ["Next.js 16 (App Router)", "TypeScript", "Tailwind CSS v4", "Recharts (equity/calendar)", "Lightweight Charts (candles)", "Poppins font"] },
              { layer: "Agents & Infra", items: ["asyncio background loop", "scan_store (in-memory)", "PostgreSQL 16 (TimescaleDB)", "Redis 7 (pub/sub)", "Docker Compose (local)", "WatchFiles hot-reload"] },
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
