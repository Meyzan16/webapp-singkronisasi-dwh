"use client";

import { Card, CardContent } from "@/components/ui/card";

// ── Reusable section components ───────────────────────────────────────────────

function SectionHeader({ icon, title, subtitle }: { icon: string; title: string; subtitle?: string }) {
  return (
    <div className="flex items-center gap-3 mb-5">
      <span className="text-3xl">{icon}</span>
      <div>
        <h2 className="text-xl font-bold text-neutral-900">{title}</h2>
        {subtitle && <p className="text-sm text-neutral-500">{subtitle}</p>}
      </div>
    </div>
  );
}

function CodeBlock({ children }: { children: string }) {
  return (
    <pre className="bg-neutral-900 text-green-400 text-[11px] font-mono p-3 rounded-lg overflow-x-auto leading-relaxed whitespace-pre-wrap">
      {children}
    </pre>
  );
}

function Tag({ label, color = "bg-teal-100 text-teal-700" }: { label: string; color?: string }) {
  return <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${color}`}>{label}</span>;
}

function Rule({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between items-start gap-4 py-1.5 border-b border-neutral-100 last:border-0">
      <span className="text-sm text-neutral-500 shrink-0">{label}</span>
      <span className="text-sm font-semibold text-neutral-800 text-right">{value}</span>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function ArchitecturePage() {
  return (
    <div className="space-y-6 max-w-5xl mx-auto">

      {/* Hero */}
      <Card className="bg-gradient-to-r from-neutral-900 to-neutral-800 text-white border-0">
        <CardContent className="pt-6 pb-5">
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <h1 className="text-3xl font-bold mb-1">📐 Arsitektur Aplikasi</h1>
              <p className="text-sm text-neutral-400 max-w-2xl leading-relaxed">
                Crypto trading agent dengan multi-timeframe TA. Scanner deteksi early breakout di 100 pair USDT futures,
                hitung entry/SL/TP berbasis S&amp;R + Fibonacci, dan catat hasilnya ke paper-trading history untuk mengukur
                win rate per trading style.
              </p>
            </div>
            <div className="flex flex-col gap-1.5 text-xs text-neutral-400 font-mono">
              <span>Backend  : FastAPI · Python 3.12</span>
              <span>Frontend : Next.js 16 · TypeScript</span>
              <span>DB       : PostgreSQL + Redis</span>
              <span>Data     : Binance Futures REST</span>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* ── 1. Data Flow Overview ─────────────────────────────────────────── */}
      <Card>
        <CardContent className="pt-6">
          <SectionHeader icon="🔄" title="Alur Data Keseluruhan" />
          <CodeBlock>{`Binance Futures API
    │
    ▼  setiap 15 menit (Scheduler)
┌─────────────────────────────────────────────────────┐
│  Scanner Engine  ─────────────────────────────────  │
│  100 pair USDT → filter 7 sinyal TA → scoring      │
│  → hanya R:R ≥ 1:3 lolos                           │
│                  ┌──────────────┐                   │
│                  │  scan_store  │  ← in-memory cache│
│                  └──────┬───────┘                   │
└─────────────────────────┼───────────────────────────┘
                          │
        ┌─────────────────┼──────────────────┐
        ▼                 ▼                  ▼
  Scanner Page       paper_trades DB    History Page
  (read-only)        (PostgreSQL)       (win rate stats)
  serve cache        1 tulis per style  per trading style
                     per koin per cycle`}
          </CodeBlock>

          <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-3 text-sm">
            <div className="bg-blue-50 rounded-xl p-3 border border-blue-100">
              <p className="font-bold text-blue-700 mb-1">🔭 Scanner API</p>
              <p className="text-neutral-600 text-xs">Read-only — serve cache dari scheduler. Tidak trigger scan baru, tidak tulis ke DB.</p>
            </div>
            <div className="bg-teal-50 rounded-xl p-3 border border-teal-100">
              <p className="font-bold text-teal-700 mb-1">⏱ Scheduler</p>
              <p className="text-neutral-600 text-xs">Satu-satunya yang scan + log. Jalan tiap 15 menit 24/7, tulis ke scan_store dan paper_trades.</p>
            </div>
            <div className="bg-purple-50 rounded-xl p-3 border border-purple-100">
              <p className="font-bold text-purple-700 mb-1">📊 History</p>
              <p className="text-neutral-600 text-xs">Baca paper_trades. Monitor TP/SL tiap 60 detik via Binance harga real-time.</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* ── 2. Scanner Engine ────────────────────────────────────────────── */}
      <Card>
        <CardContent className="pt-6">
          <SectionHeader icon="🔭" title="Scanner Engine — 7 Sinyal TA" subtitle="backend/app/api/v1/scanner.py" />

          <p className="text-sm text-neutral-600 mb-4">
            Tiap 15 menit, scanner ambil 100 pair USDT futures dengan volume tertinggi dari Binance, fetch klines,
            lalu jalankan 7 indikator TA. Setiap indikator memberi poin yang dijumlahkan jadi
            <strong className="text-neutral-800"> Probability Score (0–99)</strong>.
          </p>

          {/* 7 signals */}
          <div className="space-y-3">
            {[
              {
                n: 1, name: "Bollinger Band Squeeze", icon: "🔵",
                formula: "BB Width = (StdDev × 4) / Mid\nSqueeze  jika Width < threshold (3–8% tergantung style)\nTightening jika Width < threshold × 1.5",
                score: "Squeeze: +25 × w_squeeze | Tightening: +12 × w_squeeze",
                why: "Volatilitas yang menyempit (BB menguncup) menandakan energi yang dikompresi — sebelum breakout besar harga biasanya diam dulu.",
              },
              {
                n: 2, name: "Volume Accumulation", icon: "📦",
                formula: "vol_slope  = (vol[-1] − vol[-5]) / vol[-5]\nprice_slope = (close[-1] − close[-5]) / close[-5]\nAkumulasi   jika vol_slope > min_vol AND |price_slope| < 4%\nHidden Str  jika vol_slope tinggi AND price_slope < 0",
                score: "Akumulasi: +22 × w_accum | Hidden strength: +18 × w_accum",
                why: "Volume naik saat harga flat = smart money masuk diam-diam. Volume naik saat harga turun = hidden strength (distribusi selesai).",
              },
              {
                n: 3, name: "Near Breakout / Reversal Zone", icon: "🎯",
                formula: "dist_high = (recent_high − price) / price\ndist_low  = (price − recent_low)  / price\nNear breakout  jika 0 < dist_high < 1.5–2.5%\nNear reversal  jika 0 < dist_low  < 1.5–2.5%",
                score: "Breakout: +20 × w_breakout | Reversal: +15 × w_breakout",
                why: "Harga mendekati high/low terakhir adalah titik keputusan — bisa breakout (LONG) atau bounce (SHORT).",
              },
              {
                n: 4, name: "RSI (Relative Strength Index)", icon: "📈",
                formula: "RSI = 100 − 100 / (1 + AvgGain / AvgLoss)\nPeriod: 9 (scalping) / 14 (day,swing) / 21 (position)\n< 30 = oversold | 30–50 = energy | 50–65 = momentum | > 75 = overbought SHORT",
                score: "< 30: +15 × w_rsi | 30–50: +12 | 50–65: +8 | > 75: −10 + SHORT",
                why: "RSI oversold (< 30) menandakan potensi reversal kuat. RSI > 75 dengan volume sudah pump = entry terlambat untuk LONG, bisa SHORT.",
              },
              {
                n: 5, name: "EMA Compression & Alignment", icon: "⚡",
                formula: "EMA(n) = price × k + EMA_prev × (1−k),  k = 2/(n+1)\nSpread   = |EMA9 − EMA21| / price\nCompress jika spread < 0.3% (scalp) / 0.5% (day) / 0.8% (swing)\nBullish  jika EMA9 > EMA21 > EMA50\nBearish  jika EMA9 < EMA21 < EMA50",
                score: "Kompres: +15 × w_ema | Bullish/Bearish alignment: +8 × w_ema",
                why: "EMA 9/21 yang bersilangan dan hampir menyatu adalah kondisi pra-breakout (coiling). Alignment EMA9>21>50 konfirmasi trend bullish.",
              },
              {
                n: 6, name: "Buy/Sell Pressure Shift", icon: "🟢",
                formula: "bull_ratio = Σ vol[i] (candle hijau) / Σ vol_total  (5 candle)\nshift = bull_ratio_now − bull_ratio_prev (5 candle lalu)\nBuy pressure   jika shift > +15%\nSell pressure  jika shift < −15%",
                score: "Buy: +15 × w_pressure | Sell: +12 × w_pressure",
                why: "Pergeseran dominasi buyer/seller dalam 5 candle terakhir = konfirmasi momentum nyata, bukan sekadar noise harga.",
              },
              {
                n: 7, name: "Candle Body Shrinking", icon: "🕯",
                formula: "body[i] = |close[i] − open[i]|\nbody_slope = (body[-1] − body[0]) / body[0]  (7 candle)\nCompresi jika body_slope < −50%",
                score: "+10 × w_candle",
                why: "Badan candle yang semakin kecil (indecision) adalah tanda kelelahan trend sebelumnya — setup ideal untuk breakout berikutnya.",
              },
            ].map(sig => (
              <div key={sig.n} className="border border-neutral-200 rounded-xl overflow-hidden">
                <div className="flex items-center gap-3 px-4 py-2.5 bg-neutral-50">
                  <span className="text-lg">{sig.icon}</span>
                  <span className="font-bold text-sm text-neutral-800">{sig.n}. {sig.name}</span>
                  <Tag label={sig.score} color="bg-teal-100 text-teal-700" />
                </div>
                <div className="px-4 py-3 grid md:grid-cols-2 gap-3">
                  <CodeBlock>{sig.formula}</CodeBlock>
                  <div className="text-xs text-neutral-600 leading-relaxed flex items-start">
                    <span className="mr-1 text-base">💡</span>
                    <span>{sig.why}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* Penalty */}
          <div className="mt-4 bg-red-50 border border-red-200 rounded-xl p-4">
            <p className="font-bold text-red-700 text-sm mb-1">⚠️ Penalty — Sudah Pump/Dump</p>
            <p className="text-xs text-neutral-600">
              Jika <code className="font-mono bg-red-100 px-1 rounded">|change_24h| &gt; pump_penalty × 2</code> → <strong>−20 pts</strong>.
              Jika <code className="font-mono bg-red-100 px-1 rounded">|change_24h| &gt; pump_penalty</code> → <strong>−8 pts</strong>.
              Ini mencegah entry pada coin yang sudah bergerak terlalu jauh (FOMO).
            </p>
          </div>

          {/* Score legend */}
          <div className="mt-4 grid grid-cols-3 gap-3">
            {[
              { range: "≥ 70", label: "Setup Sangat Kuat", desc: "Multiple signal confirm", color: "bg-green-50 border-green-200 text-green-700" },
              { range: "50–69", label: "Setup Bagus", desc: "Monitor lebih lanjut", color: "bg-yellow-50 border-yellow-200 text-yellow-700" },
              { range: "< 50", label: "Early Stage", desc: "Belum cukup konfirmasi", color: "bg-neutral-50 border-neutral-200 text-neutral-500" },
            ].map(s => (
              <div key={s.range} className={`rounded-xl border p-3 text-center ${s.color}`}>
                <p className="text-2xl font-black">{s.range}</p>
                <p className="text-xs font-bold mt-0.5">{s.label}</p>
                <p className="text-[10px] opacity-70">{s.desc}</p>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* ── 3. Entry / SL / TP Logic ─────────────────────────────────────── */}
      <Card>
        <CardContent className="pt-6">
          <SectionHeader icon="📐" title="Entry Zone · SL · TP — Hierarki Kalkulasi" subtitle="Berbasis S&R Zones + Fibonacci (bukan hanya ATR)" />

          <div className="grid md:grid-cols-3 gap-4 mb-4">
            {/* Entry */}
            <div className="space-y-2">
              <p className="font-bold text-sm text-neutral-800">📍 Entry Zone</p>
              <div className="text-xs space-y-1.5 text-neutral-600">
                <div className="bg-neutral-50 rounded-lg p-2 border">
                  <p className="font-semibold text-neutral-700 mb-0.5">LONG → Support Zone</p>
                  <p><span className="font-mono bg-green-100 text-green-700 px-1 rounded">at_zone</span> — harga ≤ 1.5% di atas support → entry sekarang</p>
                  <p><span className="font-mono bg-amber-100 text-amber-700 px-1 rounded">wait_pullback</span> — 1.5–6% di atas → tunggu turun ke support, pasang limit buy</p>
                </div>
                <div className="bg-neutral-50 rounded-lg p-2 border">
                  <p className="font-semibold text-neutral-700 mb-0.5">SHORT → Resistance Zone</p>
                  <p><span className="font-mono bg-green-100 text-green-700 px-1 rounded">at_zone</span> — harga ≤ 1.5% di bawah resistance → entry sekarang</p>
                  <p><span className="font-mono bg-amber-100 text-amber-700 px-1 rounded">wait_rally</span> — 1.5–6% di bawah → tunggu naik ke resistance, pasang limit sell</p>
                </div>
              </div>
            </div>

            {/* SL */}
            <div className="space-y-2">
              <p className="font-bold text-sm text-neutral-800">⛔ Stop Loss — Prioritas</p>
              <div className="text-xs space-y-1 text-neutral-600">
                {[
                  ["1. S/R Zone", "0.3% di bawah support (LONG) / 0.3% di atas resistance (SHORT)"],
                  ["2. Swing Low/High", "Structural SL — min/max harga dalam lookback period"],
                  ["3. Fibonacci 0.618", "Retracement 61.8% dari swing range terakhir"],
                  ["4. ATR Fallback", "entry ± ATR × style_multiplier (jika semua di atas terlalu jauh)"],
                  ["5. Min Distance", "Enforced minimum SL jarak: 0.8% (scalp) → 3.0% (position)"],
                ].map(([k, v]) => (
                  <div key={k} className="bg-red-50 border border-red-100 rounded p-1.5">
                    <span className="font-bold text-red-700">{k}:</span> <span>{v}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* TP */}
            <div className="space-y-2">
              <p className="font-bold text-sm text-neutral-800">🎯 Take Profit — Prioritas</p>
              <div className="text-xs space-y-1 text-neutral-600">
                {[
                  ["1. Resistance Zone", "Next resistance (LONG) / support (SHORT) yang R:R ≥ 1:2"],
                  ["2. Fibonacci 1.618", "Extension 161.8% dari swing low ke entry (LONG) / mirror (SHORT)"],
                  ["3. ATR Fallback", "entry ± ATR × tp_multiplier (3.5–7.0 tergantung style)"],
                ].map(([k, v]) => (
                  <div key={k} className="bg-green-50 border border-green-100 rounded p-1.5">
                    <span className="font-bold text-green-700">{k}:</span> <span>{v}</span>
                  </div>
                ))}
                <div className="mt-2 bg-teal-50 border border-teal-200 rounded p-2">
                  <p className="font-bold text-teal-700">Filter Final: R:R ≥ 1:3</p>
                  <p>Signal dibuang jika reward/risk &lt; 3.0. Ini berlaku di scanner UI maupun paper_trades logging.</p>
                </div>
              </div>
            </div>
          </div>

          <CodeBlock>{`Fibonacci Levels yang Digunakan:
SL  = entry − swing_range × 0.618   (Fib 61.8% retracement)
TP1 = entry + swing_range × 1.272   (Fib 127.2% extension)
TP2 = entry + swing_range × 1.618   (Golden ratio extension ← default TP)
TP3 = entry + swing_range × 2.618   (Fib 261.8% — target jauh)

S/R Zone Detection:
1. Cari swing highs (local maxima, 2-bar rule) → resistance candidates
2. Cari swing lows  (local minima, 2-bar rule) → support candidates
3. Cluster levels yang berdekatan (< 0.5% toleransi) → single zone
4. Sort by touch count (paling banyak disentuh = paling kuat)`}
          </CodeBlock>
        </CardContent>
      </Card>

      {/* ── 4. Trading Styles ────────────────────────────────────────────── */}
      <Card>
        <CardContent className="pt-6">
          <SectionHeader icon="🎯" title="4 Trading Styles" subtitle="Timeframe & parameter berbeda, min R:R sama: 1:3" />

          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
            {[
              {
                icon: "⚡", name: "Scalping", tf: "15m", dur: "Menit–Jam",
                color: "from-orange-500/10 to-yellow-500/10 border-orange-300",
                params: [
                  ["RSI Period", "9 (responsif)"],
                  ["BB Period", "14"],
                  ["BB Squeeze", "< 3% width"],
                  ["Vol Slope Min", "> 20%"],
                  ["Min SL Jarak", "≥ 0.8% dari entry"],
                  ["SL Fallback", "ATR × 1.0"],
                  ["TP Fallback", "ATR × 3.5"],
                  ["Min Score", "25 pts"],
                  ["Min R:R", "≥ 1:3"],
                ],
                weights: "RSI×2.0 · Pressure×1.8 · Breakout×1.5 · Candle×1.5",
              },
              {
                icon: "📅", name: "Day Trade", tf: "1H", dur: "Harian",
                color: "from-blue-500/10 to-indigo-500/10 border-blue-300",
                params: [
                  ["RSI Period", "14 (standar)"],
                  ["BB Period", "20"],
                  ["BB Squeeze", "< 4.5% width"],
                  ["Vol Slope Min", "> 25%"],
                  ["Min SL Jarak", "≥ 1.2% dari entry"],
                  ["SL Fallback", "ATR × 1.2"],
                  ["TP Fallback", "ATR × 4.0"],
                  ["Min Score", "28 pts"],
                  ["Min R:R", "≥ 1:3"],
                ],
                weights: "RSI×1.5 · Pressure×1.5 · Breakout×1.3 · EMA×1.3",
              },
              {
                icon: "🌊", name: "Swing", tf: "4H", dur: "Hari–Minggu",
                color: "from-teal-500/10 to-green-500/10 border-teal-300",
                params: [
                  ["RSI Period", "14"],
                  ["BB Period", "20"],
                  ["BB Squeeze", "< 6% width"],
                  ["Vol Slope Min", "> 30%"],
                  ["Min SL Jarak", "≥ 2.0% dari entry"],
                  ["SL Fallback", "ATR × 1.5"],
                  ["TP Fallback", "ATR × 5.0"],
                  ["Min Score", "30 pts"],
                  ["Min R:R", "≥ 1:3"],
                ],
                weights: "Accumulation×2.0 · Squeeze×1.8 · Breakout×1.5",
              },
              {
                icon: "🏔", name: "Position", tf: "1D", dur: "Minggu–Bulan",
                color: "from-purple-500/10 to-violet-500/10 border-purple-300",
                params: [
                  ["RSI Period", "21 (smooth)"],
                  ["BB Period", "30"],
                  ["BB Squeeze", "< 8% width"],
                  ["Vol Slope Min", "> 40%"],
                  ["Min SL Jarak", "≥ 3.0% dari entry"],
                  ["SL Fallback", "ATR × 2.0"],
                  ["TP Fallback", "ATR × 7.0"],
                  ["Min Score", "35 pts"],
                  ["Min R:R", "≥ 1:3"],
                ],
                weights: "Accumulation×2.5 · Squeeze×2.0 · EMA×1.5",
              },
            ].map(s => (
              <div key={s.name} className={`rounded-xl border bg-gradient-to-b p-4 ${s.color}`}>
                <div className="flex items-center gap-2 mb-3">
                  <span className="text-xl">{s.icon}</span>
                  <div>
                    <p className="font-bold text-sm">{s.name}</p>
                    <p className="text-[10px] text-neutral-500">{s.tf} · {s.dur}</p>
                  </div>
                </div>
                <div className="space-y-1 mb-2">
                  {s.params.map(([k, v]) => (
                    <div key={k} className="flex justify-between text-[10px]">
                      <span className="text-neutral-500">{k}</span>
                      <span className="font-mono font-semibold text-neutral-800 text-right">{v}</span>
                    </div>
                  ))}
                </div>
                <div className="bg-white/60 rounded-lg px-2 py-1.5 mt-1">
                  <p className="text-[9px] text-neutral-500 font-bold uppercase mb-0.5">Bobot Aktif</p>
                  <p className="text-[10px] font-mono leading-relaxed text-neutral-700">{s.weights}</p>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* ── 5. Paper Trading / History ───────────────────────────────────── */}
      <Card>
        <CardContent className="pt-6">
          <SectionHeader icon="📊" title="Paper Trading History" subtitle="Tujuan: mengukur win rate per trading style" />

          <p className="text-sm text-neutral-600 mb-4">
            Setiap rekomendasi scanner yang lolos filter dicatat sebagai paper trade. Harga TP/SL dipantau
            otomatis via Binance. Win rate per style dihitung dari rasio TP:SL yang ter-close.
          </p>

          <div className="grid md:grid-cols-2 gap-4">
            <div>
              <p className="font-bold text-sm text-neutral-800 mb-2">Aturan Logging</p>
              <div className="space-y-2 text-xs">
                {[
                  ["R:R Minimum", "≥ 1:3 — signal dengan reward lebih kecil dari 3× risk dibuang"],
                  ["Dedup per coin+style", "Jika scalping BTCUSDT sudah open, skip. Scalping & daytrading BTCUSDT = data BERBEDA (terpisah per style)"],
                  ["Re-entry bebas", "Setelah trade tutup (TP/SL), slot koin+style langsung bebas — boleh masuk lagi saat sinyal baru muncul"],
                  ["Satu sumber logging", "HANYA scheduler yang menulis ke paper_trades. Scanner API bersifat read-only"],
                ].map(([k, v]) => (
                  <div key={k} className="bg-neutral-50 border border-neutral-200 rounded-lg p-2">
                    <span className="font-bold text-neutral-700">{k}: </span>
                    <span className="text-neutral-600">{v}</span>
                  </div>
                ))}
              </div>
            </div>

            <div>
              <p className="font-bold text-sm text-neutral-800 mb-2">Aturan TP/SL Check</p>
              <div className="space-y-2 text-xs">
                {[
                  ["Min Hold", "5 menit grace period setelah entry — tidak ada cek TP/SL sebelum ini (mencegah instant-TP artifact)"],
                  ["Limit Fill Check", "Untuk entry wait_pullback (LONG): cek TP/SL hanya jika current_price ≤ entry_price (order sudah terisi)"],
                  ["Limit Fill Check SHORT", "Untuk wait_rally (SHORT): cek TP/SL hanya jika current_price ≥ entry_price"],
                  ["Rate Limit", "Check_and_close_trades() dipanggil max 1× per menit (rate-limited via _CHECK_INTERVAL)"],
                ].map(([k, v]) => (
                  <div key={k} className="bg-neutral-50 border border-neutral-200 rounded-lg p-2">
                    <span className="font-bold text-neutral-700">{k}: </span>
                    <span className="text-neutral-600">{v}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="mt-4"><CodeBlock>{`Equity Curve Calculation:
  Risk per trade = 1% modal (konstant)
  TP hit → gain = 1% × RR_ratio  (misal R:R 1:4 → +4%)
  SL hit → loss = −1%
  Cumulative PnL = Σ gain/loss semua closed trades (urut waktu)`}
          </CodeBlock></div>
        </CardContent>
      </Card>

      {/* ── 6. Dashboard — Run Analysis ──────────────────────────────────── */}
      <Card>
        <CardContent className="pt-6">
          <SectionHeader icon="🏠" title="Dashboard — Run Analysis" subtitle="Analisis mendalam per koin, dijalankan manual" />

          <div className="grid md:grid-cols-2 gap-6">
            <div>
              <p className="text-sm text-neutral-600 mb-3">
                Di Dashboard, klik koin manapun untuk membuka <strong>CoinModal</strong> dengan 3 tab:
              </p>
              <div className="space-y-2 text-sm">
                {[
                  { tab: "📈 Chart", desc: "Candlestick chart dengan EMA 9/21/50, S/R zones, entry/SL/TP markers. Timeframe otomatis sesuai style yang dipilih (15m/1H/4H/1D)." },
                  { tab: "ℹ️ Info", desc: "Harga real-time, volume 24H, perubahan harga, data market dari Binance Futures." },
                  { tab: "🧠 Run Analysis", desc: "Jalankan pipeline TA lengkap untuk koin tersebut. Pilih style (Scalping/Day/Swing/Position), klik Run, lihat hasil per layer secara animasi." },
                ].map(t => (
                  <div key={t.tab} className="bg-neutral-50 border border-neutral-200 rounded-xl p-3">
                    <p className="font-bold text-neutral-800 text-sm mb-0.5">{t.tab}</p>
                    <p className="text-xs text-neutral-600">{t.desc}</p>
                  </div>
                ))}
              </div>
            </div>

            <div>
              <p className="font-bold text-sm text-neutral-800 mb-2">Pipeline Analysis — Layer by Layer</p>
              <p className="text-xs text-neutral-500 mb-3">
                Endpoint: <code className="font-mono bg-neutral-100 px-1 rounded">GET /api/v1/coin/&#123;symbol&#125;/analyze?style=&#123;style&#125;</code>
              </p>
              <div className="space-y-1.5 text-xs">
                {[
                  ["T0 Wyckoff", "Phase detection — Accumulation / Markup / Distribution / Markdown"],
                  ["T1 Trend", "EMA 13/21 trendline — Up / Down / Sideways"],
                  ["T2 S/R Zones", "Swing pivot clustering — support & resistance zones"],
                  ["T3 Pattern", "Double bottom/top, H&S, wedge, flag, triangle detection"],
                  ["T4 Trigger", "Candlestick patterns + Stochastic 5,3,3 + volume confirmation"],
                  ["Signal Output", "Entry, SL, TP, R:R, probability, entry_type"],
                ].map(([k, v], i) => (
                  <div key={k} className="flex gap-2 items-start">
                    <span className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold text-white shrink-0 mt-0.5 ${
                      ["bg-neutral-500","bg-blue-500","bg-teal-500","bg-purple-500","bg-yellow-500","bg-green-500"][i]
                    }`}>{i+1}</span>
                    <div>
                      <span className="font-bold text-neutral-700">{k}: </span>
                      <span className="text-neutral-600">{v}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="mt-4 bg-amber-50 border border-amber-200 rounded-xl p-3 text-xs text-neutral-700">
            <p className="font-bold text-amber-700 mb-1">ℹ️ Perbedaan Run Analysis vs Scanner</p>
            <p>
              <strong>Scanner</strong> = broad scan 100 pair, cepat, optimized untuk speed, dijalankan tiap 15 menit oleh scheduler.<br />
              <strong>Run Analysis</strong> = deep dive satu koin, pakai pipeline T0→T4 lengkap, dijalankan manual on-demand, hasil lebih detail.
              Scanner tidak memanggil Run Analysis — keduanya independen.
            </p>
          </div>
        </CardContent>
      </Card>

      {/* ── 7. Futures Market & Scanner Widget di Dashboard ──────────────── */}
      <Card>
        <CardContent className="pt-6">
          <SectionHeader icon="📋" title="Komponen Dashboard Lainnya" />
          <div className="grid md:grid-cols-3 gap-3 text-sm">
            {[
              {
                icon: "🏦", name: "Futures Market",
                desc: "Tabel semua pair USDT futures dengan harga, change 24H, volume, open interest. Klik koin → buka CoinModal.",
                source: "GET /api/v1/market/futures-market",
              },
              {
                icon: "💰", name: "Spot Positions",
                desc: "Posisi spot aktif di akun Binance. Menampilkan balance per asset, nilai USDT, dan perubahan harga.",
                source: "GET /api/v1/market/spot-positions",
              },
              {
                icon: "📡", name: "Live Positions (WebSocket)",
                desc: "Stream real-time posisi futures aktif via WebSocket. Update harga dan unrealized PnL setiap 2 detik.",
                source: "WS /ws/positions → PositionManager",
              },
            ].map(c => (
              <div key={c.name} className="bg-neutral-50 border border-neutral-200 rounded-xl p-3">
                <div className="flex items-center gap-2 mb-1.5">
                  <span className="text-xl">{c.icon}</span>
                  <p className="font-bold text-neutral-800">{c.name}</p>
                </div>
                <p className="text-xs text-neutral-600 mb-2">{c.desc}</p>
                <code className="text-[10px] font-mono bg-neutral-900 text-green-400 px-2 py-1 rounded block">{c.source}</code>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* ── 8. Tech Stack ────────────────────────────────────────────────── */}
      <Card>
        <CardContent className="pt-6">
          <SectionHeader icon="⚙️" title="Tech Stack" />
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
            {[
              { layer: "Backend", items: ["FastAPI + Python 3.12", "SQLAlchemy async", "asyncpg / PostgreSQL", "Redis (cache & pub/sub)", "HTTPX (Binance REST)", "Structlog"] },
              { layer: "TA Engine", items: ["RSI (Wilder, period 9/14/21)", "Bollinger Bands (SMA + 2σ)", "EMA (9 / 21 / 50)", "ATR (True Range avg)", "Fibonacci (0.618/1.272/1.618/2.618)", "S/R Swing Pivot Clustering"] },
              { layer: "Frontend", items: ["Next.js 16 (App Router)", "TypeScript", "Tailwind CSS v4", "Recharts (equity curve)", "Lightweight Charts (candles)", "Poppins font"] },
              { layer: "Infra / Data", items: ["Binance Futures REST API", "Docker Compose (local dev)", "TimescaleDB (klines)", "WatchFiles hot-reload", "Scheduler (asyncio loop)", "scan_store (in-memory cache)"] },
            ].map(s => (
              <div key={s.layer} className="bg-neutral-50 border border-neutral-200 rounded-xl p-3">
                <p className="font-bold text-neutral-700 mb-2 border-b border-neutral-200 pb-1">{s.layer}</p>
                <ul className="space-y-1">
                  {s.items.map(i => (
                    <li key={i} className="flex items-start gap-1 text-neutral-600">
                      <span className="text-teal-500 mt-0.5">·</span> {i}
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
