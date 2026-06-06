"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { MarketIntelBanner } from "@/components/MarketIntelBanner";
import { fmtPrice } from "@/lib/format";
import Link from "next/link";

// ── Types ─────────────────────────────────────────────────────────────────────

interface MarketCtx {
  sentiment: string; btc_price: number; btc_change_24h: number;
  avg_change_top50: number; pct_green: number; pct_red: number;
  coins_down_10pct?: number; btc_funding: number;
  futures_signal_count?: number; opp_signal_count?: number;
}

interface OppPos {
  id: number; symbol: string; status: string; entry: number;
  current_price: number | null; unrealized_pnl_pct: number | null;
  tp2_pct: number; risk_pct: number; rr_ratio: number;
  signals: string[]; score: number; alert_type: string;
  tp1_hit: boolean; pnl_pct: number | null; entry_at: number;
  closed_at: number | null;
}

interface FutPos {
  id: number; symbol: string; direction: "LONG" | "SHORT"; agent: string;
  status: string; entry: number; current_price: number | null;
  unrealized_pnl: number | null; pnl_pct: number | null;
  tp2_pct: number; risk_pct: number; rr_ratio: number; leverage: number;
  score: number; signals: string[]; entry_at: number; closed_at: number | null;
}

interface LearningStats {
  regime: string;
  overall: { total: number; open: number; closed: number; wins: number; losses: number; win_rate: number };
  agent1: { total: number; wins: number; losses: number; win_rate: number };
  agent2: { total: number; wins: number; losses: number; win_rate: number };
  balance: { starting: number; current: number; total_pnl: number; roi_pct: number };
  equity_points: { trade_n: number; balance: number; win: boolean; symbol: string }[];
  monitor: { running: boolean; cycle_count: number; closed_today: number };
  updater?: { running: boolean };
}

interface FuturesStatus {
  next_scan_in_min: number | null;
  agent1_results: number; agent2_results: number;
  agent1_last_scan: number | null; agent2_last_scan: number | null;
  is_scanning?: boolean;
}

interface SpotAsset {
  asset: string; total: number; usdt_value: number;
  current_price: number; avg_buy_price: number | null;
  pnl_percent: number | null; pnl_usdt: number | null;
}

interface AgentState {
  running: boolean;
  cycle_count?: number;
  interval_minutes?: number;
  next_scan_in_min?: number | null;
  last_error?: string | null;
}

interface Health {
  status: string;
  db?: string;
  spot_scanner?:    AgentState;
  spot_monitor?:    AgentState;
  futures_scanner?: AgentState;
  futures_monitor?: AgentState;
  weight_updater?:  { last_run?: number | null; last_error?: string | null };
  // legacy
  scheduler?: AgentState;
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

const POLL_MS = 15_000;
const BALANCE_START = 1000;
const RISK_PCT = 0.01;

// ── Helpers ───────────────────────────────────────────────────────────────────

function pnlDollar(pnl_pct: number, risk_pct: number) {
  if (risk_pct <= 0) return 0;
  const notional = (BALANCE_START * RISK_PCT) / (risk_pct / 100);
  return (pnl_pct / 100) * notional;
}

function fmtTime(ts: number | null) {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" });
}

function fmtRelTime(ts: number | null) {
  if (!ts) return "—";
  const diff = Math.floor((Date.now() / 1000) - ts);
  if (diff < 60)    return `${diff}s lalu`;
  if (diff < 3600)  return `${Math.floor(diff / 60)}m lalu`;
  return `${Math.floor(diff / 3600)}j lalu`;
}

// ── Sub-components ────────────────────────────────────────────────────────────

function KpiCard({ label, value, sub, color, icon }: {
  label: string; value: string; sub?: string; color: string; icon: string
}) {
  return (
    <div className="bg-white rounded-2xl border border-neutral-200 px-5 py-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-[10px] font-bold text-neutral-400 uppercase tracking-wider mb-1">{label}</p>
          <p className={`text-2xl font-black tabular-nums leading-tight ${color}`}>{value}</p>
          {sub && <p className="text-[10px] text-neutral-400 mt-0.5">{sub}</p>}
        </div>
        <span className="text-2xl opacity-80">{icon}</span>
      </div>
    </div>
  );
}

function MiniEquity({ points, height = 32 }: { points: { balance: number; win: boolean }[]; height?: number }) {
  if (points.length < 2) return null;
  const min = Math.min(...points.map(p => p.balance));
  const max = Math.max(...points.map(p => p.balance));
  const range = max - min || 1;
  return (
    <div className="flex items-end gap-px" style={{ height }}>
      {points.slice(-40).map((pt, i) => {
        const h = Math.max(((pt.balance - min) / range) * 100, 3);
        return (
          <div key={i} className={`flex-1 min-w-[2px] rounded-sm ${i === 0 ? "bg-neutral-300" : pt.win ? "bg-green-400" : "bg-red-400"}`}
            style={{ height: `${h}%` }} />
        );
      })}
    </div>
  );
}

function StatusDot({ ok }: { ok: boolean }) {
  return <span className={`w-2 h-2 rounded-full inline-block mr-1.5 ${ok ? "bg-green-500" : "bg-red-500"}`} />;
}

function DirBadge({ dir }: { dir: "LONG" | "SHORT" }) {
  return dir === "LONG"
    ? <span className="text-[9px] font-black px-1.5 py-0.5 rounded bg-green-100 text-green-700 border border-green-300">▲ L</span>
    : <span className="text-[9px] font-black px-1.5 py-0.5 rounded bg-red-100 text-red-700 border border-red-300">▼ S</span>;
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const [ctx,        setCtx]        = useState<MarketCtx | null>(null);
  const [oppPos,     setOppPos]     = useState<OppPos[]>([]);
  const [futPos,     setFutPos]     = useState<FutPos[]>([]);
  const [learning,   setLearning]   = useState<LearningStats | null>(null);
  const [futStatus,  setFutStatus]  = useState<FuturesStatus | null>(null);
  const [spotAssets, setSpotAssets] = useState<SpotAsset[]>([]);
  const [spotError,  setSpotError]  = useState<string | null>(null);
  const [spotLoading, setSpotLoading] = useState(true);
  const [health,     setHealth]     = useState<Health | null>(null);
  const [binance,    setBinance]    = useState<BinanceStatus | null>(null);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const [countdown,  setCountdown]  = useState(POLL_MS / 1000);
  const countRef = useRef(POLL_MS / 1000);

  const fetchAll = useCallback(async () => {
    try {
      const [ctxR, oppR, futR, learnR, statR, spotR, healthR, binanceR] = await Promise.allSettled([
        fetch("/api/v1/market/context"),
        fetch("/api/v1/opportunity/positions"),
        fetch("/api/v1/futures/positions?status=all"),
        fetch("/api/v1/futures/learning/stats"),
        fetch("/api/v1/futures/status"),
        fetch("/api/v1/market/spot-positions"),
        fetch("/health"),
        fetch("/api/v1/market/binance-status"),
      ]);
      if (ctxR.status === "fulfilled" && ctxR.value.ok)
        setCtx(await ctxR.value.json() as MarketCtx);
      if (oppR.status === "fulfilled" && oppR.value.ok)
        setOppPos(((await oppR.value.json() as { positions: OppPos[] }).positions ?? []));
      if (futR.status === "fulfilled" && futR.value.ok)
        setFutPos(((await futR.value.json() as { positions: FutPos[] }).positions ?? []));
      if (learnR.status === "fulfilled" && learnR.value.ok) {
        const ld = await learnR.value.json() as LearningStats;
        if (!("error" in ld)) setLearning(ld);
      }
      if (statR.status === "fulfilled" && statR.value.ok)
        setFutStatus(await statR.value.json() as FuturesStatus);
      if (spotR.status === "fulfilled") {
        if (spotR.value.ok) {
          const sd = await spotR.value.json() as { assets?: SpotAsset[]; total_usdt_value?: number };
          setSpotAssets(sd.assets ?? []);
          setSpotError(null);
        } else {
          const errText = await spotR.value.text().catch(() => "");
          let msg = `Error ${spotR.value.status}`;
          try { msg = (JSON.parse(errText) as { detail?: string }).detail ?? msg; } catch { /* */ }
          setSpotError(msg);
          setSpotAssets([]);
        }
      } else {
        setSpotError("Gagal terhubung ke backend");
      }
      setSpotLoading(false);
      if (healthR.status === "fulfilled" && healthR.value.ok)
        setHealth(await healthR.value.json() as Health);
      if (binanceR.status === "fulfilled" && binanceR.value.ok)
        setBinance(await binanceR.value.json() as BinanceStatus);
      setLastUpdate(new Date());
    } catch { /* silent */ }
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

  // ── Derived ──────────────────────────────────────────────────────────────────

  const oppOpen   = useMemo(() => oppPos.filter(p => p.status === "open"),    [oppPos]);
  const futOpen   = useMemo(() => futPos.filter(p => p.status === "open"),    [futPos]);
  const oppClosed = useMemo(() => oppPos.filter(p => p.status !== "open").slice(-20), [oppPos]);
  const futClosed = useMemo(() => futPos.filter(p => p.status !== "open").slice(-20), [futPos]);

  // Combined recent trades (newest first)
  const recentTrades = useMemo(() => {
    type Trade = { id: string; symbol: string; type: "spot" | "fut"; dir: string; status: string;
      entry: number; close_price?: number | null; pnl_pct: number | null; pnl$: number;
      agent?: string; leverage?: number; entry_at: number; closed_at: number | null };
    const s: Trade[] = oppClosed.map(p => ({
      id: `s-${p.id}`, symbol: p.symbol, type: "spot" as const, dir: "LONG",
      status: p.status, entry: p.entry, pnl_pct: p.pnl_pct,
      pnl$: p.pnl_pct != null ? pnlDollar(p.pnl_pct, p.risk_pct) : 0,
      entry_at: p.entry_at, closed_at: p.closed_at,
    }));
    const f: Trade[] = futClosed.map(p => ({
      id: `f-${p.id}`, symbol: p.symbol, type: "fut" as const, dir: p.direction,
      status: p.status, entry: p.entry, pnl_pct: p.pnl_pct,
      pnl$: p.pnl_pct != null ? pnlDollar(p.pnl_pct, p.risk_pct) : 0,
      agent: p.agent, leverage: p.leverage,
      entry_at: p.entry_at, closed_at: p.closed_at,
    }));
    return [...s, ...f].sort((a, b) => (b.closed_at ?? 0) - (a.closed_at ?? 0)).slice(0, 10);
  }, [oppClosed, futClosed]);

  // Paper balances
  const oppBalance = useMemo(() => {
    let b = BALANCE_START;
    [...oppClosed].sort((a, b) => (a.closed_at ?? 0) - (b.closed_at ?? 0))
      .forEach(p => { if (p.pnl_pct != null) b = Math.max(0, b + pnlDollar(p.pnl_pct, p.risk_pct)); });
    return b;
  }, [oppClosed]);

  const futBalance = learning?.balance.current ?? BALANCE_START;
  const combinedPnl = (oppBalance - BALANCE_START) + (futBalance - BALANCE_START);

  const oppWinRate = useMemo(() => {
    const c = oppClosed.filter(p => p.status !== "open");
    return c.length > 0 ? (c.filter(p => p.status === "tp").length / c.length * 100) : 0;
  }, [oppClosed]);
  const futWinRate = learning?.overall.win_rate ?? 0;
  const combinedWinRate = useMemo(() => {
    const allClosed = oppClosed.length + (learning?.overall.closed ?? 0);
    const allWins   = oppClosed.filter(p => p.status === "tp").length + (learning?.overall.wins ?? 0);
    return allClosed > 0 ? allWins / allClosed * 100 : 0;
  }, [oppClosed, learning]);

  const totalOpenPositions = oppOpen.length + futOpen.length;
  const futCount = typeof ctx?.futures_signal_count === "number" ? ctx.futures_signal_count : -1;
  const oppCount = typeof ctx?.opp_signal_count      === "number" ? ctx.opp_signal_count     : -1;

  return (
    <div className="space-y-5">

      {/* ── Live indicator ──────────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold text-neutral-800">Command Center</h2>
          <p className="text-xs text-neutral-400">Spot · Futures · History · Market 24H</p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-green-50 border border-green-200">
            <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
            <span className="text-xs font-bold text-green-700">LIVE</span>
            <span className="text-xs text-green-600 tabular-nums">{countdown}s</span>
          </div>
          {lastUpdate && <span className="text-[10px] text-neutral-400">{lastUpdate.toLocaleTimeString()}</span>}
        </div>
      </div>

      {/* ── 1. Market Intel Banner ─────────────────────────────────────── */}
      <MarketIntelBanner mode="spot" refreshMs={60_000} />

      {/* ── 2. KPI Row ─────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KpiCard
          label="Paper Balance"
          value={`$${(oppBalance + futBalance - BALANCE_START).toFixed(0)}`}
          sub={`Spot $${oppBalance.toFixed(0)} + Fut $${futBalance.toFixed(0)}`}
          color={combinedPnl >= 0 ? "text-green-600" : "text-red-500"}
          icon="💰"
        />
        <KpiCard
          label="Combined PnL"
          value={`${combinedPnl >= 0 ? "+" : ""}$${combinedPnl.toFixed(2)}`}
          sub={`ROI ${((combinedPnl / (BALANCE_START * 2)) * 100).toFixed(1)}%`}
          color={combinedPnl >= 0 ? "text-green-600" : "text-red-500"}
          icon={combinedPnl >= 0 ? "📈" : "📉"}
        />
        <KpiCard
          label="Posisi Terbuka"
          value={String(totalOpenPositions)}
          sub={`${oppOpen.length} Spot · ${futOpen.length} Futures`}
          color={totalOpenPositions > 0 ? "text-blue-600" : "text-neutral-400"}
          icon="🎯"
        />
        <KpiCard
          label="Win Rate"
          value={combinedWinRate > 0 ? `${combinedWinRate.toFixed(0)}%` : "—"}
          sub={`Spot ${oppWinRate.toFixed(0)}% · Fut ${futWinRate.toFixed(0)}%`}
          color={combinedWinRate >= 50 ? "text-green-600" : combinedWinRate > 0 ? "text-red-500" : "text-neutral-400"}
          icon="🏆"
        />
      </div>

      {/* ── 3. Open Positions + Scanner Status ────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">

        {/* Open Positions */}
        <div className="bg-white rounded-2xl border border-neutral-200 overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b border-neutral-100 bg-neutral-50">
            <h3 className="font-bold text-sm text-neutral-700">
              📍 Posisi Terbuka
              <span className="ml-2 text-[10px] bg-blue-100 text-blue-700 font-bold px-2 py-0.5 rounded-full">
                {totalOpenPositions}
              </span>
            </h3>
            <Link href="/history" className="text-[10px] text-teal-600 hover:underline font-semibold">
              Lihat semua →
            </Link>
          </div>

          {totalOpenPositions === 0 ? (
            <div className="py-10 text-center text-neutral-400">
              <p className="text-2xl mb-1">📭</p>
              <p className="text-sm">Tidak ada posisi terbuka</p>
            </div>
          ) : (
            <div className="divide-y divide-neutral-100 max-h-72 overflow-y-auto">
              {oppOpen.map(p => {
                const upnl = p.unrealized_pnl_pct;
                return (
                  <div key={`o-${p.id}`} className="flex items-center gap-3 px-4 py-2.5 hover:bg-neutral-50">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="font-bold text-sm">{p.symbol.replace("USDT","")}</span>
                        <span className="text-[9px] bg-teal-100 text-teal-700 px-1.5 py-0.5 rounded font-bold">SPOT</span>
                        {p.tp1_hit && <span className="text-[9px] bg-yellow-100 text-yellow-700 px-1.5 py-0.5 rounded font-bold">TP1✓</span>}
                      </div>
                      <p className="text-[10px] text-neutral-400 truncate">{p.signals[0] ?? ""}</p>
                    </div>
                    <div className="text-right shrink-0">
                      <p className="text-xs font-mono font-bold">${fmtPrice(p.entry)}</p>
                      {p.current_price != null && (
                        <p className="text-[10px] text-neutral-400">→ ${fmtPrice(p.current_price)}</p>
                      )}
                    </div>
                    <div className="shrink-0 w-16 text-right">
                      <span className={`text-xs font-black tabular-nums px-1.5 py-0.5 rounded ${
                        upnl == null ? "text-neutral-400" : upnl >= 0 ? "text-green-700 bg-green-50" : "text-red-600 bg-red-50"
                      }`}>
                        {upnl == null ? "—" : `${upnl >= 0 ? "+" : ""}${upnl.toFixed(2)}%`}
                      </span>
                    </div>
                  </div>
                );
              })}
              {futOpen.map(p => {
                const upnl = p.unrealized_pnl;
                return (
                  <div key={`f-${p.id}`} className="flex items-center gap-3 px-4 py-2.5 hover:bg-neutral-50">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="font-bold text-sm">{p.symbol.replace("USDT","")}</span>
                        <DirBadge dir={p.direction} />
                        <span className="text-[9px] bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded font-bold">
                          {p.agent === "futures_agent1" ? "AI" : "T4"} {p.leverage}x
                        </span>
                      </div>
                      <p className="text-[10px] text-neutral-400 truncate">{p.signals[0] ?? ""}</p>
                    </div>
                    <div className="text-right shrink-0">
                      <p className="text-xs font-mono font-bold">${fmtPrice(p.entry)}</p>
                      {p.current_price != null && (
                        <p className="text-[10px] text-neutral-400">→ ${fmtPrice(p.current_price)}</p>
                      )}
                    </div>
                    <div className="shrink-0 w-16 text-right">
                      <span className={`text-xs font-black tabular-nums px-1.5 py-0.5 rounded ${
                        upnl == null ? "text-neutral-400" : upnl >= 0 ? "text-green-700 bg-green-50" : "text-red-600 bg-red-50"
                      }`}>
                        {upnl == null ? "—" : `${upnl >= 0 ? "+" : ""}${upnl.toFixed(2)}%`}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Scanner Status */}
        <div className="bg-white rounded-2xl border border-neutral-200 overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b border-neutral-100 bg-neutral-50">
            <h3 className="font-bold text-sm text-neutral-700">📡 Scanner Status</h3>
          </div>
          <div className="p-4 space-y-4">

            {/* Futures scanner */}
            <div className="rounded-xl border border-neutral-200 p-3 space-y-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-black text-blue-600">⚡ FUTURES</span>
                  <Link href="/scanner" className="text-[10px] text-neutral-400 hover:underline">buka →</Link>
                </div>
                <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                  futCount > 0 ? "bg-blue-100 text-blue-700" : "bg-neutral-100 text-neutral-500"
                }`}>
                  {futCount < 0 ? "belum scan" : `${futCount} sinyal`}
                </span>
              </div>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div>
                  <p className="text-neutral-400 text-[10px]">Agent 1 (AI)</p>
                  <p className="font-bold text-blue-600">{futStatus?.agent1_results ?? 0} sinyal</p>
                  <p className="text-[10px] text-neutral-400">{fmtRelTime(futStatus?.agent1_last_scan ?? null)}</p>
                </div>
                <div>
                  <p className="text-neutral-400 text-[10px]">Agent 2 (T0-T4)</p>
                  <p className="font-bold text-purple-600">{futStatus?.agent2_results ?? 0} sinyal</p>
                  <p className="text-[10px] text-neutral-400">{fmtRelTime(futStatus?.agent2_last_scan ?? null)}</p>
                </div>
              </div>
              {futStatus?.next_scan_in_min != null && (
                <div className="flex items-center gap-1.5 text-[10px] text-neutral-500">
                  <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />
                  Next scan: <strong className="text-neutral-700">{futStatus.next_scan_in_min.toFixed(1)} mnt</strong>
                </div>
              )}
            </div>

            {/* Spot opportunity */}
            <div className="rounded-xl border border-neutral-200 p-3 space-y-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-black text-teal-600">🎯 SPOT OPP</span>
                  <Link href="/opportunity" className="text-[10px] text-neutral-400 hover:underline">buka →</Link>
                </div>
                <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                  oppCount > 0 ? "bg-teal-100 text-teal-700" : "bg-neutral-100 text-neutral-500"
                }`}>
                  {oppCount < 0 ? "belum scan" : `${oppCount} rekomendasi`}
                </span>
              </div>
              {health?.scheduler && (
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div>
                    <p className="text-neutral-400 text-[10px]">Siklus Scan</p>
                    <p className="font-bold text-teal-600">{health.scheduler.cycle_count}x</p>
                  </div>
                  <div>
                    <p className="text-neutral-400 text-[10px]">Interval</p>
                    <p className="font-bold text-neutral-700">{health.scheduler.interval_minutes}m</p>
                  </div>
                </div>
              )}
              {health?.scheduler?.next_scan_in_min != null && (
                <div className="flex items-center gap-1.5 text-[10px] text-neutral-500">
                  <span className="w-1.5 h-1.5 rounded-full bg-teal-400 animate-pulse" />
                  Next scan: <strong className="text-neutral-700">{health.scheduler.next_scan_in_min.toFixed(1)} mnt</strong>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* ── 4. Balance Simulation + Win Rates ─────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

        {/* Spot Opp Balance */}
        <div className="bg-white rounded-2xl border border-neutral-200 p-4">
          <div className="flex items-center justify-between mb-3">
            <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider">🎯 Spot Opp Balance</p>
            <Link href="/history" className="text-[10px] text-teal-600 hover:underline">detail →</Link>
          </div>
          <div className="flex items-baseline gap-2 mb-1">
            <span className={`text-3xl font-black ${oppBalance >= BALANCE_START ? "text-green-600" : "text-red-500"}`}>
              ${oppBalance.toFixed(0)}
            </span>
            <span className={`text-sm font-bold ${(oppBalance - BALANCE_START) >= 0 ? "text-green-500" : "text-red-400"}`}>
              {(oppBalance - BALANCE_START) >= 0 ? "+" : ""}${(oppBalance - BALANCE_START).toFixed(2)}
            </span>
          </div>
          <p className="text-[10px] text-neutral-400 mb-3">
            Modal $1,000 · Risk $10/trade · Win Rate <strong>{oppWinRate.toFixed(0)}%</strong>
          </p>
          {learning && (
            <MiniEquity points={[{ balance: BALANCE_START, win: true },
              ...oppClosed.map((p, i) => ({ balance: oppBalance, win: p.status === "tp", n: i+1 }))]} />
          )}
          <div className="grid grid-cols-3 gap-2 mt-3">
            {[
              { label: "Open",  val: String(oppOpen.length),   color: "text-blue-600"  },
              { label: "Win",   val: String(oppClosed.filter(p => p.status === "tp").length), color: "text-green-600" },
              { label: "Loss",  val: String(oppClosed.filter(p => p.status === "sl").length), color: "text-red-500"   },
            ].map(s => (
              <div key={s.label} className="text-center bg-neutral-50 rounded-xl py-2">
                <p className={`text-lg font-black ${s.color}`}>{s.val}</p>
                <p className="text-[9px] text-neutral-400">{s.label}</p>
              </div>
            ))}
          </div>
        </div>

        {/* Futures Balance */}
        <div className="bg-white rounded-2xl border border-neutral-200 p-4">
          <div className="flex items-center justify-between mb-3">
            <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider">⚡ Futures Balance</p>
            <Link href="/history" className="text-[10px] text-blue-600 hover:underline">detail →</Link>
          </div>
          <div className="flex items-baseline gap-2 mb-1">
            <span className={`text-3xl font-black ${futBalance >= BALANCE_START ? "text-green-600" : "text-red-500"}`}>
              ${futBalance.toFixed(0)}
            </span>
            <span className={`text-sm font-bold ${(futBalance - BALANCE_START) >= 0 ? "text-green-500" : "text-red-400"}`}>
              {(futBalance - BALANCE_START) >= 0 ? "+" : ""}${(futBalance - BALANCE_START).toFixed(2)}
            </span>
          </div>
          <p className="text-[10px] text-neutral-400 mb-3">
            Modal $1,000 · Risk $10/trade · Win Rate <strong>{futWinRate.toFixed(0)}%</strong>
          </p>
          {learning?.equity_points && learning.equity_points.length > 1 && (
            <MiniEquity points={learning.equity_points.map(p => ({ balance: p.balance, win: p.win }))} />
          )}
          <div className="grid grid-cols-4 gap-1.5 mt-3">
            {[
              { label: "Open",  val: String(learning?.overall.open   ?? futOpen.length),   color: "text-blue-600"   },
              { label: "Win",   val: String(learning?.overall.wins   ?? 0), color: "text-green-600"  },
              { label: "Loss",  val: String(learning?.overall.losses ?? 0), color: "text-red-500"    },
              { label: "WR",    val: learning && learning.overall.closed > 0 ? `${futWinRate.toFixed(0)}%` : "—", color: futWinRate >= 50 ? "text-green-600" : "text-red-500" },
            ].map(s => (
              <div key={s.label} className="text-center bg-neutral-50 rounded-xl py-2">
                <p className={`text-base font-black ${s.color}`}>{s.val}</p>
                <p className="text-[9px] text-neutral-400">{s.label}</p>
              </div>
            ))}
          </div>
          {learning?.regime && (
            <div className="mt-2 flex items-center gap-1.5">
              <span className="text-[10px] text-neutral-400">Regime:</span>
              <span className="text-[10px] font-bold bg-blue-50 text-blue-600 px-2 py-0.5 rounded-full border border-blue-200 capitalize">
                {learning.regime}
              </span>
            </div>
          )}
        </div>

        {/* System Health */}
        <div className="bg-white rounded-2xl border border-neutral-200 p-4">
          <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider mb-3">⚙️ System Health</p>

          {/* Backend + DB */}
          <div className="space-y-1.5 mb-3 pb-3 border-b border-neutral-100">
            {[
              { label: "Backend API", ok: !!health,               sub: "" },
              { label: "Database",    ok: health?.db === "ok",    sub: health?.db === "ok" ? "connected" : "unavailable" },
            ].map(row => (
              <div key={row.label} className="flex items-center justify-between py-1 rounded-lg">
                <span className="text-xs text-neutral-600 font-medium">{row.label}</span>
                <span className={`text-[10px] font-bold flex items-center gap-1 ${row.ok ? "text-green-600" : "text-neutral-400"}`}>
                  <StatusDot ok={row.ok} />
                  {row.ok ? "Online" : "—"}
                </span>
              </div>
            ))}
          </div>

          {/* Binance API */}
          <p className="text-[9px] font-black text-yellow-600 uppercase tracking-widest mb-1.5">🔗 Binance API</p>
          <div className="space-y-2 mb-3 pb-3 border-b border-neutral-100">
            {[
              {
                label: "Spot API",
                ok:    binance?.spot_ok ?? false,
                latency: binance?.spot_latency_ms,
                weightPct: binance?.spot_weight_pct ?? 0,
                weightUsed: binance?.spot_weight_used ?? 0,
                weightLimit: 1200,
                bannedUntil: binance?.spot_banned_until ?? null,
                error: binance?.spot_error ?? null,
              },
              {
                label: "Futures API",
                ok:    binance?.futures_ok ?? false,
                latency: binance?.futures_latency_ms,
                weightPct: binance?.futures_weight_pct ?? 0,
                weightUsed: binance?.futures_weight_used ?? 0,
                weightLimit: 2400,
                bannedUntil: binance?.futures_banned_until ?? null,
                error: binance?.futures_error ?? null,
              },
            ].map(row => {
              const banned = row.bannedUntil != null;
              const hot    = row.weightPct > 70;
              const warn   = row.weightPct > 40 && !hot;
              const barColor = banned ? "bg-red-500" : hot ? "bg-orange-500" : warn ? "bg-yellow-400" : "bg-green-400";
              return (
                <div key={row.label}>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs text-neutral-700 font-semibold">{row.label}</span>
                    <span className={`text-[10px] font-bold flex items-center gap-1 ${
                      banned ? "text-red-600" : row.ok ? "text-green-600" : "text-red-500"
                    }`}>
                      <StatusDot ok={row.ok && !banned} />
                      {banned ? "BANNED" : row.ok ? `OK${row.latency != null ? ` · ${row.latency}ms` : ""}` : "Down"}
                    </span>
                  </div>
                  {/* Rate limit bar */}
                  {!banned && (
                    <div className="flex items-center gap-1.5">
                      <div className="flex-1 bg-neutral-100 rounded-full h-1.5 overflow-hidden">
                        <div
                          className={`h-full rounded-full transition-all ${barColor}`}
                          style={{ width: `${Math.min(row.weightPct, 100)}%` }}
                        />
                      </div>
                      <span className={`text-[10px] tabular-nums font-semibold shrink-0 ${
                        hot ? "text-orange-600" : warn ? "text-yellow-600" : "text-neutral-400"
                      }`}>
                        {row.weightPct.toFixed(0)}%
                      </span>
                    </div>
                  )}
                  {banned && row.bannedUntil != null && (
                    <p className="text-[10px] text-red-500 font-semibold mt-0.5">
                      ⛔ sampai {new Date(row.bannedUntil * 1000).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" })}
                    </p>
                  )}
                  {!banned && row.error && (
                    <p className="text-[10px] text-orange-500 truncate mt-0.5" title={row.error}>⚠ {row.error}</p>
                  )}
                </div>
              );
            })}
            {!binance && (
              <p className="text-[10px] text-neutral-400 italic">Memuat status Binance...</p>
            )}
          </div>

          {/* Spot Agents */}
          <p className="text-[9px] font-black text-teal-600 uppercase tracking-widest mb-1.5">🎯 Spot</p>
          <div className="space-y-1.5 mb-3 pb-3 border-b border-neutral-100">
            {[
              {
                label: "Spot Opp Scanner",
                sub:   "Scans 100 pairs tiap 15m",
                ok:    !!(health?.spot_scanner?.running),
                cycle: health?.spot_scanner?.cycle_count,
                err:   health?.spot_scanner?.last_error,
              },
              {
                label: "Spot Position Monitor",
                sub:   "Monitor TP/SL posisi spot",
                ok:    !!(health?.spot_monitor?.running),
                cycle: health?.spot_monitor?.cycle_count,
                err:   health?.spot_monitor?.last_error,
              },
            ].map(row => (
              <div key={row.label} className="flex items-center justify-between py-1">
                <div className="min-w-0">
                  <p className="text-xs text-neutral-700 font-semibold">{row.label}</p>
                  <p className="text-[10px] text-neutral-400 truncate">{row.sub}</p>
                </div>
                <div className="text-right shrink-0 ml-3">
                  <span className={`text-[10px] font-bold flex items-center gap-1 justify-end ${row.ok ? "text-green-600" : "text-neutral-400"}`}>
                    <StatusDot ok={row.ok} />
                    {row.ok ? "Running" : "—"}
                  </span>
                  {row.cycle != null && (
                    <p className="text-[9px] text-neutral-400">{row.cycle}x siklus</p>
                  )}
                  {row.err && (
                    <p className="text-[9px] text-red-400 truncate max-w-[100px]" title={row.err}>⚠ error</p>
                  )}
                </div>
              </div>
            ))}
          </div>

          {/* Futures Agents */}
          <p className="text-[9px] font-black text-blue-600 uppercase tracking-widest mb-1.5">⚡ Futures</p>
          <div className="space-y-1.5">
            {[
              {
                label: "Futures Agent 1 — AI",
                sub:   "Funding · OI · Liquidation · S/R",
                ok:    !!(health?.futures_scanner?.running),
                cycle: health?.futures_scanner?.cycle_count,
                err:   health?.futures_scanner?.last_error,
              },
              {
                label: "Futures Agent 2 — T0-T4",
                sub:   "Wyckoff · Trend · Pattern · Trigger",
                ok:    !!(health?.futures_scanner?.running),
                cycle: undefined,
                err:   undefined,
              },
              {
                label: "Futures Position Monitor",
                sub:   "Monitor TP/SL posisi futures",
                ok:    !!(health?.futures_monitor?.running),
                cycle: health?.futures_monitor?.cycle_count,
                err:   health?.futures_monitor?.last_error,
              },
              {
                label: "Weight Updater",
                sub:   "Adaptive learning — bobot sinyal",
                ok:    !!(health?.weight_updater && !health.weight_updater.last_error),
                cycle: undefined,
                err:   health?.weight_updater?.last_error ?? null,
              },
            ].map(row => (
              <div key={row.label} className="flex items-center justify-between py-1 border-b border-neutral-50 last:border-0">
                <div className="min-w-0">
                  <p className="text-xs text-neutral-700 font-semibold">{row.label}</p>
                  <p className="text-[10px] text-neutral-400 truncate">{row.sub}</p>
                </div>
                <div className="text-right shrink-0 ml-3">
                  <span className={`text-[10px] font-bold flex items-center gap-1 justify-end ${row.ok ? "text-blue-600" : "text-neutral-400"}`}>
                    <StatusDot ok={row.ok} />
                    {row.ok ? "Running" : "—"}
                  </span>
                  {row.cycle != null && (
                    <p className="text-[9px] text-neutral-400">{row.cycle}x siklus</p>
                  )}
                  {row.err && (
                    <p className="text-[9px] text-red-400 truncate max-w-[100px]" title={row.err}>⚠ error</p>
                  )}
                </div>
              </div>
            ))}
          </div>

          {learning?.monitor && (
            <div className="mt-3 pt-3 border-t border-neutral-100 flex items-center justify-between text-[10px] text-neutral-400">
              <span>Monitor tertutup hari ini:</span>
              <span className="font-bold text-neutral-600">{learning.monitor.closed_today} trades</span>
            </div>
          )}
        </div>
      </div>

      {/* ── 5. Recent Trades ──────────────────────────────────────────── */}
      <div className="bg-white rounded-2xl border border-neutral-200 overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-neutral-100 bg-neutral-50">
          <h3 className="font-bold text-sm text-neutral-700">📋 Trade Terbaru (Spot + Futures)</h3>
          <Link href="/history" className="text-[10px] text-teal-600 hover:underline font-semibold">
            Lihat semua →
          </Link>
        </div>

        {recentTrades.length === 0 ? (
          <div className="py-10 text-center text-neutral-400">
            <p className="text-2xl mb-1">📭</p>
            <p className="text-sm">Belum ada trade tertutup</p>
          </div>
        ) : (
          <>
            <div className="hidden sm:grid grid-cols-[auto_1fr_auto_auto_auto_auto] gap-x-4 px-4 py-2 text-[10px] font-bold text-neutral-400 uppercase tracking-wider border-b border-neutral-100 bg-neutral-50">
              <span>Tipe</span><span>Koin</span><span className="text-right">Entry</span>
              <span className="text-right">P&L $</span><span className="text-right">P&L %</span><span className="text-right">Status</span>
            </div>
            <div className="divide-y divide-neutral-100">
              {recentTrades.map(t => {
                const win  = t.status === "tp";
                const loss = t.status === "sl";
                return (
                  <div key={t.id} className="grid grid-cols-[auto_1fr_auto_auto] sm:grid-cols-[auto_1fr_auto_auto_auto_auto] gap-x-4 items-center px-4 py-2.5 hover:bg-neutral-50">
                    {/* Type badge */}
                    <div className="flex items-center gap-1">
                      {t.type === "spot"
                        ? <span className="text-[9px] font-black bg-teal-100 text-teal-700 px-1.5 py-0.5 rounded">SPOT</span>
                        : <span className="text-[9px] font-black bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded">FUT</span>}
                      {t.type === "fut" && <DirBadge dir={t.dir as "LONG" | "SHORT"} />}
                    </div>
                    {/* Symbol */}
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="font-bold text-sm">{t.symbol.replace("USDT","")}/USDT</span>
                        {t.type === "fut" && t.agent && (
                          <span className="text-[9px] text-neutral-400">
                            {t.agent === "futures_agent1" ? "AI" : "T4"}
                            {t.leverage != null ? ` ${t.leverage}x` : ""}
                          </span>
                        )}
                      </div>
                      <p className="text-[10px] text-neutral-400">{fmtRelTime(t.closed_at)}</p>
                    </div>
                    {/* Entry */}
                    <div className="text-right hidden sm:block">
                      <p className="text-xs font-mono">${fmtPrice(t.entry)}</p>
                    </div>
                    {/* PnL $ */}
                    <div className="text-right hidden sm:block">
                      <p className={`text-xs font-black tabular-nums ${t.pnl$ >= 0 ? "text-green-600" : "text-red-500"}`}>
                        {t.pnl$ >= 0 ? "+" : ""}${Math.abs(t.pnl$).toFixed(2)}
                      </p>
                    </div>
                    {/* PnL % */}
                    <div className="text-right">
                      {t.pnl_pct != null ? (
                        <span className={`text-xs font-black tabular-nums px-1.5 py-0.5 rounded ${
                          t.pnl_pct >= 0 ? "text-green-700 bg-green-50" : "text-red-600 bg-red-50"
                        }`}>
                          {t.pnl_pct >= 0 ? "+" : ""}{t.pnl_pct.toFixed(1)}%
                        </span>
                      ) : <span className="text-neutral-300 text-xs">—</span>}
                    </div>
                    {/* Status */}
                    <div className="text-right">
                      <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded-full border ${
                        win  ? "bg-green-100 text-green-700 border-green-300" :
                        loss ? "bg-red-100 text-red-600 border-red-300" :
                               "bg-neutral-100 text-neutral-500 border-neutral-300"
                      }`}>
                        {win ? "✅ TP" : loss ? "🛑 SL" : "🤚"}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </>
        )}
      </div>

      {/* ── 6. Spot Portfolio (Real Holdings) — always visible ──────── */}
      {(() => {
        const totalValue  = spotAssets.reduce((s, a) => s + a.usdt_value, 0);
        const totalPnlUSD = spotAssets.reduce((s, a) => s + (a.pnl_usdt ?? 0), 0);
        const totalCost   = spotAssets.reduce((s, a) => {
          if (a.avg_buy_price == null || a.avg_buy_price === 0) return s;
          return s + a.avg_buy_price * a.total;
        }, 0);

        return (
          <div className="bg-white rounded-2xl border border-neutral-200 overflow-hidden">
            {/* Header */}
            <div className="flex items-start justify-between px-5 py-4 border-b border-neutral-100 bg-neutral-50">
              <div>
                <h3 className="font-bold text-sm text-neutral-700">💼 Spot Portfolio — Real Holdings</h3>
                <p className="text-[10px] text-neutral-400 mt-0.5">Saldo nyata Binance · Harga masuk (FIFO) · Unrealized PnL</p>
              </div>
              <div className="text-right">
                {spotLoading ? (
                  <div className="flex items-center gap-1.5 text-xs text-neutral-400">
                    <span className="w-3 h-3 border-2 border-teal-400 border-t-transparent rounded-full animate-spin" />
                    Memuat...
                  </div>
                ) : spotError ? (
                  <span className="text-xs text-red-500">⚠ Error</span>
                ) : spotAssets.length > 0 ? (
                  <>
                    <p className="text-xl font-black text-neutral-900 tabular-nums">
                      ${totalValue.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </p>
                    <p className={`text-xs font-bold ${totalPnlUSD >= 0 ? "text-green-600" : "text-red-500"}`}>
                      {totalPnlUSD >= 0 ? "+" : ""}${totalPnlUSD.toFixed(2)} unrealized
                      {totalCost > 0 && (
                        <span className="text-neutral-400 font-normal ml-1">(modal ${totalCost.toFixed(0)})</span>
                      )}
                    </p>
                  </>
                ) : (
                  <span className="text-xs text-neutral-400">Tidak ada holding</span>
                )}
              </div>
            </div>

            {/* ── Error state ─────────────────────────────────────────────────── */}
            {spotError && (
              <div className="px-5 py-6 text-center">
                <div className="inline-flex flex-col items-center gap-3 max-w-sm">
                  <span className="text-4xl">🔑</span>
                  <div>
                    <p className="font-bold text-neutral-700 mb-1">Tidak bisa memuat Spot Holdings</p>
                    <p className="text-xs text-red-500 bg-red-50 rounded-lg px-3 py-2 font-mono mb-3">{spotError}</p>
                    <div className="text-left text-xs text-neutral-600 space-y-1.5 bg-amber-50 border border-amber-200 rounded-xl p-3">
                      <p className="font-bold text-amber-700 mb-2">Kemungkinan penyebab:</p>
                      <p>1️⃣ <strong>API Key belum diset</strong> — tambahkan <code className="bg-white px-1 rounded">BINANCE_API_KEY</code> di <code className="bg-white px-1 rounded">backend/.env</code></p>
                      <p>2️⃣ <strong>API Key tidak punya izin Spot</strong> — pastikan permission &quot;Enable Reading&quot; + &quot;Enable Spot&quot; aktif di Binance</p>
                      <p>3️⃣ <strong>API Key hanya untuk Futures</strong> — buat API Key baru dengan akses Spot</p>
                      <p>4️⃣ <strong>Timestamp mismatch</strong> — pastikan waktu server sinkron</p>
                    </div>
                    <a
                      href="/api/v1/market/spot-debug"
                      target="_blank"
                      rel="noreferrer"
                      className="inline-block mt-2 text-xs text-teal-600 hover:text-teal-500 underline font-semibold"
                    >
                      🔍 Buka Spot Debug → (lihat detail error di browser)
                    </a>
                  </div>
                </div>
              </div>
            )}

            {/* ── Loading state ──────────────────────────────────────────────── */}
            {spotLoading && !spotError && (
              <div className="px-5 py-8 text-center text-neutral-400">
                <div className="w-8 h-8 border-2 border-teal-400 border-t-transparent rounded-full animate-spin mx-auto mb-2" />
                <p className="text-sm">Memuat portfolio Binance spot...</p>
                <p className="text-xs mt-1">Mengambil saldo + harga masuk (FIFO trade history)</p>
              </div>
            )}

            {/* ── Empty state ────────────────────────────────────────────────── */}
            {!spotLoading && !spotError && spotAssets.length === 0 && (
              <div className="px-5 py-8 text-center">
                <p className="text-3xl mb-2">📭</p>
                <p className="font-semibold text-neutral-600">Tidak ada spot holdings terdeteksi</p>
                <p className="text-xs text-neutral-400 mt-1">Semua aset {"<"} $0.01 USDT atau akun spot kosong</p>
              </div>
            )}

            {/* Column headers */}
            <div className="hidden md:grid grid-cols-[2fr_1fr_1fr_1fr_1fr_1fr] gap-x-4 px-5 py-2 text-[10px] font-bold text-neutral-400 uppercase tracking-wider border-b border-neutral-100 bg-neutral-50/50">
              <span>Aset</span>
              <span className="text-right">Harga Masuk</span>
              <span className="text-right">Harga Sekarang</span>
              <span className="text-right">Jumlah</span>
              <span className="text-right">Nilai USDT</span>
              <span className="text-right">PnL (USDT / %)</span>
            </div>

            {/* Rows */}
            <div className="divide-y divide-neutral-100">
              {spotAssets.map(a => {
                const pct        = totalValue > 0 ? (a.usdt_value / totalValue) * 100 : 0;
                const hasPnl     = a.pnl_usdt != null && a.avg_buy_price != null && a.avg_buy_price > 0;
                const isProfit   = (a.pnl_usdt ?? 0) >= 0;
                const totalInvested = a.avg_buy_price != null ? a.avg_buy_price * a.total : null;

                return (
                  <div key={a.asset} className="px-5 py-3 hover:bg-neutral-50 transition-colors">
                    {/* Mobile layout */}
                    <div className="md:hidden">
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                          <div className="w-8 h-8 rounded-full bg-teal-50 border border-teal-200 flex items-center justify-center shrink-0">
                            <span className="text-[9px] font-black text-teal-700">{a.asset.slice(0, 3)}</span>
                          </div>
                          <div>
                            <span className="font-bold text-sm">{a.asset}</span>
                            <p className="text-[10px] text-neutral-400">{pct.toFixed(1)}% portfolio</p>
                          </div>
                        </div>
                        <div className="text-right">
                          <p className="font-bold text-sm tabular-nums">${a.usdt_value.toFixed(2)}</p>
                          {hasPnl && (
                            <p className={`text-xs font-bold ${isProfit ? "text-green-600" : "text-red-500"}`}>
                              {isProfit ? "+" : ""}{a.pnl_usdt!.toFixed(2)} USDT
                            </p>
                          )}
                        </div>
                      </div>
                      <div className="grid grid-cols-3 gap-2 text-[10px]">
                        <div>
                          <p className="text-neutral-400">Masuk (avg)</p>
                          <p className="font-mono font-bold text-neutral-700">
                            {a.avg_buy_price != null ? `$${fmtPrice(a.avg_buy_price)}` : "—"}
                          </p>
                        </div>
                        <div>
                          <p className="text-neutral-400">Sekarang</p>
                          <p className="font-mono font-bold text-neutral-700">${fmtPrice(a.current_price)}</p>
                        </div>
                        <div>
                          <p className="text-neutral-400">PnL %</p>
                          <p className={`font-bold ${isProfit ? "text-green-600" : "text-red-500"}`}>
                            {a.pnl_percent != null ? `${isProfit ? "+" : ""}${a.pnl_percent.toFixed(1)}%` : "—"}
                          </p>
                        </div>
                      </div>
                    </div>

                    {/* Desktop layout */}
                    <div className="hidden md:grid grid-cols-[2fr_1fr_1fr_1fr_1fr_1fr] gap-x-4 items-center">
                      {/* Asset */}
                      <div className="flex items-center gap-3 min-w-0">
                        <div className="w-9 h-9 rounded-full bg-teal-50 border border-teal-200 flex items-center justify-center shrink-0">
                          <span className="text-[9px] font-black text-teal-700">{a.asset.slice(0, 3)}</span>
                        </div>
                        <div className="min-w-0">
                          <p className="font-bold text-sm">{a.asset}</p>
                          <div className="flex items-center gap-1.5 mt-0.5">
                            <div className="flex-1 bg-neutral-100 rounded-full h-1 w-20">
                              <div className="bg-teal-400 h-full rounded-full"
                                style={{ width: `${Math.min(pct, 100)}%` }} />
                            </div>
                            <span className="text-[10px] text-neutral-400">{pct.toFixed(1)}%</span>
                          </div>
                        </div>
                      </div>

                      {/* Avg buy price */}
                      <div className="text-right">
                        {a.avg_buy_price != null && a.avg_buy_price > 0 ? (
                          <>
                            <p className="text-sm font-mono font-bold text-neutral-800">
                              ${fmtPrice(a.avg_buy_price)}
                            </p>
                            {totalInvested != null && (
                              <p className="text-[10px] text-neutral-400 tabular-nums">
                                ≈ ${totalInvested.toFixed(2)}
                              </p>
                            )}
                          </>
                        ) : (
                          <span className="text-neutral-300 text-xs">—</span>
                        )}
                      </div>

                      {/* Current price */}
                      <div className="text-right">
                        <p className="text-sm font-mono font-bold text-neutral-800">
                          ${fmtPrice(a.current_price)}
                        </p>
                        {a.asset !== "USDT" && a.avg_buy_price != null && a.avg_buy_price > 0 && (
                          <p className={`text-[10px] font-semibold ${
                            a.current_price >= a.avg_buy_price ? "text-green-500" : "text-red-400"
                          }`}>
                            {a.current_price >= a.avg_buy_price ? "▲" : "▼"}{" "}
                            {Math.abs(((a.current_price - a.avg_buy_price) / a.avg_buy_price) * 100).toFixed(1)}%
                            {" "}vs masuk
                          </p>
                        )}
                      </div>

                      {/* Amount held */}
                      <div className="text-right">
                        <p className="text-sm font-mono font-bold text-neutral-700">
                          {a.total < 0.001 ? a.total.toFixed(6)
                            : a.total < 1    ? a.total.toFixed(4)
                            : a.total < 1000 ? a.total.toFixed(2)
                            :                  a.total.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                        </p>
                        <p className="text-[10px] text-neutral-400">{a.asset}</p>
                      </div>

                      {/* USDT value */}
                      <div className="text-right">
                        <p className="text-sm font-bold tabular-nums text-neutral-800">
                          ${a.usdt_value < 1000
                            ? a.usdt_value.toFixed(2)
                            : (a.usdt_value / 1000).toFixed(2) + "K"}
                        </p>
                      </div>

                      {/* PnL */}
                      <div className="text-right">
                        {hasPnl ? (
                          <>
                            <p className={`text-sm font-black tabular-nums ${isProfit ? "text-green-600" : "text-red-500"}`}>
                              {isProfit ? "+" : ""}${a.pnl_usdt!.toFixed(2)}
                            </p>
                            <p className={`text-[10px] font-bold ${isProfit ? "text-green-500" : "text-red-400"}`}>
                              {isProfit ? "+" : ""}{a.pnl_percent!.toFixed(2)}%
                            </p>
                          </>
                        ) : (
                          <span className="text-neutral-300 text-xs">—</span>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Summary footer */}
            <div className="px-5 py-3 bg-neutral-50 border-t border-neutral-200">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div>
                  <p className="text-[10px] text-neutral-400 uppercase tracking-wide font-semibold mb-0.5">Total Nilai</p>
                  <p className="font-black text-neutral-800 text-base tabular-nums">
                    ${totalValue.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </p>
                </div>
                <div>
                  <p className="text-[10px] text-neutral-400 uppercase tracking-wide font-semibold mb-0.5">Total Modal</p>
                  <p className="font-black text-neutral-700 text-base tabular-nums">
                    {totalCost > 0 ? `$${totalCost.toFixed(2)}` : "—"}
                  </p>
                </div>
                <div>
                  <p className="text-[10px] text-neutral-400 uppercase tracking-wide font-semibold mb-0.5">Unrealized PnL</p>
                  <p className={`font-black text-base tabular-nums ${totalPnlUSD >= 0 ? "text-green-600" : "text-red-500"}`}>
                    {totalPnlUSD >= 0 ? "+" : ""}${totalPnlUSD.toFixed(2)}
                  </p>
                </div>
                <div>
                  <p className="text-[10px] text-neutral-400 uppercase tracking-wide font-semibold mb-0.5">ROI</p>
                  <p className={`font-black text-base tabular-nums ${totalPnlUSD >= 0 ? "text-green-600" : "text-red-500"}`}>
                    {totalCost > 0
                      ? `${totalPnlUSD >= 0 ? "+" : ""}${((totalPnlUSD / totalCost) * 100).toFixed(1)}%`
                      : "—"}
                  </p>
                </div>
              </div>
            </div>
          </div>
        );
      })()}

    </div>
  );
}
