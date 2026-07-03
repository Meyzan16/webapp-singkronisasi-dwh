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
  manual?: boolean; entry_mode?: string | null;   // PLAN_v8 P2/P5
  close_reason?: string | null;                    // PLAN_v8 P2-B2
}

interface FutPos {
  id: number; symbol: string; direction: "LONG" | "SHORT"; agent: string;
  status: string; entry: number; current_price: number | null;
  unrealized_pnl: number | null; unrealized_pnl_dollar: number | null;
  pnl_pct: number | null; pnl_dollar: number | null; position_size: number | null;
  tp2_pct: number; risk_pct: number; rr_ratio: number; leverage: number;
  score: number; signals: string[]; entry_at: number; closed_at: number | null;
  close_reason?: string | null;                    // PLAN_v8 P2-B2
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

// DASH-FIX: history API adalah SOURCE OF TRUTH — sama dengan halaman History,
// supaya angka dashboard tidak pernah beda dari history spot/futures.
interface HistStyleStat {
  total: number; wins: number; losses: number; win_rate: number; avg_pnl: number;
  // PLAN_v8 P3: clean WR (exit paksa dikecualikan)
  clean_wins?: number; clean_losses?: number; managed_exits?: number; clean_win_rate?: number;
}
interface HistStats {
  overall: { total: number; open: number; closed: number; wins: number; losses: number; win_rate: number };
  by_style: Record<string, HistStyleStat>;
}
interface EquityPoint { trade_n: number; balance: number; win: boolean; symbol: string }

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
  const [histStats, setHistStats]  = useState<HistStats | null>(null);
  const [spotEquity, setSpotEquity] = useState<EquityPoint[]>([]);
  const [futEquity,  setFutEquity]  = useState<EquityPoint[]>([]);
  const countRef = useRef(POLL_MS / 1000);

  const fetchAll = useCallback(async () => {
    try {
      const [ctxR, oppR, futR, learnR, statR, spotR, healthR, binanceR, balR, futBalR] = await Promise.allSettled([
        fetch("/api/v1/market/context"),
        fetch("/api/v1/opportunity/positions?days=365"),   // DASH-FIX: endpoint cap le=365; 3650 → 422 = SEMUA posisi (termasuk open) hilang. Open selalu disertakan apa pun days.
        fetch("/api/v1/futures/positions?status=all"),
        fetch("/api/v1/futures/learning/stats"),
        fetch("/api/v1/futures/status"),
        fetch("/api/v1/market/spot-positions"),
        fetch("/health"),
        fetch("/api/v1/market/binance-status"),
        fetch("/api/v1/balance/spot"),
        fetch("/api/v1/balance/futures"),
      ]);
      // DASH-FIX: history source of truth (stats + equity per wallet) — dipisah
      // dari Promise.allSettled utama agar mudah dibaca; tetap paralel.
      const [histR, sEqR, fEqR] = await Promise.allSettled([
        fetch("/api/v1/history/stats?days=3650"),
        fetch("/api/v1/history/equity?style=spot"),
        fetch("/api/v1/history/equity?style=futures"),
      ]);
      if (histR.status === "fulfilled" && histR.value.ok) setHistStats(await histR.value.json());
      if (sEqR.status === "fulfilled" && sEqR.value.ok)   setSpotEquity((await sEqR.value.json()).points ?? []);
      if (fEqR.status === "fulfilled" && fEqR.value.ok)   setFutEquity((await fEqR.value.json()).points ?? []);
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

  // DASH-FIX: WR dari /history/stats (SATU sumber dengan halaman History) — dulu
  // dihitung ulang dari /opportunity/positions & learning/stats yang definisinya
  // beda → "Spot 0%" padahal kenyataan DB 7 TP / 4 SL = 64%.
  const spotStats = useMemo((): HistStyleStat => {
    const s = histStats?.by_style?.["opportunity_spot"];
    return s ?? { total: 0, wins: 0, losses: 0, win_rate: 0, avg_pnl: 0 };
  }, [histStats]);

  const futStats = useMemo((): HistStyleStat => {
    const agg: HistStyleStat = { total: 0, wins: 0, losses: 0, win_rate: 0, avg_pnl: 0,
      clean_wins: 0, clean_losses: 0, managed_exits: 0, clean_win_rate: 0 };
    for (const [style, s] of Object.entries(histStats?.by_style ?? {})) {
      if (!style.startsWith("futures")) continue;
      agg.total += s.total; agg.wins += s.wins; agg.losses += s.losses;
      agg.clean_wins!   += s.clean_wins ?? 0;
      agg.clean_losses! += s.clean_losses ?? 0;
      agg.managed_exits! += s.managed_exits ?? 0;
    }
    agg.win_rate = agg.total > 0 ? (agg.wins / agg.total) * 100 : 0;
    const ct = agg.clean_wins! + agg.clean_losses!;
    agg.clean_win_rate = ct > 0 ? (agg.clean_wins! / ct) * 100 : 0;
    return agg;
  }, [histStats]);

  // PLAN_v8 P3: dashboard pakai CLEAN WR (exit paksa rotation/time-stop dikecualikan).
  const spotClean = (spotStats.clean_wins ?? 0) + (spotStats.clean_losses ?? 0);
  const futClean  = (futStats.clean_wins ?? 0) + (futStats.clean_losses ?? 0);
  const oppWinRate = spotClean > 0 ? (spotStats.clean_win_rate ?? 0) : spotStats.win_rate;
  const futWinRate = futClean  > 0 ? (futStats.clean_win_rate  ?? 0) : futStats.win_rate;

  const combinedWinRate = useMemo(() => {
    const cw = (spotStats.clean_wins ?? 0) + (futStats.clean_wins ?? 0);
    const ct = spotClean + futClean;
    if (ct > 0) return (cw / ct) * 100;
    // fallback gross bila belum ada clean sample
    const total = spotStats.total + futStats.total;
    return total > 0 ? ((spotStats.wins + futStats.wins) / total) * 100 : 0;
  }, [spotStats, futStats, spotClean, futClean]);

  const recentTrades = useMemo((): RecentTrade[] => {
    const s: RecentTrade[] = oppClosed.map(p => ({
      id: `s-${p.id}`, symbol: p.symbol, type: "spot", dir: "LONG",
      status: p.status, entry: p.entry, pnl_pct: p.pnl_pct,
      "pnl$": p.pnl_dollar ?? (p.pnl_pct != null ? pnlDollar(p.pnl_pct, p.risk_pct, initialOpp) : 0),
      entry_at: p.entry_at, closed_at: p.closed_at, close_reason: p.close_reason,
    }));
    const f: RecentTrade[] = futClosed.map(p => ({
      id: `f-${p.id}`, symbol: p.symbol, type: "fut", dir: p.direction,
      status: p.status, entry: p.entry, pnl_pct: p.pnl_pct,
      "pnl$": p.pnl_dollar ?? (p.pnl_pct != null ? pnlDollar(p.pnl_pct, p.risk_pct) : 0),
      agent: p.agent, leverage: p.leverage, entry_at: p.entry_at, closed_at: p.closed_at,
      close_reason: p.close_reason,
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

      {/* KPI Row — DASH-FIX: semua kartu klik → drill-down; WR dari history + sampel (n) */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KpiCard label="Paper Balance" value={`$${(oppBalance + futBalance).toFixed(0)}`}
          sub={`Spot $${oppBalance.toFixed(0)} + Fut $${futBalance.toFixed(0)}`}
          color={combinedPnl >= 0 ? "text-green-600" : "text-red-500"} icon="💰" href="/history" />
        <KpiCard label="Combined PnL" value={`${combinedPnl >= 0 ? "+" : ""}$${combinedPnl.toFixed(2)}`}
          sub={`ROI ${((combinedPnl / (initialOpp + initialFut)) * 100).toFixed(1)}% dari modal $${(initialOpp + initialFut).toFixed(0)}`}
          color={combinedPnl >= 0 ? "text-green-600" : "text-red-500"} icon={combinedPnl >= 0 ? "📈" : "📉"} href="/history" />
        <KpiCard label="Posisi Terbuka" value={String(oppOpen.length + futOpen.length)}
          sub={`${oppOpen.length} Spot · ${futOpen.length} Futures`}
          color={(oppOpen.length + futOpen.length) > 0 ? "text-blue-600" : "text-neutral-400"} icon="🎯" href="/history" />
        {/* PLAN_v8 P3: WR bersih (TP/SL asli; rotation/time-stop dikecualikan) */}
        <KpiCard label="Win Rate (bersih)"
          value={(spotClean + futClean) > 0 ? `${combinedWinRate.toFixed(0)}%` : "—"}
          sub={`Spot ${spotClean > 0 ? `${oppWinRate.toFixed(0)}% (${spotStats.clean_wins}/${spotClean})` : "—"} · Fut ${futClean > 0 ? `${futWinRate.toFixed(0)}% (${futStats.clean_wins}/${futClean})` : "—"}${
            ((spotStats.managed_exits ?? 0) + (futStats.managed_exits ?? 0)) > 0 ? ` · ${(spotStats.managed_exits ?? 0) + (futStats.managed_exits ?? 0)} exit dikelola` : ""}`}
          color={combinedWinRate >= 50 ? "text-green-600" : (spotClean + futClean) > 0 ? "text-red-500" : "text-neutral-400"} icon="🏆" href="/history" />
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
          equityPoints={spotEquity.length > 1 ? spotEquity : oppEquityPoints}
          winRate={oppWinRate} stats={spotStats}
        />
        <FuturesBalancePanel
          balance={futBalance} initial={initialFut} unrealizedPnl={futUnrealizedPnl}
          futBal={futBal} futOpen={futOpen} learning={learning as Parameters<typeof FuturesBalancePanel>[0]["learning"]}
          equityPoints={futEquity} stats={futStats}
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
