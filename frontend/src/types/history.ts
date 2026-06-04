export type TradeStatus = "open" | "tp" | "sl";

export interface PaperTrade {
  id: number;
  symbol: string;
  direction: string;
  style: string;
  entry_price: number;
  stop_loss: number;
  take_profit: number;
  risk_reward: string;
  probability: number;
  alert_type: string;
  sl_method: string;
  tp_method: string;
  signals: string[];
  entry_type: string;
  entry_at: number;
  status: TradeStatus;
  closed_at: number | null;
  close_price: number | null;
  pnl_pct: number | null;
}

export interface StyleStats {
  total: number;
  wins: number;
  losses: number;
  open: number;
  win_rate: number;
  avg_pnl_pct: number;
}

export interface HistoryStats {
  overall: StyleStats;
  by_style: Record<string, StyleStats>;
}

export interface EquityPoint {
  ts: number;
  pnl: number;
}
