"use client";
import type { AlertStat } from "./OppSpotTypes";

interface AlertTypeStatsProps {
  alertStats: AlertStat[];
  totalClosed: number;
}

const ALERT_META: Record<string, { emoji: string; color: string; bg: string }> = {
  squeeze:      { emoji: "⚡", color: "text-purple-700", bg: "bg-purple-50 border-purple-200" },
  accumulation: { emoji: "📦", color: "text-teal-700",   bg: "bg-teal-50 border-teal-200"   },
  breakout:     { emoji: "🎯", color: "text-amber-700",  bg: "bg-amber-50 border-amber-200" },
};

export function AlertTypeStats({ alertStats, totalClosed }: AlertTypeStatsProps) {
  if (totalClosed === 0) return null;

  return (
    <div className="bg-white border border-neutral-200 rounded-2xl p-4">
      <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider mb-3">
        📊 Win Rate per Tipe Sinyal
      </p>
      <div className="grid grid-cols-3 gap-3">
        {alertStats.map(a => {
          const m = ALERT_META[a.type] ?? ALERT_META.squeeze;
          return (
            <div key={a.type} className={`rounded-xl p-3 border ${m.bg}`}>
              <p className={`text-xs font-bold ${m.color} capitalize mb-1`}>
                {m.emoji} {a.type}
              </p>
              {a.total > 0 ? (
                <>
                  <p className={`text-xl font-black ${a.winRate >= 50 ? "text-green-600" : "text-red-500"}`}>
                    {a.winRate.toFixed(0)}%
                  </p>
                  <p className="text-[10px] text-neutral-400">{a.wins}/{a.total} trades</p>
                  <p className={`text-[10px] font-semibold ${a.avgPnl >= 0 ? "text-green-500" : "text-red-400"}`}>
                    avg {a.avgPnl >= 0 ? "+" : ""}{a.avgPnl.toFixed(1)}%
                  </p>
                </>
              ) : (
                <p className="text-xs text-neutral-300 mt-1">Belum ada data</p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
