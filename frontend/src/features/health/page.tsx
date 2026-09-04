"use client";
import { apiFetch } from "@/lib/api";
import { useCallback, useEffect, useRef, useState } from "react";
import { HealthEventLog } from "./components/HealthEventLog";
import { StatusDot } from "@/components/ui/trading-badges";
import { LoadingSpinner } from "@/components/ui/feedback";
import { LiveBadge } from "@/components/ui/live-badge";
import { fmtRelTime } from "@/lib/format";
import type { Health, BinanceStatus, AgentState } from "@/types/health";

const POLL_MS = 10_000;

function fmtBanTime(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" });
}

function RateBar({ pct, banned }: { pct: number; banned?: boolean }) {
  const color = banned ? "bg-red-500" : pct > 70 ? "bg-orange-500" : pct > 40 ? "bg-yellow-400" : "bg-green-400";
  const textColor = banned ? "text-red-600" : pct > 70 ? "text-orange-600" : pct > 40 ? "text-yellow-600" : "text-neutral-500";
  return (
    <div className="flex items-center gap-2 mt-1">
      <div className="flex-1 h-2 bg-neutral-100 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all duration-500 ${color}`} style={{ width: `${Math.min(pct, 100)}%` }} />
      </div>
      <span className={`text-[11px] font-bold tabular-nums w-8 text-right ${textColor}`}>{pct.toFixed(0)}%</span>
    </div>
  );
}

function AgentCard({ icon, label, sub, state, extraRows }: {
  icon: string; label: string; sub: string; state: AgentState | undefined; extraRows?: React.ReactNode;
}) {
  const running = state?.running ?? false;
  return (
    <div className={`rounded-2xl border p-4 ${running ? "bg-green-50/40 border-green-200" : "bg-red-50/30 border-red-200"}`}>
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
          <span className={`text-xs font-bold ${running ? "text-green-700" : "text-red-500"}`}>{running ? "Running" : "Stopped"}</span>
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

function BinanceApiCard({ name, ok, latency, weightUsed, weightLimit, weightPct, banned, error, endpoint }: {
  name: string; ok: boolean; latency: number | null; weightUsed: number; weightLimit: number;
  weightPct: number; banned: number | null; error: string | null; endpoint: string;
}) {
  const isBanned = banned != null;
  return (
    <div className={`rounded-2xl border p-4 ${isBanned ? "bg-red-50/50 border-red-300" : ok ? "bg-green-50/40 border-green-200" : "bg-red-50/30 border-red-200"}`}>
      <div className="flex items-center gap-2 mb-3">
        <StatusDot ok={ok && !isBanned} />
        <span className="font-bold text-sm text-neutral-800">{name}</span>
      </div>
      <p className="text-xs text-neutral-500 font-mono">{endpoint}</p>
      <p className={`text-lg font-black mt-2 ${isBanned ? "text-red-600" : ok ? "text-green-600" : "text-red-500"}`}>
        {isBanned ? "BANNED" : ok ? `OK${latency != null ? ` · ${latency}ms` : ""}` : "Down"}
      </p>
      {isBanned && banned && <p className="text-xs text-red-500 font-bold">⛔ sampai {fmtBanTime(banned)}</p>}
      <RateBar pct={weightPct} banned={isBanned} />
      <p className="text-[10px] text-neutral-400 mt-1">Rate limit: {weightUsed} / {weightLimit}</p>
      {!isBanned && error && <p className="text-[10px] text-orange-500 mt-1 truncate" title={error}>⚠ {error}</p>}
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function HealthPage() {
  const [health,    setHealth]    = useState<Health | null>(null);
  const [binance,   setBinance]   = useState<BinanceStatus | null>(null);
  const [lastPoll,  setLastPoll]  = useState<Date | null>(null);
  const [loading,   setLoading]   = useState(true);
  const [countdown, setCountdown] = useState(POLL_MS / 1000);
  const countRef = useRef(POLL_MS / 1000);

  const fetchAll = useCallback(async () => {
    try {
      const [healthR, binanceR] = await Promise.allSettled([
        apiFetch("/health"),
        apiFetch("/api/v1/market/binance-status"),
      ]);
      if (healthR.status === "fulfilled" && healthR.value.ok)   setHealth(await healthR.value.json() as Health);
      if (binanceR.status === "fulfilled" && binanceR.value.ok) setBinance(await binanceR.value.json() as BinanceStatus);
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
  const checks    = [backendOk, dbOk, binance?.spot_ok ?? false, binance?.futures_ok ?? false,
    health?.spot_scanner?.running ?? false, health?.spot_monitor?.running ?? false,
    health?.futures_scanner?.running ?? false, health?.futures_monitor?.running ?? false];
  const passCount = checks.filter(Boolean).length;
  const allOk     = passCount === checks.length;
  const overallColor = allOk ? "text-green-600" : passCount >= 6 ? "text-yellow-600" : "text-red-600";
  const overallBg    = allOk ? "from-green-50 to-white border-green-200"
    : passCount >= 6 ? "from-yellow-50 to-white border-yellow-200"
    : "from-red-50 to-white border-red-200";

  if (loading) return (
    <div className="flex items-center justify-center h-48">
      <LoadingSpinner size="md" />
    </div>
  );

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className={`rounded-2xl border bg-gradient-to-r p-5 ${overallBg}`}>
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-2xl font-black text-neutral-900">⚙️ System Health</h1>
            <p className="text-sm text-neutral-500 mt-0.5">Monitoring real-time · semua agent, API, database</p>
          </div>
          <div className="text-right">
            <p className={`text-4xl font-black tabular-nums ${overallColor}`}>{passCount}/{checks.length}</p>
            <p className="text-xs text-neutral-500">{allOk ? "Semua sistem normal ✅" : `${checks.length - passCount} masalah terdeteksi`}</p>
          </div>
        </div>
        <div className="flex items-center gap-3 mt-4">
          <LiveBadge countdown={countdown} color="green" />
          {lastPoll && <span className="text-[11px] text-neutral-400">Terakhir: {lastPoll.toLocaleTimeString("id-ID")}</span>}
        </div>
      </div>

      {/* Infrastructure */}
      <div>
        <p className="text-xs font-black text-neutral-400 uppercase tracking-widest mb-3">🏗 Infrastruktur</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {[
            { label: "Backend API", ok: backendOk, desc: "FastAPI · Python 3.12",  val: backendOk ? "Online" : "Offline" },
            { label: "Database",    ok: dbOk,      desc: "PostgreSQL 16",          val: dbOk ? "Connected" : health?.db === "unavailable" ? "Unavailable" : "—" },
          ].map(x => (
            <div key={x.label} className={`rounded-2xl border p-4 ${x.ok ? "bg-green-50/40 border-green-200" : "bg-red-50/30 border-red-200"}`}>
              <div className="flex items-center gap-2 mb-3"><StatusDot ok={x.ok} pulse /><span className="font-bold text-sm text-neutral-800">{x.label}</span></div>
              <p className="text-xs text-neutral-500 font-mono">{x.desc}</p>
              <p className={`text-lg font-black mt-2 ${x.ok ? "text-green-600" : "text-red-500"}`}>{x.val}</p>
            </div>
          ))}
          <BinanceApiCard name="Binance Spot"    ok={binance?.spot_ok ?? false}    latency={binance?.spot_latency_ms ?? null}
            weightUsed={binance?.spot_weight_used ?? 0}    weightLimit={1200} weightPct={binance?.spot_weight_pct ?? 0}
            banned={binance?.spot_banned_until ?? null}    error={binance?.spot_error ?? null} endpoint="api.binance.com/api/v3" />
          <BinanceApiCard name="Binance Futures" ok={binance?.futures_ok ?? false} latency={binance?.futures_latency_ms ?? null}
            weightUsed={binance?.futures_weight_used ?? 0} weightLimit={2400} weightPct={binance?.futures_weight_pct ?? 0}
            banned={binance?.futures_banned_until ?? null} error={binance?.futures_error ?? null} endpoint="fapi.binance.com/fapi/v1" />
        </div>
      </div>

      {/* Futures Agents */}
      <div>
        <p className="text-xs font-black text-blue-500 uppercase tracking-widest mb-3">⚡ Futures Agents</p>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          <AgentCard icon="🎯" label="Futures Scanner — Pre-Gainer"   sub="agents/futures/agent1.py"    state={health?.futures_scanner} />
          <AgentCard icon="📦" label="Futures Scanner — Accumulation" sub="agents/futures/agent2.py"    state={health?.futures_scanner} />
          <AgentCard icon="🔥" label="Futures Scanner — Momentum"     sub="agents/futures/agent3.py"    state={health?.futures_scanner} />
          <AgentCard icon="👁" label="Futures Position Monitor"       sub="agents/futures/monitor.py"   state={health?.futures_monitor} />
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
                      <p className="text-[10px] text-neutral-500 font-mono">agents/futures/weight_updater.py · Auto-tune bobot sinyal</p>
                    </div>
                  </div>
                  <span className={`text-xs font-bold px-3 py-1 rounded-full border ${ok ? "bg-blue-100 text-blue-700 border-blue-200" : "bg-neutral-100 text-neutral-500 border-neutral-200"}`}>
                    {ok ? "Running" : "—"}
                  </span>
                </div>
                {ws?.last_run != null && <p className="text-[11px] text-neutral-400 mt-2">Last run: {fmtRelTime(ws.last_run)}</p>}
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

      {/* Spot Agents */}
      <div>
        <p className="text-xs font-black text-teal-600 uppercase tracking-widest mb-3">🎯 Spot Agents</p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <AgentCard icon="🚀" label="Spot Opportunity Scanner" sub="agents/opportunity/scheduler.py" state={health?.spot_scanner} />
          <AgentCard icon="👁" label="Spot Position Monitor"    sub="agents/opportunity/monitor.py"   state={health?.spot_monitor} />
        </div>
      </div>

      {/* Binance API Detail */}
      {binance && (
        <div>
          <p className="text-xs font-black text-neutral-400 uppercase tracking-widest mb-3">🔗 Binance API Detail</p>
          <div className="bg-white rounded-2xl border border-neutral-200 p-5">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {[
                { name: "Spot API",    ok: binance.spot_ok,    latency: binance.spot_latency_ms,    weightUsed: binance.spot_weight_used,    weightLimit: 1200, weightPct: binance.spot_weight_pct,    banned: binance.spot_banned_until,    error: binance.spot_error,    endpoint: "api.binance.com/api/v3" },
                { name: "Futures API", ok: binance.futures_ok, latency: binance.futures_latency_ms, weightUsed: binance.futures_weight_used, weightLimit: 2400, weightPct: binance.futures_weight_pct, banned: binance.futures_banned_until, error: binance.futures_error, endpoint: "fapi.binance.com/fapi/v1" },
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
                    {[
                      { label: "Latency", val: api.latency != null ? `${api.latency}ms` : "—", cls: "text-neutral-800" },
                      { label: "Weight",  val: `${api.weightUsed}`, cls: "text-neutral-800" },
                      { label: "Limit %", val: `${api.weightPct.toFixed(1)}%`, cls: api.weightPct > 70 ? "text-orange-600" : api.weightPct > 40 ? "text-yellow-600" : "text-green-600" },
                    ].map(x => (
                      <div key={x.label} className="bg-neutral-50 rounded-xl px-3 py-2">
                        <p className="text-[10px] text-neutral-400 font-semibold uppercase tracking-wide">{x.label}</p>
                        <p className={`font-black ${x.cls}`}>{x.val}</p>
                      </div>
                    ))}
                  </div>
                  <RateBar pct={api.weightPct} banned={!!api.banned} />
                  {api.banned && (
                    <div className="mt-3 bg-red-50 border border-red-300 rounded-xl p-3">
                      <p className="text-sm font-black text-red-700">⛔ IP BANNED</p>
                      <p className="text-xs text-red-600 mt-0.5">Ban berakhir: <strong>{fmtBanTime(api.banned)}</strong></p>
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
              {binance.checked_at && <span>Dicek: {fmtRelTime(binance.checked_at)}</span>}
            </div>
          </div>
        </div>
      )}

      {/* Event Log */}
      <div>
        <p className="text-xs font-black text-neutral-400 uppercase tracking-widest mb-3">📡 History System Health</p>
        <HealthEventLog />
      </div>

      {/* Raw JSON debug */}
      <details className="group">
        <summary className="cursor-pointer text-xs text-neutral-400 hover:text-neutral-600 select-none list-none flex items-center gap-1.5">
          <span className="group-open:rotate-90 transition-transform inline-block">▶</span> Raw /health response
        </summary>
        <pre className="mt-2 bg-neutral-900 text-green-400 text-[11px] font-mono p-4 rounded-xl overflow-x-auto leading-relaxed whitespace-pre-wrap">
          {JSON.stringify(health, null, 2)}
        </pre>
      </details>
    </div>
  );
}
