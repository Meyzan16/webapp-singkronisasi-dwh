"use client";
import { useEffect, useState, useCallback } from "react";

// ── Types ─────────────────────────────────────────────────────────────────────

interface LearningStats {
  regime:          string;
  target_win_rate: number;
  overall:         { total: number; open: number; closed: number; wins: number; losses: number; win_rate: number };
  agent1:          { total: number; wins: number; losses: number; win_rate: number };
  agent2:          { total: number; wins: number; losses: number; win_rate: number };
  agent3:          { total: number; wins: number; losses: number; win_rate: number };
  balance:         { starting: number; current: number; total_pnl: number; roi_pct: number };
  equity_points:   { trade_n: number; balance: number; symbol: string; win: boolean; agent: string; ts: number | null }[];
  conservative_equity: { trade_n: number; balance: number }[];
  win_rate_trend:  { trade_n: number; win_rate: number; win: boolean }[];
  top_signals:     { key: string; agent: string; win_rate: number; weight: number; total: number; wins: number }[];
  bottom_signals:  { key: string; agent: string; win_rate: number; weight: number; total: number }[];
  regime_breakdown: { regime: string; total: number; wins: number; win_rate: number; pnl_dollar: number }[];
  direction_stats: {
    long:  { total: number; wins: number; win_rate: number };
    short: { total: number; wins: number; win_rate: number };
  };
  leverage_dist:   Record<string, number>;
  monitor:         { running: boolean; cycle_count: number; closed_today: number };
}

interface SignalWeight {
  agent:       string;
  signal_key:  string;
  weight:      number;
  win_rate:    number;
  win_count:   number;
  total_count: number;
  regime:      string;
  updated_at:  number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const TARGET = 80;   // F30: starting balance now comes from stats.balance.starting (no hardcode)

const REGIME_CFG: Record<string, { emoji: string; label: string; bar: string; bg: string }> = {
  trending_up:   { emoji: "📈", label: "Trending Up",   bar: "bg-green-500",  bg: "bg-green-50 border-green-200"   },
  trending_down: { emoji: "📉", label: "Trending Down", bar: "bg-red-500",    bg: "bg-red-50 border-red-200"       },
  ranging:       { emoji: "↔️", label: "Ranging",       bar: "bg-blue-500",   bg: "bg-blue-50 border-blue-200"     },
  volatile:      { emoji: "⚡", label: "Volatile",      bar: "bg-orange-500", bg: "bg-orange-50 border-orange-200" },
  unknown:       { emoji: "❓", label: "Unknown",       bar: "bg-neutral-400",bg: "bg-neutral-50 border-neutral-200"},
};

function winsNeeded(currentWins: number, totalClosed: number, target = TARGET): number | null {
  if (totalClosed < 5) return null;
  // solve: (currentWins + x) / (totalClosed + x) = target/100
  // x(1 - target/100) = target/100 * totalClosed - currentWins
  const t   = target / 100;
  const num = t * totalClosed - currentWins;
  const den = 1 - t;
  if (den <= 0) return 0;
  return num <= 0 ? 0 : Math.ceil(num / den);
}

// ── Equity dual line chart ────────────────────────────────────────────────────

function EquityDualChart({
  leveraged, conservative, start,
}: {
  leveraged:    { trade_n: number; balance: number; win: boolean }[];
  conservative: { trade_n: number; balance: number }[];
  start:        number;   // F30: starting balance from API
}) {
  const START = start;
  if (leveraged.length < 2) return (
    <div className="text-center py-8 text-neutral-400 text-sm">Butuh minimal 2 closed trades</div>
  );

  const allBalances = [...leveraged.map(p => p.balance), ...conservative.map(p => p.balance), START];
  const minB = Math.min(...allBalances) * 0.98;
  const maxB = Math.max(...allBalances) * 1.02;
  const range = Math.max(maxB - minB, 1);
  const n = leveraged.length;

  const toY = (b: number) => 100 - ((b - minB) / range) * 100;
  const toX = (i: number) => (i / Math.max(n - 1, 1)) * 100;

  // Build SVG path strings
  const levPath = leveraged
    .map((p, i) => `${i === 0 ? "M" : "L"}${toX(i).toFixed(1)},${toY(p.balance).toFixed(1)}`)
    .join(" ");

  const conPath = conservative
    .map((p, i) => `${i === 0 ? "M" : "L"}${toX(i).toFixed(1)},${toY(p.balance).toFixed(1)}`)
    .join(" ");

  const lastLev  = leveraged[leveraged.length - 1].balance;
  const lastCon  = conservative[conservative.length - 1]?.balance ?? START;
  const startLine = toY(START);

  return (
    <div className="space-y-2">
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="w-full h-36 overflow-visible">
        {/* Start baseline */}
        <line x1="0" y1={startLine} x2="100" y2={startLine}
          stroke="#d1d5db" strokeWidth="0.4" strokeDasharray="2,2" />
        {/* Conservative (flat R:R) */}
        <path d={conPath} fill="none" stroke="#94a3b8" strokeWidth="0.8" strokeDasharray="3,2" />
        {/* Leveraged (actual) */}
        <path d={levPath} fill="none" stroke="#14b8a6" strokeWidth="1.2" />
        {/* Dots for each trade */}
        {leveraged.map((p, i) => (
          <circle key={i} cx={toX(i)} cy={toY(p.balance)} r="0.8"
            fill={p.win ? "#22c55e" : "#ef4444"} />
        ))}
      </svg>
      {/* Legend */}
      <div className="flex items-center gap-4 text-[10px] flex-wrap">
        <span className="flex items-center gap-1.5 text-teal-600 font-bold">
          <span className="w-4 h-0.5 bg-teal-500 inline-block rounded" />
          Actual: <span className={lastLev >= START ? "text-green-600" : "text-red-500"}>
            ${lastLev.toFixed(0)}
          </span>
        </span>
        <span className="flex items-center gap-1.5 text-neutral-500">
          <span className="w-4 h-px bg-neutral-400 inline-block rounded border-t-2 border-dashed" />
          Flat R:R (1:3): <span className={lastCon >= START ? "text-green-500" : "text-red-400"}>
            ${lastCon.toFixed(0)}
          </span>
        </span>
        <span className="flex items-center gap-1.5 text-neutral-400">
          <span className="w-2 h-2 rounded-full bg-green-500 inline-block" />Win
          <span className="w-2 h-2 rounded-full bg-red-500 inline-block ml-1" />Loss
        </span>
      </div>
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

export function FuturesAnalytics() {
  const [stats,    setStats]   = useState<LearningStats | null>(null);
  const [weights,  setWeights] = useState<SignalWeight[]>([]);
  const [loading,  setLoading] = useState(true);
  const [lastUpd,  setLastUpd] = useState<Date | null>(null);
  const [wAgent,   setWAgent]  = useState<"all" | "agent1" | "agent2" | "agent3">("all");
  const [wSort,    setWSort]   = useState<"win_rate" | "weight" | "total">("win_rate");
  const [updating, setUpdating]= useState(false);

  const fetchAll = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const [sRes, wRes] = await Promise.all([
        fetch("/api/v1/futures/learning/stats"),
        fetch("/api/v1/futures/learning/weights"),
      ]);
      if (sRes.ok) {
        const d = await sRes.json() as LearningStats;
        if (!("error" in d)) setStats(d);
      }
      if (wRes.ok) {
        const d = await wRes.json() as { weights: SignalWeight[] };
        setWeights(d.weights ?? []);
      }
      setLastUpd(new Date());
    } catch { /* silent */ }
    finally { if (!silent) setLoading(false); }
  }, []);

  const forceUpdate = async () => {
    setUpdating(true);
    try {
      await fetch("/api/v1/futures/learning/update", { method: "POST" });
      await fetchAll(true);
    } finally { setUpdating(false); }
  };

  useEffect(() => {
    void fetchAll();
    // F31: auto-refresh every 60s so analytics stay live without manual Update
    const poll = setInterval(() => { void fetchAll(true); }, 60_000);
    return () => clearInterval(poll);
  }, [fetchAll]);

  // ── Derived ────────────────────────────────────────────────────────────────

  const displayWeights = [...weights]
    .filter(w => wAgent === "all" || w.agent === `futures_${wAgent}`)
    .filter(w => w.regime === "all")
    .sort((a, b) =>
      wSort === "win_rate" ? b.win_rate - a.win_rate :
      wSort === "weight"   ? b.weight - a.weight :
      b.total_count - a.total_count
    );

  // ── Loading / no data ──────────────────────────────────────────────────────

  if (loading) return (
    <div className="flex items-center justify-center py-20 text-neutral-400">
      <div className="w-8 h-8 border-2 border-teal-400 border-t-transparent rounded-full animate-spin mr-3" />
      Memuat analytics...
    </div>
  );

  if (!stats || stats.overall.closed === 0) return (
    <div className="text-center py-20 text-neutral-400">
      <p className="text-4xl mb-3">📊</p>
      <p className="font-semibold text-neutral-600">Belum ada closed trades untuk dianalisis</p>
      <p className="text-sm mt-2">Buka posisi di Scanner Futures → tunggu TP/SL → analytics akan terisi</p>
    </div>
  );

  const needed = winsNeeded(stats.overall.wins, stats.overall.closed);
  const balanceColor = stats.balance.total_pnl >= 0 ? "text-green-600" : "text-red-500";

  return (
    <div className="space-y-5">

      {/* ── Header bar ──────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-base font-bold text-neutral-800">Futures Analytics</h2>
          <p className="text-xs text-neutral-400">
            {stats.overall.closed} closed trades · {lastUpd?.toLocaleTimeString()}
          </p>
        </div>
        <button onClick={() => void forceUpdate()} disabled={updating}
          className="text-xs bg-teal-600 hover:bg-teal-500 disabled:opacity-40 text-white font-semibold px-3 py-1.5 rounded-lg flex items-center gap-1.5">
          {updating
            ? <><span className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />Updating...</>
            : "🔄 Update Weights"}
        </button>
      </div>

      {/* ══════════════════════════════════════════════════════════════════════
          A. AGENT 1 VS AGENT 2 COMPARISON
      ══════════════════════════════════════════════════════════════════════ */}
      <div className="bg-white border border-neutral-200 rounded-2xl overflow-hidden">
        <div className="px-5 py-3 border-b border-neutral-100 bg-neutral-50">
          <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider">🎯 Pre-Gainer vs 📦 Accumulation vs 🔥 Momentum</p>
        </div>
        <div className="p-5 space-y-5">

          {/* Head-to-head summary cards (3 lanes) */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {[
              { key: "agent1", label: "Agent 1 — Pre-Gainer", emoji: "🎯",
                data: stats.agent1, color: "border-blue-200 bg-blue-50", badge: "bg-blue-100 text-blue-700" },
              { key: "agent2", label: "Agent 2 — Accumulation", emoji: "📦",
                data: stats.agent2, color: "border-purple-200 bg-purple-50", badge: "bg-purple-100 text-purple-700" },
              { key: "agent3", label: "Agent 3 — Momentum", emoji: "🔥",
                data: stats.agent3, color: "border-orange-200 bg-orange-50", badge: "bg-orange-100 text-orange-700" },
            ].map(a => {
              const wr = a.data.win_rate;
              const wrColor = wr >= TARGET ? "text-green-600" : wr >= 50 ? "text-yellow-600" : "text-red-500";
              return (
                <div key={a.key} className={`rounded-2xl border-2 p-4 ${a.color}`}>
                  <div className="flex items-center gap-2 mb-3">
                    <span className="text-lg">{a.emoji}</span>
                    <span className={`text-[10px] font-bold px-2 py-0.5 rounded ${a.badge}`}>{a.label}</span>
                  </div>
                  {a.data.total > 0 ? (
                    <>
                      <p className={`text-4xl font-black tabular-nums ${wrColor}`}>{wr.toFixed(0)}%</p>
                      <p className="text-xs text-neutral-500 mt-0.5">Win Rate</p>
                      <div className="mt-2 h-1.5 bg-white/60 rounded-full overflow-hidden">
                        <div className={`h-full rounded-full ${wr >= TARGET ? "bg-green-500" : wr >= 50 ? "bg-yellow-400" : "bg-red-400"}`}
                          style={{ width: `${Math.min(wr, 100)}%` }} />
                      </div>
                      <div className="mt-3 grid grid-cols-3 gap-1 text-center">
                        {[
                          { l: "Total",  v: String(a.data.total) },
                          { l: "Win",    v: String(a.data.wins)  },
                          { l: "Loss",   v: String(a.data.losses)},
                        ].map(x => (
                          <div key={x.l} className="bg-white/50 rounded-lg py-1.5">
                            <p className="text-sm font-black">{x.v}</p>
                            <p className="text-[9px] text-neutral-400">{x.l}</p>
                          </div>
                        ))}
                      </div>
                    </>
                  ) : (
                    <p className="text-sm text-neutral-400 mt-2">Belum ada trades</p>
                  )}
                </div>
              );
            })}
          </div>


          {/* Direction stats */}
          {(stats.direction_stats.long.total > 0 || stats.direction_stats.short.total > 0) && (
            <div className="grid grid-cols-2 gap-2">
              {[
                { dir: "LONG",  data: stats.direction_stats.long,  color: "text-green-600", bg: "bg-green-50 border-green-200" },
                { dir: "SHORT", data: stats.direction_stats.short, color: "text-red-500",   bg: "bg-red-50 border-red-200"     },
              ].map(d => (
                <div key={d.dir} className={`rounded-xl border p-3 ${d.bg}`}>
                  <p className={`text-[10px] font-bold ${d.color} mb-1`}>{d.dir === "LONG" ? "▲" : "▼"} {d.dir}</p>
                  {d.data.total > 0 ? (
                    <>
                      <p className={`text-2xl font-black ${d.color}`}>{d.data.win_rate.toFixed(0)}%</p>
                      <p className="text-[9px] text-neutral-400">{d.data.wins}/{d.data.total} closed</p>
                    </>
                  ) : <p className="text-xs text-neutral-400">No data</p>}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ══════════════════════════════════════════════════════════════════════
          B. LEARNING PROGRESS BAR
      ══════════════════════════════════════════════════════════════════════ */}
      <div className="bg-white border border-neutral-200 rounded-2xl overflow-hidden">
        <div className="px-5 py-3 border-b border-neutral-100 bg-neutral-50">
          <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider">🎯 Learning Progress → Target {TARGET}%</p>
        </div>
        <div className="p-5 space-y-4">

          {/* Overall progress */}
          <div>
            <div className="flex items-end justify-between mb-2">
              <div>
                <span className={`text-5xl font-black tabular-nums ${
                  stats.overall.win_rate >= TARGET ? "text-green-600" : stats.overall.win_rate >= 60 ? "text-yellow-500" : "text-red-500"
                }`}>
                  {stats.overall.win_rate.toFixed(1)}%
                </span>
                <span className="text-neutral-400 text-sm ml-2">/ {TARGET}% target</span>
              </div>
              {stats.overall.win_rate >= TARGET
                ? <span className="text-green-600 font-bold text-sm">🎉 Target tercapai!</span>
                : needed != null
                  ? <span className="text-xs text-neutral-500">Butuh <strong className="text-neutral-700">{needed} win berturut-turut</strong> untuk mencapai {TARGET}%</span>
                  : null
              }
            </div>
            <div className="relative h-4 bg-neutral-100 rounded-full overflow-hidden">
              {/* Target marker */}
              <div className="absolute top-0 bottom-0 w-0.5 bg-green-500/50 z-10"
                style={{ left: `${TARGET}%` }} />
              <div
                className={`h-full rounded-full transition-all duration-1000 ${
                  stats.overall.win_rate >= TARGET ? "bg-green-500"
                  : stats.overall.win_rate >= 60 ? "bg-yellow-400" : "bg-red-400"
                }`}
                style={{ width: `${Math.min(stats.overall.win_rate, 100)}%` }}
              />
            </div>
            <div className="flex justify-between text-[9px] text-neutral-400 mt-1">
              <span>0%</span>
              <span className="text-green-600 font-bold">🎯 {TARGET}%</span>
              <span>100%</span>
            </div>
          </div>

          {/* Per-agent progress */}
          <div className="space-y-3 pt-1 border-t border-neutral-100">
            {[
              { label: "Agent 1 — Pre-Gainer",   data: stats.agent1, bar: "bg-blue-500" },
              { label: "Agent 2 — Accumulation",  data: stats.agent2, bar: "bg-purple-500" },
              { label: "Agent 3 — Momentum",      data: stats.agent3, bar: "bg-orange-500" },
            ].map(a => (
              <div key={a.label}>
                <div className="flex justify-between text-xs mb-1">
                  <span className="text-neutral-600 font-semibold">{a.label}</span>
                  <span className={`font-black ${a.data.win_rate >= TARGET ? "text-green-600" : "text-neutral-600"}`}>
                    {a.data.total > 0 ? `${a.data.win_rate.toFixed(0)}%` : "—"}
                  </span>
                </div>
                <div className="h-2 bg-neutral-100 rounded-full overflow-hidden">
                  <div className={`h-full ${a.bar} rounded-full transition-all duration-700`}
                    style={{ width: `${Math.min(a.data.win_rate, 100)}%` }} />
                </div>
                {a.data.total > 0 && (
                  <p className="text-[9px] text-neutral-400 mt-0.5">{a.data.wins}W / {a.data.losses}L dari {a.data.total} trades</p>
                )}
              </div>
            ))}
          </div>

          {/* Stats chips */}
          <div className="flex gap-2 flex-wrap">
            {[
              { label: "Total Trades", value: String(stats.overall.total) },
              { label: "Closed",       value: String(stats.overall.closed) },
              { label: "Open",         value: String(stats.overall.open), cls: "border-blue-200 text-blue-600" },
              { label: "Wins",         value: String(stats.overall.wins),   cls: "border-green-200 text-green-600" },
              { label: "Losses",       value: String(stats.overall.losses), cls: "border-red-200 text-red-500"   },
            ].map(x => (
              <div key={x.label} className={`border rounded-xl px-3 py-1.5 text-center ${x.cls ?? "border-neutral-200 text-neutral-700"}`}>
                <p className="text-base font-black">{x.value}</p>
                <p className="text-[9px] opacity-70">{x.label}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ══════════════════════════════════════════════════════════════════════
          C. CUMULATIVE P&L WITH LEVERAGE
      ══════════════════════════════════════════════════════════════════════ */}
      <div className="bg-white border border-neutral-200 rounded-2xl overflow-hidden">
        <div className="px-5 py-3 border-b border-neutral-100 bg-neutral-50 flex items-center justify-between">
          <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider">📈 Cumulative P&L — Actual vs Flat R:R</p>
          <div className="flex gap-3 text-xs">
            <span className={`font-black ${stats.balance.total_pnl >= 0 ? "text-green-600" : "text-red-500"}`}>
              {stats.balance.total_pnl >= 0 ? "+" : ""}${stats.balance.total_pnl.toFixed(2)}
            </span>
            <span className={`font-semibold ${stats.balance.roi_pct >= 0 ? "text-green-500" : "text-red-400"}`}>
              ({stats.balance.roi_pct >= 0 ? "+" : ""}{stats.balance.roi_pct.toFixed(1)}% ROI)
            </span>
          </div>
        </div>
        <div className="p-5">
          <EquityDualChart leveraged={stats.equity_points} conservative={stats.conservative_equity} start={stats.balance.starting} />

          {/* Leverage distribution */}
          {Object.keys(stats.leverage_dist).length > 0 && (
            <div className="mt-4 pt-4 border-t border-neutral-100">
              <p className="text-[10px] font-bold text-neutral-500 uppercase tracking-wider mb-2">Distribusi Leverage</p>
              <div className="flex gap-2 flex-wrap">
                {Object.entries(stats.leverage_dist)
                  .sort(([a], [b]) => parseInt(a) - parseInt(b))
                  .map(([lev, count]) => (
                    <div key={lev} className="bg-neutral-100 rounded-lg px-3 py-1.5 text-center">
                      <p className="text-sm font-black text-neutral-700">{lev}</p>
                      <p className="text-[9px] text-neutral-400">{count} trades</p>
                    </div>
                  ))}
              </div>
            </div>
          )}

          {/* Balance summary */}
          <div className="mt-4 grid grid-cols-3 gap-2">
            {[
              { label: "Modal Awal",   value: `$${stats.balance.starting.toFixed(0)}`,          cls: "text-neutral-700" },
              { label: "Balance Kini", value: `$${stats.balance.current.toFixed(2)}`,            cls: balanceColor       },
              { label: "Total P&L",   value: `${stats.balance.total_pnl >= 0 ? "+" : ""}$${stats.balance.total_pnl.toFixed(2)}`, cls: balanceColor },
            ].map(x => (
              <div key={x.label} className="bg-neutral-50 rounded-xl p-3 text-center">
                <p className="text-[10px] text-neutral-400 font-semibold mb-0.5">{x.label}</p>
                <p className={`text-base font-black tabular-nums ${x.cls}`}>{x.value}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ══════════════════════════════════════════════════════════════════════
          D. REGIME ANALYSIS
      ══════════════════════════════════════════════════════════════════════ */}
      {stats.regime_breakdown.length > 0 && (
        <div className="bg-white border border-neutral-200 rounded-2xl overflow-hidden">
          <div className="px-5 py-3 border-b border-neutral-100 bg-neutral-50">
            <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider">🌍 Win Rate per Market Regime</p>
          </div>
          <div className="p-5 grid grid-cols-2 md:grid-cols-4 gap-3">
            {stats.regime_breakdown
              .sort((a, b) => b.total - a.total)
              .map(r => {
                const cfg = REGIME_CFG[r.regime] ?? REGIME_CFG.unknown;
                const wrColor = r.win_rate >= TARGET ? "text-green-600" : r.win_rate >= 50 ? "text-yellow-600" : r.total > 0 ? "text-red-500" : "text-neutral-400";
                return (
                  <div key={r.regime} className={`rounded-2xl border p-4 ${cfg.bg}`}>
                    <div className="flex items-center gap-1.5 mb-2">
                      <span className="text-base">{cfg.emoji}</span>
                      <span className="text-[10px] font-bold text-neutral-600">{cfg.label}</span>
                    </div>
                    <p className={`text-3xl font-black tabular-nums ${wrColor}`}>
                      {r.total > 0 ? `${r.win_rate.toFixed(0)}%` : "—"}
                    </p>
                    <p className="text-[10px] text-neutral-400 mt-0.5">{r.wins}/{r.total} trades</p>
                    <div className="mt-2 h-1.5 bg-white/60 rounded-full overflow-hidden">
                      <div className={`h-full ${cfg.bar} rounded-full`} style={{ width: `${Math.min(r.win_rate, 100)}%` }} />
                    </div>
                    <p className={`text-[10px] font-semibold mt-1.5 ${r.pnl_dollar >= 0 ? "text-green-600" : "text-red-500"}`}>
                      {r.pnl_dollar >= 0 ? "+" : ""}${r.pnl_dollar.toFixed(1)} P&L
                    </p>
                  </div>
                );
              })}
          </div>
        </div>
      )}

      {/* ══════════════════════════════════════════════════════════════════════
          E. SIGNAL PERFORMANCE TABLE
      ══════════════════════════════════════════════════════════════════════ */}
      <div className="bg-white border border-neutral-200 rounded-2xl overflow-hidden">
        <div className="px-5 py-3 border-b border-neutral-100 bg-neutral-50 flex items-center justify-between flex-wrap gap-2">
          <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider">🔬 Signal Performance Table</p>
          <div className="flex gap-2">
            {/* Agent filter */}
            <div className="flex gap-1 bg-neutral-100 p-0.5 rounded-lg">
              {(["all", "agent1", "agent2", "agent3"] as const).map(a => (
                <button key={a} onClick={() => setWAgent(a)}
                  className={`px-2 py-0.5 rounded text-[10px] font-bold transition-all ${
                    wAgent === a ? "bg-white text-neutral-800 shadow-sm" : "text-neutral-500"
                  }`}>
                  {a === "all" ? "All" : a === "agent1" ? "Pre" : a === "agent2" ? "Accum" : "Momo"}
                </button>
              ))}
            </div>
            {/* Sort */}
            <select value={wSort} onChange={e => setWSort(e.target.value as typeof wSort)}
              className="text-[10px] border border-neutral-200 rounded-lg px-2 py-1 bg-white focus:outline-none">
              <option value="win_rate">Sort: Win Rate</option>
              <option value="weight">Sort: Weight</option>
              <option value="total">Sort: Trades</option>
            </select>
          </div>
        </div>

        {displayWeights.length === 0 ? (
          <div className="text-center py-10 text-neutral-400 text-sm">
            {weights.length === 0
              ? "Belum ada signal weights — klik Update Weights setelah ada closed trades"
              : "Tidak ada signal untuk filter ini"}
          </div>
        ) : (
          <>
            {/* Header */}
            <div className="hidden sm:grid grid-cols-12 gap-2 px-5 py-2 bg-neutral-50 border-b text-[10px] font-bold text-neutral-400 uppercase tracking-wider">
              <span className="col-span-5">Signal</span>
              <span className="col-span-2 text-center">Agent</span>
              <span className="col-span-2 text-right">Win Rate</span>
              <span className="col-span-1 text-right">Weight</span>
              <span className="col-span-2 text-right">Trades</span>
            </div>
            <div className="divide-y divide-neutral-50 max-h-80 overflow-y-auto">
              {displayWeights.map((w, i) => {
                const wrColor  = w.win_rate >= 70 ? "text-green-600" : w.win_rate >= 50 ? "text-yellow-600" : "text-red-500";
                const wBadge   = w.weight >= 1.4 ? "bg-green-100 text-green-700" : w.weight >= 1.1 ? "bg-blue-100 text-blue-700" : w.weight < 0.9 ? "bg-red-100 text-red-600" : "bg-neutral-100 text-neutral-600";
                const aBadge   = w.agent === "futures_agent1" ? "bg-blue-100 text-blue-700" : w.agent === "futures_agent3" ? "bg-orange-100 text-orange-700" : "bg-purple-100 text-purple-700";
                return (
                  <div key={i} className="grid grid-cols-12 gap-2 px-5 py-2.5 hover:bg-neutral-50 items-center">
                    <div className="col-span-5 min-w-0">
                      <p className="text-xs text-neutral-700 truncate">{w.signal_key.replace(/_/g, " ")}</p>
                    </div>
                    <div className="col-span-2 text-center">
                      <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${aBadge}`}>
                        {w.agent === "futures_agent1" ? "Pre" : w.agent === "futures_agent3" ? "Momo" : "Accum"}
                      </span>
                    </div>
                    <div className="col-span-2 text-right">
                      <p className={`text-sm font-black tabular-nums ${wrColor}`}>{w.win_rate.toFixed(0)}%</p>
                    </div>
                    <div className="col-span-1 text-right">
                      <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${wBadge}`}>×{w.weight.toFixed(1)}</span>
                    </div>
                    <div className="col-span-2 text-right">
                      <p className="text-xs text-neutral-500">{w.win_count}/{w.total_count}</p>
                    </div>
                  </div>
                );
              })}
            </div>
          </>
        )}
      </div>

    </div>
  );
}
