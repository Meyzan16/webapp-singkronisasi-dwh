"use client";
import { useCallback, useEffect, useRef, useState } from "react";

// ── Types ─────────────────────────────────────────────────────────────────────

interface HealthEvent {
  id:       number;
  ts:       number;
  category: string;    // "api_spot" | "api_futures" | "agent" | "database" | "system"
  level:    string;    // "up" | "down" | "error" | "warn" | "info" | "ban"
  message:  string;
  detail:   Record<string, unknown>;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtTs(ts: number): { date: string; time: string; rel: string } {
  const d    = new Date(ts * 1000);
  const now  = Date.now() / 1000;
  const diff = Math.floor(now - ts);
  let rel: string;
  if (diff < 5)    rel = "baru saja";
  else if (diff < 60)   rel = `${diff}d lalu`;
  else if (diff < 3600) rel = `${Math.floor(diff / 60)}m ${diff % 60}d lalu`;
  else if (diff < 86400) rel = `${Math.floor(diff / 3600)}j ${Math.floor((diff % 3600) / 60)}m lalu`;
  else rel = `${Math.floor(diff / 86400)} hari lalu`;

  return {
    date: d.toLocaleDateString("id-ID", { day: "2-digit", month: "short" }),
    time: d.toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit", second: "2-digit" }),
    rel,
  };
}

const LEVEL_STYLE: Record<string, { dot: string; badge: string; row: string }> = {
  up:    { dot: "bg-green-500",  badge: "bg-green-100 text-green-700 border-green-200",   row: "hover:bg-green-50/30"   },
  down:  { dot: "bg-red-500 animate-pulse",   badge: "bg-red-100 text-red-700 border-red-200",       row: "hover:bg-red-50/20"    },
  ban:   { dot: "bg-red-600",    badge: "bg-red-200 text-red-800 border-red-300",         row: "hover:bg-red-50/30"    },
  error: { dot: "bg-orange-500", badge: "bg-orange-100 text-orange-700 border-orange-200", row: "hover:bg-orange-50/20" },
  warn:  { dot: "bg-yellow-500", badge: "bg-yellow-100 text-yellow-700 border-yellow-200", row: "hover:bg-yellow-50/20" },
  info:  { dot: "bg-blue-400",   badge: "bg-blue-100 text-blue-700 border-blue-200",      row: "hover:bg-neutral-50"   },
};

const CATEGORY_LABEL: Record<string, { icon: string; label: string }> = {
  api_spot:    { icon: "🎯", label: "Spot API"    },
  api_futures: { icon: "⚡", label: "Futures API" },
  agent:       { icon: "🤖", label: "Agent"       },
  database:    { icon: "🗄", label: "Database"    },
  system:      { icon: "⚙️", label: "System"      },
};

const LEVEL_LABEL: Record<string, string> = {
  up:    "UP",
  down:  "DOWN",
  ban:   "BANNED",
  error: "ERROR",
  warn:  "WARN",
  info:  "INFO",
};

// ── Main Component ─────────────────────────────────────────────────────────────

const POLL_MS = 10_000;

export function HealthEventLog() {
  const [events,    setEvents]    = useState<HealthEvent[]>([]);
  const [stats,     setStats]     = useState<{ total_events: number; uptime_since: number | null } | null>(null);
  const [loading,   setLoading]   = useState(true);
  const [catFilter, setCatFilter] = useState("all");
  const [lvlFilter, setLvlFilter] = useState("all");
  const [countdown, setCountdown] = useState(POLL_MS / 1000);
  const countRef = useRef(POLL_MS / 1000);

  const fetchLog = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const r = await fetch("/health/log?limit=200");
      if (r.ok) {
        const d = await r.json() as { events: HealthEvent[]; stats: typeof stats };
        setEvents(d.events ?? []);
        setStats(d.stats);
      }
    } catch { /* silent */ }
    finally { if (!silent) setLoading(false); }
  }, []);

  useEffect(() => { void fetchLog(); }, [fetchLog]);
  useEffect(() => {
    const poll = setInterval(() => {
      void fetchLog(true);
      countRef.current = POLL_MS / 1000;
      setCountdown(POLL_MS / 1000);
    }, POLL_MS);
    const tick = setInterval(() => {
      countRef.current = Math.max(0, countRef.current - 1);
      setCountdown(countRef.current);
    }, 1000);
    return () => { clearInterval(poll); clearInterval(tick); };
  }, [fetchLog]);

  // Filter
  const filtered = events.filter(e => {
    if (catFilter !== "all" && e.category !== catFilter) return false;
    if (lvlFilter !== "all" && e.level    !== lvlFilter) return false;
    return true;
  });

  // Uptime calculation
  const uptimeStr = (() => {
    if (!stats?.uptime_since) return "—";
    const secs = Math.floor(Date.now() / 1000 - stats.uptime_since);
    const h = Math.floor(secs / 3600);
    const m = Math.floor((secs % 3600) / 60);
    return h > 0 ? `${h}j ${m}m` : `${m}m`;
  })();

  return (
    <div className="space-y-4">

      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <div className="flex items-center gap-3">
            <h3 className="font-bold text-sm text-neutral-800">📡 System Health Log</h3>
            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-green-50 border border-green-200">
              <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />
              <span className="text-[10px] font-bold text-green-700">LIVE {countdown}s</span>
            </div>
          </div>
          <p className="text-[11px] text-neutral-400 mt-0.5">
            Riwayat API up/down · agents start/stop · database events · uptime sesi: {uptimeStr}
          </p>
        </div>
        <div className="flex items-center gap-2 text-[10px] text-neutral-400">
          <span>{stats?.total_events ?? 0} event tercatat</span>
          <button onClick={() => void fetchLog()} className="text-teal-600 hover:text-teal-500 font-semibold">↺</button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-2">
        {/* Category filter */}
        <div className="flex bg-neutral-100 rounded-xl p-1 gap-0.5">
          {[
            { key: "all",         label: "Semua"    },
            { key: "api_spot",    label: "🎯 Spot"  },
            { key: "api_futures", label: "⚡ Fut"   },
            { key: "agent",       label: "🤖 Agent" },
            { key: "database",    label: "🗄 DB"    },
          ].map(f => (
            <button key={f.key}
              onClick={() => setCatFilter(f.key)}
              className={`px-2.5 py-1 rounded-lg text-xs font-semibold transition-all ${
                catFilter === f.key ? "bg-white text-neutral-900 shadow-sm" : "text-neutral-500 hover:text-neutral-700"
              }`}>{f.label}</button>
          ))}
        </div>

        {/* Level filter */}
        <div className="flex bg-neutral-100 rounded-xl p-1 gap-0.5">
          {[
            { key: "all",   label: "Semua"  },
            { key: "up",    label: "✅ UP"  },
            { key: "down",  label: "🔴 DOWN" },
            { key: "ban",   label: "⛔ BAN" },
            { key: "error", label: "⚠️ ERR" },
          ].map(f => (
            <button key={f.key}
              onClick={() => setLvlFilter(f.key)}
              className={`px-2.5 py-1 rounded-lg text-xs font-semibold transition-all ${
                lvlFilter === f.key ? "bg-white text-neutral-900 shadow-sm" : "text-neutral-500 hover:text-neutral-700"
              }`}>{f.label}</button>
          ))}
        </div>

        <span className="ml-auto text-xs text-neutral-400 self-center">
          {filtered.length} event
        </span>
      </div>

      {/* Event list */}
      <div className="bg-white border border-neutral-200 rounded-2xl overflow-hidden">

        {/* Column header */}
        <div className="grid grid-cols-[auto_auto_1fr_auto] gap-x-3 px-4 py-2 bg-neutral-50 border-b text-[10px] font-bold text-neutral-400 uppercase tracking-wider">
          <span className="w-16">Waktu</span>
          <span className="w-20">Kategori</span>
          <span>Pesan</span>
          <span className="w-16 text-right">Status</span>
        </div>

        {loading && events.length === 0 ? (
          <div className="flex items-center justify-center py-12 text-neutral-400">
            <div className="w-6 h-6 border-2 border-teal-400 border-t-transparent rounded-full animate-spin mr-2" />
            Memuat log...
          </div>
        ) : filtered.length === 0 ? (
          <div className="text-center py-12 text-neutral-400">
            <p className="text-3xl mb-2">📋</p>
            <p className="font-semibold">Belum ada event</p>
            <p className="text-xs mt-1">Log akan terisi saat sistem berjalan dan API dicek setiap 30 detik</p>
          </div>
        ) : (
          <div className="divide-y divide-neutral-100 max-h-[600px] overflow-y-auto">
            {filtered.map(e => {
              const style = LEVEL_STYLE[e.level] ?? LEVEL_STYLE.info;
              const cat   = CATEGORY_LABEL[e.category] ?? { icon: "•", label: e.category };
              const ts    = fmtTs(e.ts);
              const isDown = e.level === "down" || e.level === "ban" || e.level === "error";

              return (
                <div key={e.id}
                  className={`grid grid-cols-[auto_auto_1fr_auto] gap-x-3 px-4 py-3 items-start transition-colors ${style.row} ${isDown ? "bg-red-50/10" : ""}`}
                >
                  {/* Timestamp */}
                  <div className="w-16 shrink-0">
                    <p className="text-[10px] font-mono font-bold text-neutral-700">{ts.time}</p>
                    <p className="text-[9px] text-neutral-400">{ts.date}</p>
                    <p className="text-[9px] text-neutral-300 mt-0.5">{ts.rel}</p>
                  </div>

                  {/* Category */}
                  <div className="w-20 shrink-0">
                    <span className="text-[10px] font-bold text-neutral-600">
                      {cat.icon} {cat.label}
                    </span>
                  </div>

                  {/* Message */}
                  <div className="min-w-0">
                    <p className="text-xs font-semibold text-neutral-800 leading-snug">{e.message}</p>
                    {/* Detail */}
                    {Object.keys(e.detail).length > 0 && (
                      <div className="flex flex-wrap gap-1.5 mt-1">
                        {e.detail.latency_ms != null && (
                          <span className="text-[9px] bg-neutral-100 text-neutral-500 px-1.5 py-0.5 rounded font-mono">
                            {String(e.detail.latency_ms)}ms
                          </span>
                        )}
                        {e.detail.error && (
                          <span className="text-[9px] bg-red-50 text-red-600 px-1.5 py-0.5 rounded font-mono max-w-xs truncate">
                            {String(e.detail.error)}
                          </span>
                        )}
                        {e.detail.agent && (
                          <span className="text-[9px] bg-blue-50 text-blue-600 px-1.5 py-0.5 rounded font-mono">
                            {String(e.detail.agent)}
                          </span>
                        )}
                        {e.detail.banned_until && (
                          <span className="text-[9px] bg-red-100 text-red-700 px-1.5 py-0.5 rounded font-bold">
                            ⛔ ban s/d {new Date(Number(e.detail.banned_until) * 1000).toLocaleTimeString("id-ID")}
                          </span>
                        )}
                      </div>
                    )}
                  </div>

                  {/* Level badge */}
                  <div className="w-16 flex items-start justify-end gap-1.5 shrink-0">
                    <span className={`w-2 h-2 rounded-full mt-0.5 ${style.dot}`} />
                    <span className={`text-[9px] font-black px-1.5 py-0.5 rounded border ${style.badge}`}>
                      {LEVEL_LABEL[e.level] ?? e.level.toUpperCase()}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-3 px-1">
        {Object.entries(LEVEL_STYLE).map(([level, s]) => (
          <span key={level} className="flex items-center gap-1.5 text-[10px] text-neutral-500">
            <span className={`w-2 h-2 rounded-full ${s.dot.replace("animate-pulse","")}`} />
            {LEVEL_LABEL[level] ?? level}
          </span>
        ))}
      </div>
    </div>
  );
}
