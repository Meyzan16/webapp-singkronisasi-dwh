"use client";
import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { ScannerWidget } from "@/features/dashboard/components/ScannerWidget";

const SIGNALS = [
  {
    id: 1,
    icon: "🔵",
    name: "Bollinger Band Squeeze",
    tag: "squeeze",
    tagColor: "bg-purple-600/20 text-purple-300 border-purple-600/30",
    summary: "Volatilitas menyempit — energi terkumpul sebelum ekspansi besar",
    formula: "BB Width = (Upper − Lower) / Middle\nUpper = SMA20 + 2σ\nLower = SMA20 − 2σ\nσ = Std Dev close 20 period\n\nTrigger: BB Width < 4% → Squeeze aktif",
    logic: "Ketika Bollinger Band menyempit, harga bergerak dalam range sempit = volatilitas rendah. Secara historis, periode volatilitas rendah selalu diikuti oleh pergerakan besar (ekspansi). Scanner mendeteksi ini SEBELUM breakout terjadi.",
    example: "BB Width 2.6% → squeeze kuat → breakout dalam 1-3 candle berikutnya",
  },
  {
    id: 2,
    icon: "📦",
    name: "Volume Accumulation",
    tag: "accumulation",
    tagColor: "bg-teal-600/20 text-teal-300 border-teal-600/30",
    summary: "Smart money beli diam-diam — volume naik tapi harga belum bergerak",
    formula: "Vol Slope = (Vol[-1] − Vol[-5]) / Vol[-5]\nPrice Slope = (Close[-1] − Close[-5]) / Close[-5]\nVol Ratio = Vol[-1] / Avg(Vol[-21:-1])\n\nTrigger:\n  Vol Slope > 30% AND |Price Slope| < 5% → Akumulasi\n  Vol Slope > 15% AND Price Slope < 0 → Hidden strength",
    logic: "Ketika volume naik signifikan tapi harga flat atau bahkan turun, itu indikasi institusi/whale sedang mengakumulasi posisi tanpa menggerakkan harga. Ini adalah setup paling powerful karena menandakan demand tersembunyi.",
    example: "Vol +45% dalam 5 candle, harga bergerak <2% → smart money akumulasi",
  },
  {
    id: 3,
    icon: "🎯",
    name: "Near Breakout Zone",
    tag: "breakout",
    tagColor: "bg-yellow-600/20 text-yellow-300 border-yellow-600/30",
    summary: "Harga mendekati resistance/support kritis — breakout zone",
    formula: "Recent High = Max(High[-20:])\nRecent Low  = Min(Low[-20:])\n\nDist to High = (RecentHigh − Price) / Price\nDist to Low  = (Price − RecentLow) / Price\n\nTrigger:\n  Dist to High < 2% → Near breakout\n  Dist to Low  < 2% → Near reversal",
    logic: "Harga yang mendekati level high/low 20 periode memiliki probabilitas tinggi untuk breakout atau bounce. Dikombinasikan dengan volume dan squeeze, ini menjadi zona entry yang kuat.",
    example: "Harga $0.1263, resistance $0.1265 (jarak 0.16%) → siap breakout",
  },
  {
    id: 4,
    icon: "📊",
    name: "RSI Coiling Zone",
    tag: "reversal",
    tagColor: "bg-blue-600/20 text-blue-300 border-blue-600/30",
    summary: "RSI di zona netral-bullish — energi belum habis, masih ada ruang naik",
    formula: "RSI(14) = 100 − (100 / (1 + RS))\nRS = Avg Gain(14) / Avg Loss(14)\n\nZona:\n  RSI 35–50 → Building energy (+12 poin)\n  RSI 50–65 → Momentum building (+8 poin)\n  RSI < 30  → Oversold reversal (+15 poin)\n  RSI > 75  → Extended, penalty (−10 poin)",
    logic: "RSI di zona 35-65 adalah sweet spot: tidak overbought (tidak terlambat masuk), tidak oversold ekstrem (belum bottomed). Ini zona di mana harga 'mengisi ulang energi' sebelum lanjut. RSI <30 menandakan reversal imminent.",
    example: "RSI 46 → zona coiling → potensi naik kembali ke 60+ tanpa resistensi besar",
  },
  {
    id: 5,
    icon: "⚡",
    name: "EMA Compression",
    tag: "squeeze",
    tagColor: "bg-purple-600/20 text-purple-300 border-purple-600/30",
    summary: "EMA 9 dan 21 sangat berdekatan — arah besar akan terjadi",
    formula: "EMA(n) = Price × k + EMA_prev × (1−k)\n        k = 2/(n+1)\n\nEMA Spread = |EMA9 − EMA21| / Price\n\nTrigger:\n  Spread < 0.5% → Kompresi kuat (+15 poin)\n  EMA9 > EMA21 > EMA50 → Bullish alignment (+8 poin)\n  EMA9 < EMA21 < EMA50 → Bearish alignment (+8 poin)",
    logic: "Ketika EMA 9 dan 21 berkonvergensi, itu menandakan bahwa trend jangka pendek dan menengah sedang dalam keseimbangan — tidak ada yang dominan. Kondisi ini selalu diikuti oleh breakout ke salah satu arah. EMA alignment 9>21>50 = bullish momentum building.",
    example: "EMA9=$0.1262, EMA21=$0.1264, spread=0.16% → kompresi → breakout imminent",
  },
  {
    id: 6,
    icon: "🟢",
    name: "Buy Pressure Shift",
    tag: "accumulation",
    tagColor: "bg-teal-600/20 text-teal-300 border-teal-600/30",
    summary: "Tekanan beli meningkat di 5 candle terakhir vs 5 candle sebelumnya",
    formula: "Bull Vol % = Σ(Vol where Close≥Open) / Σ(Vol total)\n\nBP Recent = BullVol%(candle[-5:])\nBP Prior  = BullVol%(candle[-10:-5])\n\nTrigger:\n  BP Recent > BP Prior + 15% → Buy pressure rising (+15 poin)\n  BP Recent < BP Prior − 15% → Sell pressure rising (+10 poin SHORT)",
    logic: "Menganalisis apakah candle-candle bullish memiliki volume lebih besar dari candle bearish. Jika terjadi pergeseran ke bullish di 5 candle terakhir, itu menandakan perubahan momentum yang biasanya mendahului kenaikan harga.",
    example: "BP Prior=38%, BP Recent=55% → shift +17% → buying interest meningkat",
  },
  {
    id: 7,
    icon: "🕯",
    name: "Candle Body Shrink",
    tag: "squeeze",
    tagColor: "bg-purple-600/20 text-purple-300 border-purple-600/30",
    summary: "Candle makin kecil = indecision = kompresi sebelum pergerakan besar",
    formula: "Body[i] = |Close[i] − Open[i]|\n\nBody Slope = (Body[-1] − Body[-6]) / Body[-6]\n\nTrigger:\n  Body Slope < −50% → Bodies shrinking significantly (+10 poin)",
    logic: "Candle body yang mengecil menandakan buyer dan seller seimbang — tidak ada yang mau bergerak. Kondisi stalemate ini biasanya berakhir dengan breakout explosif. Dikombinasikan dengan BB squeeze, ini adalah signal konfirmasi yang kuat.",
    example: "Body 6 candle lalu: $0.008, $0.006, $0.004, $0.003, $0.002, $0.001 → kompresi 87%",
  },
];

export default function ScannerPage() {
  const [expanded, setExpanded] = useState<number | null>(null);
  const [showDocs, setShowDocs] = useState(true);

  return (
    <div className="space-y-6">
      {/* Header */}
      <Card className="bg-gradient-to-r from-neutral-900 to-neutral-800 text-white border-0">
        <CardContent className="pt-6 pb-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-3 mb-2">
                <span className="text-3xl">🔭</span>
                <h1 className="text-3xl font-bold">Early Breakout Scanner</h1>
              </div>
              <p className="text-sm opacity-70 max-w-2xl">
                Deteksi koin yang <strong className="text-teal-300">akan naik</strong> sebelum kenaikan besar terjadi.
                Scanner menggunakan 7 early-warning signals berbasis matematika — bukan setelah pump, tapi <em>sebelum</em>.
              </p>
            </div>
            <button
              onClick={() => setShowDocs(v => !v)}
              className="flex-shrink-0 text-xs bg-white/10 hover:bg-white/20 px-3 py-2 rounded-lg transition-colors whitespace-nowrap">
              {showDocs ? "▲ Sembunyikan" : "▼ Lihat"} Arsitektur
            </button>
          </div>
        </CardContent>
      </Card>

      {/* Architecture & Formula Docs */}
      {showDocs && (
        <div className="space-y-3">
          {/* Section title */}
          <div className="flex items-center gap-3">
            <div className="flex-1 h-px bg-neutral-200" />
            <span className="text-xs font-bold text-muted-foreground uppercase tracking-widest px-2">
              📐 Arsitektur & Rumus — 7 Early-Warning Signals
            </span>
            <div className="flex-1 h-px bg-neutral-200" />
          </div>

          {/* Signal cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
            {SIGNALS.map((sig) => (
              <div
                key={sig.id}
                className="bg-white border rounded-xl overflow-hidden shadow-sm hover:shadow-md transition-shadow">
                {/* Card header */}
                <button
                  className="w-full text-left p-4 flex items-start gap-3"
                  onClick={() => setExpanded(expanded === sig.id ? null : sig.id)}>
                  <span className="text-2xl flex-shrink-0 mt-0.5">{sig.icon}</span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap mb-1">
                      <span className="font-bold text-sm text-neutral-900">
                        {sig.id}. {sig.name}
                      </span>
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

                {/* Expanded detail */}
                {expanded === sig.id && (
                  <div className="border-t bg-neutral-50 p-4 space-y-3">
                    {/* Formula */}
                    <div>
                      <p className="text-[10px] font-bold uppercase tracking-wider text-neutral-500 mb-1.5">
                        📐 Formula
                      </p>
                      <pre className="text-[11px] font-mono bg-neutral-900 text-green-400 p-3 rounded-lg overflow-x-auto leading-relaxed whitespace-pre-wrap">
                        {sig.formula}
                      </pre>
                    </div>
                    {/* Logic */}
                    <div>
                      <p className="text-[10px] font-bold uppercase tracking-wider text-neutral-500 mb-1.5">
                        💡 Kenapa ini works?
                      </p>
                      <p className="text-xs text-neutral-700 leading-relaxed">{sig.logic}</p>
                    </div>
                    {/* Example */}
                    <div className="bg-teal-50 border border-teal-200 rounded-lg p-3">
                      <p className="text-[10px] font-bold uppercase tracking-wider text-teal-600 mb-1">
                        📌 Contoh Real
                      </p>
                      <p className="text-xs text-teal-800 font-mono">{sig.example}</p>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* Scoring summary */}
          <div className="bg-neutral-900 text-white rounded-xl p-5">
            <p className="text-sm font-bold mb-3 text-teal-400">⚙️ Sistem Scoring — Probability Calculation</p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs font-mono">
              <div className="space-y-1.5">
                <p className="text-neutral-400 font-semibold mb-2">Poin per signal:</p>
                <p><span className="text-purple-400">BB Squeeze &lt;4%</span>    → +25 pts</p>
                <p><span className="text-purple-400">BB Squeeze &lt;7%</span>    → +12 pts</p>
                <p><span className="text-teal-400">Vol Accum (flat)</span>  → +22 pts</p>
                <p><span className="text-teal-400">Hidden strength</span>   → +18 pts</p>
                <p><span className="text-yellow-400">Near breakout</span>     → +20 pts</p>
                <p><span className="text-yellow-400">Near reversal</span>     → +15 pts</p>
              </div>
              <div className="space-y-1.5">
                <p className="text-neutral-400 font-semibold mb-2">Lanjutan:</p>
                <p><span className="text-blue-400">RSI 35-50</span>         → +12 pts</p>
                <p><span className="text-blue-400">RSI &lt;30 oversold</span>  → +15 pts</p>
                <p><span className="text-blue-400">RSI &gt;75</span>           → −10 pts</p>
                <p><span className="text-green-400">EMA compression</span>   → +15 pts</p>
                <p><span className="text-green-400">Buy pressure shift</span> → +15 pts</p>
                <p><span className="text-red-400">Already pumped &gt;20%</span> → −20 pts</p>
              </div>
            </div>
            <div className="mt-4 pt-3 border-t border-neutral-700 text-[11px] text-neutral-400 space-y-1">
              <p><span className="text-green-400 font-bold">Prob ≥ 70%</span> — Setup sangat kuat, beberapa signal confirm</p>
              <p><span className="text-yellow-400 font-bold">Prob 50–70%</span> — Setup bagus, monitor lebih lanjut</p>
              <p><span className="text-neutral-400 font-bold">Prob &lt; 50%</span> — Early stage, belum cukup konfirmasi</p>
              <p className="pt-1 text-neutral-500">Minimum threshold: 30 poin + minimal 2 signal aktif untuk masuk hasil</p>
            </div>
          </div>
        </div>
      )}

      {/* Scanner results */}
      <ScannerWidget fullPage />
    </div>
  );
}
