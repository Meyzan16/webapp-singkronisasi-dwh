"use client";
import { useEffect, useState, useCallback, useMemo, useRef } from "react";
import { fmtPrice } from "@/lib/format";

// ── Types ─────────────────────────────────────────────────────────────────────

const BALANCE_START = 1000;   // $1,000 paper balance
const RISK_PCT      = 0.01;   // 1% risk per trade = $10

interface OppPosition {
  id:                  number;
  symbol:              string;
  status:              string;     // "open" | "tp" | "sl" | "manual"
  entry:               number;
  sl:                  number;
  tp1:                 number | null;
  tp2:                 number;
  tp3:                 number | null;
  auto_open?:          boolean;
  close_reason?:       string;
  risk_pct:            number;
  tp2_pct:             number;
  rr_ratio:            number;
  score:               number;
  alert_type:          string;
  signals:             string[];
  entry_at:            number;
  close_price:         number | null;
  closed_at:           number | null;
  pnl_pct:             number | null;
  current_price:       number | null;
  unrealized_pnl_pct:  number | null;
  tp1_hit:             boolean;
  tp1_hit_price:       number | null;
}

type SortKey = "date" | "pnl" | "symbol" | "score";
type FilterKey = "all" | "open" | "win" | "loss" | "manual";

// ── Sub-components ─────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const cfg: Record<string, string> = {
    open:   "bg-blue-100 text-blue-700 border-blue-200",
    tp:     "bg-green-100 text-green-700 border-green-200",
    sl:     "bg-red-100 text-red-600 border-red-200",
    manual: "bg-neutral-100 text-neutral-600 border-neutral-300",
  };
  const label: Record<string, string> = {
    open:   "🔵 Open",
    tp:     "✅ TP Hit",
    sl:     "🛑 SL Hit",
    manual: "🤚 Manual",
  };
  return (
    <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${cfg[status] ?? "bg-neutral-100 text-neutral-500 border-neutral-200"}`}>
      {label[status] ?? status}
    </span>
  );
}

// ── Tiny sparkline bar ────────────────────────────────────────────────────────

function MiniBar({ value, max, color }: { value: number; max: number; color: string }) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0;
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-neutral-100 rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[10px] tabular-nums text-neutral-500 w-8 text-right">{value}</span>
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

const REFRESH_INTERVAL = 15_000;   // 15 s live polling

export function OppSpotTab() {
  const [positions, setPositions]     = useState<OppPosition[]>([]);
  const [loading, setLoading]         = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [error, setError]             = useState(false);
  const [closingId, setClosingId]     = useState<number | null>(null);
  const [countdown, setCountdown]     = useState(REFRESH_INTERVAL / 1000);
  const countRef                      = useRef(REFRESH_INTERVAL / 1000);

  // Sorting & filtering
  const [sortBy, setSortBy]       = useState<SortKey>("date");
  const [sortDir, setSortDir]     = useState<"desc" | "asc">("desc");
  const [filterBy, setFilterBy]   = useState<FilterKey>("all");

  // Track previous statuses for browser notifications
  const prevStatusRef = useRef<Map<number, string>>(new Map());

  const fetchPositions = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    setError(false);
    try {
      const r = await fetch("/api/v1/opportunity/positions");
      if (!r.ok) { setError(true); return; }
      const d = await r.json() as { positions: OppPosition[]; total: number };
      const newPositions = d.positions ?? [];

      // ── Browser notifications for status changes ──────────────────────────
      if ("Notification" in window && Notification.permission === "granted") {
        newPositions.forEach(p => {
          const prev = prevStatusRef.current.get(p.id);
          if (prev === "open" && p.status !== "open") {
            const pnlStr = p.pnl_pct != null
              ? `${p.pnl_pct >= 0 ? "+" : ""}${p.pnl_pct.toFixed(2)}%`
              : "";
            const icon   = p.status === "tp" ? "✅" : p.status === "sl" ? "🛑" : "🤚";
            new Notification(`${icon} ${p.symbol.replace("USDT", "")} Tertutup`, {
              body: `${StatusLabel[p.status] ?? p.status}${pnlStr ? " · " + pnlStr : ""}`,
              tag:  `opp-${p.id}`,
            });
          }
        });
      }

      // Update prev status map
      newPositions.forEach(p => prevStatusRef.current.set(p.id, p.status));

      setPositions(newPositions);
      setLastUpdated(new Date());
    } catch {
      setError(true);
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  // Manual close
  const closePosition = useCallback(async (id: number, symbol: string) => {
    if (!confirm(`Tutup posisi ${symbol.replace("USDT", "")}/USDT sekarang di harga pasar?`)) return;
    setClosingId(id);
    try {
      const r = await fetch(`/api/v1/opportunity/positions/${id}/close`, { method: "POST" });
      if (!r.ok) { alert("Gagal menutup posisi"); return; }
      await fetchPositions(true);
    } catch { alert("Gagal menutup posisi"); }
    finally { setClosingId(null); }
  }, [fetchPositions]);

  // Request browser notification permission
  const requestNotifPermission = useCallback(async () => {
    if (!("Notification" in window)) return;
    await Notification.requestPermission();
  }, []);

  useEffect(() => { void fetchPositions(); }, [fetchPositions]);

  // Polling + countdown tick
  useEffect(() => {
    const poll = setInterval(() => {
      void fetchPositions(true);
      countRef.current = REFRESH_INTERVAL / 1000;
      setCountdown(REFRESH_INTERVAL / 1000);
    }, REFRESH_INTERVAL);
    const tick = setInterval(() => {
      countRef.current = Math.max(0, countRef.current - 1);
      setCountdown(countRef.current);
    }, 1000);
    return () => { clearInterval(poll); clearInterval(tick); };
  }, [fetchPositions]);

  // ── Derived stats ────────────────────────────────────────────────────────────

  const stats = useMemo(() => {
    const closed  = positions.filter(p => p.status !== "open");
    const wins    = closed.filter(p => p.status === "tp");
    const losses  = closed.filter(p => p.status === "sl" || p.status === "manual");
    const open    = positions.filter(p => p.status === "open");
    const winRate = closed.length > 0 ? (wins.length / closed.length) * 100 : 0;
    const avgPnl  = closed.length > 0
      ? closed.reduce((s, p) => s + (p.pnl_pct ?? 0), 0) / closed.length : 0;

    // Balance simulation: $1000 start, 1% risk/trade
    let balance = BALANCE_START;
    const equityPoints: { n: number; balance: number; win: boolean; symbol: string }[] = [
      { n: 0, balance, win: true, symbol: "" }
    ];
    const sortedClosed = [...closed].sort((a, b) => (a.closed_at ?? 0) - (b.closed_at ?? 0));
    sortedClosed.forEach((p, i) => {
      const riskDollar = BALANCE_START * RISK_PCT;  // fixed $10
      const riskPct    = p.risk_pct > 0 ? p.risk_pct : 2.0;
      const notional   = riskDollar / (riskPct / 100);
      const pnl$       = ((p.pnl_pct ?? 0) / 100) * notional;
      balance          = Math.max(0, balance + pnl$);
      equityPoints.push({ n: i + 1, balance, win: (p.pnl_pct ?? 0) >= 0, symbol: p.symbol.replace("USDT","") });
    });

    // Calendar data: daily P&L in $
    const calendarMap = new Map<string, number>();
    sortedClosed.forEach(p => {
      if (!p.closed_at) return;
      const day = new Date(p.closed_at * 1000).toISOString().slice(0, 10);
      const riskDollar = BALANCE_START * RISK_PCT;
      const riskPct    = p.risk_pct > 0 ? p.risk_pct : 2.0;
      const notional   = riskDollar / (riskPct / 100);
      const pnl$       = ((p.pnl_pct ?? 0) / 100) * notional;
      calendarMap.set(day, (calendarMap.get(day) ?? 0) + pnl$);
    });

    const autoOpened = positions.filter(p => p.auto_open).length;
    const currentBalance = balance;
    const totalPnl$ = balance - BALANCE_START;

    return {
      total: positions.length, open: open.length, wins: wins.length,
      losses: losses.length, winRate, avgPnl, autoOpened,
      currentBalance, totalPnl$, equityPoints, calendarMap,
    };
  }, [positions]);

  // ── Win rate per alert type ───────────────────────────────────────────────────

  const alertStats = useMemo(() => {
    const types = ["squeeze", "accumulation", "breakout"];
    return types.map(type => {
      const all    = positions.filter(p => p.alert_type === type && p.status !== "open");
      const wins   = all.filter(p => p.status === "tp");
      const avgPnl = all.length > 0 ? all.reduce((s, p) => s + (p.pnl_pct ?? 0), 0) / all.length : 0;
      return { type, total: all.length, wins: wins.length, winRate: all.length > 0 ? wins.length / all.length * 100 : 0, avgPnl };
    });
  }, [positions]);

  // ── Per-signal performance ────────────────────────────────────────────────────

  const signalStats = useMemo(() => {
    const closed = positions.filter(p => p.status !== "open" && p.signals?.length > 0);
    const map = new Map<string, { wins: number; total: number }>();
    closed.forEach(p => {
      const isWin = p.status === "tp";
      // Use first 4 words of each signal as key
      (p.signals ?? []).forEach(s => {
        const key = s.replace(/[🔵🟢📦🎯📊⚠️]/g, "").trim().split(" ").slice(0, 4).join(" ");
        if (!key) return;
        const cur = map.get(key) ?? { wins: 0, total: 0 };
        map.set(key, { wins: cur.wins + (isWin ? 1 : 0), total: cur.total + 1 });
      });
    });
    return [...map.entries()]
      .filter(([, v]) => v.total >= 2)
      .map(([sig, v]) => ({ sig, ...v, rate: v.wins / v.total * 100 }))
      .sort((a, b) => b.rate - a.rate)
      .slice(0, 8);
  }, [positions]);

  // ── Score distribution ────────────────────────────────────────────────────────

  const scoreDist = useMemo(() => {
    const closed = positions.filter(p => p.status !== "open");
    const buckets = [
      { label: "30–49", min: 30, max: 49 },
      { label: "50–69", min: 50, max: 69 },
      { label: "70–99", min: 70, max: 99 },
    ];
    return buckets.map(b => {
      const grp  = closed.filter(p => p.score >= b.min && p.score <= b.max);
      const wins = grp.filter(p => p.status === "tp");
      return { ...b, total: grp.length, wins: wins.length, rate: grp.length > 0 ? wins.length / grp.length * 100 : 0 };
    });
  }, [positions]);

  // ── Sort + Filter ─────────────────────────────────────────────────────────────

  const displayPositions = useMemo(() => {
    let list = [...positions];

    // Filter
    if (filterBy === "open")   list = list.filter(p => p.status === "open");
    if (filterBy === "win")    list = list.filter(p => p.status === "tp");
    if (filterBy === "loss")   list = list.filter(p => p.status === "sl" || p.status === "manual");
    if (filterBy === "manual") list = list.filter(p => p.status === "manual");

    // Sort
    list.sort((a, b) => {
      let va = 0, vb = 0;
      if (sortBy === "date")   { va = a.entry_at ?? 0;  vb = b.entry_at ?? 0; }
      if (sortBy === "pnl")    { va = a.pnl_pct ?? (a.unrealized_pnl_pct ?? -999); vb = b.pnl_pct ?? (b.unrealized_pnl_pct ?? -999); }
      if (sortBy === "score")  { va = a.score; vb = b.score; }
      if (sortBy === "symbol") { return sortDir === "asc" ? a.symbol.localeCompare(b.symbol) : b.symbol.localeCompare(a.symbol); }
      return sortDir === "desc" ? vb - va : va - vb;
    });

    return list;
  }, [positions, sortBy, sortDir, filterBy]);

  const openList   = useMemo(() => displayPositions.filter(p => p.status === "open"), [displayPositions]);
  const closedList = useMemo(() => displayPositions.filter(p => p.status !== "open"), [displayPositions]);

  // ── CSV Export ────────────────────────────────────────────────────────────────

  const exportCSV = useCallback(() => {
    const headers = ["ID", "Symbol", "Status", "Alert Type", "Entry", "SL", "TP2", "Close Price", "P&L %", "Score", "R:R", "Entry Date", "Close Date"];
    const rows = positions.map(p => [
      p.id, p.symbol, p.status, p.alert_type,
      p.entry, p.sl, p.tp2,
      p.close_price ?? "", p.pnl_pct ?? "",
      p.score, p.rr_ratio,
      p.entry_at ? new Date(p.entry_at * 1000).toLocaleString("id-ID") : "",
      p.closed_at ? new Date(p.closed_at * 1000).toLocaleString("id-ID") : "",
    ]);
    const csv = [headers, ...rows].map(r => r.join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    a.href     = url;
    a.download = `opportunity_spot_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }, [positions]);

  // ── Notification permission state ─────────────────────────────────────────────

  const notifPermission = typeof window !== "undefined" && "Notification" in window
    ? Notification.permission : "default";

  // ── Loading / error ────────────────────────────────────────────────────────────

  if (loading && positions.length === 0) {
    return (
      <div className="text-center py-16 text-neutral-400">
        <div className="w-10 h-10 border-2 border-teal-400 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
        <p>Memuat posisi...</p>
      </div>
    );
  }

  if (error && positions.length === 0) {
    return (
      <div className="text-center py-16">
        <p className="text-3xl mb-2">⚠️</p>
        <p className="font-semibold text-neutral-600">Gagal memuat posisi</p>
        <button onClick={() => void fetchPositions()} className="mt-3 text-sm text-teal-600 underline">Coba lagi</button>
      </div>
    );
  }

  const totalClosed = positions.filter(p => p.status !== "open").length;

  const balanceColor = stats.currentBalance >= BALANCE_START ? "text-green-500" : "text-red-500";

  return (
    <div className="space-y-5">

      {/* ── Balance simulation banner ─────────────────────────────────────────── */}
      <div className="rounded-2xl bg-gradient-to-br from-neutral-900 via-neutral-800 to-neutral-900 text-white overflow-hidden">
        <div className="p-5">
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <p className="text-xs text-neutral-400 mb-1 font-semibold uppercase tracking-wider">Simulasi Spot Opportunity</p>
              <div className="flex items-baseline gap-2">
                <span className={`text-4xl font-black tabular-nums ${balanceColor}`}>
                  ${stats.currentBalance.toFixed(2)}
                </span>
                <span className={`text-sm font-bold ${stats.totalPnl$ >= 0 ? "text-green-400" : "text-red-400"}`}>
                  {stats.totalPnl$ >= 0 ? "+" : ""}${stats.totalPnl$.toFixed(2)}
                </span>
              </div>
              <p className="text-xs text-neutral-400 mt-1">
                Modal <strong className="text-neutral-200">$1,000</strong> · Risk <strong className="text-yellow-300">$10/trade (1%)</strong>
                {stats.autoOpened > 0 && <span className="ml-2 text-teal-300">· {stats.autoOpened} auto-opened</span>}
              </p>
            </div>
            <div className="grid grid-cols-2 gap-2 text-center">
              {[
                { label: "Open",  value: stats.open,   color: "text-blue-400"    },
                { label: "Win",   value: stats.wins,   color: "text-green-400"   },
                { label: "Loss",  value: stats.losses, color: "text-red-400"     },
                { label: "W.Rate",value: `${stats.winRate.toFixed(0)}%`, color: stats.winRate >= 50 ? "text-green-400" : "text-red-400" },
              ].map(s => (
                <div key={s.label} className="bg-white/5 rounded-xl px-3 py-2">
                  <p className={`text-xl font-black ${s.color}`}>{s.value}</p>
                  <p className="text-[9px] text-neutral-400">{s.label}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Equity mini-chart */}
          {stats.equityPoints.length > 1 && (
            <div className="mt-4">
              <div className="flex items-end gap-0.5 h-10">
                {stats.equityPoints.map((pt, i) => {
                  const minB = Math.min(...stats.equityPoints.map(p => p.balance));
                  const maxB = Math.max(...stats.equityPoints.map(p => p.balance));
                  const h = maxB > minB ? ((pt.balance - minB) / (maxB - minB)) * 100 : 50;
                  return (
                    <div key={i} title={`#${pt.n} ${pt.symbol} $${pt.balance.toFixed(0)}`}
                      className={`flex-1 min-w-[2px] rounded-t transition-all ${
                        i === 0 ? "bg-neutral-600" : pt.win ? "bg-green-500" : "bg-red-500"
                      }`}
                      style={{ height: `${Math.max(h, 4)}%` }}
                    />
                  );
                })}
              </div>
              <div className="flex justify-between text-[9px] text-neutral-500 mt-0.5">
                <span>$1,000 start</span>
                <span className={`font-bold ${balanceColor}`}>${stats.currentBalance.toFixed(0)}</span>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── PnL Calendar ─────────────────────────────────────────────────────────── */}
      {stats.calendarMap.size > 0 && (
        <div className="bg-white border border-neutral-200 rounded-2xl p-4">
          <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider mb-3">📅 P&L Kalender (30 hari terakhir)</p>
          <div className="grid grid-cols-7 gap-1">
            {Array.from({ length: 30 }, (_, i) => {
              const d   = new Date(); d.setDate(d.getDate() - (29 - i));
              const key = d.toISOString().slice(0, 10);
              const pnl = stats.calendarMap.get(key);
              const bg  = pnl == null  ? "bg-neutral-100"
                        : pnl >= 5    ? "bg-green-600"
                        : pnl >= 0    ? "bg-green-300"
                        : pnl >= -5   ? "bg-red-300"
                        :               "bg-red-600";
              return (
                <div key={key} title={`${key}: ${pnl != null ? (pnl >= 0 ? "+" : "") + "$" + pnl.toFixed(2) : "No trade"}`}
                  className={`h-7 rounded ${bg} cursor-default transition-opacity hover:opacity-70`}
                />
              );
            })}
          </div>
          <div className="flex gap-3 mt-2 text-[9px] text-neutral-400 flex-wrap">
            {[
              { bg: "bg-green-600", label: "> +$5" },
              { bg: "bg-green-300", label: "$0 – $5" },
              { bg: "bg-neutral-100", label: "No trade" },
              { bg: "bg-red-300",   label: "-$5 – $0" },
              { bg: "bg-red-600",   label: "< -$5" },
            ].map(x => (
              <span key={x.label} className="flex items-center gap-1">
                <span className={`w-3 h-3 rounded ${x.bg} inline-block`} /> {x.label}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* ── Stats row ─────────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-3 md:grid-cols-6 gap-3">
        {[
          { label: "Total",    value: String(stats.total),                                               color: "text-neutral-800" },
          { label: "🔵 Open",  value: String(stats.open),                                                color: "text-blue-600"    },
          { label: "✅ Win",   value: String(stats.wins),                                                 color: "text-green-600"   },
          { label: "🛑 Loss",  value: String(stats.losses),                                               color: "text-red-500"     },
          { label: "Win Rate", value: totalClosed > 0 ? `${stats.winRate.toFixed(0)}%` : "—",            color: stats.winRate >= 50 ? "text-green-600" : stats.winRate > 0 ? "text-red-500" : "text-neutral-400" },
          { label: "Avg P&L",  value: stats.avgPnl !== 0 ? `${stats.avgPnl >= 0 ? "+" : ""}${stats.avgPnl.toFixed(1)}%` : "—", color: stats.avgPnl > 0 ? "text-green-600" : stats.avgPnl < 0 ? "text-red-500" : "text-neutral-400" },
        ].map(s => (
          <div key={s.label} className="bg-white border border-neutral-200 rounded-2xl p-4 text-center">
            <p className="text-[10px] text-neutral-400 font-semibold uppercase tracking-wide mb-1">{s.label}</p>
            <p className={`text-2xl font-black ${s.color}`}>{s.value}</p>
          </div>
        ))}
      </div>

      {/* ── Win rate per alert type ────────────────────────────────────────────── */}
      {totalClosed > 0 && (
        <div className="bg-white border border-neutral-200 rounded-2xl p-4">
          <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider mb-3">📊 Win Rate per Tipe Sinyal</p>
          <div className="grid grid-cols-3 gap-3">
            {alertStats.map(a => {
              const meta: Record<string, { emoji: string; color: string; bg: string }> = {
                squeeze:      { emoji: "⚡", color: "text-purple-700", bg: "bg-purple-50 border-purple-200" },
                accumulation: { emoji: "📦", color: "text-teal-700",   bg: "bg-teal-50 border-teal-200"   },
                breakout:     { emoji: "🎯", color: "text-amber-700",  bg: "bg-amber-50 border-amber-200" },
              };
              const m = meta[a.type] ?? meta.squeeze;
              return (
                <div key={a.type} className={`rounded-xl p-3 border ${m.bg}`}>
                  <p className={`text-xs font-bold ${m.color} capitalize mb-1`}>{m.emoji} {a.type}</p>
                  {a.total > 0 ? (
                    <>
                      <p className={`text-xl font-black ${a.winRate >= 50 ? "text-green-600" : "text-red-500"}`}>
                        {a.winRate.toFixed(0)}%
                      </p>
                      <p className="text-[10px] text-neutral-400">{a.wins}/{a.total} trades</p>
                      <p className={`text-[10px] font-semibold ${a.avgPnl >= 0 ? "text-green-500" : "text-red-400"}`}>
                        avg {a.avgPnl >= 0 ? "+" : ""}{a.avgPnl.toFixed(1)}%
                      </p>
                    </>
                  ) : (
                    <p className="text-xs text-neutral-300 mt-1">Belum ada data</p>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Score distribution ─────────────────────────────────────────────────── */}
      {totalClosed > 0 && (
        <div className="bg-white border border-neutral-200 rounded-2xl p-4">
          <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider mb-3">🎯 Score vs Outcome</p>
          <div className="space-y-2.5">
            {scoreDist.map(b => (
              <div key={b.label} className="flex items-center gap-3">
                <span className="text-xs font-mono text-neutral-500 w-14 shrink-0">{b.label}pt</span>
                <div className="flex-1 grid grid-cols-2 gap-1.5">
                  <MiniBar value={b.wins}           max={Math.max(...scoreDist.map(x => x.total), 1)} color="bg-green-400" />
                  <MiniBar value={b.total - b.wins} max={Math.max(...scoreDist.map(x => x.total), 1)} color="bg-red-300"   />
                </div>
                <span className={`text-xs font-bold w-12 text-right tabular-nums ${b.total === 0 ? "text-neutral-300" : b.rate >= 50 ? "text-green-600" : "text-red-500"}`}>
                  {b.total > 0 ? `${b.rate.toFixed(0)}%` : "—"}
                </span>
              </div>
            ))}
            <div className="flex gap-4 pt-1 text-[10px] text-neutral-400">
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-green-400 inline-block" /> Win</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-red-300 inline-block" /> Loss</span>
            </div>
          </div>
        </div>
      )}

      {/* ── Per-signal performance ──────────────────────────────────────────────── */}
      {signalStats.length > 0 && (
        <div className="bg-white border border-neutral-200 rounded-2xl p-4">
          <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider mb-3">🔬 Signal Performance</p>
          <div className="space-y-1.5">
            {signalStats.map(s => (
              <div key={s.sig} className="flex items-center gap-3 py-1.5 border-b border-neutral-50 last:border-0">
                <span className={`text-[10px] font-black w-10 text-right tabular-nums ${s.rate >= 60 ? "text-green-600" : s.rate >= 40 ? "text-yellow-600" : "text-red-500"}`}>
                  {s.rate.toFixed(0)}%
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-[11px] text-neutral-700 truncate">{s.sig}</p>
                </div>
                <span className="text-[10px] text-neutral-400 shrink-0">{s.wins}/{s.total}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Toolbar: sort / filter / export / notification ──────────────────────── */}
      <div className="flex items-center gap-2 flex-wrap">
        {/* Filter tabs */}
        <div className="flex gap-1 bg-neutral-100 p-1 rounded-xl">
          {(["all", "open", "win", "loss", "manual"] as FilterKey[]).map(f => {
            const labels: Record<FilterKey, string> = { all: "Semua", open: "Open", win: "Win", loss: "Loss", manual: "Manual" };
            const count =
              f === "all"    ? positions.length :
              f === "open"   ? positions.filter(p => p.status === "open").length :
              f === "win"    ? positions.filter(p => p.status === "tp").length :
              f === "loss"   ? positions.filter(p => p.status === "sl").length :
                               positions.filter(p => p.status === "manual").length;
            return (
              <button key={f} onClick={() => setFilterBy(f)}
                className={`px-2.5 py-1 rounded-lg text-xs font-semibold transition-all ${
                  filterBy === f ? "bg-white text-neutral-900 shadow-sm" : "text-neutral-500 hover:text-neutral-700"
                }`}>
                {labels[f]} <span className="text-[10px] opacity-60">{count}</span>
              </button>
            );
          })}
        </div>

        {/* Sort */}
        <select
          value={sortBy}
          onChange={e => setSortBy(e.target.value as SortKey)}
          className="text-xs border border-neutral-200 rounded-lg px-2 py-1.5 bg-white text-neutral-700 focus:outline-none focus:border-teal-400"
        >
          <option value="date">Sort: Tanggal</option>
          <option value="pnl">Sort: P&amp;L</option>
          <option value="score">Sort: Score</option>
          <option value="symbol">Sort: Symbol</option>
        </select>

        <button onClick={() => setSortDir(d => d === "desc" ? "asc" : "desc")}
          className="text-xs border border-neutral-200 rounded-lg px-2 py-1.5 bg-white text-neutral-600 hover:text-neutral-900 transition-colors font-mono">
          {sortDir === "desc" ? "↓" : "↑"}
        </button>

        {/* Export CSV */}
        <button onClick={exportCSV} disabled={positions.length === 0}
          className="text-xs border border-neutral-200 rounded-lg px-3 py-1.5 bg-white text-neutral-600 hover:text-teal-600 hover:border-teal-300 transition-colors font-semibold disabled:opacity-40">
          ⬇ CSV
        </button>

        {/* Browser notification toggle */}
        {typeof window !== "undefined" && "Notification" in window && notifPermission !== "granted" && (
          <button onClick={() => void requestNotifPermission()}
            className="text-xs border border-neutral-200 rounded-lg px-3 py-1.5 bg-white text-neutral-600 hover:text-yellow-600 hover:border-yellow-300 transition-colors font-semibold">
            🔔 Aktifkan Notifikasi
          </button>
        )}
        {notifPermission === "granted" && (
          <span className="text-[10px] text-green-600 font-semibold">🔔 Notifikasi aktif</span>
        )}

        {/* Live indicator + last updated */}
        <div className="ml-auto flex items-center gap-2">
          <div className="flex items-center gap-1.5 px-2 py-1 rounded-full bg-green-50 border border-green-200">
            <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />
            <span className="text-[10px] font-bold text-green-700">LIVE</span>
            <span className="text-[10px] text-green-600 tabular-nums">{countdown}s</span>
          </div>
          {lastUpdated && (
            <p className="text-[10px] text-neutral-400">{lastUpdated.toLocaleTimeString()}</p>
          )}
          <button onClick={() => void fetchPositions()} disabled={loading}
            className="text-xs text-teal-600 hover:text-teal-500 font-semibold disabled:opacity-40 transition-colors">
            {loading ? "..." : "↺"}
          </button>
        </div>
      </div>

      {/* ── Open positions ──────────────────────────────────────────────────────── */}
      {openList.length > 0 && (
        <div className="bg-blue-50 border border-blue-100 rounded-2xl overflow-hidden">
          <div className="px-4 py-3 border-b border-blue-100">
            <h3 className="font-bold text-sm text-blue-700">🔵 Posisi Terbuka ({openList.length})</h3>
          </div>
          <div className="divide-y divide-blue-100">
            {openList.map(p => {
              const upnl      = p.unrealized_pnl_pct;
              const upnlColor = upnl == null  ? "text-neutral-400 bg-neutral-100 border-neutral-200"
                              : upnl >= 0     ? "text-green-700 bg-green-100 border-green-200"
                              :                 "text-red-600 bg-red-100 border-red-200";
              return (
                <div key={p.id} className="flex items-center gap-3 px-4 py-3 hover:bg-blue-50/50">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-0.5 flex-wrap">
                      <span className="font-bold text-sm">{p.symbol.replace("USDT", "")}/USDT</span>
                      <span className="text-[10px] bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded font-semibold">LONG SPOT</span>
                      {p.tp1_hit && (
                        <span className="text-[10px] bg-yellow-100 text-yellow-700 border border-yellow-300 px-2 py-0.5 rounded-full font-bold">
                          🟡 TP1 Hit — Riding to TP2
                        </span>
                      )}
                    </div>
                    <p className="text-[10px] text-neutral-500 truncate">{p.signals[0] ?? ""}</p>
                  </div>

                  {/* Entry → current */}
                  <div className="text-right shrink-0">
                    <p className="text-xs font-mono font-bold">${fmtPrice(p.entry)}</p>
                    {p.current_price != null
                      ? <p className="text-[10px] font-mono text-neutral-500">→ ${fmtPrice(p.current_price)}</p>
                      : <p className="text-[10px] text-neutral-400">entry</p>}
                  </div>

                  {/* Unrealized P&L */}
                  <div className="shrink-0 w-20 text-right">
                    <span className={`text-xs font-black tabular-nums px-2 py-0.5 rounded-lg border ${upnlColor}`}>
                      {upnl == null ? "—" : `${upnl >= 0 ? "+" : ""}${upnl.toFixed(2)}%`}
                    </span>
                    <p className="text-[9px] text-neutral-400 mt-0.5">unrealized</p>
                  </div>

                  {/* TP2 / SL */}
                  <div className="text-right shrink-0 hidden sm:block w-24">
                    <p className="text-xs text-green-600 font-bold">TP2 +{p.tp2_pct.toFixed(1)}%</p>
                    <p className="text-xs text-red-500 font-bold">SL -{p.risk_pct.toFixed(1)}%</p>
                  </div>

                  {/* R:R */}
                  <div className="shrink-0 hidden md:block">
                    <span className="bg-green-100 text-green-700 text-[10px] font-bold px-2 py-0.5 rounded-lg border border-green-200">
                      1:{p.rr_ratio}
                    </span>
                  </div>

                  {/* Manual close */}
                  <button
                    onClick={e => { e.stopPropagation(); void closePosition(p.id, p.symbol); }}
                    disabled={closingId === p.id}
                    className="shrink-0 text-[10px] text-neutral-400 hover:text-red-500 border border-neutral-200 hover:border-red-300 px-2 py-1 rounded-lg transition-colors disabled:opacity-40 font-semibold"
                  >
                    {closingId === p.id ? "..." : "Tutup"}
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Closed / filtered trades ─────────────────────────────────────────────── */}
      <div className="bg-white border border-neutral-200 rounded-2xl overflow-hidden">
        <div className="px-4 py-3 border-b border-neutral-100 bg-neutral-50">
          <h3 className="font-bold text-sm text-neutral-700">
            📋 Riwayat Posisi
            {filterBy !== "all" && <span className="ml-2 text-xs text-neutral-400 font-normal">({filterBy})</span>}
          </h3>
        </div>

        {closedList.length === 0 ? (
          <div className="text-center py-10 text-neutral-400">
            <p className="text-2xl mb-2">📭</p>
            <p className="text-sm">
              {filterBy !== "all" ? "Tidak ada posisi untuk filter ini" : "Belum ada posisi yang tertutup"}
            </p>
            {filterBy === "all" && (
              <p className="text-xs mt-1">Posisi otomatis tertutup saat TP/SL tercapai</p>
            )}
          </div>
        ) : (
          <>
            <div className="flex items-center gap-3 px-4 py-2 bg-neutral-50 border-b text-[10px] font-bold text-neutral-400 uppercase tracking-wider">
              <span className="flex-1">Koin</span>
              <span className="w-20 text-right hidden sm:block">Entry</span>
              <span className="w-20 text-right hidden md:block">Close</span>
              <span className="w-16 text-right">P&amp;L</span>
              <span className="w-24 text-center">Status</span>
            </div>

            {closedList.map(p => {
              const pnl        = p.pnl_pct ?? 0;
              const riskDollar = BALANCE_START * RISK_PCT;
              const riskPct    = p.risk_pct > 0 ? p.risk_pct : 2.0;
              const notional   = riskDollar / (riskPct / 100);
              const pnl$       = (pnl / 100) * notional;

              const closeReasonLabel: Record<string, string> = {
                sl_hit:           "SL Hit",
                tp2_hit:          "TP2 Hit",
                tp3_hit:          "TP3 Hit",
                trend_reversal:   "Trend Reversal",
                profit_protection:"Profit Protected",
                flow_reversal:    "Flow Reversal",
                risk_adjusted:    "Risk Adjusted",
              };

              return (
                <div key={p.id}
                  className="flex items-center gap-3 px-4 py-3 border-b border-neutral-100 hover:bg-neutral-50 last:border-0">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <span className="font-bold text-sm">{p.symbol.replace("USDT", "")}/USDT</span>
                      {p.auto_open && (
                        <span className="text-[9px] font-bold bg-teal-100 text-teal-700 px-1.5 py-0.5 rounded">AUTO</span>
                      )}
                      {p.close_reason && closeReasonLabel[p.close_reason] && (
                        <span className="text-[9px] font-semibold bg-blue-50 text-blue-600 px-1.5 py-0.5 rounded">
                          {closeReasonLabel[p.close_reason]}
                        </span>
                      )}
                    </div>
                    <p className="text-[10px] text-neutral-400">
                      {p.entry_at ? new Date(p.entry_at * 1000).toLocaleDateString("id-ID") : ""}
                      {p.closed_at ? ` → ${new Date(p.closed_at * 1000).toLocaleDateString("id-ID")}` : ""}
                    </p>
                  </div>
                  <div className="w-20 text-right hidden sm:block">
                    <p className="text-xs font-mono">${fmtPrice(p.entry)}</p>
                  </div>
                  <div className="w-20 text-right hidden md:block">
                    {p.close_price != null && <p className="text-xs font-mono">${fmtPrice(p.close_price)}</p>}
                  </div>
                  <div className="w-20 text-right">
                    <p className={`text-sm font-black tabular-nums ${pnl >= 0 ? "text-green-600" : "text-red-500"}`}>
                      {pnl >= 0 ? "+" : ""}${Math.abs(pnl$).toFixed(2)}
                    </p>
                    <p className={`text-[9px] tabular-nums ${pnl >= 0 ? "text-green-500" : "text-red-400"}`}>
                      {pnl >= 0 ? "+" : ""}{pnl.toFixed(1)}%
                    </p>
                  </div>
                  <div className="w-24 text-center">
                    <StatusBadge status={p.status} />
                  </div>
                </div>
              );
            })}
          </>
        )}
      </div>

      {/* ── Empty state ───────────────────────────────────────────────────────────── */}
      {positions.length === 0 && !loading && (
        <div className="text-center py-16 text-neutral-400">
          <p className="text-4xl mb-3">🎯</p>
          <p className="font-semibold text-neutral-600">Belum ada posisi Opportunity SPOT</p>
          <p className="text-sm mt-2 max-w-sm mx-auto">
            Buka halaman <strong>Opportunity</strong>, klik koin, lalu{" "}
            <strong className="text-teal-600">Buka Posisi SPOT</strong>
          </p>
        </div>
      )}

    </div>
  );
}

// Helper for notification
const StatusLabel: Record<string, string> = {
  tp: "TP Hit", sl: "SL Hit", manual: "Ditutup Manual",
};
