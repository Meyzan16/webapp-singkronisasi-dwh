"use client";
import { useEffect, useState } from "react";

export interface AgentConfigSpot {
  scan_interval_sec: number;
  monitor_interval_sec: number;
  fastpass: { bigmover_interval_sec: number; bigmover_min_change_pct: number };
  min_volume: Record<string, number>;
  score_thresholds: Record<string, { min: number; auto: number }>;
  bigmover: {
    min_change_24h_pct: number;
    max_change_24h_pct: number;
    explosive_threshold_pct: number;
    tp_standard_pct: number[];
    tp_explosive_pct: number[];
  };
  early_radar: {
    vol_range: number[];
    surge_min: number;
    surge_strong: number;
    near_high_pct: number;
    risk_pct: number;
    max_open: number;
    rr_min: number;
    tp_pct: number[];
  };
  regime_gates: { closed_btc_24h_pct: number; reduced_btc_24h_pct: number };
  quota: {
    max_opens_per_cycle: number;
    max_opens_per_cycle_reduced: number;
    max_bigmover_opens: number;
    daily_loss_limit_pct: number;
  };
  monitor: {
    min_hold_minutes: number;
    max_age_fresh_setup_days: number;
    max_age_momentum_days: number;
    profit_lock_tiers: { peak_pct: number; lock_frac: number }[];
  };
}

export interface AgentConfigFutures {
  scan_interval_sec: number;
  monitor_interval_sec: number;
  universe_cap: number;
  big_mover_threshold_pct: number;
  agents: Record<string, Record<string, number | boolean | string>>;
  auto_trader: {
    max_positions_global: number;
    lane_quotas: Record<string, number>;
    max_bigmover_positions: number;
    cooldown_hours: number;
    max_wallet_margin_pct: number;
    funding_gate_long_pct: number;
    funding_gate_short_pct: number;
    auto_open_threshold_fallback: number;
  };
  monitor: {
    max_age_days: number;
    max_age_extensions: number;
    lane_margin_caps_pct: Record<string, number>;
  };
  risk_gate: {
    dd_hard_stop_pct: number;
    dd_recover_pct: number;
    rar_threshold: number;
    rar_min_trades: number;
    lane_wr_pause_threshold: number;
    lane_wr_min_sample: number;
  };
}

export interface AgentConfigLearning {
  training_window_days: number;
  decay_half_life_days: number;
  step_cap: number;
  stale_key_max_days: number;
  cross_agent: { blend_pct: number; min_sample: number };
}

export interface AgentConfigResponse {
  spot: Partial<AgentConfigSpot>;
  futures: Partial<AgentConfigFutures>;
  learning: Partial<AgentConfigLearning>;
  errors: string[];
}

interface UseAgentConfigState {
  data: AgentConfigResponse | null;
  loading: boolean;
  error: string | null;
}

/**
 * Live pull of agent runtime constants (PLAN_v5 Group B) — reads directly from
 * agent modules on the backend, so the architecture page can never drift from
 * what the agents actually run with. Falls back gracefully: caller should keep
 * using static data.ts values while loading or on error.
 */
export function useAgentConfig(): UseAgentConfigState {
  const [state, setState] = useState<UseAgentConfigState>({
    data: null,
    loading: true,
    error: null,
  });

  useEffect(() => {
    let cancelled = false;

    fetch("/api/v1/agent/config")
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return (await res.json()) as AgentConfigResponse;
      })
      .then((data) => {
        if (!cancelled) setState({ data, loading: false, error: null });
      })
      .catch((err: Error) => {
        if (!cancelled) setState({ data: null, loading: false, error: err.message });
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return state;
}
