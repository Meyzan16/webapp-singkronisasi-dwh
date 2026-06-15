// Shared types and helpers for futures-market feature

export interface Coin {
  symbol:             string;
  base:               string;
  last_price:         number;
  mark_price:         number;
  price_change:       number;
  change_pct:         number;
  high_24h:           number;
  low_24h:            number;
  volume_24h:         number;
  quote_vol_24h:      number;
  trades_24h:         number;
  is_new:             boolean;
  onboard_date:       number | null;
  days_listed:        number | null;
  funding_rate:       number;
  next_funding_time:  number;
  open_interest:      number | null;
  open_interest_usdt: number | null;
  agent1_score?:      number | null;
}

export interface MarketStats {
  total_pairs:      number;
  up_count:         number;
  down_count:       number;
  neutral_count:    number;
  avg_change_pct:   number;
  total_vol_usdt:   number;
  new_count:        number;
  big_mover_count:  number;
}

export interface Sentiment {
  avg_funding_rate:  number;
  funding_pos_count: number;
  funding_neg_count: number;
  funding_neu_count: number;
  market_mood:       string;
  total_oi_usdt:     number;
}

export interface Overview {
  new_listings:      Coin[];
  top_gainers:       Coin[];
  top_losers:        Coin[];
  top_volume:        Coin[];
  big_movers:        Coin[];
  top_funding_long:  Coin[];
  top_funding_short: Coin[];
  top_oi:            Coin[];
  market_stats:      MarketStats;
  sentiment:         Sentiment;
  generated_at:      number;
}

export function fmtChangeColor(pct: number): string {
  if (pct >= 10)  return "text-green-600 font-black";
  if (pct >= 3)   return "text-green-500 font-bold";
  if (pct >= 0)   return "text-green-400";
  if (pct >= -3)  return "text-red-400";
  if (pct >= -10) return "text-red-500 font-bold";
  return "text-red-600 font-black";
}

export function fmtBg(pct: number): string {
  if (pct >= 15)  return "bg-green-600 text-white";
  if (pct >= 8)   return "bg-green-500 text-white";
  if (pct >= 3)   return "bg-green-400 text-white";
  if (pct >= 0)   return "bg-green-100 text-green-800";
  if (pct >= -3)  return "bg-red-100 text-red-700";
  if (pct >= -8)  return "bg-red-400 text-white";
  if (pct >= -15) return "bg-red-500 text-white";
  return "bg-red-700 text-white";
}

export function fmtDate(ms: number | null): string {
  if (!ms) return "—";
  return new Date(ms).toLocaleDateString("id-ID", { day: "2-digit", month: "short", year: "numeric" });
}

export function fmtFundingColor(fr: number): string {
  if (fr > 0.05)  return "bg-red-600 text-white";
  if (fr > 0.02)  return "bg-red-400 text-white";
  if (fr > 0)     return "bg-red-100 text-red-700";
  if (fr === 0)   return "bg-neutral-100 text-neutral-500";
  if (fr >= -0.02) return "bg-green-100 text-green-700";
  return "bg-green-400 text-white";
}

export const MOOD_CFG: Record<string, { label: string; color: string; desc: string; gauge: number }> = {
  extreme_greed: { label: "Extreme Greed",  color: "text-red-600",    desc: "Longs sangat overloaded — potensi reversal tinggi",      gauge: 90 },
  greed:         { label: "Greedy",          color: "text-orange-500", desc: "Longs mendominasi — hati-hati long squeeze",             gauge: 70 },
  bullish:       { label: "Bullish",         color: "text-yellow-500", desc: "Bias bullish tipis — longs sedikit mendominasi",         gauge: 60 },
  neutral:       { label: "Neutral",         color: "text-neutral-400",desc: "Pasar seimbang — tidak ada bias kuat",                   gauge: 50 },
  bearish:       { label: "Bearish",         color: "text-teal-500",   desc: "Shorts mendominasi — bias bearish tipis",               gauge: 40 },
  fear:          { label: "Fear",            color: "text-blue-500",   desc: "Shorts overloaded — potensi short squeeze",              gauge: 20 },
};
