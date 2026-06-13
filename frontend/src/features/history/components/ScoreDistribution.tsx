"use client";
import type { ScoreBucket } from "./OppSpotTypes";

interface ScoreDistributionProps {
  scoreDist:   ScoreBucket[];
  totalClosed: number;
}

function MiniBar({ value, max, color }: { value: number; max: number; color: string }) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0;
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-neutral-100 rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[10px] tabular-nums text-neutral-500 w-8 text-right">{value}</span>
    </div>
  );
}

export function ScoreDistribution({ scoreDist, totalClosed }: ScoreDistributionProps) {
  if (totalClosed === 0) return null;

  const maxTotal = Math.max(...scoreDist.map(x => x.total), 1);

  return (
    <div className="bg-white border border-neutral-200 rounded-2xl p-4">
      <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider mb-0.5">
        🎯 Score Distribution — Korelasi Score vs Win Rate
      </p>
      <p className="text-[10px] text-neutral-400 mb-3">
        <strong className="text-neutral-600">Score</strong> = kualitas setup sinyal scanner
        (0–100 poin, minimum 30).{" "}
        <strong className="text-neutral-600">Outcome</strong> = apakah trade profit (TP) atau rugi (SL).
        {" "}Apakah score lebih tinggi → win rate lebih tinggi?
      </p>
      <div className="space-y-2.5">
        {scoreDist.map(b => (
          <div key={b.label} className="flex items-center gap-3">
            <span className="text-xs font-mono text-neutral-500 w-14 shrink-0">{b.label}pt</span>
            <div className="flex-1 grid grid-cols-2 gap-1.5">
              <MiniBar value={b.wins}           max={maxTotal} color="bg-green-400" />
              <MiniBar value={b.total - b.wins} max={maxTotal} color="bg-red-300"   />
            </div>
            <span className={`text-xs font-bold w-12 text-right tabular-nums ${
              b.total === 0
                ? "text-neutral-300"
                : b.rate >= 50 ? "text-green-600" : "text-red-500"
            }`}>
              {b.total > 0 ? `${b.rate.toFixed(0)}%` : "—"}
            </span>
            <span className="text-[10px] text-neutral-400 w-14 text-right shrink-0">
              {b.total > 0 ? `${b.total} trade` : ""}
            </span>
          </div>
        ))}
        <div className="flex gap-4 pt-1 text-[10px] text-neutral-400">
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-green-400 inline-block" /> TP (Win)
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-red-300 inline-block" /> SL (Loss)
          </span>
        </div>
      </div>
    </div>
  );
}
