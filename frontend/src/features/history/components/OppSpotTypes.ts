// Shared types for OppSpotTab and its sub-components

export interface ApiBalance {
  style:           string;
  balance:         number;
  initial_balance: number;
  available:       number;
  locked_margin:   number;
  deposited_total: number;
  realized_pnl:    number;
  total_pnl:       number;
  open_positions:  number;
  updated_at:      number;
}

export interface OppPosition {
  id:                  number;
  symbol:              string;
  status:              string;
  entry:               number;
  sl:                  number;
  tp1:                 number | null;
  tp2:                 number;
  tp3:                 number | null;
  auto_open?:          boolean;
  close_reason?:       string;
  risk_pct:            number;
  tp1_pct:             number;
  tp2_pct:             number;
  tp3_pct:             number;
  rr_ratio:            number;
  score:               number;
  confidence:          number;
  alert_type:          string;
  entry_mode?:         string | null;   // PLAN_v9 — lane hint
  manual?:             boolean;          // PLAN_v9 G3b — force-open marker
  signals:             string[];
  entry_at:            number;
  close_price:         number | null;
  closed_at:           number | null;
  pnl_pct:             number | null;
  current_price:       number | null;
  unrealized_pnl_pct:  number | null;
  tp1_hit:             boolean;
  tp1_hit_price:       number | null;
  position_size?:      number;
  risk_dollar?:        number;
  balance_snapshot?:   number;
  pnl_dollar?:         number;
}


export interface EquityPoint {
  n:       number;
  balance: number;
  win:     boolean;
  symbol:  string;
}

export interface OppStats {
  total:             number;
  open:              number;
  tp:                number;
  sl:                number;
  manual:            number;
  wins:              number;
  winRate:           number;
  avgPnl:            number;
  autoOpened:        number;
  currentBalance:    number;
  totalPnl$:         number;
  equityPoints:      EquityPoint[];
  calendarMap:       Map<string, number>;
  totalRisk$:        number;
  totalNotional$:    number;
  availableBalance$: number;
  maxConcurrent:     number;
  initialBalance:    number;
  riskDollar:        number;
}

// PLAN_v9 — AlertStat/ScoreBucket/SignalStat dihapus: analitik sinyal individual
// kini hidup di halaman /signals (Signal Performance). History fokus ke TRADE + lane.
