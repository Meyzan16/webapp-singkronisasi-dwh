"use client";
import { useState } from "react";
import { WinRateBar } from "@/components/ui/stat-card";
import { FuturesWallet } from "../FuturesWallet";
import { DBHistoryTable } from "@/features/health/components/DBHistoryTable";
import { GateBanner } from "./GateBanner";
import { OpenPosCard } from "./OpenPosCard";
import { BigMoversWatchlist } from "./BigMoversWatchlist";
import type { FuturesPosition, RiskDashboard, LearningStats, RiskPosition } from "./types";

const TARGET_WIN_RATE = 80;

function fmtMonth(m: string): string {
  const [y, mo] = m.split("-");
  const names = ["", "Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Ags", "Sep", "Okt", "Nov", "Des"];
  return `${names[parseInt(mo)]} ${y}`;
}

const REGIME_CFG: Record<string, { emoji: string; label: string; cls: string }> = {
  trending_up:   { emoji: "📈", label: "Trending Up",   cls: "bg-green-100 text-green-700 border-green-300"    },
  trending_down: { emoji: "📉", label: "Trending Down", cls: "bg-red-100 text-red-600 border-red-300"          },
  ranging:       { emoji: "↔️", label: "Ranging",       cls: "bg-blue-100 text-blue-700 border-blue-300"       },
  volatile:      { emoji: "⚡", label: "Volatile",      cls: "bg-orange-100 text-orange-700 border-orange-300" },
};

interface Props {
  riskDash:        RiskDashboard | null;
  learning:        LearningStats | null;
  startingBalance: number;
  riskDollar:      number;
  equityPoints:    { balance: number; n: number; symbol: string; win: boolean }[];
  stats: {
    open: number; closed: number; wins: number; losses: number; winRate: number;
    currentBalance: number; totalPnl$: number;
    a1Open: FuturesPosition[]; a2Open: FuturesPosition[]; a3Open: FuturesPosition[];
    bmOpen: FuturesPosition[];
    a1: { total: number; wins: number; rate: number; pnl$: number };
    a2: { total: number; wins: number; rate: number; pnl$: number };
    a3: { total: number; wins: number; rate: number; pnl$: number };
    bm: { total: number; wins: number; rate: number; pnl$: number };
  };
  autoThreshold:   number | null;
  agentFilter:     "all" | "agent1" | "agent2" | "agent3" | "agent_bigmover";
  setAgentFilter:  (f: "all" | "agent1" | "agent2" | "agent3" | "agent_bigmover") => void;
  countdown:       number;
  lastUpdated:     Date | null;
  loading:         boolean;
  onRefresh:       () => void;
  onWalletChanged: () => void;
}

type AgentKey = "agent1" | "agent2" | "agent3" | "agent_bigmover";

export function OverviewTab({ riskDash, learning, startingBalance, riskDollar,
  equityPoints, stats, autoThreshold, agentFilter, setAgentFilter,
  countdown, lastUpdated, loading, onRefresh, onWalletChanged }: Props) {

  const [selectedMonth, setSelectedMonth] = useState("all");

  const balanceColor = stats.currentBalance >= startingBalance ? "text-green-600" : "text-red-500";
  const pnlColor     = stats.totalPnl$ >= 0 ? "text-green-600" : "text-red-500";

  const riskMap: Record<number, RiskPosition> = {};
  (riskDash?.positions ?? []).forEach(rp => { riskMap[rp.id] = rp; });

  const AGENTS = [
    { key: "agent1" as AgentKey,         label: "Pre-Gainer",   color: "blue",   emoji: "🎯", data: stats.a1, positions: stats.a1Open, bg: "bg-blue-50 border-blue-100",     txt: "text-blue-700" },
    { key: "agent2" as AgentKey,         label: "Accumulation", color: "purple", emoji: "📦", data: stats.a2, positions: stats.a2Open, bg: "bg-purple-50 border-purple-100", txt: "text-purple-700" },
    { key: "agent3" as AgentKey,         label: "Momentum",     color: "orange", emoji: "🔥", data: stats.a3, positions: stats.a3Open, bg: "bg-orange-50 border-orange-100", txt: "text-orange-700" },
    { key: "agent_bigmover" as AgentKey, label: "Big Mover",    color: "amber",  emoji: "💥", data: stats.bm, positions: stats.bmOpen, bg: "bg-amber-50 border-amber-100",   txt: "text-amber-700" },
  ];

  const hasOpen = stats.a1Open.length > 0 || stats.a2Open.length > 0 || stats.a3Open.length > 0 || stats.bmOpen.length > 0;

  return (
    <div className="space-y-5">
      <GateBanner gate={riskDash?.gate} />

      {/* Balance banner */}
      <div className="rounded-2xl bg-gradient-to-br from-neutral-900 via-neutral-800 to-neutral-900 text-white overflow-hidden p-5">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <p className="text-xs text-neutral-400 mb-1 font-semibold uppercase tracking-wider">Simulasi Paper Trading</p>
            <div className="flex items-baseline gap-2">
              <span className={`text-4xl font-black tabular-nums ${balanceColor}`}>${stats.currentBalance.toFixed(2)}</span>
              <span className={`text-sm font-bold ${pnlColor}`}>{stats.totalPnl$ >= 0 ? "+" : ""}${stats.totalPnl$.toFixed(2)}</span>
            </div>
            <p className="text-xs text-neutral-400 mt-1">
              Modal awal <strong className="text-neutral-200">${startingBalance.toLocaleString()}</strong>
              {" · "}Risk <strong className="text-yellow-300">${riskDollar.toFixed(0)}/trade (1%)</strong>
              {" · "}Target R:R ≥ 1:3
            </p>
          </div>
          <div className="grid grid-cols-2 gap-2 text-center">
            {[
              { label: "Open",   value: stats.open,    color: "text-blue-400"    },
              { label: "Closed", value: stats.closed,  color: "text-neutral-200" },
              { label: "Win",    value: stats.wins,    color: "text-green-400"   },
              { label: "Loss",   value: stats.losses,  color: "text-red-400"     },
            ].map(s => (
              <div key={s.label} className="bg-white/5 rounded-xl px-3 py-2">
                <p className={`text-2xl font-black ${s.color}`}>{s.value}</p>
                <p className="text-[9px] text-neutral-400">{s.label}</p>
              </div>
            ))}
          </div>
        </div>

        {stats.closed > 0 && (
          <div className="mt-4">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-xs text-neutral-400 font-semibold">Win Rate</span>
              <span className={`text-sm font-black ${stats.winRate >= 50 ? "text-green-400" : "text-red-400"}`}>{stats.winRate.toFixed(0)}%</span>
            </div>
            <div className="h-2 bg-neutral-700 rounded-full overflow-hidden">
              <div className={`h-full rounded-full transition-all duration-700 ${stats.winRate >= 60 ? "bg-green-500" : stats.winRate >= 50 ? "bg-yellow-500" : "bg-red-500"}`}
                style={{ width: `${Math.min(stats.winRate, 100)}%` }} />
            </div>
            <div className="flex justify-between text-[9px] text-neutral-500 mt-0.5">
              <span>Target 80%</span>
              <span className="text-neutral-300">{stats.wins}W / {stats.losses}L dari {stats.closed} trades</span>
            </div>
          </div>
        )}
      </div>

      <FuturesWallet onChanged={onWalletChanged} />

      {/* Phase 1 T1 — Big Movers Watchlist (manual override) */}
      <BigMoversWatchlist onChanged={onRefresh} />

      {/* Open positions */}
      {hasOpen && (
        <div>
          <h3 className="text-sm font-bold text-neutral-700 mb-3 flex items-center gap-2">
            🔵 Posisi Terbuka ({stats.open})
            <span className="text-[10px] text-neutral-400 font-normal">— Dipisah per strategi</span>
            {agentFilter !== "all" && (
              <button onClick={() => setAgentFilter("all")} className="text-[10px] text-teal-600 font-semibold underline ml-1">
                Filter: {agentFilter === "agent1" ? "Pre-Gainer" : agentFilter === "agent2" ? "Accumulation" : agentFilter === "agent3" ? "Momentum" : "Big Mover"} ✕
              </button>
            )}
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {AGENTS.map(a => {
              if (agentFilter !== "all" && agentFilter !== a.key) return null;
              const atRisk =
                a.key === "agent1" ? riskDash?.agent_breakdown.agent1.at_risk
                : a.key === "agent2" ? riskDash?.agent_breakdown.agent2.at_risk
                : a.key === "agent3" ? riskDash?.agent_breakdown.agent3?.at_risk
                : riskDash?.agent_breakdown.agent_bigmover?.at_risk;
              return (
                <div key={a.key} className={`border rounded-2xl overflow-hidden ${a.bg}`}>
                  <div className="px-4 py-2.5 border-b flex items-center gap-2" style={{ borderColor: "inherit" }}>
                    <span className={`text-xs font-bold ${a.txt}`}>{a.emoji} {a.label}</span>
                    <span className="ml-auto text-[10px] text-neutral-500">{a.positions.length} open</span>
                    {(atRisk ?? 0) > 0 && <span className="text-[9px] text-red-600 font-bold bg-red-100 px-1.5 py-0.5 rounded">⚠️ AT RISK</span>}
                  </div>
                  {a.positions.length === 0
                    ? <div className="text-center py-6 text-neutral-400 text-xs">Tidak ada posisi terbuka</div>
                    : <div className="p-2 space-y-1.5">{a.positions.map(p => <OpenPosCard key={p.id} p={p} risk={riskMap[p.id]} riskDollar={riskDollar} />)}</div>
                  }
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Agent comparison */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {AGENTS.map(a => {
          const rateColor = a.data.rate >= 60 ? "text-green-600" : a.data.rate >= 50 ? "text-yellow-600" : a.data.total > 0 ? "text-red-500" : "text-neutral-400";
          const borderCls =
            a.color === "blue"   ? "border-blue-200 bg-blue-50"     :
            a.color === "purple" ? "border-purple-200 bg-purple-50" :
            a.color === "orange" ? "border-orange-200 bg-orange-50" :
                                   "border-amber-200 bg-amber-50";
          const badgeCls =
            a.color === "blue"   ? "bg-blue-100 text-blue-700"     :
            a.color === "purple" ? "bg-purple-100 text-purple-700" :
            a.color === "orange" ? "bg-orange-100 text-orange-700" :
                                   "bg-amber-100 text-amber-700";
          const ringCls =
            a.color === "blue"   ? "ring-blue-400"   :
            a.color === "purple" ? "ring-purple-400" :
            a.color === "orange" ? "ring-orange-400" :
                                   "ring-amber-400";
          return (
            <div key={a.key} onClick={() => setAgentFilter(agentFilter === a.key ? "all" : a.key)}
              className={`rounded-2xl border-2 p-4 cursor-pointer transition-all ${agentFilter === a.key ? `${borderCls} ring-2 ring-offset-1 ${ringCls}` : "border-neutral-200 bg-white hover:border-neutral-300"}`}>
              <div className="flex items-center gap-2 mb-2">
                <span className="text-lg">{a.emoji}</span>
                <span className={`text-[10px] font-bold px-2 py-0.5 rounded ${badgeCls}`}>{a.label}</span>
              </div>
              {a.data.total > 0 ? (
                <>
                  <p className={`text-3xl font-black ${rateColor}`}>{a.data.rate.toFixed(0)}%</p>
                  <p className="text-[10px] text-neutral-400">{a.data.wins}/{a.data.total} trades closed</p>
                  <p className={`text-sm font-bold mt-1 ${a.data.pnl$ >= 0 ? "text-green-600" : "text-red-500"}`}>
                    {a.data.pnl$ >= 0 ? "+" : ""}${a.data.pnl$.toFixed(2)}
                  </p>
                </>
              ) : <p className="text-sm text-neutral-400 mt-1">Belum ada trades</p>}
            </div>
          );
        })}
      </div>

      {/* Monthly win rate */}
      {learning?.monthly_stats && learning.monthly_stats.length > 0 && (
        <div className="bg-white border border-neutral-200 rounded-2xl p-4">
          <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
            <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider">📅 Win Rate Bulanan — per Strategi</p>
            <select value={selectedMonth} onChange={e => setSelectedMonth(e.target.value)}
              className="text-xs border border-neutral-200 rounded-lg px-2 py-1 bg-white text-neutral-700 focus:outline-none">
              <option value="all">Semua bulan</option>
              {learning.monthly_stats.map(m => <option key={m.month} value={m.month}>{fmtMonth(m.month)}</option>)}
            </select>
          </div>
          <div className="space-y-3">
            {learning.monthly_stats.filter(m => selectedMonth === "all" || m.month === selectedMonth).map(m => (
              <div key={m.month} className={`rounded-xl p-3 ${selectedMonth === m.month ? "bg-teal-50 border border-teal-200" : "bg-neutral-50"}`}>
                <div className="flex items-center justify-between mb-2">
                  <p className="text-xs font-bold text-neutral-700">{fmtMonth(m.month)}</p>
                  <div className="flex gap-3 text-[10px] text-neutral-500">
                    <span>Pre: {m.agent1.wins}/{m.agent1.total}</span>
                    <span>Acc: {m.agent2.wins}/{m.agent2.total}</span>
                    {m.agent3 && <span>Momo: {m.agent3.wins}/{m.agent3.total}</span>}
                  </div>
                </div>
                <div className="space-y-1.5">
                  <WinRateBar rate={m.agent1.win_rate} label={`🎯 Pre-Gainer: ${m.agent1.win_rate.toFixed(0)}%`} />
                  <WinRateBar rate={m.agent2.win_rate} label={`📦 Accumulation: ${m.agent2.win_rate.toFixed(0)}%`} />
                  {m.agent3 && <WinRateBar rate={m.agent3.win_rate} label={`🔥 Momentum: ${m.agent3.win_rate.toFixed(0)}%`} />}
                </div>
              </div>
            ))}
          </div>
          {selectedMonth !== "all" && (
            <div className="mt-2 text-center">
              <button onClick={() => setSelectedMonth("all")} className="text-xs text-neutral-400 hover:text-neutral-600 underline">Tampilkan semua bulan</button>
            </div>
          )}
        </div>
      )}

      {/* Regime + monitor status */}
      {learning && (
        <div className="flex flex-wrap gap-2 items-center">
          {(() => {
            const cfg = REGIME_CFG[learning.regime] ?? { emoji: "🔍", label: learning.regime, cls: "bg-neutral-100 text-neutral-600 border-neutral-300" };
            return (
              <span className={`flex items-center gap-1.5 text-xs font-bold px-3 py-1.5 rounded-full border ${cfg.cls}`}>
                {cfg.emoji} Regime: {cfg.label}
              </span>
            );
          })()}
          {learning.monitor?.running && (
            <span className="flex items-center gap-1.5 text-xs font-semibold text-teal-700 bg-teal-50 border border-teal-200 px-3 py-1.5 rounded-full">
              <span className="w-1.5 h-1.5 rounded-full bg-teal-500 animate-pulse" />
              Monitor aktif · Liq Guards: {learning.monitor.liq_guards ?? 0} · TP Extended: {learning.monitor.tp_extended ?? 0}
            </span>
          )}
          {learning.overall.closed > 0 && (
            <span className={`text-xs font-bold px-3 py-1.5 rounded-full border ${
              learning.overall.win_rate >= TARGET_WIN_RATE ? "bg-green-100 text-green-700 border-green-300" : "bg-yellow-100 text-yellow-700 border-yellow-300"
            }`}>
              {learning.overall.win_rate.toFixed(0)}% / {TARGET_WIN_RATE}% target{learning.overall.win_rate >= TARGET_WIN_RATE ? " 🎯" : ""}
            </span>
          )}
        </div>
      )}

      {/* Win rate trend */}
      {learning && learning.win_rate_trend.length > 2 && (
        <div className="bg-white border border-neutral-200 rounded-2xl p-4">
          <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider mb-3">📊 Win Rate Trend (rolling 10 trades)</p>
          <div className="flex items-end gap-0.5 h-12">
            {learning.win_rate_trend.map((pt, i) => {
              const h = Math.max((pt.win_rate / 100) * 100, 4);
              const cls = pt.win_rate >= TARGET_WIN_RATE ? "bg-green-500" : pt.win_rate >= 50 ? "bg-yellow-400" : "bg-red-400";
              return <div key={i} title={`Trade #${pt.trade_n}: ${pt.win_rate}%`} className={`flex-1 min-w-[4px] rounded-t ${cls}`} style={{ height: `${h}%` }} />;
            })}
          </div>
          <div className="flex justify-between text-[9px] text-neutral-400 mt-1">
            <span>0%</span>
            <span className="text-green-600 font-semibold">Target {TARGET_WIN_RATE}%</span>
            <span>100%</span>
          </div>
        </div>
      )}

      {/* Equity chart */}
      {equityPoints.length > 1 && (
        <div className="bg-white border border-neutral-200 rounded-2xl p-4">
          <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider mb-3">📈 Pertumbuhan Balance (per trade)</p>
          <div className="flex items-end gap-0.5 h-16">
            {equityPoints.map((pt, i) => {
              const minBal    = Math.min(...equityPoints.map(p => p.balance));
              const maxBal    = Math.max(...equityPoints.map(p => p.balance));
              const heightPct = ((pt.balance - minBal) / Math.max(maxBal - minBal, 1)) * 100;
              return (
                <div key={i} title={pt.n === 0 ? `Start $${pt.balance.toFixed(0)}` : `#${pt.n} ${pt.symbol} → $${pt.balance.toFixed(0)}`}
                  className={`flex-1 min-w-[3px] rounded-t transition-all ${i === 0 ? "bg-neutral-300" : pt.win ? "bg-green-400" : "bg-red-400"}`}
                  style={{ height: `${Math.max(heightPct, 5)}%` }} />
              );
            })}
          </div>
          <div className="flex justify-between text-[9px] text-neutral-400 mt-1">
            <span>${startingBalance.toLocaleString()} start</span>
            <span className={`font-bold ${balanceColor}`}>${stats.currentBalance.toFixed(0)} sekarang</span>
          </div>
        </div>
      )}

      {/* Position sizing info */}
      <div className="bg-amber-50 border border-amber-200 rounded-2xl p-4">
        <p className="text-xs font-bold text-amber-700 uppercase tracking-wider mb-2">💡 Logika Position Sizing</p>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-center">
          {[
            { label: "Modal Awal",   value: `$${startingBalance.toLocaleString()}`,          sub: "paper balance"   },
            { label: "Risk/Trade",   value: `$${riskDollar.toFixed(0)} (1%)`,                sub: "fixed per trade" },
            { label: "R:R Minimum",  value: "1 : 3",                                         sub: `win $${(riskDollar * 3).toFixed(0)}, lose $${riskDollar.toFixed(0)}` },
            { label: "Auto-Open",    value: autoThreshold != null ? `≥ ${autoThreshold}pt` : "—", sub: "score threshold" },
          ].map(x => (
            <div key={x.label} className="bg-white/60 rounded-xl p-2.5">
              <p className="text-[10px] text-amber-600 font-semibold">{x.label}</p>
              <p className="text-base font-black text-neutral-800">{x.value}</p>
              <p className="text-[9px] text-neutral-400">{x.sub}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Live indicator */}
      <div className="flex items-center justify-end gap-2">
        <div className="flex items-center gap-1.5 px-2 py-1 rounded-full bg-blue-50 border border-blue-200">
          <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
          <span className="text-[10px] font-bold text-blue-700">LIVE</span>
          <span className="text-[10px] text-blue-600 tabular-nums">{countdown}s</span>
        </div>
        {lastUpdated && <p className="text-[10px] text-neutral-400">{lastUpdated.toLocaleTimeString()}</p>}
        <button onClick={onRefresh} disabled={loading} className="text-xs text-teal-600 hover:text-teal-500 font-semibold disabled:opacity-40">
          {loading ? "..." : "↺"}
        </button>
      </div>

      {/* DB History */}
      <div className="bg-white border border-neutral-200 rounded-2xl overflow-hidden">
        <div className="px-5 py-3 border-b border-neutral-100 bg-neutral-50">
          <h3 className="font-bold text-sm text-neutral-700">🗄 Riwayat Database — Futures Agents 1, 2, 3</h3>
          <p className="text-[10px] text-neutral-400 mt-0.5">Semua trade · search simbol · pagination · alasan tutup posisi lengkap</p>
        </div>
        <div className="p-4">
          <DBHistoryTable
            defaultStyle="futures"
            hideStyleTabs={false}
            compact={true}
            reasonScope="futures"
            styleOptions={[
              { key: "futures",        label: "Semua" },
              { key: "agent1",         label: "🎯 Pre-Gainer" },
              { key: "agent2",         label: "📦 Accumulation" },
              { key: "agent3",         label: "🔥 Momentum" },
              { key: "agent_bigmover", label: "💥 Big Mover" },
            ]}
          />
        </div>
      </div>
    </div>
  );
}
