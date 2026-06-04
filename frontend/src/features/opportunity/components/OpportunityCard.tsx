"use client";
import { fmtPrice } from "@/lib/format";

export interface OpportunityResult {
  symbol:             string;
  current_price:      number;
  opportunity_score:  number;
  signals:            string[];
  alert_type:         string;
  change_24h:         number;
  change_1h:          number;
  vol_ratio:          number;
  bb_width_15m:       number | null;
  rsi_1h:             number | null;
  tfs_confirmed:      string[];
  squeeze_tfs:        string[];
}

const ALERT_COLORS: Record<string, string> = {
  squeeze:      "border-purple-500/40 bg-purple-950/20",
  accumulation: "border-teal-500/40 bg-teal-950/20",
  breakout:     "border-yellow-500/40 bg-yellow-950/20",
};

const ALERT_BADGES: Record<string, string> = {
  squeeze:      "bg-purple-600",
  accumulation: "bg-teal-600",
  breakout:     "bg-yellow-600",
};

const ALERT_LABELS: Record<string, string> = {
  squeeze:      "⚡ Squeeze",
  accumulation: "📦 Akumulasi",
  breakout:     "🎯 Breakout",
};

function scoreColor(s: number) {
  if (s >= 70) return "text-green-400";
  if (s >= 50) return "text-yellow-400";
  return "text-neutral-400";
}
function scoreBar(s: number) {
  if (s >= 70) return "bg-green-500";
  if (s >= 50) return "bg-yellow-500";
  return "bg-neutral-500";
}
function scoreBg(s: number) {
  if (s >= 70) return "border-green-500/30 bg-green-950/20";
  if (s >= 50) return "border-yellow-500/30 bg-yellow-950/20";
  return "border-neutral-700 bg-neutral-900/30";
}

export function OpportunityCard({ r }: { r: OpportunityResult }) {
  const base     = r.symbol.replace("USDT", "");
  const cardBg   = ALERT_COLORS[r.alert_type] ?? "border-neutral-800 bg-neutral-900/30";
  const badgeBg  = ALERT_BADGES[r.alert_type] ?? "bg-neutral-700";

  return (
    <div className={`rounded-xl p-3 border transition-all hover:brightness-110 ${cardBg}`}>
      {/* Header */}
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <div className="w-8 h-8 rounded-full bg-white/10 flex items-center justify-center text-[10px] font-black text-white flex-shrink-0">
            {base.slice(0, 4)}
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="font-bold text-sm text-white">{base}/USDT</span>
              <span className={`text-[10px] px-1.5 py-0.5 rounded font-bold text-white ${badgeBg}`}>
                {ALERT_LABELS[r.alert_type] ?? r.alert_type}
              </span>
            </div>
            <p className="text-xs font-mono text-neutral-400 mt-0.5">${fmtPrice(r.current_price)}</p>
          </div>
        </div>

        {/* Score */}
        <div className={`text-right flex-shrink-0 px-2.5 py-1.5 rounded-lg border ${scoreBg(r.opportunity_score)}`}>
          <p className={`text-xl font-black leading-tight ${scoreColor(r.opportunity_score)}`}>
            {r.opportunity_score.toFixed(0)}<span className="text-xs font-normal text-neutral-500">pt</span>
          </p>
          <p className="text-[9px] text-neutral-500">opportunity</p>
        </div>
      </div>

      {/* Score bar */}
      <div className="w-full bg-neutral-800 rounded-full h-1 mb-2">
        <div className={`h-full rounded-full ${scoreBar(r.opportunity_score)}`}
          style={{ width: `${r.opportunity_score}%` }} />
      </div>

      {/* Signals */}
      <div className="space-y-0.5 mb-2">
        {r.signals.map((s, i) => (
          <p key={i} className="text-[10px] text-neutral-300 leading-relaxed">{s}</p>
        ))}
      </div>

      {/* TF badges */}
      {r.squeeze_tfs.length > 0 && (
        <div className="flex gap-1 mb-2">
          {r.squeeze_tfs.map(tf => (
            <span key={tf} className="text-[9px] bg-purple-800/40 text-purple-300 px-1.5 py-0.5 rounded font-bold">
              SQUEEZE {tf}
            </span>
          ))}
        </div>
      )}

      {/* Stats row */}
      <div className="flex items-center justify-between text-[10px] text-neutral-400 pt-1.5 border-t border-neutral-700/50 flex-wrap gap-1">
        <div className="flex gap-2">
          <span className={r.change_24h >= 0 ? "text-green-400" : "text-red-400"}>
            {r.change_24h >= 0 ? "+" : ""}{r.change_24h}%
          </span>
          <span>Vol <strong className="text-neutral-300">{r.vol_ratio}x</strong></span>
          {r.rsi_1h !== null && (
            <span>RSI <strong className="text-neutral-300">{r.rsi_1h}</strong></span>
          )}
        </div>
        <div className="flex gap-1">
          {r.tfs_confirmed.map(tf => (
            <span key={tf} className="bg-neutral-800 px-1 rounded text-neutral-500">{tf}</span>
          ))}
        </div>
      </div>
    </div>
  );
}

export { ALERT_LABELS, ALERT_BADGES };
