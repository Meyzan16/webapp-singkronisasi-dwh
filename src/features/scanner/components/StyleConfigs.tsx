import { STYLE_CONFIGS } from "../data/styles";

export function StyleConfigs() {
  return (
    <div className="space-y-4">
      {/* Style cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        {STYLE_CONFIGS.map(s => (
          <div key={s.key} className={`rounded-xl border bg-gradient-to-b p-4 ${s.color}`}>
            <div className="flex items-center gap-2 mb-3">
              <span className="text-2xl">{s.icon}</span>
              <div>
                <p className="font-bold text-sm">{s.label}</p>
                <p className="text-[10px] text-muted-foreground">{s.tf} · {s.duration}</p>
              </div>
            </div>

            <div className="space-y-1 mb-3">
              {s.params.map(([k, v]) => (
                <div key={k} className="flex justify-between text-[11px]">
                  <span className="text-neutral-500">{k}</span>
                  <span className="font-mono font-semibold text-neutral-800 text-right max-w-[55%]">{v}</span>
                </div>
              ))}
            </div>

            <div className={`rounded-lg px-2.5 py-2 mb-2 ${s.badge} bg-opacity-30`}>
              <p className="text-[9px] font-bold uppercase tracking-wider mb-1 opacity-70">Bobot Sinyal Aktif</p>
              <p className="text-[10px] font-mono leading-relaxed">{s.weights}</p>
            </div>

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
              <p><span className="text-red-400">Sell pressure −15%</span>        → 12 pts</p>
              <p><span className="text-red-400">Candle shrink −50%</span>        → 10 pts</p>
              <p><span className="text-red-400">Sudah pump (style×)</span>       → −8 to −20</p>
              <p className="pt-1 text-neutral-500">Score final = Σ(pts × w_signal)</p>
            </div>
          </div>
        </div>

        {/* Min SL + Min RR table */}
        <div className="mt-3 pt-3 border-t border-neutral-700">
          <p className="text-xs text-teal-400 font-bold mb-2">📐 Filter Akhir — Min SL jarak & Min R:R per Style</p>
          <div className="grid grid-cols-4 gap-2 text-[11px] font-mono">
            {[
              { style: "⚡ Scalping",  minSL: "≥ 0.8%", minRR: "≥ 1:3", entry: "Support 15m" },
              { style: "📅 Day Trade", minSL: "≥ 1.2%", minRR: "≥ 1:3", entry: "Support 1H"  },
              { style: "🌊 Swing",     minSL: "≥ 2.0%", minRR: "≥ 1:3", entry: "Support 4H"  },
              { style: "🏔 Position",  minSL: "≥ 3.0%", minRR: "≥ 1:3", entry: "Support 1D"  },
            ].map(s => (
              <div key={s.style} className="bg-neutral-800 rounded-lg p-2 space-y-1">
                <p className="font-bold text-neutral-200">{s.style}</p>
                <p className="text-red-400">SL min {s.minSL}</p>
                <p className="text-green-400">R:R {s.minRR}</p>
                <p className="text-yellow-400">Entry: {s.entry}</p>
              </div>
            ))}
          </div>
        </div>

        {/* Score legend */}
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
  );
}
