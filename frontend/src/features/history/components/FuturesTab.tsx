"use client";
import { useEffect, useState, useCallback, useMemo, useRef } from "react";
import { FuturesAnalytics } from "./FuturesAnalytics";
import { LoadingPage } from "@/components/ui/feedback";
import { MonitorTab } from "./futures/MonitorTab";
import { OverviewTab } from "./futures/OverviewTab";
import { type FuturesPosition, type LearningStats, type RiskDashboard, isRealWin, tradePnlDollar, calcNotional } from "./futures/types";

const FALLBACK_BALANCE = 1000;
const RISK_PCT         = 0.01;
const REFRESH_MS       = 15_000;

type SubTab = "overview" | "monitor" | "analytics";

function buildEquity(closed: FuturesPosition[], startingBalance: number, riskDollar: number) {
  const sorted = [...closed].sort((a, b) => (a.closed_at ?? 0) - (b.closed_at ?? 0));
  let balance = startingBalance;
  const points = [{ balance, n: 0, symbol: "", win: true }];
  sorted.forEach((p, i) => {
    const pnl$ = tradePnlDollar(p, riskDollar);
    if (pnl$ != null) balance = Math.max(0, balance + pnl$);
    points.push({ balance, n: i + 1, symbol: p.symbol.replace("USDT", ""), win: (p.pnl_pct ?? 0) >= 0 });
  });
  return points;
}

export function FuturesTab() {
  const [subTab,       setSubTab]       = useState<SubTab>("overview");
  const [positions,    setPositions]    = useState<FuturesPosition[]>([]);
  const [learning,     setLearning]     = useState<LearningStats | null>(null);
  const [riskDash,     setRiskDash]     = useState<RiskDashboard | null>(null);
  const [loading,      setLoading]      = useState(true);
  const [lastUpdated,  setLastUpdated]  = useState<Date | null>(null);
  const [agentFilter,  setAgentFilter]  = useState<"all" | "agent1" | "agent2" | "agent3">("all");
  const [countdown,    setCountdown]    = useState(REFRESH_MS / 1000);
  const [autoThreshold, setAutoThreshold] = useState<number | null>(null);
  const countRef = useRef(REFRESH_MS / 1000);

  const fetchPositions = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const [posRes, learnRes, riskRes, autoRes] = await Promise.all([
        fetch("/api/v1/futures/positions?status=all"),
        fetch("/api/v1/futures/learning/stats"),
        fetch("/api/v1/futures/monitor/risk"),
        fetch("/api/v1/futures/auto/status"),
      ]);
      if (!posRes.ok) return;
      setPositions(((await posRes.json()) as { positions: FuturesPosition[] }).positions ?? []);
      if (learnRes.ok) {
        const ld = await learnRes.json() as LearningStats;
        if (!("error" in ld)) setLearning(ld);
      }
      if (riskRes.ok) {
        const rd = await riskRes.json() as RiskDashboard;
        if (!("error" in rd)) setRiskDash(rd);
      }
      if (autoRes.ok) {
        const ad = await autoRes.json() as { threshold?: number };
        if (typeof ad.threshold === "number") setAutoThreshold(ad.threshold);
      }
      setLastUpdated(new Date());
    } catch { /* stale data shown */ }
    finally { if (!silent) setLoading(false); }
  }, []);

  useEffect(() => { void fetchPositions(); }, [fetchPositions]);
  useEffect(() => {
    const poll = setInterval(() => {
      void fetchPositions(true);
      countRef.current = REFRESH_MS / 1000;
      setCountdown(REFRESH_MS / 1000);
    }, REFRESH_MS);
    const tick = setInterval(() => {
      countRef.current = Math.max(0, countRef.current - 1);
      setCountdown(countRef.current);
    }, 1000);
    return () => { clearInterval(poll); clearInterval(tick); };
  }, [fetchPositions]);

  // ── Derived ───────────────────────────────────────────────────────────────────

  const startingBalance = learning?.balance?.starting ?? FALLBACK_BALANCE;
  const riskDollar      = startingBalance * RISK_PCT;

  const stats = useMemo(() => {
    const open   = positions.filter(p => p.status === "open");
    const closed = positions.filter(p => p.status === "tp" || p.status === "sl");
    const wins   = closed.filter(isRealWin);
    const losses = closed.filter(p => !isRealWin(p));
    const totalPnl$ = closed.reduce((acc, p) => acc + (tradePnlDollar(p, riskDollar) ?? 0), 0);
    const currentBalance = learning?.balance?.current ?? (startingBalance + totalPnl$);
    const winRate = closed.length > 0 ? (wins.length / closed.length) * 100 : 0;

    const a1Closed = closed.filter(p => p.agent === "futures_agent1");
    const a2Closed = closed.filter(p => p.agent === "futures_agent2");
    const a3Closed = closed.filter(p => p.agent === "futures_agent3");
    const a1Open   = open.filter(p => p.agent === "futures_agent1");
    const a2Open   = open.filter(p => p.agent === "futures_agent2");
    const a3Open   = open.filter(p => p.agent === "futures_agent3");

    return {
      open: open.length, closed: closed.length, wins: wins.length, losses: losses.length,
      winRate, currentBalance, totalPnl$,
      a1Open, a2Open, a3Open,
      a1: { total: a1Closed.length, wins: a1Closed.filter(isRealWin).length, rate: a1Closed.length > 0 ? a1Closed.filter(isRealWin).length / a1Closed.length * 100 : 0 },
      a2: { total: a2Closed.length, wins: a2Closed.filter(isRealWin).length, rate: a2Closed.length > 0 ? a2Closed.filter(isRealWin).length / a2Closed.length * 100 : 0 },
      a3: { total: a3Closed.length, wins: a3Closed.filter(isRealWin).length, rate: a3Closed.length > 0 ? a3Closed.filter(isRealWin).length / a3Closed.length * 100 : 0 },
    };
  }, [positions, learning, startingBalance, riskDollar]);

  const equityPoints = useMemo(
    () => buildEquity(positions.filter(p => p.status === "tp" || p.status === "sl"), startingBalance, riskDollar),
    [positions, startingBalance, riskDollar],
  );

  // ── Sub-tab bar ───────────────────────────────────────────────────────────────

  const subTabBar = (
    <div className="flex gap-1 bg-neutral-100 p-1 rounded-xl w-fit">
      {([
        { key: "overview",  label: "📋 Overview"  },
        { key: "monitor",   label: "🔍 Monitor"   },
        { key: "analytics", label: "📊 Analytics" },
      ] as { key: SubTab; label: string }[]).map(t => (
        <button key={t.key} onClick={() => setSubTab(t.key)}
          className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all ${subTab === t.key ? "bg-white text-neutral-900 shadow-sm" : "text-neutral-500 hover:text-neutral-700"}`}>
          {t.label}
        </button>
      ))}
    </div>
  );

  if (loading && positions.length === 0) {
    return (
      <div className="space-y-4">
        {subTabBar}
        {subTab === "analytics" ? <FuturesAnalytics /> : <LoadingPage message="Memuat posisi futures..." />}
      </div>
    );
  }

  if (subTab === "analytics") {
    return <div className="space-y-4">{subTabBar}<FuturesAnalytics /></div>;
  }

  const commonProps = { positions, riskDash, learning, startingBalance, riskDollar, countdown, onRefresh: () => void fetchPositions() };

  return (
    <div className="space-y-4">
      {subTabBar}
      {subTab === "monitor" ? (
        <MonitorTab {...commonProps} />
      ) : (
        <OverviewTab {...commonProps}
          equityPoints={equityPoints} stats={stats} autoThreshold={autoThreshold}
          agentFilter={agentFilter} setAgentFilter={setAgentFilter}
          lastUpdated={lastUpdated} loading={loading}
          onWalletChanged={() => void fetchPositions(true)}
        />
      )}
    </div>
  );
}
