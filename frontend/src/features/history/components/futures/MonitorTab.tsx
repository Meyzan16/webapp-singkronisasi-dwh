"use client";
import { useState } from "react";
import { EmptyState } from "@/components/ui/feedback";
import { GateBanner } from "./GateBanner";
import { OpenPosCard } from "./OpenPosCard";
import type { FuturesPosition, RiskDashboard, LearningStats, RiskPosition } from "./types";
import { calcNotional, calcMargin, tradePnlDollar } from "./types";

type AgentFilter = "all" | "agent1" | "agent2" | "agent3" | "agent_bigmover";

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
  const [agentFilter, setAgentFilter] = useState<AgentFilter>("all");

  const pd = riskDash?.portfolio;
  const ab = riskDash?.agent_breakdown;

  const riskMap: Record<number, RiskPosition> = {};
  (riskDash?.positions ?? []).forEach(rp => { riskMap[rp.id] = rp; });

  const openPos = positions.filter(p => p.status === "open");
  const a1Open  = openPos.filter(p => p.agent === "futures_agent1");
  const a2Open  = openPos.filter(p => p.agent === "futures_agent2");
  const a3Open  = openPos.filter(p => p.agent === "futures_agent3");
  const bmOpen  = openPos.filter(p => p.agent === "futures_agent_bigmover");
  const hasOpen = openPos.length > 0;

  // Compute financial summary from positions (same logic as OpenPosCard)
  const getMargin = (p: FuturesPosition) => {
    const notional = p.position_size ?? calcNotional(p.risk_pct, riskDollar);
    return riskMap[p.id]?.margin ?? calcMargin(notional, p.leverage);
  };
  const totalUnrealized = openPos.reduce((s, p) => s + (tradePnlDollar(p, riskDollar) ?? 0), 0);
  const totalMargin     = openPos.reduce((s, p) => s + getMargin(p), 0);
  const momentumMargin  = a3Open.reduce((s, p) => s + getMargin(p), 0);
  const bmMargin        = bmOpen.reduce((s, p) => s + getMargin(p), 0);

  return (
    <div className="space-y-5">
      <GateBanner gate={riskDash?.gate} />

      {/* Portfolio summary — full data from riskDash, fallback from positions when API unavailable */}
      {pd ? (
        <div className="rounded-2xl bg-gradient-to-br from-neutral-900 via-neutral-800 to-neutral-900 text-white p-5">
          <div className="flex items-start justify-between gap-4 flex-wrap mb-4">
            <div>
              <p className="text-xs text-neutral-400 uppercase tracking-wider font-semibold mb-1">🔍 Portfolio Risk Dashboard</p>
              {(() => {
                const equity = pd.current_balance + pd.total_unrealized;
                const equityDelta = equity - startingBalance;
                return (
                  <>
                    <div className="flex items-baseline gap-3">
                      <span className={`text-4xl font-black ${equity >= startingBalance ? "text-green-400" : "text-red-400"}`}>
                        ${equity.toFixed(2)}
                      </span>
                      <span className={`text-sm font-bold ${equityDelta >= 0 ? "text-green-400" : "text-red-400"}`}>
                        {equityDelta >= 0 ? "+" : ""}${equityDelta.toFixed(2)}
                      </span>
                    </div>
                    <p className="text-xs text-neutral-500 mt-1">
                      Realized ${pd.current_balance.toFixed(2)} · Unrealized {pd.total_unrealized >= 0 ? "+" : ""}${pd.total_unrealized.toFixed(2)}
                      {" · "}Sharpe ≈ {pd.risk_adjusted_return != null ? pd.risk_adjusted_return.toFixed(2) : "—"}
                    </p>
                  </>
                );
              })()}
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
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {([
                { key: "agent1",         label: "🎯 Pre-Gainer",   cls: "text-blue-300",   data: ab.agent1 },
                { key: "agent2",         label: "📦 Accumulation", cls: "text-purple-300", data: ab.agent2 },
                { key: "agent3",         label: "🔥 Momentum",     cls: "text-orange-300", data: ab.agent3 },
                { key: "agent_bigmover", label: "💥 Big Mover",    cls: "text-amber-300",  data: ab.agent_bigmover },
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

          <div className="mt-3 flex gap-4 text-xs flex-wrap items-center">
            <span className="text-neutral-400">Total Margin: <strong className="text-yellow-300">${pd.total_margin.toFixed(0)}</strong></span>
            <span className="text-neutral-400">Notional: <strong className="text-neutral-200">${pd.total_notional.toFixed(0)}</strong></span>
            <span className="text-neutral-400">Unrealized: <strong className={pd.total_unrealized >= 0 ? "text-green-400" : "text-red-400"}>
              {pd.total_unrealized >= 0 ? "+" : ""}${pd.total_unrealized.toFixed(2)}
            </strong></span>
            {/* G7: margin ratio warning */}
            {pd.margin_ratio != null && (
              <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${
                pd.margin_ratio > 80
                  ? "bg-red-900/40 text-red-300 border-red-700/60"
                  : pd.margin_ratio > 60
                  ? "bg-yellow-900/40 text-yellow-300 border-yellow-700/60"
                  : "bg-white/5 text-neutral-400 border-white/10"
              }`}>
                {pd.margin_ratio > 80 ? "⚠️ " : pd.margin_ratio > 60 ? "⚡ " : ""}
                Margin Ratio {pd.margin_ratio.toFixed(1)}%
              </span>
            )}
            {/* PLAN_v2 P2.3 — aggregate ROI on margin */}
            {pd.aggregate_roi_pct != null && pd.open_count > 0 && (
              <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${
                pd.aggregate_roi_pct < -50
                  ? "bg-red-900/40 text-red-300 border-red-700/60"
                  : pd.aggregate_roi_pct < 0
                  ? "bg-yellow-900/40 text-yellow-300 border-yellow-700/60"
                  : "bg-green-900/40 text-green-300 border-green-700/60"
              }`}>
                Aggregate ROI {pd.aggregate_roi_pct >= 0 ? "+" : ""}{pd.aggregate_roi_pct.toFixed(1)}%
              </span>
            )}
          </div>
          {/* PLAN_v2 P2.3 — Worst ROI Open */}
          {pd.worst_roi && pd.worst_roi.roi_pct < 0 && (
            <div className="mt-3 rounded-xl bg-red-900/30 border border-red-700/40 px-3 py-2 text-xs">
              <span className="text-neutral-400 mr-2">Worst ROI Open:</span>
              <span className="font-bold text-red-300">{pd.worst_roi.symbol.replace("USDT", "")}</span>
              <span className="text-neutral-500 ml-1">({pd.worst_roi.setup_type ?? pd.worst_roi.agent.replace("futures_", "")})</span>
              <span className={`ml-2 font-bold ${pd.worst_roi.roi_pct < -100 ? "text-red-400 animate-pulse" : "text-red-300"}`}>
                {pd.worst_roi.roi_pct >= 0 ? "+" : ""}{pd.worst_roi.roi_pct.toFixed(1)}%
                {pd.worst_roi.roi_pct < -100 && " ⚠"}
              </span>
              <span className="text-neutral-500 ml-2">
                ${pd.worst_roi.upnl_dollar.toFixed(2)} on ${pd.worst_roi.margin.toFixed(0)} margin · {pd.worst_roi.leverage}x
              </span>
            </div>
          )}
        </div>
      ) : hasOpen ? (
        // MN1: fallback banner computed from positions when riskDash API unavailable
        <div className="rounded-2xl bg-gradient-to-br from-neutral-900 via-neutral-800 to-neutral-900 text-white p-5">
          <p className="text-xs text-neutral-400 uppercase tracking-wider font-semibold mb-3">🔍 Portfolio Risk Dashboard <span className="text-neutral-600 normal-case">(estimasi lokal)</span></p>
          <div className="flex items-baseline gap-3 mb-3">
            <span className={`text-4xl font-black ${totalUnrealized >= 0 ? "text-green-400" : "text-red-400"}`}>
              {totalUnrealized >= 0 ? "+" : ""}${totalUnrealized.toFixed(2)}
            </span>
            <span className="text-sm text-neutral-400">unrealized P&L</span>
          </div>
          <div className="flex gap-4 text-xs flex-wrap">
            <span className="text-neutral-400">Open: <strong className="text-blue-400">{openPos.length}</strong></span>
            <span className="text-neutral-400">Total Margin: <strong className="text-yellow-300">${totalMargin.toFixed(0)}</strong></span>
            <span className="text-neutral-400">Margin Momo+BM: <strong className="text-orange-300">${(momentumMargin + bmMargin).toFixed(0)}</strong></span>
          </div>
        </div>
      ) : null}

      {/* MN3: Agent filter chips */}
      {hasOpen && (
        <div className="flex gap-1.5 flex-wrap">
          {([
            { key: "all",            label: "Semua",           cls: "bg-neutral-100 text-neutral-700 border-neutral-300"  },
            { key: "agent1",         label: "🎯 Pre-Gainer",   cls: "bg-blue-100 text-blue-700 border-blue-200"           },
            { key: "agent2",         label: "📦 Accumulation", cls: "bg-purple-100 text-purple-700 border-purple-200"     },
            { key: "agent3",         label: "🔥 Momentum",     cls: "bg-orange-100 text-orange-700 border-orange-200"     },
            { key: "agent_bigmover", label: "💥 Big Mover",    cls: "bg-amber-100 text-amber-700 border-amber-200"        },
          ] as { key: AgentFilter; label: string; cls: string }[]).map(f => (
            <button key={f.key} onClick={() => setAgentFilter(f.key)}
              className={`text-[10px] font-bold px-3 py-1 rounded-full border transition-all ${
                agentFilter === f.key ? `${f.cls} ring-2 ring-offset-1 ring-current` : "bg-white text-neutral-400 border-neutral-200 hover:border-neutral-300"
              }`}>
              {f.label}
            </button>
          ))}
        </div>
      )}

      {/* Open positions by agent */}
      {hasOpen ? (
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
          {(agentFilter === "all" || agentFilter === "agent1") && (
            <AgentColumn label="🎯 Pre-Gainer"   color="bg-blue-100 text-blue-700 border-blue-200"
              positions={a1Open} riskMap={riskMap} riskDollar={riskDollar} atRisk={ab?.agent1.at_risk} />
          )}
          {(agentFilter === "all" || agentFilter === "agent2") && (
            <AgentColumn label="📦 Accumulation" color="bg-purple-100 text-purple-700 border-purple-200"
              positions={a2Open} riskMap={riskMap} riskDollar={riskDollar} atRisk={ab?.agent2.at_risk} />
          )}
          {(agentFilter === "all" || agentFilter === "agent3") && (
            <AgentColumn label="🔥 Momentum"     color="bg-orange-100 text-orange-700 border-orange-200"
              positions={a3Open} riskMap={riskMap} riskDollar={riskDollar} atRisk={ab?.agent3?.at_risk} />
          )}
          {(agentFilter === "all" || agentFilter === "agent_bigmover") && (
            <AgentColumn label="💥 Big Mover"    color="bg-amber-100 text-amber-700 border-amber-200"
              positions={bmOpen} riskMap={riskMap} riskDollar={riskDollar} atRisk={ab?.agent_bigmover?.at_risk} />
          )}
        </div>
      ) : (
        <EmptyState icon="📭" title="Tidak ada posisi terbuka saat ini" />
      )}

      {/* Monitor stats */}
      <div className="bg-white border border-neutral-200 rounded-2xl p-4">
        <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider mb-3">📊 Ringkasan Posisi</p>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-center">
          {/* Unrealized P&L — always computed from positions */}
          <div className={`rounded-xl p-3 ${hasOpen ? (totalUnrealized >= 0 ? "bg-green-50 border border-green-100" : "bg-red-50 border border-red-100") : "bg-neutral-50"}`}>
            <p className={`text-xl font-black tabular-nums ${
              !hasOpen ? "text-neutral-400" : totalUnrealized >= 0 ? "text-green-600" : "text-red-600"
            }`}>
              {hasOpen ? `${totalUnrealized >= 0 ? "+" : ""}$${totalUnrealized.toFixed(2)}` : "—"}
            </p>
            <p className="text-[10px] text-neutral-600 font-semibold mt-1">Unrealized P&L</p>
            <p className="text-[9px] text-neutral-400">{openPos.length} posisi open</p>
          </div>

          {/* Total Margin */}
          <div className={`rounded-xl p-3 ${hasOpen ? "bg-yellow-50 border border-yellow-100" : "bg-neutral-50"}`}>
            <p className={`text-xl font-black tabular-nums ${hasOpen ? "text-yellow-600" : "text-neutral-400"}`}>
              {hasOpen ? `$${totalMargin.toFixed(0)}` : "—"}
            </p>
            <p className="text-[10px] text-neutral-600 font-semibold mt-1">Total Margin</p>
            <p className="text-[9px] text-neutral-400">semua {openPos.length} posisi</p>
          </div>

          {/* Momentum + BigMover Margin */}
          <div className={`rounded-xl p-3 ${(a3Open.length + bmOpen.length) > 0 ? "bg-orange-50 border border-orange-100" : "bg-neutral-50"}`}>
            <p className={`text-xl font-black tabular-nums ${(a3Open.length + bmOpen.length) > 0 ? "text-orange-600" : "text-neutral-400"}`}>
              {(a3Open.length + bmOpen.length) > 0 ? `$${(momentumMargin + bmMargin).toFixed(0)}` : "—"}
            </p>
            <p className="text-[10px] text-neutral-600 font-semibold mt-1">Margin Momo+BM</p>
            <p className="text-[9px] text-neutral-400">{a3Open.length} Momentum · {bmOpen.length} BigMover</p>
          </div>

          {/* Closed Today */}
          <div className="bg-neutral-50 rounded-xl p-3">
            <p className="text-xl font-black tabular-nums text-blue-600">
              {learning?.monitor?.closed_today ?? 0}
            </p>
            <p className="text-[10px] text-neutral-600 font-semibold mt-1">Tutup Hari Ini</p>
            <p className="text-[9px] text-neutral-400">posisi closed hari ini</p>
          </div>
        </div>
      </div>

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
