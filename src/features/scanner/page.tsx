"use client";
import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { ScannerWidget } from "@/features/dashboard/components/ScannerWidget";

// ── 7 Early-Warning Signals ────────────────────────────────────────────────────
const SIGNALS = [
  {
    id: 1, icon: "🔵", name: "Bollinger Band Squeeze",
    tag: "squeeze", tagColor: "bg-purple-600/20 text-purple-300 border-purple-600/30",
    summary: "Volatilitas menyempit — energi terkumpul sebelum ekspansi besar",
    formula: `BB Width = (Upper − Lower) / Middle
Upper  = SMA(n) + 2σ
Lower  = SMA(n) − 2σ
σ      = Std Dev close n-period

Trigger per style:
  Scalping   → BB Width < 3%  (BB period 14)
  Day Trade  → BB Width < 4.5% (BB period 20)
  Swing      → BB Width < 6%  (BB period 20)
  Position   → BB Width < 8%  (BB period 30)`,
    logic: "Bollinger Band menyempit = volatilitas rendah = market sedang coiling. Secara historis, squeeze selalu diikuti ekspansi besar ke salah satu arah. Scanner mendeteksi ini SEBELUM breakout.",
    example: "XAUUSDT BB Width 0.5% (Scalping) → squeeze sangat kuat → breakout imminent",
  },
  {
    id: 2, icon: "📦", name: "Volume Accumulation",
    tag: "accumulation", tagColor: "bg-teal-600/20 text-teal-300 border-teal-600/30",
    summary: "Smart money beli diam-diam — volume naik tapi harga belum bergerak",
    formula: `Vol Slope  = (Vol[-1] − Vol[-5]) / Vol[-5]
Price Slope = (Close[-1] − Close[-5]) / Close[-5]
Vol Ratio   = Vol[-1] / Avg(Vol[-21:-1])

Trigger per style (Vol Slope minimum):
  Scalping  → Vol Slope > 20% AND |Price Slope| < 4%
  Day Trade → Vol Slope > 25%
  Swing     → Vol Slope > 30%
  Position  → Vol Slope > 40%

Hidden Strength: Vol Slope > min AND Price Slope < 0`,
    logic: "Volume naik signifikan tapi harga flat/turun = institusi/whale akumulasi diam-diam. Ini sinyal paling powerful karena demand tersembunyi selalu mendahului kenaikan harga.",
    example: "ETHUSDT vol +52% dalam 5 candle, harga +0.3% → smart money masuk",
  },
  {
    id: 3, icon: "🎯", name: "Near Breakout Zone",
    tag: "breakout", tagColor: "bg-yellow-600/20 text-yellow-300 border-yellow-600/30",
    summary: "Harga mendekati resistance/support kritis — satu candle dari breakout",
    formula: `Lookback per style:
  Scalping  → 10 candle terakhir
  Day Trade → 15 candle terakhir
  Swing     → 20 candle terakhir
  Position  → 50 candle terakhir

Recent High = Max(High[-lookback:])
Recent Low  = Min(Low[-lookback:])

Dist to High = (RecentHigh − Price) / Price
Dist to Low  = (Price − RecentLow) / Price

Breakout pct per style:
  Scalping  → < 1.5%
  Day Trade → < 2.0%
  Swing/Pos → < 2.5%`,
    logic: "Harga mendekati high/low historis = tekanan beli/jual akan terkonsentrasi. Breakout dari zona ini biasanya dilanjutkan momentum besar.",
    example: "OPUSDT harga $0.1263, resistance $0.1265 (1.58%) → Scalping trigger",
  },
  {
    id: 4, icon: "📊", name: "RSI Coiling Zone",
    tag: "reversal", tagColor: "bg-blue-600/20 text-blue-300 border-blue-600/30",
    summary: "RSI di zona energi — belum overbought, momentum masih ada ruang",
    formula: `RSI(n) = 100 − (100 / (1 + RS))
RS = Avg Gain(n) / Avg Loss(n)

Period per style:
  Scalping  → RSI(9)  — lebih responsif, sinyal cepat
  Day Trade → RSI(14) — standar
  Swing     → RSI(14) — standar
  Position  → RSI(21) — lebih smooth, kurangi noise

Scoring:
  RSI < 30          → +15 × w_rsi  (oversold reversal)
  RSI 30–50         → +12 × w_rsi  (energy building)
  RSI 50–65         → +8  × w_rsi  (momentum building)
  RSI > 75          → −10 × w_rsi  (extended)

Weight w_rsi:
  Scalping×2.0 | DayTrade×1.5 | Swing×1.0 | Position×0.8`,
    logic: "RSI di zona 30-65 adalah sweet spot: tidak overbought (masih ada ruang), tidak oversold ekstrem. Scalping butuh RSI cepat (9) untuk menangkap momentum singkat. Position pakai RSI lambat (21) untuk filter noise.",
    example: "Scalping RSI(9)=28 → oversold → bouncing dalam 1-3 candle 15m berikutnya",
  },
  {
    id: 5, icon: "⚡", name: "EMA Compression",
    tag: "squeeze", tagColor: "bg-purple-600/20 text-purple-300 border-purple-600/30",
    summary: "EMA 9 dan 21 berkonvergensi — arah besar akan terjadi",
    formula: `EMA(n) = Price × k + EMA_prev × (1−k)
        k = 2 / (n+1)

EMA Spread = |EMA9 − EMA21| / Price

Compression threshold per style:
  Scalping  → Spread < 0.3%
  Day Trade → Spread < 0.5%
  Swing     → Spread < 0.8%
  Position  → Spread < 0.8%

Alignment bonus:
  EMA9 > EMA21 > EMA50 → +8 × w_ema (bullish)
  EMA9 < EMA21 < EMA50 → +8 × w_ema (bearish)

Weight w_ema:
  Scalping×1.2 | DayTrade×1.3 | Swing×1.0 | Position×1.5`,
    logic: "EMA 9/21 berkonvergensi = short-term dan mid-term trend seimbang. Kondisi ini selalu diikuti breakout. Position trading bobot EMA lebih tinggi karena trend makro lebih penting.",
    example: "Swing: EMA9=$0.1262, EMA21=$0.1264, spread=0.16% → compressed → breakout",
  },
  {
    id: 6, icon: "🟢", name: "Buy/Sell Pressure Shift",
    tag: "accumulation", tagColor: "bg-teal-600/20 text-teal-300 border-teal-600/30",
    summary: "Pergeseran tekanan beli/jual — momentum mulai berubah arah",
    formula: `Bull Vol % = Σ(Vol dimana Close ≥ Open) / Σ(Vol total)

n = min(5, len/2)  [window adaptif]

BP Recent = BullVol%(candle[-n:])
BP Prior  = BullVol%(candle[-2n:-n])
Shift     = BP Recent − BP Prior

Trigger:
  Shift > +15% → Buy pressure rising  (+15 × w_pressure)
  Shift < −15% → Sell pressure rising (+12 × w_pressure)

Weight w_pressure:
  Scalping×1.8 | DayTrade×1.5 | Swing×1.2 | Position×1.0`,
    logic: "Menganalisis apakah candle bullish punya lebih banyak volume dari candle bearish. Pergeseran buy pressure mendahului kenaikan harga. Scalping sangat sensitif terhadap perubahan ini (×1.8).",
    example: "BP Prior=38%, BP Recent=57%, shift=+19% → Scalping trigger → entry LONG",
  },
  {
    id: 7, icon: "🕯", name: "Candle Body Shrink",
    tag: "squeeze", tagColor: "bg-purple-600/20 text-purple-300 border-purple-600/30",
    summary: "Candle makin kecil = indecision = kompresi sebelum ekspansi",
    formula: `Body[i] = |Close[i] − Open[i]|

Body Slope = (Body[-1] − Body[-6]) / Body[-6]

Trigger: Body Slope < −50%

Diterapkan pada: Scalping, Day Trade, Swing
(Position TIDAK dipakai — noise terlalu tinggi di 1D)

Weight w_candle:
  Scalping×1.5 | DayTrade×1.2 | Swing×0.8 | Position×0.5`,
    logic: "Candle body mengecil = buyer dan seller seimbang = stalemate. Kondisi ini selalu berakhir breakout explosif. Untuk Position trading, candle 1D memiliki noise besar sehingga sinyal ini dinonaktifkan.",
    example: "Scalping 15m: bodies $0.008→$0.006→$0.004→$0.002 → −75% slope → coiling",
  },
];

// ── Per-Style Configs ──────────────────────────────────────────────────────────
const STYLE_CONFIGS = [
  {
    key: "scalping", icon: "⚡", label: "Scalping", tf: "15m", duration: "Menit–Jam",
    color: "from-yellow-500/20 to-orange-500/20 border-yellow-500/30",
    badge: "bg-yellow-600/20 text-yellow-300",
    params: [
      ["Timeframe", "15m"],
      ["RSI Period", "9 (cepat, responsif)"],
      ["BB Period", "14"],
      ["Lookback H/L", "10 candle"],
      ["BB Squeeze", "< 3% width"],
      ["Vol Slope Min", "> 20%"],
      ["Pump Penalty", "> 5% sudah naik"],
      ["SL", "ATR × 1.0"],
      ["TP", "ATR × 2.5"],
      ["Min Score", "25 pts"],
    ],
    weights: "RSI×2.0 · Pressure×1.8 · Breakout×1.5 · Candle×1.5",
    focus: "Momentum cepat, RSI ekstrem, volume spike, breakout zone. Cocok untuk intraday trader yang buka-tutup posisi dalam jam.",
  },
  {
    key: "daytrading", icon: "📅", label: "Day Trade", tf: "1H", duration: "Harian",
    color: "from-blue-500/20 to-indigo-500/20 border-blue-500/30",
    badge: "bg-blue-600/20 text-blue-300",
    params: [
      ["Timeframe", "1H"],
      ["RSI Period", "14 (standar)"],
      ["BB Period", "20"],
      ["Lookback H/L", "15 candle"],
      ["BB Squeeze", "< 4.5% width"],
      ["Vol Slope Min", "> 25%"],
      ["Pump Penalty", "> 8% sudah naik"],
      ["SL", "ATR × 1.2"],
      ["TP", "ATR × 3.0"],
      ["Min Score", "28 pts"],
    ],
    weights: "RSI×1.5 · Pressure×1.5 · Breakout×1.3 · EMA×1.3",
    focus: "Balance antara momentum dan trend. Cocok untuk yang buka posisi pagi dan tutup sebelum malam.",
  },
  {
    key: "swing", icon: "🌊", label: "Swing", tf: "4H", duration: "Hari–Minggu",
    color: "from-teal-500/20 to-green-500/20 border-teal-500/30",
    badge: "bg-teal-600/20 text-teal-300",
    params: [
      ["Timeframe", "4H"],
      ["RSI Period", "14"],
      ["BB Period", "20"],
      ["Lookback H/L", "20 candle (3.3 hari)"],
      ["BB Squeeze", "< 6% width"],
      ["Vol Slope Min", "> 30%"],
      ["Pump Penalty", "> 12% sudah naik"],
      ["SL", "ATR × 1.5"],
      ["TP", "ATR × 4.5"],
      ["Min Score", "30 pts"],
    ],
    weights: "Accumulation×2.0 · Squeeze×1.8 · Breakout×1.5 · RSI×1.0",
    focus: "BB squeeze + akumulasi smart money + breakout zone. Cocok untuk trader yang hold 2–7 hari.",
  },
  {
    key: "position", icon: "🏔", label: "Position", tf: "1D", duration: "Minggu–Bulan",
    color: "from-purple-500/20 to-violet-500/20 border-purple-500/30",
    badge: "bg-purple-600/20 text-purple-300",
    params: [
      ["Timeframe", "1D"],
      ["RSI Period", "21 (smooth)"],
      ["BB Period", "30"],
      ["Lookback H/L", "50 candle (~7 minggu)"],
      ["BB Squeeze", "< 8% width"],
      ["Vol Slope Min", "> 40%"],
      ["Pump Penalty", "> 20% sudah naik"],
      ["SL", "ATR × 2.0"],
      ["TP", "ATR × 7.0"],
      ["Min Score", "35 pts"],
    ],
    weights: "Accumulation×2.5 · Squeeze×2.0 · EMA×1.5 · Breakout×1.8",
    focus: "Akumulasi panjang, trend makro weekly, S/R major. Cocok untuk yang hold minggu–bulan.",
  },
];

export default function ScannerPage() {
  const [expanded, setExpanded]   = useState<number | null>(null);
  const [activeTab, setActiveTab] = useState<"signals" | "styles">("styles");
  const [showDocs, setShowDocs]   = useState(true);

  return (
    <div className="space-y-6">
      {/* Header */}
      <Card className="bg-gradient-to-r from-neutral-900 to-neutral-800 text-white border-0">
        <CardContent className="pt-6 pb-5">
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <div className="flex items-center gap-3 mb-2">
                <span className="text-3xl">🔭</span>
                <h1 className="text-3xl font-bold">Early Breakout Scanner</h1>
              </div>
              <p className="text-sm opacity-70 max-w-2xl leading-relaxed">
                Deteksi koin yang <strong className="text-teal-300">akan naik/turun</strong> sebelum pergerakan besar terjadi.
                Setiap trading style memiliki <strong className="text-yellow-300">parameter, rumus, dan bobot sinyal berbeda</strong> yang disesuaikan dengan karakteristik timeframe-nya.
              </p>
            </div>
            <button onClick={() => setShowDocs(v => !v)}
              className="flex-shrink-0 text-xs bg-white/10 hover:bg-white/20 px-3 py-2 rounded-lg transition-colors">
              {showDocs ? "▲ Sembunyikan" : "▼ Lihat"} Arsitektur
            </button>
          </div>
        </CardContent>
      </Card>

      {/* Docs section */}
      {showDocs && (
        <div className="space-y-4">

          {/* Tab switcher */}
          <div className="flex items-center gap-3">
            <div className="flex bg-white border rounded-xl p-1 gap-1">
              <button onClick={() => setActiveTab("styles")}
                className={`px-4 py-1.5 rounded-lg text-sm font-semibold transition-colors ${
                  activeTab === "styles" ? "bg-neutral-900 text-white" : "text-neutral-500 hover:text-black"
                }`}>
                🎯 Config per Trading Style
              </button>
              <button onClick={() => setActiveTab("signals")}
                className={`px-4 py-1.5 rounded-lg text-sm font-semibold transition-colors ${
                  activeTab === "signals" ? "bg-neutral-900 text-white" : "text-neutral-500 hover:text-black"
                }`}>
                📐 7 Early-Warning Signals
              </button>
            </div>
            <div className="flex-1 h-px bg-neutral-200" />
          </div>

          {/* ── Tab: Style Configs ─────────────────────────────────────────── */}
          {activeTab === "styles" && (
            <div className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
                {STYLE_CONFIGS.map(s => (
                  <div key={s.key}
                    className={`rounded-xl border bg-gradient-to-b p-4 ${s.color}`}>
                    {/* Header */}
                    <div className="flex items-center gap-2 mb-3">
                      <span className="text-2xl">{s.icon}</span>
                      <div>
                        <p className="font-bold text-sm">{s.label}</p>
                        <p className="text-[10px] text-muted-foreground">{s.tf} · {s.duration}</p>
                      </div>
                    </div>

                    {/* Params table */}
                    <div className="space-y-1 mb-3">
                      {s.params.map(([k, v]) => (
                        <div key={k} className="flex justify-between text-[11px]">
                          <span className="text-neutral-500">{k}</span>
                          <span className="font-mono font-semibold text-neutral-800 text-right max-w-[55%]">{v}</span>
                        </div>
                      ))}
                    </div>

                    {/* Weights */}
                    <div className={`rounded-lg px-2.5 py-2 mb-2 ${s.badge} bg-opacity-30`}>
                      <p className="text-[9px] font-bold uppercase tracking-wider mb-1 opacity-70">Bobot Sinyal Aktif</p>
                      <p className="text-[10px] font-mono leading-relaxed">{s.weights}</p>
                    </div>

                    {/* Focus */}
                    <p className="text-[10px] text-neutral-600 leading-relaxed">{s.focus}</p>
                  </div>
                ))}
              </div>

              {/* Scoring system */}
              <div className="bg-neutral-900 text-white rounded-xl p-5">
                <p className="text-sm font-bold text-teal-400 mb-4">⚙️ Cara Hitung Probability Score</p>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-6 text-xs font-mono">
                  <div>
                    <p className="text-neutral-400 font-bold mb-2 font-sans">Base points (×bobot style):</p>
                    <div className="space-y-1">
                      <p><span className="text-purple-400">BB Squeeze &lt;threshold</span> → 25 pts</p>
                      <p><span className="text-purple-400">BB tightening</span>          → 12 pts</p>
                      <p><span className="text-teal-400">Akumulasi (flat price)</span>   → 22 pts</p>
                      <p><span className="text-teal-400">Hidden strength</span>          → 18 pts</p>
                      <p><span className="text-teal-400">Vol spike flat</span>           → 10 pts</p>
                    </div>
                  </div>
                  <div>
                    <p className="text-neutral-400 font-bold mb-2 font-sans">Lanjutan:</p>
                    <div className="space-y-1">
                      <p><span className="text-yellow-400">Near breakout</span>          → 20 pts</p>
                      <p><span className="text-yellow-400">Near reversal</span>          → 15 pts</p>
                      <p><span className="text-blue-400">RSI oversold &lt;30</span>        → 15 pts</p>
                      <p><span className="text-blue-400">RSI 30–50</span>                → 12 pts</p>
                      <p><span className="text-blue-400">RSI 50–65</span>                →  8 pts</p>
                      <p><span className="text-blue-400">RSI &gt;75</span>                 → −10 pts</p>
                    </div>
                  </div>
                  <div>
                    <p className="text-neutral-400 font-bold mb-2 font-sans">Lanjutan:</p>
                    <div className="space-y-1">
                      <p><span className="text-green-400">EMA compression</span>         → 15 pts</p>
                      <p><span className="text-green-400">EMA alignment</span>           →  8 pts</p>
                      <p><span className="text-green-400">Buy pressure +15%</span>       → 15 pts</p>
                      <p><span className="text-red-400">Candle shrink −50%</span>        → 10 pts</p>
                      <p><span className="text-red-400">Sudah pump (style×)</span>       → −8 to −20</p>
                      <p className="pt-1 text-neutral-500">Score final = Σ(pts × w_signal)</p>
                    </div>
                  </div>
                </div>
                <div className="mt-4 pt-3 border-t border-neutral-700 grid grid-cols-3 gap-3 text-[11px]">
                  <div className="text-center">
                    <p className="text-green-400 font-bold text-base">≥ 70</p>
                    <p className="text-neutral-400">Setup sangat kuat</p>
                    <p className="text-neutral-500 text-[10px]">Multiple signal confirm</p>
                  </div>
                  <div className="text-center">
                    <p className="text-yellow-400 font-bold text-base">50–69</p>
                    <p className="text-neutral-400">Setup bagus</p>
                    <p className="text-neutral-500 text-[10px]">Monitor lebih lanjut</p>
                  </div>
                  <div className="text-center">
                    <p className="text-neutral-400 font-bold text-base">&lt; 50</p>
                    <p className="text-neutral-400">Early stage</p>
                    <p className="text-neutral-500 text-[10px]">Belum cukup konfirmasi</p>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ── Tab: 7 Signals ────────────────────────────────────────────── */}
          {activeTab === "signals" && (
            <div className="space-y-3">
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                {SIGNALS.map((sig) => (
                  <div key={sig.id} className="bg-white border rounded-xl overflow-hidden shadow-sm hover:shadow-md transition-shadow">
                    <button className="w-full text-left p-4 flex items-start gap-3"
                      onClick={() => setExpanded(expanded === sig.id ? null : sig.id)}>
                      <span className="text-2xl flex-shrink-0 mt-0.5">{sig.icon}</span>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 flex-wrap mb-1">
                          <span className="font-bold text-sm">{sig.id}. {sig.name}</span>
                          <span className={`text-[10px] px-2 py-0.5 rounded-full border font-semibold ${sig.tagColor}`}>
                            {sig.tag}
                          </span>
                        </div>
                        <p className="text-xs text-muted-foreground leading-relaxed">{sig.summary}</p>
                      </div>
                      <span className="text-neutral-400 text-sm flex-shrink-0 mt-1">
                        {expanded === sig.id ? "▲" : "▼"}
                      </span>
                    </button>
                    {expanded === sig.id && (
                      <div className="border-t bg-neutral-50 p-4 space-y-3">
                        <div>
                          <p className="text-[10px] font-bold uppercase tracking-wider text-neutral-500 mb-1.5">📐 Formula</p>
                          <pre className="text-[11px] font-mono bg-neutral-900 text-green-400 p-3 rounded-lg overflow-x-auto leading-relaxed whitespace-pre-wrap">
                            {sig.formula}
                          </pre>
                        </div>
                        <div>
                          <p className="text-[10px] font-bold uppercase tracking-wider text-neutral-500 mb-1.5">💡 Kenapa works?</p>
                          <p className="text-xs text-neutral-700 leading-relaxed">{sig.logic}</p>
                        </div>
                        <div className="bg-teal-50 border border-teal-200 rounded-lg p-3">
                          <p className="text-[10px] font-bold uppercase tracking-wider text-teal-600 mb-1">📌 Contoh Real</p>
                          <p className="text-xs text-teal-800 font-mono">{sig.example}</p>
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Scanner results */}
      <ScannerWidget fullPage />
    </div>
  );
}
