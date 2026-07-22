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

// PLAN_SPOT_LANES S2 — corong per lane dari scan terakhir: di tahap mana kandidat
// gugur. Ini yang membuat "kenapa lane ini kosong" bisa dijawab dengan angka.
export interface LaneFunnel {
  pool:              number;
  no_data:           number;
  rejected_score:    number;
  rejected_levels:   number;
  rejected_net_ev:   number;
  rejected_learning: number;
  found:             number;
  auto_eligible:     number;
}

export interface ScanMeta {
  generated_at:     number;
  regime_status:    string | null;
  btc_regime:       string | null;
  btc_change_24h:   number | null;
  alt_breadth_pct:  number | null;
  lane_funnel:      Record<string, LaneFunnel>;
  /** Ambang HIDUP per lane (sudah termasuk override agent_config) — jangan pakai
   *  konstanta frontend, itu basi begitu threshold diubah lewat config. */
  lane_thresholds:  Record<string, { min: number; auto: number }>;
}

// State realtime dari monitor agent (agents/opportunity/monitor.py) — satu-satunya
// angka yang benar-benar dipakai agent untuk menutup posisi.
export interface MonitorState {
  lane:            string;   // identitas lane immutable (B-Fix 3)
  phase:           string;
  sl_live:         number;
  sl_pct:          number | null;   // jarak SL dari ENTRY (%)
  sl_source:       string;          // awal | breakeven | trailing 4h | lantai ladder
  sl_moved:        boolean;
  to_sl_pct:       number | null;   // jarak SL dari HARGA SEKARANG (%)
  next_target:     { name: string; price: number | null; pct: number | null; sell_fraction: number } | null;
  to_target_pct:   number | null;   // jarak target berikut dari HARGA SEKARANG (%)
  peak_pnl_pct:    number;
  lock_at_pct:     number | null;   // profit-lock aktif: tutup bila P&L turun ke sini
  age_days:        number | null;
  max_age_days:    number;
  check_every_sec: number;
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
  entry_mode?:         string | null;   // MODE SAAT INI — dimutasi monitor di TP2/TP3
  lane?:               string | null;   // S6 — identitas lane immutable (untuk analitik)
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
  // PLAN_v10 — dynamic profit ladder
  ladder?:             { rung: string; price: number; frac: number; pnl_dollar: number }[];
  banked_dollar?:      number;
  remaining_fraction?: number;
  is_runner?:          boolean;
  last_rung_price?:    number | null;
  monitor?:            MonitorState | null;
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
