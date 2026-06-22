"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { MarketIntelBanner } from "@/components/MarketIntelBanner";
import { KpiCard } from "@/components/ui/stat-card";
import { LiveBadge } from "@/components/ui/live-badge";
import { fmtPrice } from "@/lib/format";
import { OpenPositionsPanel } from "./components/OpenPositionsPanel";
import { ScannerStatusPanel } from "./components/ScannerStatusPanel";
import { SpotBalancePanel, FuturesBalancePanel } from "./components/BalancePanels";
import { SystemHealthPanel } from "./components/SystemHealthPanel";
import { RecentTradesPanel, type RecentTrade } from "./components/RecentTradesPanel";
import { SpotPortfolioPanel, type SpotAsset } from "./components/SpotPortfolioPanel";
import type { Health, BinanceStatus } from "@/types/health";

// ── Types ─────────────────────────────────────────────────────────────────────

interface OppPos {
  id: number; symbol: string; status: string; entry: number;
  current_price: number | null; unrealized_pnl_pct: number | null;
  tp2_pct: number; risk_pct: number; rr_ratio: number;
  signals: string[]; score: number; alert_type: string;
  tp1_hit: boolean; pnl_pct: number | null; entry_at: number;
  closed_at: number | null; pnl_dollar?: number | null;
  position_size?: number | null; risk_dollar?: number | null;
}

interface FutPos {
  id: number; symbol: string; direction: "LONG" | "SHORT"; agent: string;
  status: string; entry: number; current_price: number | null;
  unrealized_pnl: number | null; unrealized_pnl_dollar: number | null;
  pnl_pct: number | null; pnl_dollar: number | null; position_size: number | null;
  tp2_pct: number; risk_pct: number; rr_ratio: number; leverage: number;
  score: number; signals: string[]; entry_at: number; closed_at: number | null;
}

interface LearningStats {
  regime: string;
  overall: { total: number; open: number; closed: number; wins: number; losses: number; win_rate: number };
  balance: { starting: number; current: number; total_pnl: number; roi_pct: number };
  equity_points: { trade_n: number; balance: number; win: boolean; symbol: string }[];
  monitor: { running: boolean; cycle_count: number; closed_today: number };
}

interface FuturesStatus {
  next_scan_in_min: number | null;
  agent1_results: number; agent2_results: number; agent3_results?: number;
  agent1_last_scan: number | null; agent2_last_scan: number | null; agent3_last_scan?: number | null;
}

interface SpotBalance {
  balance: number; initial_balance: number; available: number;
  locked_margin: number; realized_pnl: number; total_pnl: number; open_positions: number;
}

const POLL_MS     = 15_000;
const BALANCE_START = 1000;
const RISK_PCT    = 0.01;

function pnlDollar(pnl_pct: number, risk_pct: number, balance = BALANCE_START): number {
  if (risk_pct <= 0) return 0;
  const notional = (balance * RISK_PCT) / (risk_pct / 100);
  return (pnl_pct / 100) * notional;
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const [ctx,       setCtx]        = useState<{ sentiment: string; btc_price: number; futures_signal_count?: number; opp_signal_count?: number } | null>(null);
  const [oppPos,    setOppPos]     = useState<OppPos[]>([]);
  const [futPos,    setFutPos]     = useState<FutPos[]>([]);
  const [learning,  setLearning]   = useState<LearningStats | null>(null);
  const [futStatus, setFutStatus]  = useState<FuturesStatus | null>(null);
  const [spotAssets, setSpotAssets] = useState<SpotAsset[]>([]);
  const [spotError,  setSpotError]  = useState<string | null>(null);
  const [spotLoading, setSpotLoading] = useState(true);
  const [health,    setHealth]     = useState<Health | null>(null);
  const [binance,   setBinance]    = useState<BinanceStatus | null>(null);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const [countdown, setCountdown]  = useState(POLL_MS / 1000);
  const [spotBal,   setSpotBal]    = useState<SpotBalance | null>(null);
  const [futBal,    setFutBal]     = useState<SpotBalance | null>(null);
  const countRef = useRef(POLL_MS / 1000);

  const fetchAll = useCallback(async () => {
    try {
      const [ctxR, oppR, futR, learnR, statR, spotR, healthR, binanceR, balR, futBalR] = await Promise.allSettled([
        fetch("/api/v1/market/context"),
        fetch("/api/v1/opportunity/positions?days=3650"),
        fetch("/api/v1/futures/positions?status=all"),
        fetch("/api/v1/futures/learning/stats"),
        fetch("/api/v1/futures/status"),
        fetch("/api/v1/market/spot-positions"),
        fetch("/health"),
        fetch("/api/v1/market/binance-status"),
        fetch("/api/v1/balance/spot"),
        fetch("/api/v1/balance/futures"),
      ]);
      if (ctxR.status === "fulfilled" && ctxR.value.ok)   setCtx(await ctxR.value.json());
      if (oppR.status === "fulfilled" && oppR.value.ok)   setOppPos((await oppR.value.json()).positions ?? []);
      if (futR.status === "fulfilled" && futR.value.ok)   setFutPos((await futR.value.json()).positions ?? []);
      if (learnR.status === "fulfilled" && learnR.value.ok) {
        const ld = await learnR.value.json();
        if (!("error" in ld)) setLearning(ld);
      }
      if (statR.status === "fulfilled" && statR.value.ok)   setFutStatus(await statR.value.json());
      if (spotR.status === "fulfilled") {
        if (spotR.value.ok) {
          const sd = await spotR.value.json();
          setSpotAssets(sd.assets ?? []); setSpotError(null);
        } else {
          const t = await spotR.value.text().catch(() => "");
          let msg = `Error ${spotR.value.status}`;
          try { msg = JSON.parse(t).detail ?? msg; } catch { /* */ }
          setSpotError(msg); setSpotAssets([]);
        }
      } else { setSpotError("Gagal terhubung ke backend"); }
      setSpotLoading(false);
      if (healthR.status === "fulfilled" && healthR.value.ok)   setHealth(await healthR.value.json());
      if (binanceR.status === "fulfilled" && binanceR.value.ok) setBinance(await binanceR.value.json());
      if (balR.status === "fulfilled" && balR.value.ok)         setSpotBal(await balR.value.json());
      if (futBalR.status === "fulfilled" && futBalR.value.ok)   setFutBal(await futBalR.value.json());
      setLastUpdate(new Date());
    } catch { /* silent */ }
  }, []);

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { fetchAll().catch(() => {}); }, [fetchAll]);
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

  // ── Derived ───────────────────────────────────────────────────────────────────

  const oppOpen      = useMemo(() => oppPos.filter(p => p.status === "open"), [oppPos]);
  const futOpen      = useMemo(() => futPos.filter(p => p.status === "open"), [futPos]);
  const oppClosedAll = useMemo(() => oppPos.filter(p => p.status !== "open"), [oppPos]);
  const oppClosed    = useMemo(
    () => [...oppClosedAll].sort((a, b) => (b.closed_at ?? 0) - (a.closed_at ?? 0)).slice(0, 20),
    [oppClosedAll],
  );
  const futClosed = useMemo(
    () => futPos.filter(p => p.status !== "open").sort((a, b) => (b.closed_at ?? 0) - (a.closed_at ?? 0)).slice(0, 20),
    [futPos],
  );

  const initialOpp = spotBal?.initial_balance ?? BALANCE_START;

  const oppBalance = useMemo(() => {
    if (spotBal != null) return spotBal.balance;
    let b = initialOpp;
    [...oppClosedAll].sort((a, b) => (a.closed_at ?? 0) - (b.closed_at ?? 0))
      .forEach(p => { b = Math.max(0, b + (p.pnl_dollar ?? (p.pnl_pct != null ? pnlDollar(p.pnl_pct, p.risk_pct, initialOpp) : 0))); });
    return b;
  }, [oppClosedAll, spotBal, initialOpp]);

  const oppEquityPoints = useMemo(() => {
    const sorted = [...oppClosedAll].sort((a, b) => (a.closed_at ?? 0) - (b.closed_at ?? 0));
    let b = initialOpp;
    const pts: { balance: number; win: boolean }[] = [{ balance: b, win: true }];
    for (const p of sorted) {
      b = Math.max(0, b + (p.pnl_dollar ?? (p.pnl_pct != null ? pnlDollar(p.pnl_pct, p.risk_pct, initialOpp) : 0)));
      pts.push({ balance: b, win: p.status === "tp" });
    }
    return pts;
  }, [oppClosedAll, initialOpp]);

  const oppUnrealizedPnl = useMemo(
    () => oppOpen.reduce((s, p) => s + ((p.unrealized_pnl_pct ?? 0) / 100 * (p.position_size ?? 0)), 0),
    [oppOpen],
  );
  const futUnrealizedPnl = useMemo(
    () => futOpen.reduce((s, p) => {
      if (p.unrealized_pnl_dollar != null) return s + p.unrealized_pnl_dollar;
      if (p.unrealized_pnl == null || !p.position_size) return s;
      return s + (p.unrealized_pnl / 100) * p.position_size;
    }, 0),
    [futOpen],
  );

  const futBalance  = futBal?.balance ?? learning?.balance.current ?? BALANCE_START;
  const initialFut  = futBal?.initial_balance ?? learning?.balance.starting ?? BALANCE_START;
  const oppTradingPnl = spotBal != null ? spotBal.total_pnl : (oppBalance - initialOpp);
  const combinedPnl = oppTradingPnl + (futBalance - initialFut);

  const oppWinRate = useMemo(() => {
    const tpSl = oppClosedAll.filter(p => p.status === "tp" || p.status === "sl");
    const wins  = tpSl.filter(p => p.status === "tp" && (p.pnl_pct ?? 0) > 0);
    return tpSl.length > 0 ? (wins.length / tpSl.length) * 100 : 0;
  }, [oppClosedAll]);

  const futWinRate = learning?.overall.win_rate ?? 0;

  const combinedWinRate = useMemo(() => {
    const tpSl  = oppClosedAll.filter(p => p.status === "tp" || p.status === "sl");
    const wins  = tpSl.filter(p => p.status === "tp" && (p.pnl_pct ?? 0) > 0);
    const total = tpSl.length + (learning?.overall.closed ?? 0);
    return total > 0 ? (wins.length + (learning?.overall.wins ?? 0)) / total * 100 : 0;
  }, [oppClosedAll, learning]);

  const recentTrades = useMemo((): RecentTrade[] => {
    const s: RecentTrade[] = oppClosed.map(p => ({
      id: `s-${p.id}`, symbol: p.symbol, type: "spot", dir: "LONG",
      status: p.status, entry: p.entry, pnl_pct: p.pnl_pct,
      "pnl$": p.pnl_dollar ?? (p.pnl_pct != null ? pnlDollar(p.pnl_pct, p.risk_pct, initialOpp) : 0),
      entry_at: p.entry_at, closed_at: p.closed_at,
    }));
    const f: RecentTrade[] = futClosed.map(p => ({
      id: `f-${p.id}`, symbol: p.symbol, type: "fut", dir: p.direction,
      status: p.status, entry: p.entry, pnl_pct: p.pnl_pct,
      "pnl$": p.pnl_dollar ?? (p.pnl_pct != null ? pnlDollar(p.pnl_pct, p.risk_pct) : 0),
      agent: p.agent, leverage: p.leverage, entry_at: p.entry_at, closed_at: p.closed_at,
    }));
    return [...s, ...f].sort((a, b) => (b.closed_at ?? 0) - (a.closed_at ?? 0)).slice(0, 10);
  }, [oppClosed, futClosed, initialOpp]);

  const futCount = typeof ctx?.futures_signal_count === "number" ? ctx.futures_signal_count : -1;
  const oppCount = typeof ctx?.opp_signal_count     === "number" ? ctx.opp_signal_count     : -1;

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold text-neutral-800">Command Center</h2>
          <p className="text-xs text-neutral-400">Spot · Futures · History · Market 24H</p>
        </div>
        <div className="flex items-center gap-2">
          <LiveBadge countdown={countdown} color="green" />
          {lastUpdate && <span className="text-[10px] text-neutral-400">{lastUpdate.toLocaleTimeString()}</span>}
        </div>
      </div>

      <MarketIntelBanner mode="spot" refreshMs={60_000} />

      {/* KPI Row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KpiCard label="Paper Balance" value={`$${(oppBalance + futBalance).toFixed(0)}`}
          sub={`Spot $${oppBalance.toFixed(0)} + Fut $${futBalance.toFixed(0)}`}
          color={combinedPnl >= 0 ? "text-green-600" : "text-red-500"} icon="💰" />
        <KpiCard label="Combined PnL" value={`${combinedPnl >= 0 ? "+" : ""}$${combinedPnl.toFixed(2)}`}
          sub={`ROI ${((combinedPnl / (initialOpp + initialFut)) * 100).toFixed(1)}% dari modal $${(initialOpp + initialFut).toFixed(0)}`}
          color={combinedPnl >= 0 ? "text-green-600" : "text-red-500"} icon={combinedPnl >= 0 ? "📈" : "📉"} />
        <KpiCard label="Posisi Terbuka" value={String(oppOpen.length + futOpen.length)}
          sub={`${oppOpen.length} Spot · ${futOpen.length} Futures`}
          color={(oppOpen.length + futOpen.length) > 0 ? "text-blue-600" : "text-neutral-400"} icon="🎯" />
        <KpiCard label="Win Rate" value={combinedWinRate > 0 ? `${combinedWinRate.toFixed(0)}%` : "—"}
          sub={`Spot ${oppWinRate.toFixed(0)}% · Fut ${futWinRate.toFixed(0)}%`}
          color={combinedWinRate >= 50 ? "text-green-600" : combinedWinRate > 0 ? "text-red-500" : "text-neutral-400"} icon="🏆" />
      </div>

      {/* Open Positions + Scanner Status */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <OpenPositionsPanel oppOpen={oppOpen} futOpen={futOpen} />
        <ScannerStatusPanel futStatus={futStatus} futCount={futCount} oppCount={oppCount} schedulerState={health?.scheduler} />
      </div>

      {/* Balance Panels + System Health */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <SpotBalancePanel
          balance={oppBalance} initial={initialOpp} unrealizedPnl={oppUnrealizedPnl}
          spotBal={spotBal} oppOpen={oppOpen} oppClosedAll={oppClosedAll}
          equityPoints={oppEquityPoints} winRate={oppWinRate}
        />
        <FuturesBalancePanel
          balance={futBalance} initial={initialFut} unrealizedPnl={futUnrealizedPnl}
          futBal={futBal} futOpen={futOpen} learning={learning as Parameters<typeof FuturesBalancePanel>[0]["learning"]}
        />
        <SystemHealthPanel
          health={health} binance={binance}
          closedToday={learning?.monitor.closed_today}
          futResultsA2={futStatus?.agent2_results}
          futResultsA3={futStatus?.agent3_results}
        />
      </div>

      <RecentTradesPanel trades={recentTrades} />

      <SpotPortfolioPanel assets={spotAssets} loading={spotLoading} error={spotError} />
    </div>
  );
}
