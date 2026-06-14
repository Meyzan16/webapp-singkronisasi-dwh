"use client";
import { useEffect, useState, useCallback, useMemo, useRef } from "react";
import { fmtPrice } from "@/lib/format";
import { FuturesAnalytics } from "./FuturesAnalytics";
import { FuturesWallet } from "./FuturesWallet";
import { DBHistoryTable } from "@/features/health/components/DBHistoryTable";

// ── Constants (F21: fallbacks only — runtime values from API) ─────────────────

const _FALLBACK_BALANCE  = 1000;   // used only when /futures/learning/stats not loaded yet
const RISK_PCT           = 0.01;   // 1% fixed-fractional (matches trading_costs.py)
const REFRESH_MS         = 15_000; // 15 s live polling
const TARGET_WIN_RATE    = 80;

// ── Types ─────────────────────────────────────────────────────────────────────

interface MonthlyStats {
  month:  string;
  agent1: { total: number; wins: number; win_rate: number };
  agent2: { total: number; wins: number; win_rate: number };
}

interface LearningStats {
  regime:          string;
  target_win_rate: number;
  overall:         { total: number; open: number; closed: number; wins: number; losses: number; win_rate: number };
  agent1:          { total: number; wins: number; losses: number; win_rate: number };
  agent2:          { total: number; wins: number; losses: number; win_rate: number };
  balance:         { starting: number; current: number; total_pnl: number; roi_pct: number };
  win_rate_trend:  { trade_n: number; win_rate: number; win: boolean }[];
  top_signals:     { key: string; agent: string; win_rate: number; weight: number; total: number; wins: number }[];
  bottom_signals:  { key: string; agent: string; win_rate: number; weight: number; total: number }[];
  monthly_stats?:  MonthlyStats[];
  monitor:         { running: boolean; cycle_count: number; closed_today: number; liq_guards?: number; tp_extended?: number };
}

interface RiskPosition {
  id:           number;
  symbol:       string;
  direction:    "LONG" | "SHORT";
  agent:        string;
  entry:        number;
  current:      number;
  sl:           number;
  tp1:          number | null;
  tp2:          number;
  tp3:          number | null;
  leverage:     number;
  notional:     number;
  margin:       number;
  liq_price:    number;
  liq_dist_pct: number;
  sl_dist_pct:  number;
  upnl_pct:     number;
  upnl_dollar:  number;
  risk_status:  "SAFE" | "WARNING" | "DANGER";
  trail_active: boolean;
  score:        number;
  auto_opened:  boolean;
}

// Phase 10: risk gate state (included in risk dashboard response)
interface GateState {
  active:        boolean;
  gate_type:     "none" | "circuit_breaker" | "rar" | "override";
  reason:        string;
  drawdown_pct:  number;
  rar:           number;
  n_trades:      number;
  dd_threshold:  number;
  rar_threshold: number;
}

interface RiskDashboard {
  positions: RiskPosition[];
  portfolio: {
    open_count:       number;
    total_margin:     number;
    total_notional:   number;
    total_unrealized: number;
    at_risk_count:    number;
    max_drawdown_pct: number;
    risk_adjusted_return: number;
    total_closed_pnl: number;
    current_balance:  number;
  };
  agent_breakdown: {
    agent1: { open: number; margin: number; at_risk: number };
    agent2: { open: number; margin: number; at_risk: number };
  };
  gate?: GateState;
}

interface FuturesPosition {
  id:             number;
  symbol:         string;
  direction:      "LONG" | "SHORT";
  agent:          string;
  status:         string;
  entry:          number;
  sl:             number;
  tp1:            number | null;
  tp2:            number;
  tp3:            number | null;
  risk_pct:       number;
  tp2_pct:        number;
  rr_ratio:       number;
  leverage:       number;
  margin_type:    string;
  score:          number;
  signals:        string[];
  funding_rate:   number;
  oi_change:      number;
  entry_at:       number;
  close_price:    number | null;
  closed_at:      number | null;
  pnl_pct:        number | null;
  current_price:  number | null;
  unrealized_pnl: number | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

// F46: fallback only — real riskDollar derived from API starting balance and threaded in
const FALLBACK_RISK_DOLLAR = _FALLBACK_BALANCE * RISK_PCT; // $10 (matches trading_costs.py)

function calcNotional(riskPct: number, riskDollar = FALLBACK_RISK_DOLLAR): number {
  return riskPct > 0 ? riskDollar / (riskPct / 100) : 0;
}

function calcMargin(notional: number, leverage: number): number {
  return leverage > 0 ? notional / leverage : notional;
}

function calcLiqPrice(entry: number, leverage: number, direction: "LONG" | "SHORT"): number {
  const dist = entry * (0.95 / Math.max(leverage, 1));
  return direction === "LONG" ? entry - dist : entry + dist;
}

// F104: a "win" is status=="tp" AND net pnl > 0 (matches backend _is_real_win)
function isRealWin(p: FuturesPosition): boolean {
  return p.status === "tp" && (p.pnl_pct ?? 0) > 0;
}

function tradePnlDollar(p: FuturesPosition, riskDollar = FALLBACK_RISK_DOLLAR): number | null {
  if (p.status === "open") {
    if (p.unrealized_pnl == null || p.risk_pct <= 0) return null;
    return (p.unrealized_pnl / 100) * calcNotional(p.risk_pct, riskDollar);
  }
  if (p.pnl_pct == null || p.risk_pct <= 0) return null;
  return (p.pnl_pct / 100) * calcNotional(p.risk_pct, riskDollar);
}

function fmtMonth(m: string): string {
  const [y, mo] = m.split("-");
  const names = ["", "Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Ags", "Sep", "Okt", "Nov", "Des"];
  return `${names[parseInt(mo)]} ${y}`;
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function DirBadge({ dir }: { dir: "LONG" | "SHORT" }) {
  return dir === "LONG"
    ? <span className="text-[9px] font-black px-1.5 py-0.5 rounded bg-green-100 text-green-700 border border-green-300">▲ L</span>
    : <span className="text-[9px] font-black px-1.5 py-0.5 rounded bg-red-100 text-red-700 border border-red-300">▼ S</span>;
}


function RiskStatusBadge({ status }: { status: "SAFE" | "WARNING" | "DANGER" }) {
  const cfg = {
    SAFE:    "bg-green-100 text-green-700 border-green-200",
    WARNING: "bg-yellow-100 text-yellow-700 border-yellow-200",
    DANGER:  "bg-red-100 text-red-600 border-red-200 animate-pulse",
  };
  const emoji = { SAFE: "✅", WARNING: "⚠️", DANGER: "🚨" };
  return (
    <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded border ${cfg[status]}`}>
      {emoji[status]} {status}
    </span>
  );
}

function PnlDollar({ value }: { value: number | null }) {
  if (value == null) return <span className="text-neutral-400">—</span>;
  const color = value > 0 ? "text-green-600" : value < 0 ? "text-red-500" : "text-neutral-500";
  return (
    <span className={`font-black tabular-nums ${color}`}>
      {value >= 0 ? "+" : ""}${Math.abs(value).toFixed(2)}
    </span>
  );
}

function WinRateBar({ rate, label }: { rate: number; label: string }) {
  const color = rate >= 70 ? "bg-green-500" : rate >= 50 ? "bg-yellow-400" : "bg-red-400";
  return (
    <div>
      <div className="flex justify-between text-[10px] mb-1">
        <span className="text-neutral-500">{label}</span>
        <span className={`font-black ${rate >= 50 ? "text-green-600" : "text-red-500"}`}>{rate.toFixed(0)}%</span>
      </div>
      <div className="h-1.5 bg-neutral-200 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${Math.min(rate, 100)}%` }} />
      </div>
    </div>
  );
}

// ── Phase 10: Risk gate banner (circuit-breaker + RAR gate) ──────────────────

function GateBanner({ gate }: { gate: GateState | undefined }) {
  if (!gate || !gate.active) return null;

  const isCB       = gate.gate_type === "circuit_breaker";
  const isRAR      = gate.gate_type === "rar";
  const isOverride = gate.gate_type === "override";

  const cfg = isCB
    ? { bg: "bg-red-50 border-red-300",  icon: "⛔", title: "Circuit Breaker Aktif", textCls: "text-red-700" }
    : isRAR
    ? { bg: "bg-orange-50 border-orange-300", icon: "⚠️", title: "RAR Gate Aktif", textCls: "text-orange-700" }
    : { bg: "bg-yellow-50 border-yellow-300", icon: "🔒", title: "Gate Manual (Override)", textCls: "text-yellow-800" };

  return (
    <div className={`border rounded-2xl p-4 ${cfg.bg}`}>
      <div className="flex items-start gap-3">
        <span className="text-2xl leading-none mt-0.5">{cfg.icon}</span>
        <div className="flex-1 min-w-0">
          <p className={`font-black text-sm mb-1 ${cfg.textCls}`}>{cfg.title}</p>
          <p className={`text-xs leading-relaxed ${cfg.textCls} opacity-90`}>{gate.reason}</p>

          {/* Metrics strip */}
          {!isOverride && (
            <div className="flex gap-4 mt-2 text-xs">
              <span className={cfg.textCls}>
                DD dari peak: <strong className={isCB ? "text-red-700" : ""}>{gate.drawdown_pct.toFixed(1)}%</strong>
                <span className="opacity-60 ml-1">(batas {gate.dd_threshold}%)</span>
              </span>
              {gate.n_trades >= 5 && (
                <span className={cfg.textCls}>
                  Sharpe: <strong className={isRAR ? "text-orange-700" : ""}>{gate.rar.toFixed(3)}</strong>
                  <span className="opacity-60 ml-1">(batas {gate.rar_threshold})</span>
                </span>
              )}
              <span className="opacity-60 text-neutral-500">{gate.n_trades} trade tertutup</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Open Position Card — used in separated Agent 1 / Agent 2 panels ────────────

function OpenPosCard({ p, risk, riskDollar }: { p: FuturesPosition; risk?: RiskPosition; riskDollar: number }) {
  const upnl$   = tradePnlDollar(p, riskDollar);
  const upnlPct = p.unrealized_pnl;
  const notional = calcNotional(p.risk_pct, riskDollar);
  const margin   = calcMargin(notional, p.leverage);
  const liq     = calcLiqPrice(p.entry, p.leverage, p.direction);
  const rStatus = risk?.risk_status ?? "SAFE";

  return (
    <div className={`rounded-xl border p-3 transition-all ${
      rStatus === "DANGER"  ? "border-red-300 bg-red-50"    :
      rStatus === "WARNING" ? "border-yellow-200 bg-yellow-50" :
      "border-neutral-200 bg-white"
    }`}>
      {/* Header row */}
      <div className="flex items-center gap-1.5 mb-2 flex-wrap">
        <span className="font-bold text-sm">{p.symbol.replace("USDT", "")}</span>
        <DirBadge dir={p.direction} />
        <span className="text-[9px] bg-neutral-100 text-neutral-600 px-1.5 py-0.5 rounded">{p.leverage}x</span>
        {risk?.auto_opened && (
          <span className="text-[9px] bg-teal-100 text-teal-700 px-1.5 py-0.5 rounded font-bold border border-teal-200">AUTO</span>
        )}
        {risk?.trail_active && (
          <span className="text-[9px] bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded">Trail✓</span>
        )}
        <RiskStatusBadge status={rStatus} />
      </div>

      {/* Prices */}
      <div className="grid grid-cols-3 gap-1.5 mb-2 text-center">
        <div className="bg-neutral-50 rounded-lg px-2 py-1.5">
          <p className="text-[9px] text-neutral-400">Entry</p>
          <p className="text-xs font-mono font-bold">${fmtPrice(p.entry)}</p>
        </div>
        <div className="bg-neutral-50 rounded-lg px-2 py-1.5">
          <p className="text-[9px] text-neutral-400">Current</p>
          <p className={`text-xs font-mono font-bold ${upnl$ != null && upnl$ >= 0 ? "text-green-600" : "text-red-500"}`}>
            {p.current_price != null ? `$${fmtPrice(p.current_price)}` : "—"}
          </p>
        </div>
        <div className="bg-orange-50 rounded-lg px-2 py-1.5">
          <p className="text-[9px] text-orange-400">Liq ≈</p>
          <p className="text-xs font-mono font-bold text-orange-600">${fmtPrice(liq)}</p>
        </div>
      </div>

      {/* SL / TP bar */}
      <div className="flex gap-1.5 mb-2 text-[10px]">
        <div className="flex-1 bg-red-50 border border-red-100 rounded-lg px-2 py-1">
          <span className="text-red-400 font-semibold">SL </span>
          <span className="font-mono text-red-600">${fmtPrice(p.sl)}</span>
          <span className="text-red-300 ml-1">-{p.risk_pct.toFixed(1)}%</span>
        </div>
        <div className="flex-1 bg-green-50 border border-green-100 rounded-lg px-2 py-1">
          <span className="text-green-500 font-semibold">TP2 </span>
          <span className="font-mono text-green-700">${fmtPrice(p.tp2)}</span>
          <span className="text-green-400 ml-1">+{p.tp2_pct.toFixed(1)}%</span>
        </div>
      </div>

      {/* Margin + P&L */}
      <div className="flex items-center justify-between text-xs">
        <span className="text-neutral-500">
          Margin <strong className="text-blue-600">${margin.toFixed(0)}</strong>
          <span className="mx-1 text-neutral-300">·</span>
          Liq dist <strong className={risk ? (rStatus === "DANGER" ? "text-red-600" : rStatus === "WARNING" ? "text-yellow-600" : "text-neutral-700") : "text-neutral-700"}>
            {risk ? `${risk.liq_dist_pct.toFixed(1)}%` : "—"}
          </strong>
        </span>
        <span className={`font-black tabular-nums ${upnl$ != null && upnl$ >= 0 ? "text-green-600" : "text-red-500"}`}>
          <PnlDollar value={upnl$} />
          {upnlPct != null && (
            <span className="text-[10px] ml-1">({upnlPct >= 0 ? "+" : ""}{upnlPct.toFixed(2)}%)</span>
          )}
        </span>
      </div>
    </div>
  );
}

// ── Balance simulation ─────────────────────────────────────────────────────────

function buildEquity(closed: FuturesPosition[], startingBalance: number, riskDollar: number): { balance: number; n: number; symbol: string; win: boolean }[] {
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

// ── Main component ─────────────────────────────────────────────────────────────

type SubTab   = "overview" | "monitor" | "analytics";

export function FuturesTab() {
  const [subTab, setSubTab]           = useState<SubTab>("overview");
  const [positions, setPositions]     = useState<FuturesPosition[]>([]);
  const [learning, setLearning]       = useState<LearningStats | null>(null);
  const [riskDash, setRiskDash]       = useState<RiskDashboard | null>(null);
  const [loading, setLoading]         = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  // (sortBy/sortDir/filterBy removed — history now uses DBHistoryTable)
  const [agentFilter, setAgentFilter] = useState<"all" | "agent1" | "agent2">("all");
  const [countdown, setCountdown]     = useState(REFRESH_MS / 1000);
  const [selectedMonth, setSelectedMonth] = useState<string>("all");
  const [autoThreshold, setAutoThreshold] = useState<number | null>(null);  // F26/F10
  const countRef = useRef(REFRESH_MS / 1000);

  const fetchPositions = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    // reset error state
    try {
      const [posRes, learnRes, riskRes, autoRes] = await Promise.all([
        fetch("/api/v1/futures/positions?status=all"),
        fetch("/api/v1/futures/learning/stats"),
        fetch("/api/v1/futures/monitor/risk"),
        fetch("/api/v1/futures/auto/status"),   // F26/F10: real auto-open threshold
      ]);
      if (!posRes.ok) return; // fetch error — show stale data or empty state
      const d = await posRes.json() as { positions: FuturesPosition[] };
      setPositions(d.positions ?? []);
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
    } catch {
      // fetch error — will show stale data or empty state
    } finally {
      if (!silent) setLoading(false);
    }
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

  // ── Derived stats ──────────────────────────────────────────────────────────────

  // F46: reactive risk-dollar from API starting balance (falls back to $1000 × 1%)
  const startingBalance = learning?.balance?.starting ?? _FALLBACK_BALANCE;
  const riskDollar      = startingBalance * RISK_PCT;

  const stats = useMemo(() => {
    const open   = positions.filter(p => p.status === "open");
    // F43: only tp/sl count as closed — expired must not inflate the win-rate denominator
    const closed = positions.filter(p => p.status === "tp" || p.status === "sl");
    const wins   = closed.filter(isRealWin);                  // F104
    const losses = closed.filter(p => !isRealWin(p));         // sl + tp-with-negative-pnl

    const totalPnl$ = closed.reduce((acc, p) => acc + (tradePnlDollar(p, riskDollar) ?? 0), 0);
    // F22: prefer server-computed balance (/futures/learning/stats) over client-side calc
    const currentBalance = learning?.balance?.current ?? (startingBalance + totalPnl$);
    const winRate = closed.length > 0 ? (wins.length / closed.length) * 100 : 0;

    const a1Closed = closed.filter(p => p.agent === "futures_agent1");
    const a2Closed = closed.filter(p => p.agent === "futures_agent2");
    const a1Wins   = a1Closed.filter(isRealWin).length;      // F104
    const a2Wins   = a2Closed.filter(isRealWin).length;      // F104
    const a1Open   = open.filter(p => p.agent === "futures_agent1");
    const a2Open   = open.filter(p => p.agent === "futures_agent2");

    return {
      open: open.length, closed: closed.length, wins: wins.length, losses: losses.length,
      winRate, currentBalance, totalPnl$,
      a1Open, a2Open,
      a1: { total: a1Closed.length, wins: a1Wins, rate: a1Closed.length > 0 ? a1Wins / a1Closed.length * 100 : 0 },
      a2: { total: a2Closed.length, wins: a2Wins, rate: a2Closed.length > 0 ? a2Wins / a2Closed.length * 100 : 0 },
    };
  }, [positions, learning, startingBalance, riskDollar]);

  const equityPoints = useMemo(
    () => buildEquity(positions.filter(p => p.status === "tp" || p.status === "sl"), startingBalance, riskDollar),
    [positions, startingBalance, riskDollar]
  );

  // (displayClosed removed — riwayat now handled by DBHistoryTable below)

  const balanceColor = stats.currentBalance >= startingBalance ? "text-green-600" : "text-red-500";
  const pnlColor     = stats.totalPnl$ >= 0 ? "text-green-600" : "text-red-500";

  // Risk map for open positions
  const riskMap = useMemo(() => {
    const m: Record<number, RiskPosition> = {};
    (riskDash?.positions ?? []).forEach(rp => { m[rp.id] = rp; });
    return m;
  }, [riskDash]);

  // ── Sub-tab bar ────────────────────────────────────────────────────────────────

  const SubTabBar = (
    <div className="flex gap-1 bg-neutral-100 p-1 rounded-xl w-fit">
      {([
        { key: "overview",  label: "📋 Overview"  },
        { key: "monitor",   label: "🔍 Monitor"   },
        { key: "analytics", label: "📊 Analytics" },
      ] as { key: SubTab; label: string }[]).map(t => (
        <button key={t.key} onClick={() => setSubTab(t.key)}
          className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all ${
            subTab === t.key ? "bg-white text-neutral-900 shadow-sm" : "text-neutral-500 hover:text-neutral-700"
          }`}>
          {t.label}
        </button>
      ))}
    </div>
  );

  if (loading && positions.length === 0) {
    return (
      <div className="space-y-4">
        {SubTabBar}
        {subTab === "analytics" ? <FuturesAnalytics /> : (
          <div className="text-center py-16 text-neutral-400">
            <div className="w-10 h-10 border-2 border-teal-400 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
            <p>Memuat posisi futures...</p>
          </div>
        )}
      </div>
    );
  }

  // ── Monitor sub-tab ────────────────────────────────────────────────────────────

  if (subTab === "monitor") {
    const pd = riskDash?.portfolio;
    const ab = riskDash?.agent_breakdown;
    return (
      <div className="space-y-5">
        {SubTabBar}

        {/* Phase 10: risk gate banner */}
        <GateBanner gate={riskDash?.gate} />

        {/* Portfolio summary */}
        {pd && (
          <div className="rounded-2xl bg-gradient-to-br from-neutral-900 via-neutral-800 to-neutral-900 text-white p-5">
            <div className="flex items-start justify-between gap-4 flex-wrap mb-4">
              <div>
                <p className="text-xs text-neutral-400 uppercase tracking-wider font-semibold mb-1">🔍 Portfolio Risk Dashboard</p>
                <div className="flex items-baseline gap-3">
                  <span className={`text-4xl font-black ${pd.current_balance >= startingBalance ? "text-green-400" : "text-red-400"}`}>
                    ${pd.current_balance.toFixed(2)}
                  </span>
                  <span className={`text-sm font-bold ${pd.total_closed_pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                    {pd.total_closed_pnl >= 0 ? "+" : ""}${pd.total_closed_pnl.toFixed(2)}
                  </span>
                </div>
                <p className="text-xs text-neutral-500 mt-1">Modal ${startingBalance.toLocaleString()} · Risk ${riskDollar.toFixed(0)}/trade · Sharpe ≈ {pd.risk_adjusted_return.toFixed(2)}</p>
              </div>
              <div className="grid grid-cols-3 gap-2 text-center">
                <div className="bg-white/5 rounded-xl px-3 py-2">
                  <p className="text-2xl font-black text-blue-400">{pd.open_count}</p>
                  <p className="text-[9px] text-neutral-400">Open</p>
                </div>
                <div className={`rounded-xl px-3 py-2 ${pd.at_risk_count > 0 ? "bg-red-900/40 border border-red-700/40" : "bg-white/5"}`}>
                  <p className={`text-2xl font-black ${pd.at_risk_count > 0 ? "text-red-400" : "text-green-400"}`}>{pd.at_risk_count}</p>
                  <p className="text-[9px] text-neutral-400">At Risk</p>
                </div>
                <div className="bg-white/5 rounded-xl px-3 py-2">
                  <p className="text-2xl font-black text-orange-400">{pd.max_drawdown_pct.toFixed(1)}%</p>
                  <p className="text-[9px] text-neutral-400">Max DD</p>
                </div>
              </div>
            </div>

            {/* Agent breakdown */}
            {ab && (
              <div className="grid grid-cols-2 gap-3">
                {[
                  { key: "agent1", label: "🤖 Agent 1 AI", color: "blue",   data: ab.agent1 },
                  { key: "agent2", label: "🧠 Agent 2 T4", color: "purple", data: ab.agent2 },
                ].map(a => (
                  <div key={a.key} className={`bg-white/5 rounded-xl p-3 border ${a.data.at_risk > 0 ? "border-red-700/40" : "border-white/5"}`}>
                    <p className={`text-[10px] font-bold mb-2 ${a.color === "blue" ? "text-blue-300" : "text-purple-300"}`}>{a.label}</p>
                    <div className="flex justify-between text-xs">
                      <span className="text-neutral-400">Open: <strong className="text-white">{a.data.open}</strong></span>
                      <span className="text-neutral-400">Margin: <strong className="text-yellow-300">${a.data.margin.toFixed(0)}</strong></span>
                      {a.data.at_risk > 0 && <span className="text-red-400 font-bold">⚠️ {a.data.at_risk} at risk</span>}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Totals row */}
            <div className="mt-3 flex gap-4 text-xs flex-wrap">
              <span className="text-neutral-400">Total Margin: <strong className="text-yellow-300">${pd.total_margin.toFixed(0)}</strong></span>
              <span className="text-neutral-400">Notional: <strong className="text-neutral-200">${pd.total_notional.toFixed(0)}</strong></span>
              <span className="text-neutral-400">Unrealized: <strong className={pd.total_unrealized >= 0 ? "text-green-400" : "text-red-400"}>
                {pd.total_unrealized >= 0 ? "+" : ""}${pd.total_unrealized.toFixed(2)}
              </strong></span>
            </div>
          </div>
        )}

        {/* Open positions by agent — side by side */}
        {(stats.a1Open.length > 0 || stats.a2Open.length > 0) ? (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Agent 1 */}
            <div>
              <div className="flex items-center gap-2 mb-2">
                <span className="text-[10px] font-bold bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full border border-blue-200">🤖 Agent 1 — AI Knowledge</span>
                <span className="text-xs text-neutral-500">{stats.a1Open.length} posisi</span>
                {ab && ab.agent1.at_risk > 0 && (
                  <span className="text-[10px] text-red-600 font-bold">⚠️ {ab.agent1.at_risk} at risk</span>
                )}
              </div>
              {stats.a1Open.length === 0
                ? <div className="text-center py-8 text-neutral-400 text-sm border border-dashed border-neutral-200 rounded-2xl">Tidak ada posisi terbuka</div>
                : <div className="space-y-2">
                    {stats.a1Open.map(p => <OpenPosCard key={p.id} p={p} risk={riskMap[p.id]} riskDollar={riskDollar} />)}
                  </div>
              }
            </div>

            {/* Agent 2 */}
            <div>
              <div className="flex items-center gap-2 mb-2">
                <span className="text-[10px] font-bold bg-purple-100 text-purple-700 px-2 py-0.5 rounded-full border border-purple-200">🧠 Agent 2 — T0-T4</span>
                <span className="text-xs text-neutral-500">{stats.a2Open.length} posisi</span>
                {ab && ab.agent2.at_risk > 0 && (
                  <span className="text-[10px] text-red-600 font-bold">⚠️ {ab.agent2.at_risk} at risk</span>
                )}
              </div>
              {stats.a2Open.length === 0
                ? <div className="text-center py-8 text-neutral-400 text-sm border border-dashed border-neutral-200 rounded-2xl">Tidak ada posisi terbuka</div>
                : <div className="space-y-2">
                    {stats.a2Open.map(p => <OpenPosCard key={p.id} p={p} risk={riskMap[p.id]} riskDollar={riskDollar} />)}
                  </div>
              }
            </div>
          </div>
        ) : (
          <div className="text-center py-12 text-neutral-400 border border-dashed border-neutral-200 rounded-2xl">
            <p className="text-3xl mb-2">📭</p>
            <p>Tidak ada posisi terbuka saat ini</p>
          </div>
        )}

        {/* Monitor stats */}
        {learning?.monitor && (
          <div className="bg-white border border-neutral-200 rounded-2xl p-4">
            <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider mb-3">🔬 Monitor Stats</p>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-center">
              {[
                { label: "Cycles",       value: learning.monitor.cycle_count,             color: "text-neutral-700" },
                { label: "Tutup Hari Ini", value: learning.monitor.closed_today,          color: "text-blue-600"    },
                { label: "Liq Guards",   value: learning.monitor.liq_guards ?? 0,         color: "text-orange-600"  },
                { label: "TP Extended",  value: learning.monitor.tp_extended ?? 0,        color: "text-green-600"   },
              ].map(x => (
                <div key={x.label} className="bg-neutral-50 rounded-xl p-3">
                  <p className={`text-2xl font-black ${x.color}`}>{x.value}</p>
                  <p className="text-[10px] text-neutral-400 mt-0.5">{x.label}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="flex items-center justify-end gap-2">
          <div className="flex items-center gap-1.5 px-2 py-1 rounded-full bg-blue-50 border border-blue-200">
            <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
            <span className="text-[10px] font-bold text-blue-700">LIVE</span>
            <span className="text-[10px] text-blue-600 tabular-nums">{countdown}s</span>
          </div>
          <button onClick={() => void fetchPositions()} className="text-xs text-teal-600 hover:text-teal-500 font-semibold">↺ Refresh</button>
        </div>
      </div>
    );
  }

  if (subTab === "analytics") {
    return (
      <div className="space-y-5">
        {SubTabBar}
        <FuturesAnalytics />
      </div>
    );
  }

  // ── Overview tab ───────────────────────────────────────────────────────────────

  return (
    <div className="space-y-5">
      {SubTabBar}

      {/* ── Phase 10: risk gate banner ─────────────────────────────────────────── */}
      <GateBanner gate={riskDash?.gate} />

      {/* ── Balance simulation banner ──────────────────────────────────────────── */}
      <div className="rounded-2xl bg-gradient-to-br from-neutral-900 via-neutral-800 to-neutral-900 text-white overflow-hidden">
        <div className="p-5">
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <p className="text-xs text-neutral-400 mb-1 font-semibold uppercase tracking-wider">Simulasi Paper Trading</p>
              <div className="flex items-baseline gap-2">
                <span className={`text-4xl font-black tabular-nums ${balanceColor}`}>
                  ${stats.currentBalance.toFixed(2)}
                </span>
                <span className={`text-sm font-bold ${pnlColor}`}>
                  {stats.totalPnl$ >= 0 ? "+" : ""}${stats.totalPnl$.toFixed(2)}
                </span>
              </div>
              <p className="text-xs text-neutral-400 mt-1">Modal awal <strong className="text-neutral-200">${startingBalance.toLocaleString()}</strong> · Risk <strong className="text-yellow-300">${riskDollar.toFixed(0)}/trade (1%)</strong> · Target R:R ≥ 1:3</p>
            </div>
            <div className="grid grid-cols-2 gap-2 text-center">
              {[
                { label: "Open",   value: stats.open,    color: "text-blue-400"    },
                { label: "Closed", value: stats.closed,  color: "text-neutral-200" },
                { label: "Win",    value: stats.wins,    color: "text-green-400"   },
                { label: "Loss",   value: stats.losses,  color: "text-red-400"     },
              ].map(s => (
                <div key={s.label} className="bg-white/5 rounded-xl px-3 py-2">
                  <p className={`text-2xl font-black ${s.color}`}>{s.value}</p>
                  <p className="text-[9px] text-neutral-400">{s.label}</p>
                </div>
              ))}
            </div>
          </div>

          {stats.closed > 0 && (
            <div className="mt-4">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-xs text-neutral-400 font-semibold">Win Rate</span>
                <span className={`text-sm font-black ${stats.winRate >= 50 ? "text-green-400" : "text-red-400"}`}>
                  {stats.winRate.toFixed(0)}%
                </span>
              </div>
              <div className="h-2 bg-neutral-700 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-700 ${stats.winRate >= 60 ? "bg-green-500" : stats.winRate >= 50 ? "bg-yellow-500" : "bg-red-500"}`}
                  style={{ width: `${Math.min(stats.winRate, 100)}%` }}
                />
              </div>
              <div className="flex justify-between text-[9px] text-neutral-500 mt-0.5">
                <span>Target 80%</span>
                <span className="text-neutral-300">{stats.wins}W / {stats.losses}L dari {stats.closed} trades</span>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Wallet: deposit / withdraw + balance sheet (Phase 9) ──────────────── */}
      <FuturesWallet onChanged={() => void fetchPositions(true)} />

      {/* ── Agent 1 vs Agent 2 OPEN POSITIONS (separated) ────────────────────── */}
      {(stats.a1Open.length > 0 || stats.a2Open.length > 0) && (
        <div>
          <h3 className="text-sm font-bold text-neutral-700 mb-3 flex items-center gap-2">
            🔵 Posisi Terbuka ({stats.open})
            <span className="text-[10px] text-neutral-400 font-normal">— Dipisah per agent</span>
            {agentFilter !== "all" && (   // F25: agentFilter now actually filters the panels
              <button onClick={() => setAgentFilter("all")}
                className="text-[10px] text-teal-600 font-semibold underline ml-1">
                Filter: {agentFilter === "agent1" ? "Agent 1" : "Agent 2"} ✕
              </button>
            )}
          </h3>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Agent 1 Open */}
            {agentFilter !== "agent2" && (
            <div className="bg-blue-50 border border-blue-100 rounded-2xl overflow-hidden">
              <div className="px-4 py-2.5 border-b border-blue-100 flex items-center gap-2">
                <span className="text-xs font-bold text-blue-700">🤖 Agent 1 — AI Knowledge</span>
                <span className="ml-auto text-[10px] text-blue-500">{stats.a1Open.length} open</span>
                {riskDash?.agent_breakdown.agent1.at_risk ? (
                  <span className="text-[9px] text-red-600 font-bold bg-red-100 px-1.5 py-0.5 rounded">⚠️ AT RISK</span>
                ) : null}
              </div>
              {stats.a1Open.length === 0 ? (
                <div className="text-center py-6 text-neutral-400 text-xs">Tidak ada posisi terbuka</div>
              ) : (
                <div className="divide-y divide-blue-50 p-2 space-y-1.5">
                  {stats.a1Open.map(p => <OpenPosCard key={p.id} p={p} risk={riskMap[p.id]} riskDollar={riskDollar} />)}
                </div>
              )}
            </div>
            )}

            {/* Agent 2 Open */}
            {agentFilter !== "agent1" && (
            <div className="bg-purple-50 border border-purple-100 rounded-2xl overflow-hidden">
              <div className="px-4 py-2.5 border-b border-purple-100 flex items-center gap-2">
                <span className="text-xs font-bold text-purple-700">🧠 Agent 2 — T0-T4</span>
                <span className="ml-auto text-[10px] text-purple-500">{stats.a2Open.length} open</span>
                {riskDash?.agent_breakdown.agent2.at_risk ? (
                  <span className="text-[9px] text-red-600 font-bold bg-red-100 px-1.5 py-0.5 rounded">⚠️ AT RISK</span>
                ) : null}
              </div>
              {stats.a2Open.length === 0 ? (
                <div className="text-center py-6 text-neutral-400 text-xs">Tidak ada posisi terbuka</div>
              ) : (
                <div className="divide-y divide-purple-50 p-2 space-y-1.5">
                  {stats.a2Open.map(p => <OpenPosCard key={p.id} p={p} risk={riskMap[p.id]} riskDollar={riskDollar} />)}
                </div>
              )}
            </div>
            )}
          </div>
        </div>
      )}

      {/* ── Agent comparison ──────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-3">
        {[
          { key: "agent1" as const, label: "Agent 1 — AI Knowledge", color: "blue",   emoji: "🤖", data: stats.a1 },
          { key: "agent2" as const, label: "Agent 2 — T0-T4",         color: "purple", emoji: "🧠", data: stats.a2 },
        ].map(a => {
          const rateColor = a.data.rate >= 60 ? "text-green-600" : a.data.rate >= 50 ? "text-yellow-600" : a.data.total > 0 ? "text-red-500" : "text-neutral-400";
          const border    = a.color === "blue" ? "border-blue-200 bg-blue-50" : "border-purple-200 bg-purple-50";
          const badge     = a.color === "blue" ? "bg-blue-100 text-blue-700" : "bg-purple-100 text-purple-700";
          return (
            <div key={a.key}
              onClick={() => setAgentFilter(f => f === a.key ? "all" : a.key)}
              className={`rounded-2xl border-2 p-4 cursor-pointer transition-all ${
                agentFilter === a.key ? border + " ring-2 ring-offset-1 " + (a.color === "blue" ? "ring-blue-400" : "ring-purple-400") : "border-neutral-200 bg-white hover:border-neutral-300"
              }`}>
              <div className="flex items-center gap-2 mb-2">
                <span className="text-lg">{a.emoji}</span>
                <span className={`text-[10px] font-bold px-2 py-0.5 rounded ${badge}`}>{a.label}</span>
              </div>
              {a.data.total > 0 ? (
                <>
                  <p className={`text-3xl font-black ${rateColor}`}>{a.data.rate.toFixed(0)}%</p>
                  <p className="text-[10px] text-neutral-400">{a.data.wins}/{a.data.total} trades closed</p>
                </>
              ) : (
                <p className="text-sm text-neutral-400 mt-1">Belum ada trades</p>
              )}
            </div>
          );
        })}
      </div>

      {/* ── Monthly win rate comparison ───────────────────────────────────────────── */}
      {learning?.monthly_stats && learning.monthly_stats.length > 0 && (
        <div className="bg-white border border-neutral-200 rounded-2xl p-4">
          <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
            <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider">📅 Win Rate Bulanan — Agent 1 vs 2</p>
            <select
              value={selectedMonth}
              onChange={e => setSelectedMonth(e.target.value)}
              className="text-xs border border-neutral-200 rounded-lg px-2 py-1 bg-white text-neutral-700 focus:outline-none"
            >
              <option value="all">Semua bulan</option>
              {learning.monthly_stats.map(m => (
                <option key={m.month} value={m.month}>{fmtMonth(m.month)}</option>
              ))}
            </select>
          </div>
          <div className="space-y-3">
            {learning.monthly_stats
              .filter(m => selectedMonth === "all" || m.month === selectedMonth)   // F49: actually filter
              .map(m => (
              <div key={m.month} className={`rounded-xl p-3 ${selectedMonth === m.month ? "bg-teal-50 border border-teal-200" : "bg-neutral-50"}`}>
                <div className="flex items-center justify-between mb-2">
                  <p className="text-xs font-bold text-neutral-700">{fmtMonth(m.month)}</p>
                  <div className="flex gap-3 text-[10px] text-neutral-500">
                    <span>A1: {m.agent1.wins}/{m.agent1.total}</span>
                    <span>A2: {m.agent2.wins}/{m.agent2.total}</span>
                  </div>
                </div>
                <div className="space-y-1.5">
                  <WinRateBar rate={m.agent1.win_rate} label={`🤖 Agent 1: ${m.agent1.win_rate.toFixed(0)}%`} />
                  <WinRateBar rate={m.agent2.win_rate} label={`🧠 Agent 2: ${m.agent2.win_rate.toFixed(0)}%`} />
                </div>
              </div>
            ))}
          </div>
          {selectedMonth !== "all" && (
            <div className="mt-2 text-center">
              <button onClick={() => setSelectedMonth("all")} className="text-xs text-neutral-400 hover:text-neutral-600 underline">
                Tampilkan semua bulan
              </button>
            </div>
          )}
        </div>
      )}

      {/* ── Regime + Monitor status ──────────────────────────────────────────────── */}
      {learning && (
        <div className="flex flex-wrap gap-2 items-center">
          {(() => {
            const regimeCfg: Record<string, { emoji: string; label: string; cls: string }> = {
              trending_up:   { emoji: "📈", label: "Trending Up",   cls: "bg-green-100 text-green-700 border-green-300" },
              trending_down: { emoji: "📉", label: "Trending Down", cls: "bg-red-100 text-red-600 border-red-300"       },
              ranging:       { emoji: "↔️", label: "Ranging",       cls: "bg-blue-100 text-blue-700 border-blue-300"   },
              volatile:      { emoji: "⚡", label: "Volatile",      cls: "bg-orange-100 text-orange-700 border-orange-300" },
            };
            const cfg = regimeCfg[learning.regime] ?? { emoji: "🔍", label: learning.regime, cls: "bg-neutral-100 text-neutral-600 border-neutral-300" };
            return (
              <span className={`flex items-center gap-1.5 text-xs font-bold px-3 py-1.5 rounded-full border ${cfg.cls}`}>
                {cfg.emoji} Regime: {cfg.label}
              </span>
            );
          })()}
          {learning.monitor?.running && (
            <span className="flex items-center gap-1.5 text-xs font-semibold text-teal-700 bg-teal-50 border border-teal-200 px-3 py-1.5 rounded-full">
              <span className="w-1.5 h-1.5 rounded-full bg-teal-500 animate-pulse" />
              Monitor aktif · Liq Guards: {learning.monitor.liq_guards ?? 0} · TP Extended: {learning.monitor.tp_extended ?? 0}
            </span>
          )}
          {learning.overall.closed > 0 && (
            <span className={`text-xs font-bold px-3 py-1.5 rounded-full border ${
              learning.overall.win_rate >= TARGET_WIN_RATE
                ? "bg-green-100 text-green-700 border-green-300"
                : "bg-yellow-100 text-yellow-700 border-yellow-300"
            }`}>
              {learning.overall.win_rate.toFixed(0)}% / {TARGET_WIN_RATE}% target
              {learning.overall.win_rate >= TARGET_WIN_RATE ? " 🎯" : ""}
            </span>
          )}
        </div>
      )}

      {/* ── Win rate trend ────────────────────────────────────────────────────────── */}
      {learning && learning.win_rate_trend.length > 2 && (
        <div className="bg-white border border-neutral-200 rounded-2xl p-4">
          <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider mb-3">📊 Win Rate Trend (rolling 10 trades)</p>
          <div className="flex items-end gap-0.5 h-12">
            {learning.win_rate_trend.map((pt, i) => {
              const h = Math.max((pt.win_rate / 100) * 100, 4);
              const cls = pt.win_rate >= TARGET_WIN_RATE ? "bg-green-500" : pt.win_rate >= 50 ? "bg-yellow-400" : "bg-red-400";
              return (
                <div key={i} title={`Trade #${pt.trade_n}: ${pt.win_rate}%`}
                  className={`flex-1 min-w-[4px] rounded-t transition-all ${cls}`}
                  style={{ height: `${h}%` }}
                />
              );
            })}
          </div>
          <div className="flex justify-between text-[9px] text-neutral-400 mt-1">
            <span>0%</span>
            <span className="text-green-600 font-semibold">Target {TARGET_WIN_RATE}%</span>
            <span>100%</span>
          </div>
        </div>
      )}

      {/* ── Top signals ─────────────────────────────────────────────────────────── */}
      {learning && learning.top_signals.length > 0 && (
        <div className="bg-white border border-neutral-200 rounded-2xl p-4">
          <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider mb-3">🔬 Signal Terbaik</p>
          <div className="space-y-2">
            {learning.top_signals.map((s, i) => (
              <div key={i} className="flex items-center gap-3 py-1.5 border-b border-neutral-50 last:border-0">
                <span className={`text-sm font-black w-10 text-right tabular-nums ${
                  s.win_rate >= 70 ? "text-green-600" : s.win_rate >= 50 ? "text-yellow-600" : "text-red-500"
                }`}>
                  {s.win_rate.toFixed(0)}%
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-[11px] text-neutral-700 truncate">{s.key.replace(/_/g, " ")}</p>
                  <p className="text-[9px] text-neutral-400">{s.agent === "futures_agent1" ? "AI" : "T0-T4"} · {s.wins}/{s.total} trades</p>
                </div>
                <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                  s.weight >= 1.4 ? "bg-green-100 text-green-700" : s.weight >= 1.1 ? "bg-blue-100 text-blue-700" : "bg-neutral-100 text-neutral-600"
                }`}>
                  ×{s.weight.toFixed(1)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Mini equity line ─────────────────────────────────────────────────────── */}
      {equityPoints.length > 1 && (
        <div className="bg-white border border-neutral-200 rounded-2xl p-4">
          <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider mb-3">📈 Pertumbuhan Balance (per trade)</p>
          <div className="flex items-end gap-0.5 h-16">
            {equityPoints.map((pt, i) => {
              const minBal = Math.min(...equityPoints.map(p => p.balance));
              const maxBal = Math.max(...equityPoints.map(p => p.balance));
              const range  = Math.max(maxBal - minBal, 1);
              const heightPct = ((pt.balance - minBal) / range) * 100;
              return (
                <div key={i}
                  title={pt.n === 0 ? `Start $${pt.balance.toFixed(0)}` : `#${pt.n} ${pt.symbol} → $${pt.balance.toFixed(0)}`}
                  className={`flex-1 min-w-[3px] rounded-t transition-all ${
                    i === 0 ? "bg-neutral-300" : pt.win ? "bg-green-400" : "bg-red-400"
                  }`}
                  style={{ height: `${Math.max(heightPct, 5)}%` }}
                />
              );
            })}
          </div>
          <div className="flex justify-between text-[9px] text-neutral-400 mt-1">
            <span>${startingBalance.toLocaleString()} start</span>
            <span className={`font-bold ${balanceColor}`}>${stats.currentBalance.toFixed(0)} sekarang</span>
          </div>
        </div>
      )}

      {/* ── Position sizing explainer ────────────────────────────────────────────── */}
      <div className="bg-amber-50 border border-amber-200 rounded-2xl p-4">
        <p className="text-xs font-bold text-amber-700 uppercase tracking-wider mb-2">💡 Logika Position Sizing</p>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-center">
          {[
            { label: "Modal Awal",   value: `$${startingBalance.toLocaleString()}`,        sub: "paper balance" },
            { label: "Risk/Trade",   value: `$${riskDollar.toFixed(0)} (1%)`,              sub: "fixed per trade" },
            { label: "R:R Minimum",  value: "1 : 3",                                       sub: `win $${(riskDollar * 3).toFixed(0)}, lose $${riskDollar.toFixed(0)}` },
            { label: "Auto-Open",    value: autoThreshold != null ? `≥ ${autoThreshold}pt` : "—", sub: "score threshold" },
          ].map(x => (
            <div key={x.label} className="bg-white/60 rounded-xl p-2.5">
              <p className="text-[10px] text-amber-600 font-semibold">{x.label}</p>
              <p className="text-base font-black text-neutral-800">{x.value}</p>
              <p className="text-[9px] text-neutral-400">{x.sub}</p>
            </div>
          ))}
        </div>
      </div>

      {/* ── Live indicator ────────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-end gap-2">
        <div className="flex items-center gap-1.5 px-2 py-1 rounded-full bg-blue-50 border border-blue-200">
          <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
          <span className="text-[10px] font-bold text-blue-700">LIVE</span>
          <span className="text-[10px] text-blue-600 tabular-nums">{countdown}s</span>
        </div>
        {lastUpdated && <p className="text-[10px] text-neutral-400">{lastUpdated.toLocaleTimeString()}</p>}
        <button onClick={() => void fetchPositions()} disabled={loading}
          className="text-xs text-teal-600 hover:text-teal-500 font-semibold disabled:opacity-40">
          {loading ? "..." : "↺"}
        </button>
      </div>

      {/* ── 🗄 Riwayat DB Lengkap — Futures ───────────────────────────────────── */}
      <div className="bg-white border border-neutral-200 rounded-2xl overflow-hidden">
        <div className="px-5 py-3 border-b border-neutral-100 bg-neutral-50">
          <h3 className="font-bold text-sm text-neutral-700">
            🗄 Riwayat Database — Futures Agent 1 + 2
          </h3>
          <p className="text-[10px] text-neutral-400 mt-0.5">
            Semua trade · search simbol · pagination · alasan tutup posisi lengkap
          </p>
        </div>
        <div className="p-4">
          <DBHistoryTable
            defaultStyle="futures"
            hideStyleTabs={false}
            compact={true}
          />
        </div>
      </div>

    </div>
  );
}
