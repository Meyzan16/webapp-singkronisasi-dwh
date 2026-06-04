import { Badge } from "@/components/ui/badge";
import { fmtPrice } from "@/lib/format";
import type { ScanSignal } from "@/types/scanner";

const ALERT_COLORS: Record<string, string> = {
  squeeze:      "border-purple-500/40 bg-purple-950/20",
  accumulation: "border-teal-500/40 bg-teal-950/20",
  breakout:     "border-yellow-500/40 bg-yellow-950/20",
  reversal:     "border-blue-500/40 bg-blue-950/20",
};

const ALERT_BADGES: Record<string, string> = {
  squeeze:      "bg-purple-600",
  accumulation: "bg-teal-600",
  breakout:     "bg-yellow-600",
  reversal:     "bg-blue-600",
};

const ALERT_LABELS: Record<string, string> = {
  squeeze:      "⚡ Squeeze",
  accumulation: "📦 Accum",
  breakout:     "🎯 Breakout",
  reversal:     "↩ Reversal",
};

const probColor = (p: number) => p >= 70 ? "text-green-400" : p >= 50 ? "text-yellow-400" : "text-neutral-400";
const probBar   = (p: number) => p >= 70 ? "bg-green-500"   : p >= 50 ? "bg-yellow-500"   : "bg-neutral-500";

interface SignalCardProps { signal: ScanSignal; }

export function SignalCard({ signal: r }: SignalCardProps) {
  const base    = r.symbol.replace("USDT", "");
  const isLong  = r.direction === "LONG";
  const cardBg  = ALERT_COLORS[r.alert_type]  ?? "border-neutral-800 bg-neutral-900/30";
  const badgeBg = ALERT_BADGES[r.alert_type] ?? "bg-neutral-700";

  return (
    <div className={`rounded-xl p-3 border transition-all hover:brightness-110 ${cardBg}`}>
      {/* Header */}
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <div className={`w-8 h-8 rounded-full flex items-center justify-center text-[10px] font-black flex-shrink-0 ${
            isLong ? "bg-green-500/20 text-green-400" : "bg-red-500/20 text-red-400"
          }`}>
            {base.slice(0, 4)}
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="font-bold text-sm text-white">{base}/USDT</span>
              <Badge className={`text-[10px] px-1.5 py-0 font-bold ${isLong ? "bg-green-600" : "bg-red-600"}`}>
                {isLong ? "▲ LONG" : "▼ SHORT"}
              </Badge>
              <Badge className={`text-[10px] px-1.5 py-0 ${badgeBg}`}>
                {ALERT_LABELS[r.alert_type]}
              </Badge>
            </div>
            <p className="text-xs font-mono text-neutral-400 mt-0.5">${fmtPrice(r.current_price)}</p>
          </div>
        </div>
        <div className="text-right flex-shrink-0">
          <p className={`text-xl font-black leading-tight ${probColor(r.probability)}`}>
            {r.probability.toFixed(0)}<span className="text-xs font-normal text-neutral-500">%</span>
          </p>
          <p className="text-[10px] text-neutral-500">probability</p>
        </div>
      </div>

      {/* Probability bar */}
      <div className="w-full bg-neutral-800 rounded-full h-1 mb-2">
        <div className={`h-full rounded-full transition-all ${probBar(r.probability)}`}
          style={{ width: `${r.probability}%` }} />
      </div>

      {/* Signals */}
      <div className="space-y-0.5 mb-2">
        {r.signals.map((s, i) => (
          <p key={i} className="text-[10px] text-neutral-300 leading-relaxed">{s}</p>
        ))}
      </div>

      {/* Entry note */}
      {r.entry_note && (
        <div className={`rounded-lg px-2.5 py-1.5 mb-1.5 text-[10px] leading-relaxed ${
          r.entry_type === "at_zone" ? "bg-green-900/40 text-green-300" : "bg-amber-900/30 text-amber-300"
        }`}>
          {r.entry_note}
        </div>
      )}

      {/* Entry / SL / TP */}
      <div className="grid grid-cols-3 gap-1.5 mb-2">
        <div className={`rounded-lg px-2 py-1.5 ${
          r.entry_type === "at_zone" ? "bg-green-900/40" : "bg-amber-900/30"
        }`}>
          <p className="text-[9px] text-neutral-400 font-bold uppercase mb-0.5">
            {r.entry_type === "at_zone" ? "✅ Entry" : "⏳ Limit"}
          </p>
          <p className="text-xs font-bold text-white font-mono">${fmtPrice(r.entry)}</p>
          {r.entry_zone_low && (
            <p className="text-[9px] text-neutral-500">
              {fmtPrice(r.entry_zone_low)}–{fmtPrice(r.entry_zone_high!)}
            </p>
          )}
        </div>
        <div className="bg-black/20 rounded-lg px-2 py-1.5">
          <p className="text-[9px] text-red-400 font-bold uppercase mb-0.5">⛔ SL</p>
          <p className="text-xs font-bold text-red-300 font-mono">${fmtPrice(r.stop_loss)}</p>
          <p className="text-[9px] text-neutral-500 truncate">{r.sl_method.split("(")[0]}</p>
        </div>
        <div className="bg-black/20 rounded-lg px-2 py-1.5">
          <p className="text-[9px] text-green-400 font-bold uppercase mb-0.5">🎯 TP</p>
          <p className="text-xs font-bold text-green-300 font-mono">${fmtPrice(r.take_profit)}</p>
          <p className="text-[9px] text-neutral-500 truncate">{r.tp_method.split("$")[0]}</p>
        </div>
      </div>

      {/* Stats row */}
      <div className="flex items-center justify-between text-[10px] text-neutral-400 pt-1.5 border-t border-neutral-700/50">
        <div className="flex gap-2">
          <span className={r.change_24h >= 0 ? "text-green-400" : "text-red-400"}>
            {r.change_24h >= 0 ? "+" : ""}{r.change_24h}%
          </span>
          <span>Vol <strong className="text-neutral-300">{r.volume_ratio}x</strong></span>
        </div>
        <span className="text-teal-400 font-bold text-sm">{r.risk_reward}</span>
      </div>
    </div>
  );
}

export { ALERT_BADGES, ALERT_LABELS };
