"use client";
import { LANES } from "@/lib/lanes";

// PLAN_v9 G1a — performa per LANE, dinamis dari data aktual (bukan 3-tipe hardcode).
// Ini memperbaiki bug lama di mana trade BigMover & Early Radar tak pernah muncul.
export interface LaneStat {
  key:     string;
  label:   string;
  emoji:   string;
  total:   number;   // trade selesai (tp/sl) di lane ini
  wins:    number;
  winRate: number;
  avgPnl:  number;
  pnl$:    number;
}

export function LanePerformance({ laneStats }: { laneStats: LaneStat[] }) {
  const shown = laneStats.filter(l => l.total > 0);
  if (shown.length === 0) return null;

  return (
    <div className="bg-white border border-neutral-200 rounded-2xl p-4">
      <div className="flex items-center justify-between mb-3">
        <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider">
          🛣 Win Rate per Lane
        </p>
        <a href="/signals" className="text-[10px] font-semibold text-teal-600 hover:underline">
          Analisa sinyal individual → /signals
        </a>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        {shown.map(l => {
          const badge = LANES[l.key]?.badge ?? "bg-neutral-100 text-neutral-600";
          const auto  = LANES[l.key]?.autoScore;
          return (
            <div key={l.key} className="rounded-xl p-3 border border-neutral-200 bg-neutral-50">
              <div className="flex items-center gap-1.5 mb-1">
                <span className={`text-[10px] px-1.5 py-0.5 rounded font-bold ${badge}`}>{l.emoji} {l.label}</span>
              </div>
              <p className={`text-xl font-black ${l.winRate >= 50 ? "text-green-600" : "text-red-500"}`}>
                {l.winRate.toFixed(0)}%
              </p>
              <p className="text-[10px] text-neutral-400">{l.wins}/{l.total} trades{auto != null ? ` · auto ≥${auto}` : ""}</p>
              <p className={`text-[10px] font-semibold ${l.avgPnl >= 0 ? "text-green-500" : "text-red-400"}`}>
                avg {l.avgPnl >= 0 ? "+" : ""}{l.avgPnl.toFixed(1)}%
              </p>
              <p className={`text-[10px] font-bold ${l.pnl$ >= 0 ? "text-green-600" : "text-red-500"}`}>
                {l.pnl$ >= 0 ? "+" : ""}${l.pnl$.toFixed(2)}
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
