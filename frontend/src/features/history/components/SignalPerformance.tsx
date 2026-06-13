"use client";
import type { SignalStat } from "./OppSpotTypes";

interface SignalPerformanceProps {
  signalStats:  SignalStat[];
  closedCount:  number;
}

export function SignalPerformance({ signalStats, closedCount }: SignalPerformanceProps) {
  if (signalStats.length === 0) return null;

  return (
    <div className="bg-white border border-neutral-200 rounded-2xl p-4">
      <div className="mb-3">
        <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider">
          🔬 Signal Performance
        </p>
        <p className="text-[10px] text-neutral-400 mt-0.5">
          Dari {closedCount} trade tertutup (TP+SL saja, bukan manual)
          {" "}·{" "}
          <span className="text-green-600 font-semibold">update live setiap 15 detik</span>
          {" "}· Minimal 2 sampel per sinyal
        </p>
      </div>
      <div className="space-y-1.5">
        {signalStats.map(s => (
          <div
            key={s.sig}
            className="flex items-center gap-3 py-1.5 border-b border-neutral-50 last:border-0"
          >
            <span className={`text-[10px] font-black w-10 text-right tabular-nums ${
              s.rate >= 60
                ? "text-green-600"
                : s.rate >= 40 ? "text-yellow-600" : "text-red-500"
            }`}>
              {s.rate.toFixed(0)}%
            </span>
            <div className="flex-1 min-w-0">
              <p className="text-[11px] text-neutral-700 truncate">{s.sig}</p>
            </div>
            <span className="text-[10px] text-neutral-400 shrink-0">{s.wins}/{s.total}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
