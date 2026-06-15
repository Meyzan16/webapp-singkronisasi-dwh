"use client";
import { EmptyState } from "@/components/ui/feedback";
import { GateBanner } from "./GateBanner";
import { OpenPosCard } from "./OpenPosCard";
import type { FuturesPosition, RiskDashboard, LearningStats, RiskPosition } from "./types";

interface Props {
  positions:    FuturesPosition[];
  riskDash:     RiskDashboard | null;
  learning:     LearningStats | null;
  startingBalance: number;
  riskDollar:   number;
  countdown:    number;
  onRefresh:    () => void;
}

function AgentColumn({ label, color, positions, riskMap, riskDollar, atRisk }: {
  label: string; color: string; positions: FuturesPosition[];
  riskMap: Record<number, RiskPosition>; riskDollar: number; atRisk?: number;
}) {
  return (
    <div>
      <div className="flex items-center gap-2 mb-2">
        <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${color}`}>{label}</span>
        <span className="text-xs text-neutral-500">{positions.length} posisi</span>
        {(atRisk ?? 0) > 0 && <span className="text-[10px] text-red-600 font-bold">⚠️ {atRisk}</span>}
      </div>
      {positions.length === 0
        ? <div className="text-center py-8 text-neutral-400 text-xs border border-dashed border-neutral-200 rounded-2xl">Kosong</div>
        : <div className="space-y-2">{positions.map(p => <OpenPosCard key={p.id} p={p} risk={riskMap[p.id]} riskDollar={riskDollar} />)}</div>
      }
    </div>
  );
}

export function MonitorTab({ positions, riskDash, learning, startingBalance, riskDollar, countdown, onRefresh }: Props) {
  const pd = riskDash?.portfolio;
  const ab = riskDash?.agent_breakdown;

  const a1Open = positions.filter(p => p.status === "open" && p.agent === "futures_agent1");
  const a2Open = positions.filter(p => p.status === "open" && p.agent === "futures_agent2");
  const a3Open = positions.filter(p => p.status === "open" && p.agent === "futures_agent3");
  const hasOpen = a1Open.length > 0 || a2Open.length > 0 || a3Open.length > 0;

  const riskMap: Record<number, RiskPosition> = {};
  (riskDash?.positions ?? []).forEach(rp => { riskMap[rp.id] = rp; });

  return (
    <div className="space-y-5">
      <GateBanner gate={riskDash?.gate} />

      {/* Portfolio summary */}
      {pd && (
        <div className="rounded-2xl bg-gradient-to-br from-neutral-900 via-neutral-800 to-neutral-900 text-white p-5">
          <div className="flex items-start justify-between gap-4 flex-wrap mb-4">
            <div>
              <p className="text-xs text-neutral-400 uppercase tracking-wider font-semibold mb-1">🔍 Portfolio Risk Dashboard</p>
              <div className="flex items-baseline gap-3">
                <span className={`text-4xl font-black ${pd.current_balance >= startingBalance ? "text-green-400" : "text-red-400"}`}>
                  ${pd.current_balance.toFixed(2)}
                </span>
                <span className={`text-sm font-bold ${pd.total_closed_pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                  {pd.total_closed_pnl >= 0 ? "+" : ""}${pd.total_closed_pnl.toFixed(2)}
                </span>
              </div>
              <p className="text-xs text-neutral-500 mt-1">
                Modal ${startingBalance.toLocaleString()} · Risk ${riskDollar.toFixed(0)}/trade · Sharpe ≈ {pd.risk_adjusted_return.toFixed(2)}
              </p>
            </div>
            <div className="grid grid-cols-3 gap-2 text-center">
              {[
                { val: pd.open_count,       cls: "text-blue-400",                                                     label: "Open"   },
                { val: pd.at_risk_count,    cls: pd.at_risk_count > 0 ? "text-red-400" : "text-green-400",            label: "At Risk"},
                { val: `${pd.max_drawdown_pct.toFixed(1)}%`, cls: "text-orange-400",                                  label: "Max DD" },
              ].map(x => (
                <div key={x.label} className="bg-white/5 rounded-xl px-3 py-2">
                  <p className={`text-2xl font-black ${x.cls}`}>{x.val}</p>
                  <p className="text-[9px] text-neutral-400">{x.label}</p>
                </div>
              ))}
            </div>
          </div>

          {ab && (
            <div className="grid grid-cols-3 gap-3">
              {([
                { key: "agent1", label: "🎯 Pre-Gainer",   cls: "text-blue-300",   data: ab.agent1 },
                { key: "agent2", label: "📦 Accumulation", cls: "text-purple-300", data: ab.agent2 },
                { key: "agent3", label: "🔥 Momentum",     cls: "text-orange-300", data: ab.agent3 },
              ] as const).filter(a => a.data).map(a => (
                <div key={a.key} className={`bg-white/5 rounded-xl p-3 border ${(a.data!.at_risk ?? 0) > 0 ? "border-red-700/40" : "border-white/5"}`}>
                  <p className={`text-[10px] font-bold mb-2 ${a.cls}`}>{a.label}</p>
                  <div className="flex flex-col gap-1 text-xs">
                    <span className="text-neutral-400">Open: <strong className="text-white">{a.data!.open}</strong></span>
                    <span className="text-neutral-400">Margin: <strong className="text-yellow-300">${a.data!.margin.toFixed(0)}</strong></span>
                    {(a.data!.at_risk ?? 0) > 0 && <span className="text-red-400 font-bold">⚠️ {a.data!.at_risk} at risk</span>}
                  </div>
                </div>
              ))}
            </div>
          )}

          <div className="mt-3 flex gap-4 text-xs flex-wrap">
            <span className="text-neutral-400">Total Margin: <strong className="text-yellow-300">${pd.total_margin.toFixed(0)}</strong></span>
            <span className="text-neutral-400">Notional: <strong className="text-neutral-200">${pd.total_notional.toFixed(0)}</strong></span>
            <span className="text-neutral-400">Unrealized: <strong className={pd.total_unrealized >= 0 ? "text-green-400" : "text-red-400"}>
              {pd.total_unrealized >= 0 ? "+" : ""}${pd.total_unrealized.toFixed(2)}
            </strong></span>
          </div>
        </div>
      )}

      {/* Open positions by agent */}
      {hasOpen ? (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <AgentColumn label="🎯 Pre-Gainer"   color="bg-blue-100 text-blue-700 border-blue-200"
            positions={a1Open} riskMap={riskMap} riskDollar={riskDollar} atRisk={ab?.agent1.at_risk} />
          <AgentColumn label="📦 Accumulation" color="bg-purple-100 text-purple-700 border-purple-200"
            positions={a2Open} riskMap={riskMap} riskDollar={riskDollar} atRisk={ab?.agent2.at_risk} />
          <AgentColumn label="🔥 Momentum"     color="bg-orange-100 text-orange-700 border-orange-200"
            positions={a3Open} riskMap={riskMap} riskDollar={riskDollar} atRisk={ab?.agent3?.at_risk} />
        </div>
      ) : (
        <EmptyState icon="📭" title="Tidak ada posisi terbuka saat ini" />
      )}

      {/* Monitor stats */}
      {learning?.monitor && (
        <div className="bg-white border border-neutral-200 rounded-2xl p-4">
          <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider mb-3">🔬 Monitor Stats</p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-center">
            {[
              { label: "Cycles",        value: learning.monitor.cycle_count,        color: "text-neutral-700" },
              { label: "Tutup Hari Ini", value: learning.monitor.closed_today,      color: "text-blue-600"    },
              { label: "Liq Guards",    value: learning.monitor.liq_guards ?? 0,    color: "text-orange-600"  },
              { label: "TP Extended",   value: learning.monitor.tp_extended ?? 0,   color: "text-green-600"   },
            ].map(x => (
              <div key={x.label} className="bg-neutral-50 rounded-xl p-3">
                <p className={`text-2xl font-black ${x.color}`}>{x.value}</p>
                <p className="text-[10px] text-neutral-400 mt-0.5">{x.label}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="flex items-center justify-end gap-2">
        <div className="flex items-center gap-1.5 px-2 py-1 rounded-full bg-blue-50 border border-blue-200">
          <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
          <span className="text-[10px] font-bold text-blue-700">LIVE</span>
          <span className="text-[10px] text-blue-600 tabular-nums">{countdown}s</span>
        </div>
        <button onClick={onRefresh} className="text-xs text-teal-600 hover:text-teal-500 font-semibold">↺ Refresh</button>
      </div>
    </div>
  );
}
