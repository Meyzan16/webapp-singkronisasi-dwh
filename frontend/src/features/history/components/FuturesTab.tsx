"use client";
import { useEffect, useState, useCallback, useMemo, useRef } from "react";
import { FuturesAnalytics } from "./FuturesAnalytics";
import { LoadingPage } from "@/components/ui/feedback";
import { MonitorTab } from "./futures/MonitorTab";
import { OverviewTab } from "./futures/OverviewTab";
import { type FuturesPosition, type LearningStats, type RiskDashboard, isRealWin, tradePnlDollar } from "./futures/types";

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
  const [agentFilter,  setAgentFilter]  = useState<"all" | "agent1" | "agent2" | "agent3" | "agent_bigmover">("all");
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
        // always update when no "error" key — let MonitorTab handle empty portfolio gracefully
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

  // G12: Big Mover push notification WebSocket
  useEffect(() => {
    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout>;
    let mounted = true;

    function connect() {
      if (!mounted) return;
      const proto = typeof window !== "undefined" && window.location.protocol === "https:" ? "wss:" : "ws:";
      const host  = typeof window !== "undefined" ? window.location.hostname : "localhost";
      ws = new WebSocket(`${proto}//${host}:8000/ws/big-movers`);

      ws.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data as string) as {
            type: string; symbol?: string; change_24h?: number; price?: number;
          };
          if (data.type === "big_mover" && data.symbol && data.change_24h != null) {
            const dir   = data.change_24h > 0 ? "▲" : "▼";
            const title = `Big Mover: ${data.symbol.replace("USDT", "")} ${dir}${Math.abs(data.change_24h).toFixed(1)}%`;
            const body  = `Price: $${data.price?.toFixed(4) ?? "—"}`;
            if (typeof window !== "undefined" && "Notification" in window) {
              if (Notification.permission === "granted") {
                new Notification(title, { body, icon: "/favicon.ico" });
              } else if (Notification.permission !== "denied") {
                void Notification.requestPermission().then(p => {
                  if (p === "granted") new Notification(title, { body, icon: "/favicon.ico" });
                });
              }
            }
          }
        } catch { /* ignore parse errors */ }
      };

      ws.onclose = () => {
        if (mounted) reconnectTimer = setTimeout(connect, 5000);
      };
      ws.onerror = () => ws?.close();
    }

    connect();
    return () => {
      mounted = false;
      clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, []);

  // ── Derived ───────────────────────────────────────────────────────────────────

  const startingBalance = learning?.balance?.starting ?? FALLBACK_BALANCE;
  const riskDollar      = startingBalance * RISK_PCT;

  const stats = useMemo(() => {
    const open   = positions.filter(p => p.status === "open");
    const closed = positions.filter(p => p.status === "tp" || p.status === "sl" || p.status === "expired");
    const wins   = closed.filter(isRealWin);
    const losses = closed.filter(p => !isRealWin(p));
    const totalPnl$ = closed.reduce((acc, p) => acc + (tradePnlDollar(p, riskDollar) ?? 0), 0);
    // OV2: paper balance only — never use real Binance balance (futBal) for paper simulation
    const currentBalance = learning?.balance?.current ?? (startingBalance + totalPnl$);
    const winRate = closed.length > 0 ? (wins.length / closed.length) * 100 : 0;

    const a1Closed = closed.filter(p => p.agent === "futures_agent1");
    const a2Closed = closed.filter(p => p.agent === "futures_agent2");
    const a3Closed = closed.filter(p => p.agent === "futures_agent3");
    const bmClosed = closed.filter(p => p.agent === "futures_agent_bigmover");
    const a1Open   = open.filter(p => p.agent === "futures_agent1");
    const a2Open   = open.filter(p => p.agent === "futures_agent2");
    const a3Open   = open.filter(p => p.agent === "futures_agent3");
    const bmOpen   = open.filter(p => p.agent === "futures_agent_bigmover");

    // OV3: per-agent P&L in dollars
    const pnlSum = (arr: FuturesPosition[]) => arr.reduce((s, p) => s + (tradePnlDollar(p, riskDollar) ?? 0), 0);

    return {
      open: open.length, closed: closed.length, wins: wins.length, losses: losses.length,
      winRate, currentBalance, totalPnl$,
      a1Open, a2Open, a3Open, bmOpen,
      a1: { total: a1Closed.length, wins: a1Closed.filter(isRealWin).length, rate: a1Closed.length > 0 ? a1Closed.filter(isRealWin).length / a1Closed.length * 100 : 0, pnl$: pnlSum(a1Closed) },
      a2: { total: a2Closed.length, wins: a2Closed.filter(isRealWin).length, rate: a2Closed.length > 0 ? a2Closed.filter(isRealWin).length / a2Closed.length * 100 : 0, pnl$: pnlSum(a2Closed) },
      a3: { total: a3Closed.length, wins: a3Closed.filter(isRealWin).length, rate: a3Closed.length > 0 ? a3Closed.filter(isRealWin).length / a3Closed.length * 100 : 0, pnl$: pnlSum(a3Closed) },
      bm: { total: bmClosed.length, wins: bmClosed.filter(isRealWin).length, rate: bmClosed.length > 0 ? bmClosed.filter(isRealWin).length / bmClosed.length * 100 : 0, pnl$: pnlSum(bmClosed) },
    };
  }, [positions, learning, startingBalance, riskDollar]);

  // OV1: equity chart uses same set as win rate (tp|sl only) — expired excluded from both
  const equityPoints = useMemo(
    () => buildEquity(
      positions.filter(p => p.status === "tp" || p.status === "sl"),
      startingBalance, riskDollar,
    ),
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

  const sharedProps = { riskDash, learning, startingBalance, riskDollar, countdown, onRefresh: () => void fetchPositions() };

  return (
    <div className="space-y-4">
      {subTabBar}
      {subTab === "monitor" ? (
        <MonitorTab {...sharedProps} positions={positions} />
      ) : (
        <OverviewTab {...sharedProps}
          equityPoints={equityPoints} stats={stats} autoThreshold={autoThreshold}
          agentFilter={agentFilter} setAgentFilter={setAgentFilter}
          lastUpdated={lastUpdated} loading={loading}
          onWalletChanged={() => void fetchPositions(true)}
        />
      )}
    </div>
  );
}
