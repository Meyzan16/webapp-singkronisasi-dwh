"use client";
import { useCallback, useEffect, useState } from "react";

// ── Types ─────────────────────────────────────────────────────────────────────

interface AgentStat {
  label:       string;
  win_rate:    number;
  total:       number;
  wins:        number;
  avg_pnl_pct: number;
  weight:      number;
}

interface SignalRow {
  signal_key:    string;
  agents:        Record<string, AgentStat>;
  best_win_rate: number;
  best_avg_pnl:  number;
  total_trades:  number;
  cross_weight:  number | null;
}

interface CrossSignalRow {
  signal_key:      string;
  cross_weight:    number;
  cross_win_rate:  number;
  cross_total:     number;
  avg_pnl_pct:     number;
  agent_count:     number;
  agents:          Record<string, { label: string; win_rate: number; total: number; weight: number }>;
  reliability:     "high" | "medium" | "low";
}

interface UpdaterState {
  futures: { last_run?: number; last_error?: string; cached_agents?: string[] };
  spot:    { last_run?: number; last_error?: string; last_count?: number };
  cross:   { last_run?: number; last_error?: string; cached_keys?: number };
}

interface PerformanceResponse {
  signals: SignalRow[];
  meta:    { total: number; shown: number };
}

interface CrossResponse {
  signals: CrossSignalRow[];
  meta:    { total: number };
}

type SubTab = "overview" | "spot" | "futures" | "cross";
type SortBy = "win_rate" | "avg_pnl_pct" | "total_count" | "weight";

const AGENT_TABS = [
  { key: "opportunity_spot", label: "SPOT",          color: "text-teal-700",   bg: "bg-teal-100 border-teal-200" },
  { key: "futures_agent1",   label: "Pre-Gainer",    color: "text-blue-700",   bg: "bg-blue-100 border-blue-200" },
  { key: "futures_agent2",   label: "Accumulation",  color: "text-purple-700", bg: "bg-purple-100 border-purple-200" },
  { key: "futures_agent3",   label: "Momentum",      color: "text-orange-700", bg: "bg-orange-100 border-orange-200" },
];

// ── WeightBar ─────────────────────────────────────────────────────────────────

function WeightBar({ weight }: { weight: number }) {
  const pct = Math.round(((weight - 0.7) / (1.5 - 0.7)) * 100);
  const cls = weight >= 1.3 ? "bg-green-500" : weight >= 1.1 ? "bg-teal-400" : weight >= 0.9 ? "bg-neutral-300" : "bg-red-400";
  const txt = weight >= 1.3 ? "text-green-700" : weight >= 1.1 ? "text-teal-700" : weight >= 0.9 ? "text-neutral-500" : "text-red-600";
  return (
    <div className="flex items-center gap-1.5">
      <div className="w-16 h-1.5 bg-neutral-100 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${cls}`} style={{ width: `${Math.max(4, pct)}%` }} />
      </div>
      <span className={`text-[10px] font-bold tabular-nums ${txt}`}>×{weight.toFixed(2)}</span>
    </div>
  );
}

// ── WinRateBadge ──────────────────────────────────────────────────────────────

function WinRateBadge({ rate, total }: { rate: number; total: number }) {
  const cls = total < 5 ? "text-neutral-400" : rate >= 65 ? "text-green-600" : rate >= 50 ? "text-yellow-600" : "text-red-500";
  return (
    <div className="text-right">
      <p className={`text-sm font-black tabular-nums ${cls}`}>{rate.toFixed(0)}%</p>
      <p className="text-[9px] text-neutral-400">{total} trades</p>
    </div>
  );
}

// ── ReliabilityBadge ──────────────────────────────────────────────────────────

function ReliabilityBadge({ r }: { r: "high" | "medium" | "low" }) {
  const map = {
    high:   "bg-green-100 text-green-700 border-green-200",
    medium: "bg-yellow-100 text-yellow-700 border-yellow-200",
    low:    "bg-neutral-100 text-neutral-500 border-neutral-200",
  };
  return (
    <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded-full border ${map[r]}`}>
      {r === "high" ? "✦ High" : r === "medium" ? "◈ Med" : "◇ Low"}
    </span>
  );
}

// ── UpdaterStatus ─────────────────────────────────────────────────────────────

function UpdaterStatus({ state, onForce }: { state: UpdaterState | null; onForce: () => void }) {
  const fmt = (ts?: number) => ts ? new Date(ts * 1000).toLocaleTimeString("id-ID") : "—";
  const items = [
    { label: "SPOT",        last: state?.spot?.last_run,    error: state?.spot?.last_error,    extra: state?.spot?.last_count != null ? `${state.spot.last_count} keys` : "" },
    { label: "Futures",     last: state?.futures?.last_run, error: state?.futures?.last_error, extra: (state?.futures?.cached_agents ?? []).join(", ") || "" },
    { label: "Cross-Agent", last: state?.cross?.last_run,   error: state?.cross?.last_error,   extra: state?.cross?.cached_keys != null ? `${state.cross.cached_keys} keys` : "" },
  ];
  return (
    <div className="bg-white border border-neutral-200 rounded-2xl p-4">
      <div className="flex items-center justify-between mb-3">
        <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider">⚙️ Learning Loop Status</p>
        <button onClick={onForce}
          className="text-xs bg-teal-600 text-white px-3 py-1 rounded-lg font-semibold hover:bg-teal-500 transition-colors">
          ↺ Force Update
        </button>
      </div>
      <div className="grid grid-cols-3 gap-3">
        {items.map(x => (
          <div key={x.label} className={`rounded-xl p-3 ${x.error ? "bg-red-50 border border-red-100" : "bg-neutral-50"}`}>
            <p className="text-[10px] font-bold text-neutral-500 uppercase mb-1">{x.label}</p>
            <p className="text-xs font-mono font-semibold text-neutral-800">{fmt(x.last)}</p>
            {x.extra && <p className="text-[9px] text-neutral-400 mt-0.5">{x.extra}</p>}
            {x.error && <p className="text-[9px] text-red-500 mt-0.5 truncate">{x.error}</p>}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── SortTh ───────────────────────────────────────────────────────────────────

function SortTh({ col, label, sortBy, setSortBy, sortDir, setSortDir }: {
  col: SortBy; label: string;
  sortBy: SortBy; setSortBy: (s: SortBy) => void;
  sortDir: "desc" | "asc"; setSortDir: (d: "desc" | "asc") => void;
}) {
  return (
    <button className="flex items-center gap-0.5 hover:text-neutral-700 transition-colors"
      onClick={() => {
        if (sortBy === col) setSortDir(sortDir === "desc" ? "asc" : "desc");
        else { setSortBy(col); setSortDir("desc"); }
      }}>
      {label}
      <span className="text-[10px]">{sortBy === col ? (sortDir === "desc" ? "↓" : "↑") : "↕"}</span>
    </button>
  );
}

// ── SignalTable ───────────────────────────────────────────────────────────────

function SignalTable({ signals, agentKey, sortBy, setSortBy, sortDir, setSortDir }: {
  signals: SignalRow[];
  agentKey: string;
  sortBy: SortBy;
  setSortBy: (s: SortBy) => void;
  sortDir: "desc" | "asc";
  setSortDir: (d: "desc" | "asc") => void;
}) {
  if (signals.length === 0) return (
    <div className="text-center py-10 text-neutral-400 text-sm">Belum ada data sinyal dengan filter ini</div>
  );

  return (
    <div className="overflow-hidden rounded-xl border border-neutral-200">
      <div className="grid grid-cols-[1fr_auto_auto_auto_auto] gap-x-4 px-4 py-2 bg-neutral-50 border-b border-neutral-200 text-[10px] font-bold text-neutral-400 uppercase tracking-wider">
        <span>Signal</span>
        <SortTh col="win_rate"    label="Win Rate" sortBy={sortBy} setSortBy={setSortBy} sortDir={sortDir} setSortDir={setSortDir} />
        <SortTh col="avg_pnl_pct" label="Avg PnL%" sortBy={sortBy} setSortBy={setSortBy} sortDir={sortDir} setSortDir={setSortDir} />
        <SortTh col="total_count" label="Trades"   sortBy={sortBy} setSortBy={setSortBy} sortDir={sortDir} setSortDir={setSortDir} />
        <SortTh col="weight"      label="Weight"   sortBy={sortBy} setSortBy={setSortBy} sortDir={sortDir} setSortDir={setSortDir} />
      </div>
      <div className="divide-y divide-neutral-100">
        {signals.map(s => {
          const agentData = agentKey === "all"
            ? Object.values(s.agents)[0]
            : s.agents[agentKey];
          if (!agentData) return null;
          return (
            <div key={s.signal_key} className="grid grid-cols-[1fr_auto_auto_auto_auto] gap-x-4 px-4 py-2.5 items-center hover:bg-neutral-50">
              <div>
                <p className="text-xs font-semibold text-neutral-800 font-mono truncate max-w-xs">
                  {s.signal_key.replace(/_/g, " ")}
                </p>
                {s.cross_weight && (
                  <span className="text-[9px] text-purple-600 font-semibold">
                    cross ×{s.cross_weight.toFixed(2)}
                  </span>
                )}
              </div>
              <WinRateBadge rate={agentData.win_rate} total={agentData.total} />
              <div className="text-right w-16">
                <span className={`text-xs font-bold tabular-nums ${agentData.avg_pnl_pct > 0 ? "text-green-600" : agentData.avg_pnl_pct < 0 ? "text-red-500" : "text-neutral-400"}`}>
                  {agentData.avg_pnl_pct > 0 ? "+" : ""}{agentData.avg_pnl_pct.toFixed(1)}%
                </span>
              </div>
              <div className="text-right w-12">
                <span className="text-xs text-neutral-600 tabular-nums">{agentData.total}</span>
              </div>
              <WeightBar weight={agentData.weight} />
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── CrossAgentTable ───────────────────────────────────────────────────────────

function CrossAgentTable({ signals }: { signals: CrossSignalRow[] }) {
  if (signals.length === 0) return (
    <div className="text-center py-10 text-neutral-400 text-sm">
      Belum ada sinyal dengan data cross-agent yang cukup (min 10 trades)
    </div>
  );

  return (
    <div className="space-y-2">
      {signals.map(s => (
        <div key={s.signal_key} className="bg-white border border-neutral-200 rounded-xl p-3">
          <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs font-bold font-mono text-neutral-800">
                {s.signal_key.replace(/_/g, " ")}
              </span>
              <ReliabilityBadge r={s.reliability} />
              <span className="text-[9px] text-neutral-400">{s.agent_count} agen · {s.cross_total} trades</span>
            </div>
            <div className="flex items-center gap-3">
              <div className="text-right">
                <p className={`text-sm font-black ${s.cross_win_rate >= 65 ? "text-green-600" : s.cross_win_rate >= 50 ? "text-yellow-600" : "text-red-500"}`}>
                  {s.cross_win_rate.toFixed(0)}%
                </p>
                <p className="text-[9px] text-neutral-400">win rate</p>
              </div>
              <div className="text-right">
                <p className={`text-sm font-black ${s.avg_pnl_pct > 0 ? "text-green-600" : "text-red-500"}`}>
                  {s.avg_pnl_pct > 0 ? "+" : ""}{s.avg_pnl_pct.toFixed(1)}%
                </p>
                <p className="text-[9px] text-neutral-400">avg PnL</p>
              </div>
              <WeightBar weight={s.cross_weight} />
            </div>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(s.agents).map(([agent, data]) => (
              <div key={agent} className="bg-neutral-50 rounded-lg px-2 py-1 text-[10px]">
                <span className="text-neutral-500">{data.label}: </span>
                <span className={`font-bold ${data.win_rate >= 60 ? "text-green-600" : data.win_rate >= 50 ? "text-yellow-600" : "text-red-500"}`}>
                  {data.win_rate.toFixed(0)}%
                </span>
                <span className="text-neutral-400"> ({data.total})</span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function SignalsPage() {
  const [subTab,      setSubTab]      = useState<SubTab>("overview");
  const [agentFilter, setAgentFilter] = useState("opportunity_spot");
  const [sortBy,      setSortBy]      = useState<SortBy>("win_rate");
  const [sortDir,     setSortDir]     = useState<"desc" | "asc">("desc");
  const [minTrades,   setMinTrades]   = useState(3);
  const [perfData,    setPerfData]    = useState<PerformanceResponse | null>(null);
  const [crossData,   setCrossData]   = useState<CrossResponse | null>(null);
  const [updaterState,setUpdaterState]= useState<UpdaterState | null>(null);
  const [loading,     setLoading]     = useState(true);
  const [forceMsg,    setForceMsg]    = useState<string | null>(null);

  const fetchAll = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const [perfRes, crossRes, stateRes] = await Promise.all([
        fetch(`/api/v1/signals/performance?agent=all&regime=all&min_trades=${minTrades}&sort_by=${sortBy}&sort_dir=${sortDir}&limit=50`),
        fetch(`/api/v1/signals/cross_agent?min_trades=5`),
        fetch("/api/v1/signals/updater/state"),
      ]);
      if (perfRes.ok)  setPerfData(await perfRes.json() as PerformanceResponse);
      if (crossRes.ok) setCrossData(await crossRes.json() as CrossResponse);
      if (stateRes.ok) setUpdaterState(await stateRes.json() as UpdaterState);
    } catch { /* stale */ }
    finally { if (!silent) setLoading(false); }
  }, [minTrades, sortBy, sortDir]);

  useEffect(() => { void fetchAll(); }, [fetchAll]);

  const handleForce = async () => {
    setForceMsg("Memperbarui...");
    try {
      const r = await fetch("/api/v1/signals/updater/run", { method: "POST" });
      if (r.ok) {
        const d = await r.json() as { updated: Record<string, number | string> };
        setForceMsg(`Selesai: SPOT=${d.updated.spot} · Futures=${d.updated.futures} · Cross=${d.updated.cross}`);
        void fetchAll(true);
      }
    } catch { setForceMsg("Error — coba lagi"); }
    setTimeout(() => setForceMsg(null), 5000);
  };

  const allSignals = perfData?.signals ?? [];
  const spotSignals = allSignals.filter(s => s.agents["opportunity_spot"]);
  const futSignals  = allSignals.filter(s =>
    s.agents["futures_agent1"] || s.agents["futures_agent2"] || s.agents["futures_agent3"]
  );
  const crossSignals = crossData?.signals ?? [];

  const topSpot    = [...allSignals].filter(s => s.agents["opportunity_spot"]).slice(0, 3);
  const topFutures = [...allSignals].filter(s =>
    s.agents["futures_agent1"] || s.agents["futures_agent2"] || s.agents["futures_agent3"]
  ).slice(0, 3);
  const topCross   = crossSignals.filter(s => s.reliability === "high").slice(0, 3);

  const subTabBar = (
    <div className="flex gap-1 bg-neutral-100 p-1 rounded-xl w-fit">
      {([
        { key: "overview", label: "📊 Overview"    },
        { key: "spot",     label: "🎯 SPOT"        },
        { key: "futures",  label: "⚡ Futures"     },
        { key: "cross",    label: "🔗 Cross-Agent" },
      ] as { key: SubTab; label: string }[]).map(t => (
        <button key={t.key} onClick={() => setSubTab(t.key)}
          className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all ${subTab === t.key ? "bg-white text-neutral-900 shadow-sm" : "text-neutral-500 hover:text-neutral-700"}`}>
          {t.label}
        </button>
      ))}
    </div>
  );

  return (
    <div className="space-y-5 max-w-6xl">
      {/* Header */}
      <div className="rounded-2xl bg-gradient-to-br from-neutral-900 via-neutral-800 to-neutral-900 text-white p-5">
        <p className="text-xs text-neutral-400 uppercase tracking-wider font-semibold mb-1">🧠 Adaptive Learning</p>
        <h1 className="text-2xl font-black mb-1">Signal Performance</h1>
        <p className="text-sm text-neutral-400">
          Setiap sinyal dilacak dari entry → close. Weight naik bila sinyal profitable,
          turun bila sering loss. Agents saling belajar via cross-agent blending.
        </p>
        {forceMsg && (
          <p className="mt-2 text-xs text-teal-300 font-semibold">{forceMsg}</p>
        )}
      </div>

      {subTabBar}

      {loading ? (
        <div className="flex items-center justify-center py-16 text-neutral-400 gap-2">
          <div className="w-5 h-5 border-2 border-teal-400 border-t-transparent rounded-full animate-spin" />
          Memuat data sinyal...
        </div>
      ) : (
        <>
          {/* ── OVERVIEW ─────────────────────────────────────────────────── */}
          {subTab === "overview" && (
            <div className="space-y-5">
              {/* Summary strip */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                {[
                  { label: "Total Signal Keys", val: perfData?.meta.total ?? 0,    color: "text-neutral-800" },
                  { label: "SPOT Signals",       val: spotSignals.length,            color: "text-teal-600"    },
                  { label: "Futures Signals",    val: futSignals.length,             color: "text-blue-600"    },
                  { label: "Cross-Agent",        val: crossSignals.length,           color: "text-purple-600"  },
                ].map(x => (
                  <div key={x.label} className="bg-white border border-neutral-200 rounded-2xl p-4 text-center">
                    <p className={`text-3xl font-black ${x.color}`}>{x.val}</p>
                    <p className="text-[10px] text-neutral-400 mt-0.5 font-semibold uppercase">{x.label}</p>
                  </div>
                ))}
              </div>

              {/* Top signals preview */}
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                {[
                  { title: "🎯 Top SPOT Signals",     signals: topSpot,    agentKey: "opportunity_spot" },
                  { title: "⚡ Top Futures Signals",  signals: topFutures, agentKey: "futures_agent2"  },
                  { title: "🔗 Proven Cross-Agent",   signals: topCross,   agentKey: "cross"           },
                ].map(col => (
                  <div key={col.title} className="bg-white border border-neutral-200 rounded-2xl p-4">
                    <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider mb-3">{col.title}</p>
                    {col.signals.length === 0 ? (
                      <p className="text-xs text-neutral-400 text-center py-4">Belum ada data</p>
                    ) : col.agentKey === "cross" ? (
                      <div className="space-y-2">
                        {(col.signals as CrossSignalRow[]).map(s => (
                          <div key={s.signal_key} className="flex items-center justify-between py-1.5 border-b border-neutral-50 last:border-0">
                            <div className="flex-1 min-w-0">
                              <p className="text-[11px] font-semibold text-neutral-700 truncate font-mono">
                                {s.signal_key.replace(/_/g, " ")}
                              </p>
                              <p className="text-[9px] text-neutral-400">{s.agent_count} agen · {s.cross_total} trades</p>
                            </div>
                            <WinRateBadge rate={s.cross_win_rate} total={s.cross_total} />
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="space-y-2">
                        {(col.signals as SignalRow[]).map(s => {
                          const d = s.agents[col.agentKey] ?? Object.values(s.agents)[0];
                          if (!d) return null;
                          return (
                            <div key={s.signal_key} className="flex items-center justify-between py-1.5 border-b border-neutral-50 last:border-0">
                              <div className="flex-1 min-w-0">
                                <p className="text-[11px] font-semibold text-neutral-700 truncate font-mono">
                                  {s.signal_key.replace(/_/g, " ")}
                                </p>
                                <WeightBar weight={d.weight} />
                              </div>
                              <WinRateBadge rate={d.win_rate} total={d.total} />
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                ))}
              </div>

              {/* Updater status */}
              <UpdaterStatus state={updaterState} onForce={handleForce} />
            </div>
          )}

          {/* ── SPOT ─────────────────────────────────────────────────────── */}
          {subTab === "spot" && (
            <div className="space-y-4">
              <div className="flex flex-wrap gap-2 items-center">
                <span className="text-xs text-neutral-500">{spotSignals.length} sinyal · min {minTrades} trades</span>
                <div className="flex bg-neutral-100 rounded-xl p-1 gap-0.5 ml-auto">
                  {[3, 5, 10].map(n => (
                    <button key={n} onClick={() => setMinTrades(n)}
                      className={`px-3 py-1 rounded-lg text-xs font-semibold transition-all ${minTrades === n ? "bg-white text-neutral-900 shadow-sm" : "text-neutral-500"}`}>
                      ≥{n}
                    </button>
                  ))}
                </div>
              </div>
              <SignalTable signals={spotSignals} agentKey="opportunity_spot"
                sortBy={sortBy} setSortBy={setSortBy} sortDir={sortDir} setSortDir={setSortDir} />
            </div>
          )}

          {/* ── FUTURES ──────────────────────────────────────────────────── */}
          {subTab === "futures" && (
            <div className="space-y-4">
              <div className="flex flex-wrap gap-2 items-center">
                <div className="flex gap-1 bg-neutral-100 p-1 rounded-xl">
                  {AGENT_TABS.map(a => (
                    <button key={a.key} onClick={() => setAgentFilter(a.key)}
                      className={`px-3 py-1 rounded-lg text-xs font-bold transition-all ${agentFilter === a.key ? `bg-white shadow-sm ${a.color}` : "text-neutral-500 hover:text-neutral-700"}`}>
                      {a.label}
                    </button>
                  ))}
                </div>
                <div className="flex bg-neutral-100 rounded-xl p-1 gap-0.5 ml-auto">
                  {[3, 5, 10].map(n => (
                    <button key={n} onClick={() => setMinTrades(n)}
                      className={`px-3 py-1 rounded-lg text-xs font-semibold transition-all ${minTrades === n ? "bg-white text-neutral-900 shadow-sm" : "text-neutral-500"}`}>
                      ≥{n}
                    </button>
                  ))}
                </div>
              </div>
              <SignalTable
                signals={futSignals.filter(s => s.agents[agentFilter])}
                agentKey={agentFilter}
                sortBy={sortBy} setSortBy={setSortBy} sortDir={sortDir} setSortDir={setSortDir}
              />
            </div>
          )}

          {/* ── CROSS-AGENT ───────────────────────────────────────────────── */}
          {subTab === "cross" && (
            <div className="space-y-4">
              <div className="bg-purple-50 border border-purple-100 rounded-2xl p-4 text-sm text-purple-800">
                <p className="font-bold mb-1">🔗 Cross-Agent Learning</p>
                <p className="text-xs text-purple-600">
                  Sinyal di bawah terbukti menghasilkan profit di <strong>lebih dari satu agen</strong>.
                  Weight cross-agent (30%) dicampur dengan weight agen sendiri (70%) untuk
                  meningkatkan scoring secara konsisten.
                  Hanya aktif jika total ≥ 10 trades gabungan.
                </p>
              </div>
              <CrossAgentTable signals={crossSignals} />
            </div>
          )}
        </>
      )}
    </div>
  );
}
