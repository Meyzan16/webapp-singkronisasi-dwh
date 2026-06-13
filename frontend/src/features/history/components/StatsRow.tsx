"use client";
import type { OppStats } from "./OppSpotTypes";

interface StatsRowProps {
  stats: Pick<OppStats, "total" | "open" | "tp" | "sl" | "manual" | "winRate" | "avgPnl">;
}

export function StatsRow({ stats }: StatsRowProps) {
  const cards = [
    { label: "Total",     value: String(stats.total),  color: "text-neutral-800" },
    { label: "🔵 Open",   value: String(stats.open),   color: "text-blue-600"    },
    { label: "✅ TP Hit", value: String(stats.tp),     color: "text-green-600"   },
    { label: "🛑 SL Hit", value: String(stats.sl),     color: "text-red-500"     },
    {
      label: "Win Rate",
      value: (stats.tp + stats.sl) > 0 ? `${stats.winRate.toFixed(0)}%` : "—",
      color: stats.winRate >= 50
        ? "text-green-600"
        : stats.winRate > 0 ? "text-red-500" : "text-neutral-400",
    },
    {
      label: "Avg P&L",
      value: stats.avgPnl !== 0
        ? `${stats.avgPnl >= 0 ? "+" : ""}${stats.avgPnl.toFixed(1)}%`
        : "—",
      color: stats.avgPnl > 0
        ? "text-green-600"
        : stats.avgPnl < 0 ? "text-red-500" : "text-neutral-400",
    },
  ];

  return (
    <>
      <div className="grid grid-cols-3 md:grid-cols-6 gap-3">
        {cards.map(s => (
          <div key={s.label} className="bg-white border border-neutral-200 rounded-2xl p-4 text-center">
            <p className="text-[10px] text-neutral-400 font-semibold uppercase tracking-wide mb-1">
              {s.label}
            </p>
            <p className={`text-2xl font-black ${s.color}`}>{s.value}</p>
          </div>
        ))}
      </div>
      {stats.manual > 0 && (
        <p className="text-[11px] text-neutral-400 text-center -mt-2">
          + {stats.manual} tutup manual (tidak masuk Win Rate — Win Rate hanya dari TP+SL)
        </p>
      )}
    </>
  );
}
