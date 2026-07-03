"use client";
import Link from "next/link";

export function KpiCard({ label, value, sub, color, icon, href }: {
  label: string; value: string; sub?: string; color: string; icon: string;
  /** DASH-FIX: optional drill-down target — makes the KPI interactive (click → detail page) */
  href?: string;
}) {
  const inner = (
    <div className={`bg-white rounded-2xl border border-neutral-200 px-5 py-4 h-full ${
      href ? "transition-all hover:border-teal-300 hover:shadow-sm cursor-pointer" : ""}`}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-[10px] font-bold text-neutral-400 uppercase tracking-wider mb-1">{label}</p>
          <p className={`text-2xl font-black tabular-nums leading-tight ${color}`}>{value}</p>
          {sub && <p className="text-[10px] text-neutral-400 mt-0.5">{sub}</p>}
        </div>
        <span className="text-2xl opacity-80">{icon}</span>
      </div>
    </div>
  );
  return href ? <Link href={href} className="block">{inner}</Link> : inner;
}

export function WinRateBar({ rate, label }: { rate: number; label: string }) {
  const color = rate >= 70 ? "bg-green-500" : rate >= 50 ? "bg-yellow-400" : "bg-red-400";
  return (
    <div>
      <div className="flex justify-between text-[10px] mb-1">
        <span className="text-neutral-500">{label}</span>
        <span className={`font-black ${rate >= 50 ? "text-green-600" : "text-red-500"}`}>{rate.toFixed(0)}%</span>
      </div>
      <div className="h-1.5 bg-neutral-200 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${Math.min(rate, 100)}%` }} />
      </div>
    </div>
  );
}

export function MiniEquityChart({ points, height = 32 }: {
  points: { balance: number; win: boolean; symbol?: string }[];
  height?: number;
}) {
  if (points.length < 2) return null;
  const min = Math.min(...points.map(p => p.balance));
  const max = Math.max(...points.map(p => p.balance));
  const range = max - min || 1;
  return (
    <div className="flex items-end gap-px" style={{ height }}>
      {points.slice(-40).map((pt, i) => {
        const h = Math.max(((pt.balance - min) / range) * 100, 3);
        const cls = i === 0 ? "bg-neutral-300" : pt.win ? "bg-green-400" : "bg-red-400";
        // DASH-FIX: native tooltip per bar — hover shows the exact balance (+symbol)
        const tip = `${pt.symbol ? pt.symbol + " · " : ""}$${pt.balance.toFixed(2)}`;
        return (
          <div key={i} title={tip}
            className={`flex-1 min-w-[2px] rounded-sm hover:opacity-70 ${cls}`}
            style={{ height: `${h}%` }} />
        );
      })}
    </div>
  );
}

export function StatGrid({ stats }: {
  stats: { label: string; val: string; color: string }[];
}) {
  return (
    <div className={`grid grid-cols-${stats.length} gap-1.5`}>
      {stats.map(s => (
        <div key={s.label} className="text-center bg-neutral-50 rounded-xl py-2">
          <p className={`text-sm font-black ${s.color}`}>{s.val}</p>
          <p className="text-[9px] text-neutral-400">{s.label}</p>
        </div>
      ))}
    </div>
  );
}
