export interface FuturesPosition {
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
  pnl_pct:               number | null;
  pnl_dollar:            number | null;
  position_size:         number | null;
  current_price:         number | null;
  unrealized_pnl:        number | null;
  unrealized_pnl_dollar: number | null;
}

export interface RiskPosition {
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
  trail_active:             boolean;
  score:                    number;
  auto_opened:              boolean;
  cumulative_funding_paid?: number | null;   // G6: simulated funding cost accrued
  cumulative_fee_paid?:     number | null;   // G15: round-trip fee cost
  peak_pnl_pct?:            number | null;   // G5b: highest unrealized % reached
}

export interface GateState {
  active:        boolean;
  gate_type:     "none" | "circuit_breaker" | "rar" | "override";
  reason:        string;
  drawdown_pct:  number;
  rar:           number;
  n_trades:      number;
  dd_threshold:  number;
  rar_threshold: number;
}

export interface LearningStats {
  regime:          string;
  target_win_rate: number;
  overall:         { total: number; open: number; closed: number; wins: number; losses: number; win_rate: number };
  agent1:          { total: number; wins: number; losses: number; win_rate: number };
  agent2:          { total: number; wins: number; losses: number; win_rate: number };
  agent3?:         { total: number; wins: number; losses: number; win_rate: number };
  agent_bigmover?: { total: number; wins: number; losses: number; win_rate: number };   // Phase 2 BM1
  balance:         { starting: number; current: number; total_pnl: number; roi_pct: number };
  win_rate_trend:  { trade_n: number; win_rate: number; win: boolean }[];
  top_signals:     { key: string; agent: string; win_rate: number; weight: number; total: number; wins: number }[];
  bottom_signals:  { key: string; agent: string; win_rate: number; weight: number; total: number }[];
  monthly_stats?:  { month: string; agent1: { total: number; wins: number; win_rate: number }; agent2: { total: number; wins: number; win_rate: number }; agent3?: { total: number; wins: number; win_rate: number } }[];
  monitor:         { running: boolean; cycle_count: number; closed_today: number; liq_guards?: number; tp_extended?: number };
}

export interface RiskDashboard {
  positions: RiskPosition[];
  portfolio: {
    open_count: number; total_margin: number; total_notional: number;
    total_unrealized: number; at_risk_count: number; max_drawdown_pct: number;
    risk_adjusted_return: number | null; total_closed_pnl: number; current_balance: number;
    margin_ratio?: number | null;   // G7: effective_margin / wallet_balance (%)
  };
  agent_breakdown: {
    agent1: { open: number; margin: number; at_risk: number };
    agent2: { open: number; margin: number; at_risk: number };
    agent3?: { open: number; margin: number; at_risk: number };
    agent_bigmover?: { open: number; margin: number; at_risk: number };   // Phase 2 BM1
  };
  gate?: GateState;
}

export function isRealWin(p: FuturesPosition): boolean {
  return p.status === "tp" && (p.pnl_pct ?? 0) > 0;
}

export function calcNotional(riskPct: number, riskDollar: number): number {
  return riskPct > 0 ? riskDollar / (riskPct / 100) : 0;
}

export function calcMargin(notional: number, leverage: number): number {
  return leverage > 0 ? notional / leverage : notional;
}

export function calcLiqPrice(entry: number, leverage: number, direction: "LONG" | "SHORT"): number {
  const dist = entry * (0.95 / Math.max(leverage, 1));
  return direction === "LONG" ? entry - dist : entry + dist;
}

export function tradePnlDollar(p: FuturesPosition, riskDollar: number): number | null {
  if (p.status === "open") {
    if (p.unrealized_pnl_dollar != null) return p.unrealized_pnl_dollar;
    if (p.unrealized_pnl == null) return null;
    const notional = p.position_size ?? calcNotional(p.risk_pct, riskDollar);
    return (p.unrealized_pnl / 100) * notional;
  }
  if (p.pnl_dollar != null) return p.pnl_dollar;
  if (p.pnl_pct == null) return null;
  const notional = p.position_size ?? calcNotional(p.risk_pct, riskDollar);
  return (p.pnl_pct / 100) * notional;
}
