export interface AgentState {
  running: boolean;
  cycle_count?: number;
  interval_minutes?: number;
  next_scan_in_min?: number | null;
  last_scan?: number | null;
  last_error?: string | null;
}

export interface WeightUpdaterState {
  last_run?: number | null;
  last_error?: string | null;
}

export interface Health {
  status: string;
  db?: string;
  database?: string;
  spot_scanner?:    AgentState;
  spot_monitor?:    AgentState;
  futures_scanner?: AgentState;
  futures_monitor?: AgentState;
  weight_updater?:  WeightUpdaterState;
  scheduler?:       AgentState;
}

export interface BinanceStatus {
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
