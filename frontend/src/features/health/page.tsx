"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { HealthEventLog } from "./components/HealthEventLog";

// ── Types ──────────────────────────────────────────────────────────────────────

interface AgentState {
  running: boolean;
  cycle_count?: number;
  interval_minutes?: number;
  next_scan_in_min?: number | null;
  last_error?: string | null;
  last_scan?: number | null;
}

interface WeightUpdaterState {
  last_run?: number | null;
  last_error?: string | null;
}

interface Health {
  status: string;
  db: string;
  database?: string;
  spot_scanner?:    AgentState;
  spot_monitor?:    AgentState;
  futures_scanner?: AgentState;
  futures_monitor?: AgentState;
  weight_updater?:  WeightUpdaterState;
}

interface BinanceStatus {
  spot_ok:              boolean;
  futures_ok:           boolean;
  spot_latency_ms:      number | null;
  futures_latency_ms:   number | null;
  spot_weight_used:     number;
  futures_weight_used:  number;
  spot_weight_pct:      number;
  futures_weight_pct:   number;
  spot_banned_until:    number | null;
  futures_banned_until: number | null;
  spot_error:           string | null;
  futures_error:        string | null;
  checked_at:           number;
}

const POLL_MS = 10_000;

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtRelTime(ts: number | null | undefined): string {
  if (!ts) return "—";
  const diff = Math.floor(Date.now() / 1000 - ts);
  if (diff < 5)    return "baru saja";
  if (diff < 60)   return `${diff}d lalu`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m lalu`;
  return `${Math.floor(diff / 3600)}j lalu`;
}

function fmtBanTime(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" });
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function StatusDot({ ok, pulse }: { ok: boolean; pulse?: boolean }) {
  return (
    <span className={`inline-block w-2.5 h-2.5 rounded-full shrink-0 ${
      ok ? "bg-green-500" : "bg-red-500"
    } ${ok && pulse ? "animate-pulse" : ""}`} />
  );
}

function RateBar({ pct, banned }: { pct: number; banned?: boolean }) {
  const color = banned ? "bg-red-500"
    : pct > 70 ? "bg-orange-500"
    : pct > 40 ? "bg-yellow-400"
    : "bg-green-400";
  const textColor = banned ? "text-red-600"
    : pct > 70 ? "text-orange-600"
    : pct > 40 ? "text-yellow-600"
    : "text-neutral-500";
  return (
    <div className="flex items-center gap-2 mt-1">
      <div className="flex-1 h-2 bg-neutral-100 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${color}`}
          style={{ width: `${Math.min(pct, 100)}%` }}
        />
      </div>
      <span className={`text-[11px] font-bold tabular-nums w-8 text-right ${textColor}`}>
        {pct.toFixed(0)}%
      </span>
    </div>
  );
}

function AgentCard({
  icon, label, sub, color, state, extraRows,
}: {
  icon: string;
  label: string;
  sub: string;
  color: string;
  state: AgentState | undefined;
  extraRows?: React.ReactNode;
}) {
  const running = state?.running ?? false;
  return (
    <div className={`rounded-2xl border p-4 ${running
      ? "bg-green-50/40 border-green-200"
      : "bg-red-50/30 border-red-200"
    }`}>
      <div className="flex items-start justify-between gap-2 mb-3">
        <div className="flex items-center gap-2">
          <span className="text-xl">{icon}</span>
          <div>
            <p className="font-bold text-sm text-neutral-800">{label}</p>
            <p className="text-[10px] text-neutral-500 font-mono">{sub}</p>
          </div>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <StatusDot ok={running} pulse={running} />
          <span className={`text-xs font-bold ${running ? "text-green-700" : "text-red-500"}`}>
            {running ? "Running" : "Stopped"}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
        <div>
          <p className="text-[10px] text-neutral-400 uppercase tracking-wide font-semibold">Siklus</p>
          <p className="font-black text-neutral-700 text-sm">{state?.cycle_count ?? "—"}</p>
        </div>
        {state?.interval_minutes != null && (
          <div>
            <p className="text-[10px] text-neutral-400 uppercase tracking-wide font-semibold">Interval</p>
            <p className="font-bold text-neutral-600">{state.interval_minutes}m</p>
          </div>
        )}
        {state?.next_scan_in_min != null && (
          <div>
            <p className="text-[10px] text-neutral-400 uppercase tracking-wide font-semibold">Next Scan</p>
            <p className="font-bold text-blue-600">{state.next_scan_in_min.toFixed(1)} mnt</p>
          </div>
        )}
        {state?.last_scan != null && (
          <div>
            <p className="text-[10px] text-neutral-400 uppercase tracking-wide font-semibold">Last Scan</p>
            <p className="font-bold text-neutral-600">{fmtRelTime(state.last_scan)}</p>
          </div>
        )}
        {extraRows}
      </div>

      {state?.last_error && (
        <div className="mt-3 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
          <p className="text-[10px] font-bold text-red-600 mb-0.5">Last Error</p>
          <p className="text-[10px] text-red-500 font-mono break-all">{state.last_error}</p>
        </div>
      )}
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function HealthPage() {
  const [health,   setHealth]   = useState<Health | null>(null);
  const [binance,  setBinance]  = useState<BinanceStatus | null>(null);
  const [lastPoll, setLastPoll] = useState<Date | null>(null);
  const [loading,  setLoading]  = useState(true);
  const [countdown, setCountdown] = useState(POLL_MS / 1000);
  const countRef = useRef(POLL_MS / 1000);

  const fetchAll = useCallback(async () => {
    try {
      const [healthR, binanceR] = await Promise.allSettled([
        fetch("/health"),
        fetch("/api/v1/market/binance-status"),
      ]);
      if (healthR.status === "fulfilled" && healthR.value.ok)
        setHealth(await healthR.value.json() as Health);
      if (binanceR.status === "fulfilled" && binanceR.value.ok)
        setBinance(await binanceR.value.json() as BinanceStatus);
      setLastPoll(new Date());
    } catch { /* silent */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { void fetchAll(); }, [fetchAll]);
  useEffect(() => {
    const poll = setInterval(() => {
      void fetchAll();
      countRef.current = POLL_MS / 1000;
      setCountdown(POLL_MS / 1000);
    }, POLL_MS);
    const tick = setInterval(() => {
      countRef.current = Math.max(0, countRef.current - 1);
      setCountdown(countRef.current);
    }, 1000);
    return () => { clearInterval(poll); clearInterval(tick); };
  }, [fetchAll]);

  const backendOk = !!health;
  const dbOk      = health?.db === "ok";

  // Overall system health score
  const checks = [
    backendOk,
    dbOk,
    binance?.spot_ok ?? false,
    binance?.futures_ok ?? false,
    health?.spot_scanner?.running ?? false,
    health?.spot_monitor?.running ?? false,
    health?.futures_scanner?.running ?? false,
    health?.futures_monitor?.running ?? false,
  ];
  const passCount = checks.filter(Boolean).length;
  const allOk = passCount === checks.length;
  const overallColor = allOk ? "text-green-600" : passCount >= 6 ? "text-yellow-600" : "text-red-600";
  const overallBg    = allOk ? "from-green-50 to-white border-green-200"
    : passCount >= 6  ? "from-yellow-50 to-white border-yellow-200"
    : "from-red-50 to-white border-red-200";

  if (loading) return (
    <div className="flex items-center justify-center h-48">
      <div className="w-8 h-8 border-2 border-teal-400 border-t-transparent rounded-full animate-spin" />
    </div>
  );

  return (
    <div className="space-y-6 max-w-6xl mx-auto">

      {/* ── Header ────────────────────────────────────────────────────────── */}
      <div className={`rounded-2xl border bg-gradient-to-r p-5 ${overallBg}`}>
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-2xl font-black text-neutral-900">⚙️ System Health</h1>
            <p className="text-sm text-neutral-500 mt-0.5">
              Monitoring real-time · semua agent, API, database
            </p>
          </div>
          <div className="text-right">
            <p className={`text-4xl font-black tabular-nums ${overallColor}`}>
              {passCount}/{checks.length}
            </p>
            <p className="text-xs text-neutral-500">
              {allOk ? "Semua sistem normal ✅" : `${checks.length - passCount} masalah terdeteksi`}
            </p>
          </div>
        </div>

        {/* Live indicator */}
        <div className="flex items-center gap-3 mt-4">
          <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-green-100 border border-green-200">
            <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
            <span className="text-xs font-bold text-green-700">LIVE</span>
            <span className="text-xs text-green-600 tabular-nums">{countdown}s</span>
          </div>
          {lastPoll && (
            <span className="text-[11px] text-neutral-400">
              Terakhir: {lastPoll.toLocaleTimeString("id-ID")}
            </span>
          )}
        </div>
      </div>

      {/* ── Infrastructure: Backend + DB + Binance ─────────────────────── */}
      <div>
        <p className="text-xs font-black text-neutral-400 uppercase tracking-widest mb-3">🏗 Infrastruktur</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">

          {/* Backend */}
          <div className={`rounded-2xl border p-4 ${backendOk ? "bg-green-50/40 border-green-200" : "bg-red-50/30 border-red-200"}`}>
            <div className="flex items-center gap-2 mb-3">
              <StatusDot ok={backendOk} pulse />
              <span className="font-bold text-sm text-neutral-800">Backend API</span>
            </div>
            <p className="text-xs text-neutral-500 font-mono">FastAPI · Python 3.12</p>
            <p className={`text-lg font-black mt-2 ${backendOk ? "text-green-600" : "text-red-500"}`}>
              {backendOk ? "Online" : "Offline"}
            </p>
          </div>

          {/* Database */}
          <div className={`rounded-2xl border p-4 ${dbOk ? "bg-green-50/40 border-green-200" : "bg-red-50/30 border-red-200"}`}>
            <div className="flex items-center gap-2 mb-3">
              <StatusDot ok={dbOk} />
              <span className="font-bold text-sm text-neutral-800">Database</span>
            </div>
            <p className="text-xs text-neutral-500 font-mono">PostgreSQL 16</p>
            <p className={`text-lg font-black mt-2 ${dbOk ? "text-green-600" : "text-red-500"}`}>
              {dbOk ? "Connected" : health?.db === "unavailable" ? "Unavailable" : "—"}
            </p>
          </div>

          {/* Binance Spot */}
          {(() => {
            const ok     = binance?.spot_ok ?? false;
            const banned = binance?.spot_banned_until != null;
            const pct    = binance?.spot_weight_pct ?? 0;
            return (
              <div className={`rounded-2xl border p-4 ${banned ? "bg-red-50/50 border-red-300" : ok ? "bg-green-50/40 border-green-200" : "bg-red-50/30 border-red-200"}`}>
                <div className="flex items-center gap-2 mb-3">
                  <StatusDot ok={ok && !banned} />
                  <span className="font-bold text-sm text-neutral-800">Binance Spot</span>
                </div>
                <p className="text-xs text-neutral-500 font-mono">REST API · 1200 w/min</p>
                <p className={`text-lg font-black mt-2 ${banned ? "text-red-600" : ok ? "text-green-600" : "text-red-500"}`}>
                  {banned ? `BANNED` : ok ? `OK${binance?.spot_latency_ms != null ? ` · ${binance.spot_latency_ms}ms` : ""}` : "Down"}
                </p>
                {banned && binance?.spot_banned_until && (
                  <p className="text-xs text-red-500 font-bold">⛔ sampai {fmtBanTime(binance.spot_banned_until)}</p>
                )}
                <RateBar pct={pct} banned={banned} />
                <p className="text-[10px] text-neutral-400 mt-1">
                  Rate limit: {binance?.spot_weight_used ?? 0} / 1200
                </p>
                {!banned && binance?.spot_error && (
                  <p className="text-[10px] text-orange-500 mt-1 truncate" title={binance.spot_error}>
                    ⚠ {binance.spot_error}
                  </p>
                )}
              </div>
            );
          })()}

          {/* Binance Futures */}
          {(() => {
            const ok     = binance?.futures_ok ?? false;
            const banned = binance?.futures_banned_until != null;
            const pct    = binance?.futures_weight_pct ?? 0;
            return (
              <div className={`rounded-2xl border p-4 ${banned ? "bg-red-50/50 border-red-300" : ok ? "bg-green-50/40 border-green-200" : "bg-red-50/30 border-red-200"}`}>
                <div className="flex items-center gap-2 mb-3">
                  <StatusDot ok={ok && !banned} />
                  <span className="font-bold text-sm text-neutral-800">Binance Futures</span>
                </div>
                <p className="text-xs text-neutral-500 font-mono">FAPI · 2400 w/min</p>
                <p className={`text-lg font-black mt-2 ${banned ? "text-red-600" : ok ? "text-green-600" : "text-red-500"}`}>
                  {banned ? "BANNED" : ok ? `OK${binance?.futures_latency_ms != null ? ` · ${binance.futures_latency_ms}ms` : ""}` : "Down"}
                </p>
                {banned && binance?.futures_banned_until && (
                  <p className="text-xs text-red-500 font-bold">⛔ sampai {fmtBanTime(binance.futures_banned_until)}</p>
                )}
                <RateBar pct={pct} banned={banned} />
                <p className="text-[10px] text-neutral-400 mt-1">
                  Rate limit: {binance?.futures_weight_used ?? 0} / 2400
                </p>
                {!banned && binance?.futures_error && (
                  <p className="text-[10px] text-orange-500 mt-1 truncate" title={binance.futures_error}>
                    ⚠ {binance.futures_error}
                  </p>
                )}
              </div>
            );
          })()}
        </div>
      </div>

      {/* ── Futures Agents ─────────────────────────────────────────────────── */}
      <div>
        <p className="text-xs font-black text-blue-500 uppercase tracking-widest mb-3">⚡ Futures Agents</p>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          <AgentCard
            icon="🎯"
            label="Futures Scanner — Pre-Gainer"
            sub="agents/futures/agent1.py"
            color="blue"
            state={health?.futures_scanner}
          />
          <AgentCard
            icon="📦"
            label="Futures Scanner — Accumulation"
            sub="agents/futures/agent2.py"
            color="purple"
            state={health?.futures_scanner}
          />
          <AgentCard
            icon="🔥"
            label="Futures Scanner — Momentum"
            sub="agents/futures/agent3.py"
            color="orange"
            state={health?.futures_scanner}
          />
          <AgentCard
            icon="👁"
            label="Futures Position Monitor"
            sub="agents/futures/monitor.py"
            color="indigo"
            state={health?.futures_monitor}
          />
        </div>

        {/* Weight Updater */}
        <div className="mt-3">
          {(() => {
            const ws = health?.weight_updater;
            const ok = ws != null && !ws.last_error;
            return (
              <div className={`rounded-2xl border p-4 ${ok ? "bg-blue-50/30 border-blue-200" : "bg-neutral-50 border-neutral-200"}`}>
                <div className="flex items-start justify-between gap-3 flex-wrap">
                  <div className="flex items-center gap-2">
                    <StatusDot ok={ok} />
                    <div>
                      <p className="font-bold text-sm text-neutral-800">🧠 Weight Updater — Adaptive Learning</p>
                      <p className="text-[10px] text-neutral-500 font-mono">agents/futures/weight_updater.py · Auto-tune bobot sinyal per win rate</p>
                    </div>
                  </div>
                  <span className={`text-xs font-bold px-3 py-1 rounded-full border ${ok ? "bg-blue-100 text-blue-700 border-blue-200" : "bg-neutral-100 text-neutral-500 border-neutral-200"}`}>
                    {ok ? "Running" : "—"}
                  </span>
                </div>
                {ws?.last_run != null && (
                  <p className="text-[11px] text-neutral-400 mt-2">
                    Last run: {fmtRelTime(ws.last_run)}
                  </p>
                )}
                {ws?.last_error && (
                  <div className="mt-2 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
                    <p className="text-[10px] font-bold text-red-600 mb-0.5">Error</p>
                    <p className="text-[10px] text-red-500 font-mono break-all">{ws.last_error}</p>
                  </div>
                )}
              </div>
            );
          })()}
        </div>
      </div>

      {/* ── Spot Agents ────────────────────────────────────────────────────── */}
      <div>
        <p className="text-xs font-black text-teal-600 uppercase tracking-widest mb-3">🎯 Spot Agents</p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <AgentCard
            icon="🚀"
            label="Spot Opportunity Scanner"
            sub="agents/opportunity/scheduler.py"
            color="teal"
            state={health?.spot_scanner}
          />
          <AgentCard
            icon="👁"
            label="Spot Position Monitor"
            sub="agents/opportunity/monitor.py"
            color="amber"
            state={health?.spot_monitor}
          />
        </div>
      </div>

      {/* ── Binance API Detail ─────────────────────────────────────────────── */}
      {binance && (
        <div>
          <p className="text-xs font-black text-neutral-400 uppercase tracking-widest mb-3">🔗 Binance API Detail</p>
          <div className="bg-white rounded-2xl border border-neutral-200 p-5">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {[
                {
                  name: "Spot API",
                  ok: binance.spot_ok,
                  latency: binance.spot_latency_ms,
                  weightUsed: binance.spot_weight_used,
                  weightLimit: 1200,
                  weightPct: binance.spot_weight_pct,
                  banned: binance.spot_banned_until,
                  error: binance.spot_error,
                  endpoint: "api.binance.com/api/v3",
                },
                {
                  name: "Futures API",
                  ok: binance.futures_ok,
                  latency: binance.futures_latency_ms,
                  weightUsed: binance.futures_weight_used,
                  weightLimit: 2400,
                  weightPct: binance.futures_weight_pct,
                  banned: binance.futures_banned_until,
                  error: binance.futures_error,
                  endpoint: "fapi.binance.com/fapi/v1",
                },
              ].map(api => (
                <div key={api.name}>
                  <div className="flex items-center justify-between mb-3">
                    <div>
                      <p className="font-bold text-neutral-800">{api.name}</p>
                      <p className="text-[10px] text-neutral-400 font-mono">{api.endpoint}</p>
                    </div>
                    <div className="flex items-center gap-2">
                      <StatusDot ok={api.ok && !api.banned} />
                      <span className={`text-sm font-black ${api.banned ? "text-red-600" : api.ok ? "text-green-600" : "text-red-500"}`}>
                        {api.banned ? "BANNED" : api.ok ? "OK" : "Down"}
                      </span>
                    </div>
                  </div>

                  <div className="grid grid-cols-3 gap-3 mb-3">
                    <div className="bg-neutral-50 rounded-xl px-3 py-2">
                      <p className="text-[10px] text-neutral-400 font-semibold uppercase tracking-wide">Latency</p>
                      <p className="font-black text-neutral-800">
                        {api.latency != null ? `${api.latency}ms` : "—"}
                      </p>
                    </div>
                    <div className="bg-neutral-50 rounded-xl px-3 py-2">
                      <p className="text-[10px] text-neutral-400 font-semibold uppercase tracking-wide">Weight</p>
                      <p className="font-black text-neutral-800">
                        {api.weightUsed} <span className="text-neutral-400 font-normal text-xs">/ {api.weightLimit}</span>
                      </p>
                    </div>
                    <div className="bg-neutral-50 rounded-xl px-3 py-2">
                      <p className="text-[10px] text-neutral-400 font-semibold uppercase tracking-wide">Limit %</p>
                      <p className={`font-black ${api.weightPct > 70 ? "text-orange-600" : api.weightPct > 40 ? "text-yellow-600" : "text-green-600"}`}>
                        {api.weightPct.toFixed(1)}%
                      </p>
                    </div>
                  </div>

                  <div className="mb-2">
                    <div className="flex justify-between text-[10px] text-neutral-400 mb-1">
                      <span>Rate Limit Usage</span>
                      <span>{api.weightUsed} / {api.weightLimit} per menit</span>
                    </div>
                    <RateBar pct={api.weightPct} banned={!!api.banned} />
                  </div>

                  {/* Status legend */}
                  <div className="flex gap-3 text-[10px] text-neutral-400 mt-2">
                    <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-green-400 inline-block" /> Normal (&lt;40%)</span>
                    <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-yellow-400 inline-block" /> Moderate (40–70%)</span>
                    <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-orange-500 inline-block" /> Hot (&gt;70%)</span>
                  </div>

                  {api.banned && (
                    <div className="mt-3 bg-red-50 border border-red-300 rounded-xl p-3">
                      <p className="text-sm font-black text-red-700">⛔ IP BANNED</p>
                      <p className="text-xs text-red-600 mt-0.5">
                        Binance memblokir IP karena terlalu banyak request.
                        Ban berakhir: <strong>{fmtBanTime(api.banned)}</strong>
                      </p>
                    </div>
                  )}

                  {!api.banned && api.error && (
                    <div className="mt-3 bg-orange-50 border border-orange-200 rounded-xl p-3">
                      <p className="text-xs font-bold text-orange-700">⚠ Error</p>
                      <p className="text-xs text-orange-600 font-mono mt-0.5">{api.error}</p>
                    </div>
                  )}
                </div>
              ))}
            </div>

            <div className="mt-4 pt-4 border-t border-neutral-100 text-[10px] text-neutral-400 flex items-center justify-between">
              <span>Cache TTL: 30 detik · Auto-refresh setiap {POLL_MS / 1000}s</span>
              {binance.checked_at && (
                <span>Dicek: {fmtRelTime(binance.checked_at)}</span>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── System Health Event Log ────────────────────────────────────────── */}
      <div>
        <p className="text-xs font-black text-neutral-400 uppercase tracking-widest mb-3">
          📡 History System Health
        </p>
        <HealthEventLog />
      </div>

      {/* ── Raw Health JSON (collapsible) ──────────────────────────────────── */}
      <details className="group">
        <summary className="cursor-pointer text-xs text-neutral-400 hover:text-neutral-600 select-none list-none flex items-center gap-1.5">
          <span className="group-open:rotate-90 transition-transform inline-block">▶</span>
          Raw /health response
        </summary>
        <pre className="mt-2 bg-neutral-900 text-green-400 text-[11px] font-mono p-4 rounded-xl overflow-x-auto leading-relaxed whitespace-pre-wrap">
          {JSON.stringify(health, null, 2)}
        </pre>
      </details>

    </div>
  );
}
