export interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface CoinInfo {
  symbol: string;
  last_price: number;
  mark_price: number;
  index_price: number;
  change_24h: number;
  high_24h: number;
  low_24h: number;
  volume_24h: number;
  quote_volume_24h: number;
  open_interest: number;
  funding_rate: number;
  next_funding_time: number;
  count_24h: number;
}

export interface TALayer {
  name: string;
  timeframe: string;
  status: string;
  signal?: string;
  detail?: string;
}

export interface TakeProfit {
  level: number;
  price: number;
  rr: string;
  basis: string;
}

export interface Analysis {
  direction: string | null;
  entry: number | null;
  entry_zone_low: number | null;
  entry_zone_high: number | null;
  entry_type: string | null;
  entry_note: string | null;
  stop_loss: number | null;
  sl_basis: string | null;
  take_profits: TakeProfit[];
  risk_reward: string | null;
  confidence: number | null;
  skip_reason: string | null;
  stop_explanation: string | null;
  layers: TALayer[];
  timeframes: Record<string, string>;
  style: string;
}

export type PipelineStatus = "idle" | "running" | "done" | "error";

export const STYLES = [
  { key: "scalping",   label: "Scalping",  icon: "⚡", desc: "Minutes–Hours",  tfs: "T0:4H → T1:1H → T2:1H → T3:15M → T4:15M", color: "from-yellow-500 to-orange-500" },
  { key: "daytrading", label: "Day Trade", icon: "📅", desc: "Intraday",        tfs: "T0:1D → T1:4H → T2:4H → T3:1H → T4:1H",  color: "from-blue-500 to-indigo-500"   },
  { key: "swing",      label: "Swing",     icon: "🌊", desc: "Days–Weeks",      tfs: "T0:1W → T1:1D → T2:1D → T3:4H → T4:4H",  color: "from-primarygreen to-teal-500" },
  { key: "position",   label: "Position",  icon: "🏔", desc: "Weeks–Months",    tfs: "T0:1W → T1:1W → T2:1D → T3:1D → T4:1D",  color: "from-purple-500 to-violet-500" },
] as const;

export type StyleKey = typeof STYLES[number]["key"];

export const PIPELINE_STEPS = [
  { layer: "T0", name: "T0 Wyckoff",   icon: "🌀", desc: "Phase"     },
  { layer: "T1", name: "T1 Trend",     icon: "📈", desc: "EMA Trend" },
  { layer: "T2", name: "T2 S/R Zones", icon: "🏔", desc: "S/R Zones" },
  { layer: "T3", name: "T3 Pattern",   icon: "🔷", desc: "Pattern"   },
  { layer: "T4", name: "T4 Trigger",   icon: "⚡", desc: "Trigger"   },
];

export const STYLE_CHART_TF: Record<StyleKey, string> = {
  scalping:   "15m",
  daytrading: "1h",
  swing:      "4h",
  position:   "1d",
};
