"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { fmtPrice } from "@/lib/format";

// ── Types ─────────────────────────────────────────────────────────────────────

interface Trade {
  id:           number;
  symbol:       string;
  style:        string;
  direction:    string;
  status:       string;
  entry:        number;
  sl:           number;
  close_price:  number | null;
  pnl_pct:      number | null;
  pnl_gross_pct?: number | null;
  fee_pct?:     number | null;
  risk_pct:     number;
  rr_ratio:     number;
  score:        number;
  leverage:     number | null;
  signals:      string[];
  alert_type:   string;
  close_reason: string | null;
  tp1_hit:      boolean;
  entry_at:     number;
  closed_at:    number | null;
  position_size?: number | null;
  risk_dollar?:   number | null;
  pnl_dollar?:    number | null;
}

interface Summary {
  total_all: number; open: number; closed: number;
  wins: number; losses: number; win_rate: number; avg_pnl: number;
  manual_count?: number;
  realized_pnl_dollar?: number;
  profit_factor?: number | null;
  max_drawdown_dollar?: number;
}

interface TradeResponse {
  trades:    Trade[];
  total:     number;
  page:      number;
  page_size: number;
  pages:     number;
  summary:   Summary;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtDateTime(ts: number | null): { date: string; time: string } {
  if (!ts) return { date: "—", time: "" };
  const d = new Date(ts * 1000);
  return {
    date: d.toLocaleDateString("id-ID", { day: "2-digit", month: "short", year: "2-digit" }),
    time: d.toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit", second: "2-digit" }),
  };
}

function fmtDuration(entry_at: number, closed_at: number | null): string {
  if (!closed_at) return "Open";
  const secs = Math.floor(closed_at - entry_at);
  // PLAN-SIGNAL-GAP F3: was "d" for seconds-remainder, easily misread as "days"
  // since "hr" (hari) is used for actual days a few lines below — now "dtk" (detik).
  if (secs < 60)    return `${secs}dtk`;
  if (secs < 3600)  return `${Math.floor(secs / 60)}m ${secs % 60}dtk`;
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  return h < 24 ? `${h}j ${m}m` : `${Math.floor(h / 24)}hr ${h % 24}j`;
}


// ── Sub-components ────────────────────────────────────────────────────────────

function TypeBadge({ style }: { style: string }) {
  if (style === "opportunity_spot")
    return <span className="text-[9px] font-bold px-1.5 py-0.5 rounded-full bg-teal-100 text-teal-700 border border-teal-200 shrink-0">🎯 SPOT</span>;
  if (style === "futures_agent1")
    return <span className="text-[9px] font-bold px-1.5 py-0.5 rounded-full bg-blue-100 text-blue-700 border border-blue-200 shrink-0">🎯 Pre-Gainer</span>;
  if (style === "futures_agent2")
    return <span className="text-[9px] font-bold px-1.5 py-0.5 rounded-full bg-purple-100 text-purple-700 border border-purple-200 shrink-0">📦 Accumulation</span>;
  if (style === "futures_agent3")
    return <span className="text-[9px] font-bold px-1.5 py-0.5 rounded-full bg-orange-100 text-orange-700 border border-orange-200 shrink-0">🔥 Momentum</span>;
  return <span className="text-[9px] font-bold px-1.5 py-0.5 rounded-full bg-neutral-100 text-neutral-600 border border-neutral-200 shrink-0">{style}</span>;
}

function StatusBadge({ status, pnl }: { status: string; pnl: number | null }) {
  if (status === "open") return <span className="text-[9px] font-bold px-2 py-0.5 rounded-full bg-blue-100 text-blue-700 border border-blue-200">🔵 Open</span>;
  if (status === "tp") {
    const isRealWin = (pnl ?? 0) > 0;
    return isRealWin
      ? <span className="text-[9px] font-bold px-2 py-0.5 rounded-full bg-green-100 text-green-700 border border-green-200">✅ TP</span>
      : <span className="text-[9px] font-bold px-2 py-0.5 rounded-full bg-yellow-100 text-yellow-700 border border-yellow-200">⚠️ TP-</span>;
  }
  if (status === "sl") {
    // F114: SL+ = trail moved above entry, closed at profit
    if ((pnl ?? 0) > 0)
      return <span className="text-[9px] font-bold px-2 py-0.5 rounded-full bg-teal-100 text-teal-700 border border-teal-200">🛡 SL+</span>;
    return <span className="text-[9px] font-bold px-2 py-0.5 rounded-full bg-red-100 text-red-600 border border-red-200">🛑 SL</span>;
  }
  return <span className="text-[9px] font-bold px-2 py-0.5 rounded-full bg-neutral-100 text-neutral-500 border border-neutral-200">{status}</span>;
}

// PLAN-SIGNAL-GAP F1: `scope` marks which trade type can actually produce this reason —
// "both" reasons exist in both monitors; "spot"/"futures" only exist in one. The legend
// at the bottom filters by `reasonScope` so a Futures-only table doesn't show Spot-only
// reasons (trend_reversal etc.) that can never appear there, and vice versa.
// Removed `opportunity_lost` — grepped the whole backend, never produced anywhere (dead).
// Added `tp1_breakeven`, `stagnant_rotation` (spot) and `stagnant_48h`, `breakeven_stop`
// (futures) — these close reasons exist in the monitors but were missing from this map,
// so they fell back to the raw-string badge instead of a proper label.
const CLOSE_REASON_META: Record<string, { label: string; color: string; emoji: string; scope: "spot" | "futures" | "both" }> = {
  sl_hit:            { label: "SL Hit",          color: "bg-red-100 text-red-700",         emoji: "🛑", scope: "both" },
  sl_plus:           { label: "SL+ Profit",      color: "bg-teal-100 text-teal-700",       emoji: "🛡", scope: "futures" },
  breakeven_stop:    { label: "Breakeven Stop",  color: "bg-neutral-200 text-neutral-600", emoji: "⏸",  scope: "futures" },
  tp1_breakeven:     { label: "TP1 Breakeven",   color: "bg-teal-100 text-teal-700",       emoji: "🛡", scope: "spot" },
  tp2_hit:           { label: "TP2 Hit",         color: "bg-green-100 text-green-700",     emoji: "✅", scope: "both" },
  tp3_hit:           { label: "TP3 Hit",         color: "bg-emerald-100 text-emerald-700", emoji: "🎯", scope: "both" },
  trend_reversal:    { label: "Trend Reversal",  color: "bg-orange-100 text-orange-700",   emoji: "↩️", scope: "spot" },
  profit_protection: { label: "Profit Guard",    color: "bg-yellow-100 text-yellow-700",   emoji: "🛡", scope: "spot" },
  flow_reversal:     { label: "Flow Reversal",   color: "bg-purple-100 text-purple-700",   emoji: "🔄", scope: "spot" },
  risk_adjusted:     { label: "Risk Adjusted",   color: "bg-pink-100 text-pink-700",       emoji: "⚖️", scope: "spot" },
  stagnant_rotation: { label: "Stagnant Rotate", color: "bg-neutral-100 text-neutral-500", emoji: "🔁", scope: "spot" },
  liq_guard:         { label: "Liq Guard",       color: "bg-red-200 text-red-800",         emoji: "🚨", scope: "futures" },
  stagnant_48h:      { label: "Stagnant 48h",    color: "bg-neutral-100 text-neutral-500", emoji: "💤", scope: "futures" },
  max_age_expired:      { label: "Max Age",          color: "bg-neutral-100 text-neutral-500", emoji: "⏰", scope: "both" },
  trend_structure_broken: { label: "Structure Break", color: "bg-orange-100 text-orange-700",   emoji: "📉", scope: "spot" },
};

function CloseReasonBadge({ reason }: { reason: string | null }) {
  if (!reason) return <span className="text-neutral-300 text-[10px]">—</span>;
  const meta = CLOSE_REASON_META[reason];
  if (!meta) return <span className="text-[9px] px-1.5 py-0.5 rounded bg-neutral-100 text-neutral-500 font-mono">{reason}</span>;
  return (
    <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded-full ${meta.color}`}>
      {meta.emoji} {meta.label}
    </span>
  );
}

function SortIcon({ col, active, dir }: { col: string; active: string; dir: string }) {
  if (col !== active) return <span className="text-neutral-300 ml-0.5">↕</span>;
  return <span className="text-teal-500 ml-0.5">{dir === "desc" ? "↓" : "↑"}</span>;
}

// ── Main Component ─────────────────────────────────────────────────────────────

interface StyleOption { key: string; label: string }

interface DBHistoryTableProps {
  defaultStyle?:  "all" | "spot" | "agent1" | "agent2" | "agent3" | "futures";
  hideStyleTabs?: boolean;
  styleOptions?:  StyleOption[];   // F115: override default style tabs (e.g. futures-only)
  compact?:       boolean;
  autoRefresh?:   number;   // polling interval ms — 0 or undefined = disabled
  days?:          number;   // §16.6: window riwayat (default 90 hari)
  reasonScope?:   "all" | "spot" | "futures";   // PLAN-SIGNAL-GAP F1: filters the legend
}

const DEFAULT_STYLE_TABS: StyleOption[] = [
  { key: "all",    label: "Semua" },
  { key: "spot",   label: "🎯 Spot" },
  { key: "agent1", label: "🎯 Pre-Gainer" },
  { key: "agent2", label: "📦 Accumulation" },
  { key: "agent3", label: "🔥 Momentum" },
];

export function DBHistoryTable({
  defaultStyle  = "all",
  hideStyleTabs = false,
  styleOptions,
  compact:      _compact = false,  // eslint-disable-line @typescript-eslint/no-unused-vars
  autoRefresh   = 0,
  days          = 90,
  reasonScope   = "all",
}: DBHistoryTableProps = {}) {
  const [data,        setData]        = useState<TradeResponse | null>(null);
  const [loading,     setLoading]     = useState(true);
  const [page,        setPage]        = useState(1);
  const [search,      setSearch]      = useState("");
  const [debouncedQ,  setDebouncedQ]  = useState("");
  const [styleFilter, setStyleFilter] = useState<string>(defaultStyle);
  const [statusFilter,setStatusFilter]= useState("all");
  const [sortBy,      setSortBy]      = useState("entry_at");
  const [sortDir,     setSortDir]     = useState<"desc"|"asc">("desc");
  const [expanded,    setExpanded]    = useState<number | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const PAGE_SIZE = 25;
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Debounce search
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      setDebouncedQ(search.trim());
      setPage(1);
    }, 350);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [search]);

  const fetchData = useCallback(async (p = page, silent = false) => {
    if (!silent) setLoading(true);
    try {
      const params = new URLSearchParams({
        page:      String(p),
        page_size: String(PAGE_SIZE),
        sort_by:   sortBy,
        sort_dir:  sortDir,
        days:      String(days),
      });
      if (styleFilter  !== "all") params.set("style",  styleFilter);
      if (statusFilter !== "all") params.set("status", statusFilter);
      if (debouncedQ)              params.set("search", debouncedQ);

      const r = await fetch(`/api/v1/history/trades?${params.toString()}`);
      if (r.ok) {
        setData(await r.json() as TradeResponse);
        setLastRefresh(new Date());
      }
    } catch { /* silent */ }
    finally { if (!silent) setLoading(false); }
  }, [page, sortBy, sortDir, styleFilter, statusFilter, debouncedQ, days]);

  // Initial + reactive fetch
  useEffect(() => { void fetchData(page); }, [fetchData, page]);

  // Auto-refresh polling
  useEffect(() => {
    if (!autoRefresh || autoRefresh <= 0) return;
    const id = setInterval(() => void fetchData(page, true), autoRefresh);
    return () => clearInterval(id);
  }, [autoRefresh, fetchData, page]);

  const handleSort = (col: string) => {
    if (sortBy === col) setSortDir(d => d === "desc" ? "asc" : "desc");
    else { setSortBy(col); setSortDir("desc"); }
    setPage(1);
  };

  const summary = data?.summary;
  const trades  = data?.trades ?? [];
  const totalPages = data?.pages ?? 1;

  return (
    <div className="space-y-4">

      {/* ── Live indicator + last refresh ─────────────────────────────────────── */}
      {autoRefresh > 0 && (
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5 px-2 py-1 rounded-full bg-green-50 border border-green-200 w-fit">
            <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />
            <span className="text-[10px] font-bold text-green-700">LIVE</span>
            <span className="text-[10px] text-green-600">refresh {autoRefresh / 1000}s</span>
          </div>
          {lastRefresh && (
            <span className="text-[10px] text-neutral-400">
              Diperbarui: {lastRefresh.toLocaleTimeString("id-ID")}
            </span>
          )}
        </div>
      )}

      {/* ── Summary strip ─────────────────────────────────────────────────────── */}
      {summary && (
        <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-8 gap-2">
          {[
            { label: "Total",   val: summary.total_all,                        color: "text-neutral-700" },
            { label: "Open",    val: summary.open,                             color: "text-blue-600"    },
            { label: "Closed",  val: summary.closed,                           color: "text-neutral-600" },
            { label: "Win",     val: summary.wins,                             color: "text-green-600"   },
            { label: "Loss",    val: summary.losses,                           color: "text-red-500"     },
            { label: "Win Rate",val: `${summary.win_rate.toFixed(1)}%`,        color: summary.win_rate >= 50 ? "text-green-600" : "text-red-500" },
            {
              label: "P&L $",
              val: summary.realized_pnl_dollar != null
                ? `${summary.realized_pnl_dollar >= 0 ? "+" : ""}$${summary.realized_pnl_dollar.toFixed(2)}`
                : "—",
              color: (summary.realized_pnl_dollar ?? 0) >= 0 ? "text-green-600" : "text-red-500",
            },
            {
              label: "Profit Factor",
              val: summary.profit_factor != null ? summary.profit_factor.toFixed(2) : "—",
              color: (summary.profit_factor ?? 0) >= 1 ? "text-green-600" : "text-red-500",
            },
          ].map(s => (
            <div key={s.label} className="bg-neutral-50 border border-neutral-200 rounded-xl px-3 py-2 text-center">
              <p className={`text-lg font-black ${s.color}`}>{s.val}</p>
              <p className="text-[9px] text-neutral-400 uppercase tracking-wide font-semibold">{s.label}</p>
            </div>
          ))}
        </div>
      )}

      {/* ── Filters + Search ──────────────────────────────────────────────────── */}
      <div className="flex flex-wrap gap-2 items-center">

        {/* Style tabs — hidden when embedded in specific tab */}
        {!hideStyleTabs && (
          <div className="flex bg-neutral-100 rounded-xl p-1 gap-0.5">
            {(styleOptions ?? DEFAULT_STYLE_TABS).map(f => (
              <button key={f.key}
                onClick={() => { setStyleFilter(f.key); setPage(1); }}
                className={`px-2.5 py-1 rounded-lg text-xs font-semibold transition-all ${
                  styleFilter === f.key ? "bg-white text-neutral-900 shadow-sm" : "text-neutral-500 hover:text-neutral-700"
                }`}>{f.label}</button>
            ))}
          </div>
        )}

        {/* Status filter */}
        <div className="flex bg-neutral-100 rounded-xl p-1 gap-0.5">
          {[
            { key: "all",  label: "Status" },
            { key: "open", label: "Open"   },
            { key: "win",  label: "✅ TP"  },
            { key: "loss", label: "🛑 SL"  },
          ].map(f => (
            <button key={f.key}
              onClick={() => { setStatusFilter(f.key); setPage(1); }}
              className={`px-2.5 py-1 rounded-lg text-xs font-semibold transition-all ${
                statusFilter === f.key ? "bg-white text-neutral-900 shadow-sm" : "text-neutral-500 hover:text-neutral-700"
              }`}>{f.label}</button>
          ))}
        </div>

        {/* Search */}
        <div className="relative">
          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-neutral-400 text-xs">🔍</span>
          <input
            type="text"
            placeholder="Cari simbol..."
            value={search}
            onChange={e => setSearch(e.target.value.toUpperCase())}
            className="pl-8 pr-3 py-1.5 bg-white border border-neutral-200 rounded-xl text-xs focus:outline-none focus:border-teal-400 w-40"
          />
          {search && (
            <button onClick={() => { setSearch(""); setPage(1); }}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-neutral-400 hover:text-neutral-600 text-xs">✕</button>
          )}
        </div>

        {/* Count */}
        <span className="text-xs text-neutral-400 ml-auto tabular-nums">
          {loading ? "..." : `${data?.total ?? 0} trade`}
        </span>
      </div>

      {/* ── Table ─────────────────────────────────────────────────────────────── */}
      <div className="bg-white border border-neutral-200 rounded-2xl overflow-hidden">

        {/* Header */}
        <div className="grid grid-cols-[auto_1fr_auto_auto_auto_auto_auto_auto_auto_auto_auto] gap-x-2 px-3 py-2 bg-neutral-50 border-b border-neutral-200 text-[10px] font-bold text-neutral-400 uppercase tracking-wider">
          <span className="w-8">#</span>
          <button className="text-left flex items-center hover:text-neutral-600" onClick={() => handleSort("symbol")}>
            Simbol <SortIcon col="symbol" active={sortBy} dir={sortDir} />
          </button>
          <span className="w-24">Tipe</span>
          <span className="w-16">Status</span>
          <button className="w-28 text-right flex items-center justify-end hover:text-neutral-600" onClick={() => handleSort("entry_at")}>
            Entry <SortIcon col="entry_at" active={sortBy} dir={sortDir} />
          </button>
          <button className="w-28 text-right flex items-center justify-end hover:text-neutral-600" onClick={() => handleSort("closed_at")}>
            Tutup <SortIcon col="closed_at" active={sortBy} dir={sortDir} />
          </button>
          <span className="w-16 text-center">Durasi</span>
          <span className="w-16 text-right">Notional</span>
          <button className="w-20 text-right flex items-center justify-end hover:text-neutral-600" onClick={() => handleSort("pnl_pct")}>
            P&L% <SortIcon col="pnl_pct" active={sortBy} dir={sortDir} />
          </button>
          <span className="w-20 text-right">P&L $</span>
          <span className="w-28 text-center">Alasan Tutup</span>
        </div>

        {/* Rows */}
        {loading && trades.length === 0 ? (
          <div className="flex items-center justify-center py-12 text-neutral-400">
            <div className="w-6 h-6 border-2 border-teal-400 border-t-transparent rounded-full animate-spin mr-2" />
            Memuat data...
          </div>
        ) : trades.length === 0 ? (
          <div className="text-center py-12 text-neutral-400">
            <p className="text-3xl mb-2">📭</p>
            <p className="font-semibold">Belum ada trade</p>
            <p className="text-xs mt-1">Agents akan mulai mencatat setelah scan berikutnya</p>
          </div>
        ) : (
          <div className={`divide-y divide-neutral-100 ${loading ? "opacity-60" : ""} transition-opacity`}>
            {trades.map((t, i) => {
              const entryDT  = fmtDateTime(t.entry_at);
              const closeDT  = fmtDateTime(t.closed_at);
              const duration = fmtDuration(t.entry_at, t.closed_at);
              // §3: pakai pnl_dollar TERSIMPAN dari API (margin riil), bukan rumus hardcode
              const pnl$     = t.pnl_dollar ?? null;
              // F114: SL+ (trail above entry, closed at profit) counts as win
              const isWin    = (t.pnl_pct ?? 0) > 0 && (t.status === "tp" || t.status === "sl");
              const isLoss   = (t.status === "sl" && (t.pnl_pct ?? 0) <= 0) || (t.status === "tp" && (t.pnl_pct ?? 0) <= 0);
              const isOpen   = t.status === "open";
              const isExpanded = expanded === t.id;

              return (
                <div key={t.id}>
                  {/* Main row */}
                  <div
                    onClick={() => setExpanded(isExpanded ? null : t.id)}
                    className={`grid grid-cols-[auto_1fr_auto_auto_auto_auto_auto_auto_auto_auto_auto] gap-x-2 px-3 py-2.5 items-center cursor-pointer transition-colors ${
                      isExpanded ? "bg-teal-50" :
                      isWin ? "hover:bg-green-50/30" :
                      isLoss ? "hover:bg-red-50/20" :
                      "hover:bg-neutral-50"
                    }`}
                  >
                    {/* # */}
                    <span className="w-8 text-[10px] text-neutral-400 tabular-nums">
                      {(page - 1) * PAGE_SIZE + i + 1}
                    </span>

                    {/* Symbol */}
                    <div className="flex items-center gap-1.5 min-w-0">
                      <span className="font-bold text-sm truncate">{t.symbol.replace("USDT", "")}</span>
                      {t.direction && (
                        <span className={`text-[9px] font-black shrink-0 ${t.direction === "LONG" ? "text-green-600" : "text-red-500"}`}>
                          {t.direction === "LONG" ? "▲" : "▼"}
                        </span>
                      )}
                      <button className={`text-[9px] ml-0.5 text-neutral-300 hover:text-neutral-600 shrink-0 transition-transform ${isExpanded ? "rotate-180" : ""}`}>▾</button>
                    </div>

                    {/* Type */}
                    <div className="w-24 flex items-center">
                      <TypeBadge style={t.style} />
                    </div>

                    {/* Status */}
                    <div className="w-16">
                      <StatusBadge status={t.status} pnl={t.pnl_pct} />
                    </div>

                    {/* Entry time */}
                    <div className="w-28 text-right">
                      <p className="text-[10px] font-mono text-neutral-700">{entryDT.time}</p>
                      <p className="text-[9px] text-neutral-400">{entryDT.date}</p>
                    </div>

                    {/* Close time */}
                    <div className="w-28 text-right">
                      {t.closed_at ? (
                        <>
                          <p className="text-[10px] font-mono text-neutral-700">{closeDT.time}</p>
                          <p className="text-[9px] text-neutral-400">{closeDT.date}</p>
                        </>
                      ) : (
                        <p className="text-[10px] text-blue-500 font-semibold">Running...</p>
                      )}
                    </div>

                    {/* Duration */}
                    <div className="w-16 text-center">
                      <span className={`text-[10px] font-mono font-bold ${isOpen ? "text-blue-500" : "text-neutral-600"}`}>
                        {duration}
                      </span>
                    </div>

                    {/* Notional + margin (F116) */}
                    <div className="w-16 text-right">
                      {t.position_size != null ? (
                        <div>
                          <p className="text-[10px] font-mono font-bold text-neutral-600 tabular-nums">
                            ${t.position_size.toFixed(0)}
                          </p>
                          {t.leverage != null && (
                            <p className="text-[9px] text-neutral-400 tabular-nums">
                              ${Math.round(t.position_size / t.leverage)} mrg
                            </p>
                          )}
                        </div>
                      ) : (
                        <span className="text-neutral-300 text-xs">—</span>
                      )}
                    </div>

                    {/* PnL % */}
                    <div className="w-20 text-right">
                      {t.pnl_pct != null ? (
                        <span className={`text-xs font-black tabular-nums ${t.pnl_pct > 0 ? "text-green-600" : t.pnl_pct < 0 ? "text-red-500" : "text-neutral-400"}`}>
                          {t.pnl_pct >= 0 ? "+" : ""}{t.pnl_pct.toFixed(2)}%
                        </span>
                      ) : (
                        <span className="text-neutral-300 text-xs">—</span>
                      )}
                    </div>

                    {/* PnL $ */}
                    <div className="w-20 text-right">
                      {pnl$ != null ? (
                        <span className={`text-xs font-black tabular-nums ${pnl$ > 0 ? "text-green-600" : pnl$ < 0 ? "text-red-500" : "text-neutral-400"}`}>
                          {pnl$ >= 0 ? "+" : ""}${Math.abs(pnl$).toFixed(2)}
                        </span>
                      ) : (
                        <span className="text-neutral-300 text-xs">—</span>
                      )}
                    </div>

                    {/* Close reason */}
                    <div className="w-28 flex justify-center">
                      <CloseReasonBadge reason={t.close_reason} />
                    </div>
                  </div>

                  {/* Expanded detail row */}
                  {isExpanded && (
                    <div className="px-4 py-3 bg-teal-50/40 border-t border-teal-100 text-xs">
                      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3 mb-3">
                        {[
                          { label: "Entry Price",  val: `$${fmtPrice(t.entry)}` },
                          { label: "Stop Loss",    val: `$${fmtPrice(t.sl)}` },
                          { label: "Close Price",  val: t.close_price != null ? `$${fmtPrice(t.close_price)}` : "—" },
                          { label: "Score",        val: `${t.score.toFixed(0)} pt` },
                          { label: "R:R",          val: t.rr_ratio ? `1:${t.rr_ratio}` : "—" },
                          { label: "Risk %",       val: `${t.risk_pct.toFixed(2)}%` },
                          { label: "Notional",     val: t.position_size != null ? `$${t.position_size.toFixed(2)}` : "—" },
                          { label: "Margin (Jaminan)", val: (t.position_size != null && t.leverage != null) ? `$${(t.position_size / t.leverage).toFixed(2)}` : "—" },
                          { label: "Risk $",       val: t.risk_dollar != null ? `$${t.risk_dollar.toFixed(2)}` : "—" },
                          { label: "Leverage",     val: t.leverage ? `${t.leverage}x` : "—" },
                          { label: "P&L Gross",    val: t.pnl_gross_pct != null ? `${t.pnl_gross_pct >= 0 ? "+" : ""}${t.pnl_gross_pct.toFixed(2)}%` : "—" },
                          { label: "Fee",          val: t.fee_pct != null ? `-${t.fee_pct.toFixed(2)}%` : "—" },
                          { label: "TP1 Hit",      val: t.tp1_hit ? "✅ Ya" : "❌ Tidak" },
                        ].map(x => (
                          <div key={x.label} className="bg-white rounded-lg px-2.5 py-1.5 border border-teal-100">
                            <p className="text-[9px] text-neutral-400 uppercase tracking-wide font-semibold mb-0.5">{x.label}</p>
                            <p className="font-bold text-neutral-800 font-mono text-[11px]">{x.val}</p>
                          </div>
                        ))}
                      </div>

                      {/* Signals */}
                      {t.signals.length > 0 && (
                        <div>
                          <p className="text-[9px] font-bold text-neutral-400 uppercase tracking-wider mb-1.5">Sinyal</p>
                          <div className="flex flex-wrap gap-1.5">
                            {t.signals.map((sig, si) => (
                              <span key={si} className="text-[10px] bg-white border border-teal-200 text-teal-800 px-2 py-0.5 rounded-lg">
                                {sig}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* ── Pagination ────────────────────────────────────────────────────────── */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs text-neutral-400">
            Halaman <strong className="text-neutral-700">{page}</strong> dari <strong className="text-neutral-700">{totalPages}</strong>
            {" "}· {data?.total ?? 0} total trade
          </p>
          <div className="flex gap-1">
            <button
              onClick={() => setPage(1)}
              disabled={page === 1}
              className="px-2 py-1 rounded-lg text-xs border border-neutral-200 bg-white text-neutral-600 hover:border-teal-400 disabled:opacity-30 disabled:cursor-not-allowed"
            >«</button>
            <button
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page === 1}
              className="px-3 py-1 rounded-lg text-xs border border-neutral-200 bg-white text-neutral-600 hover:border-teal-400 disabled:opacity-30 disabled:cursor-not-allowed"
            >‹ Prev</button>

            {/* Page number pills */}
            {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
              let pg = page - 2 + i;
              if (pg < 1) pg += Math.max(0, 1 - (page - 2));
              if (pg > totalPages) pg -= Math.max(0, pg - totalPages);
              return pg;
            }).filter((pg, i, arr) => arr.indexOf(pg) === i && pg >= 1 && pg <= totalPages).map(pg => (
              <button key={pg}
                onClick={() => setPage(pg)}
                className={`px-3 py-1 rounded-lg text-xs border transition-all ${
                  pg === page
                    ? "bg-teal-600 text-white border-teal-600 font-bold"
                    : "border-neutral-200 bg-white text-neutral-600 hover:border-teal-400"
                }`}
              >{pg}</button>
            ))}

            <button
              onClick={() => setPage(p => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              className="px-3 py-1 rounded-lg text-xs border border-neutral-200 bg-white text-neutral-600 hover:border-teal-400 disabled:opacity-30 disabled:cursor-not-allowed"
            >Next ›</button>
            <button
              onClick={() => setPage(totalPages)}
              disabled={page === totalPages}
              className="px-2 py-1 rounded-lg text-xs border border-neutral-200 bg-white text-neutral-600 hover:border-teal-400 disabled:opacity-30 disabled:cursor-not-allowed"
            >»</button>
          </div>
        </div>
      )}

      {/* ── Close Reason Legend ───────────────────────────────────────────────── */}
      <details className="group">
        <summary className="cursor-pointer text-xs text-neutral-400 hover:text-neutral-600 select-none flex items-center gap-1.5">
          <span className="group-open:rotate-90 transition-transform inline-block">▶</span>
          Legenda Alasan Tutup Posisi
        </summary>
        <div className="mt-3 grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-2">
          {Object.entries(CLOSE_REASON_META)
            .filter(([, meta]) => reasonScope === "all" || meta.scope === "both" || meta.scope === reasonScope)
            .map(([key, meta]) => (
            <div key={key} className={`rounded-xl px-3 py-2 border ${meta.color.replace("text-", "border-").replace(/[-\d]+$/, "200")}`}>
              <p className={`text-xs font-bold mb-0.5 ${meta.color}`}>{meta.emoji} {meta.label}</p>
              <p className="text-[9px] text-neutral-500 font-mono">{key}</p>
            </div>
          ))}
        </div>
      </details>
    </div>
  );
}
