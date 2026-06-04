import type { HistoryStats, StyleStats } from "@/types/history";

const STYLE_META: Record<string, { icon: string; label: string; color: string; badge: string }> = {
  scalping:   { icon: "⚡", label: "Scalping",  color: "from-yellow-500/20 to-orange-500/20 border-yellow-400/40", badge: "bg-yellow-500" },
  daytrading: { icon: "📅", label: "Day Trade", color: "from-blue-500/20 to-indigo-500/20 border-blue-400/40",    badge: "bg-blue-500"   },
  swing:      { icon: "🌊", label: "Swing",     color: "from-teal-500/20 to-green-500/20 border-teal-400/40",    badge: "bg-teal-500"   },
  position:   { icon: "🏔", label: "Position",  color: "from-purple-500/20 to-violet-500/20 border-purple-400/40", badge: "bg-purple-500" },
};

interface AccuracyStatsProps { stats: HistoryStats; }

export function AccuracyStats({ stats }: AccuracyStatsProps) {
  return (
    <div className="space-y-3">
      {/* Overall */}
      <OverallCard stats={stats} />

      {/* Per style */}
      <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
        {Object.entries(STYLE_META).map(([key, meta]) => {
          const s = stats.by_style[key];
          if (!s) return null;
          return <StyleCard key={key} meta={meta} stats={s} />;
        })}
      </div>
    </div>
  );
}

function OverallCard({ stats }: { stats: HistoryStats }) {
  const s = stats?.overall;
  if (!s) return null;
  const wr = s.win_rate ?? 0;
  const barColor = wr >= 60 ? "bg-green-500" : wr >= 40 ? "bg-yellow-500" : "bg-red-500";
  const wrColor  = wr >= 60 ? "text-green-600" : wr >= 40 ? "text-yellow-600" : "text-red-500";

  return (
    <div className="bg-neutral-900 text-white rounded-2xl p-5">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <p className="text-xs text-neutral-400 font-semibold uppercase tracking-wider mb-1">Overall Performance</p>
          <div className="flex items-end gap-4">
            <div>
              <p className={`text-5xl font-black ${wrColor}`}>{wr.toFixed(0)}<span className="text-2xl">%</span></p>
              <p className="text-xs text-neutral-400 mt-0.5">Win Rate</p>
            </div>
            <div className="text-sm space-y-1 mb-1">
              <p><span className="text-green-400 font-bold">{s.wins}</span> <span className="text-neutral-400">TP hit</span></p>
              <p><span className="text-red-400 font-bold">{s.losses}</span> <span className="text-neutral-400">SL hit</span></p>
              <p><span className="text-neutral-300 font-bold">{s.open}</span> <span className="text-neutral-400">open</span></p>
            </div>
          </div>
        </div>

        <div className="flex gap-6 text-center">
          <Metric label="Total Trades" value={String(s.total)} />
          <Metric
            label="Avg PnL / trade"
            value={`${s.avg_pnl_pct >= 0 ? "+" : ""}${s.avg_pnl_pct.toFixed(2)}%`}
            color={s.avg_pnl_pct >= 0 ? "text-green-400" : "text-red-400"}
          />
          <Metric label="Closed" value={String(s.wins + s.losses)} />
        </div>
      </div>

      {/* Win rate bar */}
      <div className="mt-4">
        <div className="flex justify-between text-xs text-neutral-500 mb-1">
          <span>Win rate progress</span>
          <span>Target ≥ 55%</span>
        </div>
        <div className="w-full h-2 bg-neutral-700 rounded-full overflow-hidden">
          <div className={`h-full rounded-full transition-all ${barColor}`} style={{ width: `${Math.min(wr, 100)}%` }} />
        </div>
        <div className="flex justify-between text-[10px] text-neutral-600 mt-0.5">
          <span>0%</span><span className="text-yellow-500">55%</span><span>100%</span>
        </div>
      </div>
    </div>
  );
}

function StyleCard({ meta, stats: s }: { meta: typeof STYLE_META[string]; stats: StyleStats }) {
  if (!s) return null;
  const wr = s.win_rate ?? 0;
  const wrColor = wr >= 60 ? "text-green-600" : wr >= 40 ? "text-yellow-600" : "text-red-500";

  return (
    <div className={`rounded-xl border bg-gradient-to-b p-4 ${meta.color}`}>
      <div className="flex items-center gap-2 mb-3">
        <span className="text-xl">{meta.icon}</span>
        <p className="font-bold text-sm">{meta.label}</p>
      </div>

      <p className={`text-3xl font-black mb-0.5 ${wrColor}`}>
        {wr.toFixed(0)}<span className="text-base font-semibold">%</span>
      </p>
      <p className="text-[10px] text-neutral-500 mb-3">win rate</p>

      <div className="space-y-1 text-xs">
        <Row label="Total"   value={String(s.total)} />
        <Row label="TP hit"  value={String(s.wins)}    color="text-green-600" />
        <Row label="SL hit"  value={String(s.losses)}  color="text-red-500"   />
        <Row label="Open"    value={String(s.open)}    color="text-neutral-500" />
        <Row
          label="Avg PnL"
          value={`${s.avg_pnl_pct >= 0 ? "+" : ""}${s.avg_pnl_pct.toFixed(2)}%`}
          color={s.avg_pnl_pct >= 0 ? "text-green-600" : "text-red-500"}
        />
      </div>
    </div>
  );
}

function Metric({ label, value, color = "text-white" }: { label: string; value: string; color?: string }) {
  return (
    <div>
      <p className={`text-xl font-bold ${color}`}>{value}</p>
      <p className="text-[10px] text-neutral-400 mt-0.5">{label}</p>
    </div>
  );
}

function Row({ label, value, color = "text-neutral-700" }: { label: string; value: string; color?: string }) {
  return (
    <div className="flex justify-between">
      <span className="text-neutral-500">{label}</span>
      <span className={`font-semibold ${color}`}>{value}</span>
    </div>
  );
}
